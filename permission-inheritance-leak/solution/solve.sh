#!/usr/bin/env bash
set -euo pipefail

cat > /app/access_control.py <<'PY'
from copy import deepcopy
from math import isfinite


DEFAULT_ACTIONS = ("read", "write", "delete", "admin")

_EFFECTS = ("allow", "deny")
_WILDCARD = "*"
_SUBJECT_KINDS = ("principal", "role", "group")
_LEAF_OPS = ("equals", "not_equals", "in", "not_in", "at_least", "at_most", "between", "exists")
_COMBINATORS = ("all", "any", "not")
_RESOURCE_PREFIX = "resource:"

_TIERS = {"principal": 0, "role": 1, "group": 2}


class AccessError(ValueError):
    pass


def _is_str(value):
    return isinstance(value, str) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _values_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_values_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _valid_action_name(value):
    if not _is_str(value) or not value:
        return False
    if _WILDCARD in value:
        return False
    return all(segment for segment in value.split("."))


def _validate_json(value, seen):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise AccessError("values may not contain non-finite numbers")
        return
    if isinstance(value, str):
        return
    if isinstance(value, list):
        if id(value) in seen:
            raise AccessError("values must be acyclic")
        seen = seen | {id(value)}
        for item in value:
            _validate_json(item, seen)
        return
    if isinstance(value, dict):
        if id(value) in seen:
            raise AccessError("values must be acyclic")
        seen = seen | {id(value)}
        for key, item in value.items():
            if not _is_str(key):
                raise AccessError("keys must be strings")
            _validate_json(item, seen)
        return
    raise AccessError("values must be JSON-compatible")


def _validate_matcher(matcher):
    if not isinstance(matcher, dict) or len(matcher) != 1:
        raise AccessError("each matcher must be a single-operator dictionary")
    op = next(iter(matcher))
    operand = matcher[op]
    if op in _COMBINATORS:
        if op == "not":
            _validate_matcher(operand)
            return
        if not isinstance(operand, list) or not operand:
            raise AccessError("'all'/'any' operand must be a non-empty list")
        for inner in operand:
            _validate_matcher(inner)
        return
    if op not in _LEAF_OPS:
        raise AccessError("unknown matcher operator")
    if op in ("in", "not_in"):
        if not isinstance(operand, list):
            raise AccessError("'in'/'not_in' operand must be a list")
        for item in operand:
            _validate_json(item, set())
    elif op in ("at_least", "at_most"):
        if not _is_number(operand) or not isfinite(operand):
            raise AccessError("comparison operand must be a finite number")
    elif op == "between":
        if (not isinstance(operand, list) or len(operand) != 2
                or not all(_is_number(x) and isfinite(x) for x in operand)
                or operand[0] > operand[1]):
            raise AccessError("'between' operand must be [low, high] finite numbers with low <= high")
    elif op == "exists":
        if not isinstance(operand, bool):
            raise AccessError("'exists' operand must be a boolean")
    else:
        _validate_json(operand, set())


def _validate_conditions(conditions):
    for key, matcher in conditions.items():
        if not _is_str(key) or not key:
            raise AccessError("condition keys must be non-empty strings")
        if key.startswith(_RESOURCE_PREFIX) and not key[len(_RESOURCE_PREFIX):]:
            raise AccessError("resource attribute name must be non-empty")
        _validate_matcher(matcher)


def _matcher_satisfied(matcher, present, value):
    op = next(iter(matcher))
    operand = matcher[op]
    if op == "all":
        return all(_matcher_satisfied(inner, present, value) for inner in operand)
    if op == "any":
        return any(_matcher_satisfied(inner, present, value) for inner in operand)
    if op == "not":
        return not _matcher_satisfied(operand, present, value)
    if op == "exists":
        return operand is present
    if not present:
        return False
    if op == "equals":
        return _values_equal(value, operand)
    if op == "not_equals":
        return not _values_equal(value, operand)
    if op == "in":
        return any(_values_equal(value, item) for item in operand)
    if op == "not_in":
        return not any(_values_equal(value, item) for item in operand)
    if op == "at_least":
        return _is_number(value) and value >= operand
    if op == "at_most":
        return _is_number(value) and value <= operand
    if op == "between":
        return _is_number(value) and operand[0] <= value <= operand[1]
    return False


class AccessControl:
    def __init__(self, *, actions=DEFAULT_ACTIONS):
        if isinstance(actions, str) or not isinstance(actions, (list, tuple)):
            raise AccessError("actions must be a list or tuple")
        if not actions:
            raise AccessError("actions must be non-empty")
        ordered = []
        for action in actions:
            if not _valid_action_name(action):
                raise AccessError("actions must be dotted non-empty strings without '*'")
            if action in ordered:
                raise AccessError("actions must be unique")
            ordered.append(action)
        self._actions = tuple(ordered)
        self._action_set = frozenset(ordered)
        self._resources = {}
        self._groups = {}
        self._roles = {}
        self._principal_roles = {}


    def _require_resource(self, resource_id):
        if not _is_str(resource_id) or not resource_id:
            raise AccessError("resource_id must be a non-empty string")
        if resource_id not in self._resources:
            raise AccessError("unknown resource")

    def _require_principal(self, principal):
        if not _is_str(principal) or not principal:
            raise AccessError("principal must be a non-empty string")

    def _require_subject(self, subject, subject_kind):
        if subject_kind not in _SUBJECT_KINDS:
            raise AccessError("subject_kind must be 'principal', 'role', or 'group'")
        if not _is_str(subject) or not subject:
            raise AccessError("subject must be a non-empty string")
        if subject_kind == "group" and subject not in self._groups:
            raise AccessError("unknown group")
        if subject_kind == "role" and subject not in self._roles:
            raise AccessError("unknown role")

    def _require_query_action(self, action):
        if action not in self._action_set:
            raise AccessError("action must be one of the configured actions")

    def _require_grant_action(self, action):
        if action == _WILDCARD:
            return
        if action in self._action_set:
            return
        if _is_str(action) and action.endswith(".*"):
            prefix = action[:-2]
            if prefix and _WILDCARD not in prefix and all(seg for seg in prefix.split(".")):
                return
        raise AccessError("grant action must be '*', a configured action, or a 'P.*' pattern")

    def _normalize_context(self, context):
        if context is None:
            return {}
        if not isinstance(context, dict):
            raise AccessError("context must be a dictionary or None")
        for key in context:
            if not _is_str(key):
                raise AccessError("context keys must be strings")
        _validate_json(context, set())
        return context

    @staticmethod
    def _action_key(grant_action, queried):
        if grant_action == queried:
            return (0, 0)
        if grant_action == _WILDCARD:
            return (1, 0)
        if grant_action.endswith(".*"):
            prefix = grant_action[:-2]
            prefix_segments = prefix.split(".")
            queried_segments = queried.split(".")
            if (len(queried_segments) > len(prefix_segments)
                    and queried_segments[:len(prefix_segments)] == prefix_segments):
                return (1, -len(prefix_segments))
        return None


    def add_resource(self, resource_id, parent=None):
        if not _is_str(resource_id) or not resource_id:
            raise AccessError("resource_id must be a non-empty string")
        if resource_id in self._resources:
            raise AccessError("resource already exists")
        if parent is not None:
            if not _is_str(parent) or not parent:
                raise AccessError("parent must be a non-empty string")
            if parent not in self._resources:
                raise AccessError("unknown parent resource")
        self._resources[resource_id] = {"parent": parent, "grants": [], "attributes": {}}

    def _is_descendant(self, candidate, ancestor):
        current = candidate
        seen = set()
        while current is not None and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            current = self._resources[current]["parent"]
        return False

    def move_resource(self, resource_id, new_parent):
        self._require_resource(resource_id)
        if new_parent is not None:
            if not _is_str(new_parent) or not new_parent:
                raise AccessError("new_parent must be a non-empty string")
            if new_parent not in self._resources:
                raise AccessError("unknown parent resource")
            if new_parent == resource_id or self._is_descendant(new_parent, resource_id):
                raise AccessError("move would create a cycle")
        self._resources[resource_id]["parent"] = new_parent

    def set_attribute(self, resource_id, key, value):
        self._require_resource(resource_id)
        if not _is_str(key) or not key:
            raise AccessError("attribute key must be a non-empty string")
        _validate_json(value, set())
        self._resources[resource_id]["attributes"][key] = deepcopy(value)

    def _effective_attributes(self, resource_id):
        resolved = {}
        for node_id in self._chain(resource_id):
            for key, value in self._resources[node_id]["attributes"].items():
                if key not in resolved:
                    resolved[key] = value
        return resolved


    def add_role(self, role_id):
        if not _is_str(role_id) or not role_id:
            raise AccessError("role_id must be a non-empty string")
        if role_id in self._roles:
            raise AccessError("role already exists")
        self._roles[role_id] = True

    def assign_role(self, principal, role_id):
        self._require_principal(principal)
        if role_id not in self._roles:
            raise AccessError("unknown role")
        self._principal_roles.setdefault(principal, set()).add(role_id)

    def _roles_for_principal(self, principal):
        return self._principal_roles.get(principal, set())


    def add_group(self, group_id):
        if not _is_str(group_id) or not group_id:
            raise AccessError("group_id must be a non-empty string")
        if group_id in self._groups:
            raise AccessError("group already exists")
        self._groups[group_id] = {"members": set()}

    def _group_contains_group(self, start, target):
        stack = [start]
        seen = set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            for kind, member in self._groups[current]["members"]:
                if kind == "group":
                    stack.append(member)
        return False

    def add_member(self, group_id, member, member_kind="principal"):
        if group_id not in self._groups:
            raise AccessError("unknown group")
        if member_kind not in ("principal", "group"):
            raise AccessError("member_kind must be 'principal' or 'group'")
        if not _is_str(member) or not member:
            raise AccessError("member must be a non-empty string")
        if member_kind == "group":
            if member not in self._groups:
                raise AccessError("unknown member group")
            if self._group_contains_group(member, group_id):
                raise AccessError("membership would create a cycle")
        self._groups[group_id]["members"].add((member_kind, member))

    def _groups_for_principal(self, principal):
        result = set()
        for group_id, group in self._groups.items():
            if ("principal", principal) in group["members"]:
                result.add(group_id)
        changed = True
        while changed:
            changed = False
            for group_id, group in self._groups.items():
                if group_id in result:
                    continue
                for kind, member in group["members"]:
                    if kind == "group" and member in result:
                        result.add(group_id)
                        changed = True
                        break
        return result


    def grant(self, resource_id, subject, action, effect, *, subject_kind="principal",
              inheritable=True, conditions=None, priority=0):
        self._require_resource(resource_id)
        self._require_subject(subject, subject_kind)
        self._require_grant_action(action)
        if effect not in _EFFECTS:
            raise AccessError("effect must be 'allow' or 'deny'")
        if type(inheritable) is not bool:
            raise AccessError("inheritable must be a boolean")
        if not _is_int(priority):
            raise AccessError("priority must be an integer")
        if conditions is not None and not isinstance(conditions, dict):
            raise AccessError("conditions must be a dictionary or None")
        if conditions is not None:
            _validate_conditions(conditions)
        stored_conditions = deepcopy(conditions) if conditions is not None else {}
        grants = self._resources[resource_id]["grants"]
        for existing in grants:
            if (existing["subject"] == subject and existing["subject_kind"] == subject_kind
                    and existing["action"] == action and existing["effect"] == effect):
                existing["inheritable"] = inheritable
                existing["conditions"] = stored_conditions
                existing["priority"] = priority
                return
        grants.append({
            "subject": subject,
            "subject_kind": subject_kind,
            "action": action,
            "effect": effect,
            "inheritable": inheritable,
            "conditions": stored_conditions,
            "priority": priority,
        })

    def revoke(self, resource_id, subject, action, *, subject_kind="principal"):
        self._require_resource(resource_id)
        if subject_kind not in _SUBJECT_KINDS:
            raise AccessError("subject_kind must be 'principal', 'role', or 'group'")
        if not _is_str(subject) or not subject:
            raise AccessError("subject must be a non-empty string")
        self._require_grant_action(action)
        grants = self._resources[resource_id]["grants"]
        kept = [
            g for g in grants
            if not (g["subject"] == subject and g["subject_kind"] == subject_kind and g["action"] == action)
        ]
        removed = len(kept) != len(grants)
        self._resources[resource_id]["grants"] = kept
        return removed


    def _chain(self, resource_id):
        chain = []
        current = resource_id
        seen = set()
        while current is not None and current not in seen:
            chain.append(current)
            seen.add(current)
            current = self._resources[current]["parent"]
        return chain

    def _grant_applies_to(self, grant, principal, groups, roles):
        kind = grant["subject_kind"]
        if kind == "principal":
            return grant["subject"] == principal
        if kind == "role":
            return grant["subject"] in roles
        return grant["subject"] in groups

    def _conditions_satisfied(self, grant, context, attributes):
        for key, matcher in grant["conditions"].items():
            if key.startswith(_RESOURCE_PREFIX):
                attr = key[len(_RESOURCE_PREFIX):]
                present = attr in attributes
                value = attributes.get(attr)
            else:
                present = key in context
                value = context.get(key)
            if not _matcher_satisfied(matcher, present, value):
                return False
        return True

    def _resolve(self, principal, resource_id, action, context):
        groups = self._groups_for_principal(principal)
        roles = self._roles_for_principal(principal)
        attributes = self._effective_attributes(resource_id)
        best_key = None
        best_node = None
        best_action_key = None
        deciding = []
        for distance, node_id in enumerate(self._chain(resource_id)):
            for g in self._resources[node_id]["grants"]:
                if distance != 0 and not g["inheritable"]:
                    continue
                if not self._grant_applies_to(g, principal, groups, roles):
                    continue
                action_key = self._action_key(g["action"], action)
                if action_key is None:
                    continue
                if not self._conditions_satisfied(g, context, attributes):
                    continue
                subject_tier = _TIERS[g["subject_kind"]]
                key = (-g["priority"], distance, subject_tier, action_key)
                if best_key is None or key < best_key:
                    best_key = key
                    best_node = node_id
                    best_action_key = action_key
                    deciding = [g]
                elif key == best_key:
                    deciding.append(g)
        if best_key is None:
            return {
                "allowed": False,
                "decided_by": None,
                "effect": None,
                "matched": None,
                "subject": None,
                "distance": None,
                "inherited": False,
                "priority": None,
            }
        neg_priority, distance, subject_tier, _ = best_key
        effect = "deny" if any(g["effect"] == "deny" for g in deciding) else "allow"
        if best_action_key == (0, 0):
            matched = "exact"
        elif best_action_key == (1, 0):
            matched = "any"
        else:
            matched = "prefix"
        subject = {0: "principal", 1: "role", 2: "group"}[subject_tier]
        return {
            "allowed": effect == "allow",
            "decided_by": best_node,
            "effect": effect,
            "matched": matched,
            "subject": subject,
            "distance": distance,
            "inherited": distance > 0,
            "priority": -neg_priority,
        }

    def check(self, principal, resource_id, action, context=None):
        self._require_principal(principal)
        self._require_resource(resource_id)
        self._require_query_action(action)
        ctx = self._normalize_context(context)
        return self._resolve(principal, resource_id, action, ctx)["allowed"]

    def explain(self, principal, resource_id, action, context=None):
        self._require_principal(principal)
        self._require_resource(resource_id)
        self._require_query_action(action)
        ctx = self._normalize_context(context)
        return self._resolve(principal, resource_id, action, ctx)

    def effective_permissions(self, principal, resource_id, context=None):
        self._require_principal(principal)
        self._require_resource(resource_id)
        ctx = self._normalize_context(context)
        allowed = [a for a in self._actions if self._resolve(principal, resource_id, a, ctx)["allowed"]]
        return sorted(allowed)

    def list_grants(self, resource_id):
        self._require_resource(resource_id)
        grants = self._resources[resource_id]["grants"]
        result = [deepcopy(g) for g in grants]
        result.sort(key=lambda g: (g["subject_kind"], g["subject"], g["action"], g["effect"]))
        return result
PY

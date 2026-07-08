"""Hierarchical access control with namespaced actions, roles, resources, and groups."""

DEFAULT_ACTIONS = ("read", "write", "delete", "admin")

_EFFECTS = ("allow", "deny")
_SUBJECT_KINDS = ("principal", "role", "group")


class AccessError(ValueError):
    pass


class AccessControl:
    _resources = {}
    _groups = {}
    _roles = {}
    _principal_roles = {}

    def __init__(self, *, actions=DEFAULT_ACTIONS):
        if not actions:
            raise AccessError("actions must be provided")
        self._actions = tuple(actions)
        self._action_set = set(actions)
        self._resources = AccessControl._resources
        self._groups = AccessControl._groups
        self._roles = AccessControl._roles
        self._principal_roles = AccessControl._principal_roles

    def add_resource(self, resource_id, parent=None):
        if not isinstance(resource_id, str) or not resource_id:
            raise AccessError("resource_id must be a non-empty string")
        if parent is not None and parent not in self._resources:
            raise AccessError("unknown parent resource")
        self._resources[resource_id] = {"parent": parent, "grants": [], "attributes": {}}

    def move_resource(self, resource_id, new_parent):
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        if new_parent is not None and new_parent not in self._resources:
            raise AccessError("unknown parent resource")
        self._resources[resource_id]["parent"] = new_parent

    def set_attribute(self, resource_id, key, value):
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        self._resources[resource_id]["attributes"][key] = value

    def add_role(self, role_id):
        if not isinstance(role_id, str) or not role_id:
            raise AccessError("role_id must be a non-empty string")
        self._roles[role_id] = True

    def assign_role(self, principal, role_id):
        self._principal_roles.setdefault(principal, set()).add(role_id)

    def add_group(self, group_id):
        if not isinstance(group_id, str) or not group_id:
            raise AccessError("group_id must be a non-empty string")
        self._groups[group_id] = {"members": set()}

    def add_member(self, group_id, member, member_kind="principal"):
        if group_id not in self._groups:
            raise AccessError("unknown group")
        if member_kind == "group" and member not in self._groups:
            raise AccessError("unknown member group")
        self._groups[group_id]["members"].add((member_kind, member))

    def _groups_for_principal(self, principal):
        result = set()
        for group_id, group in self._groups.items():
            if ("principal", principal) in group["members"]:
                result.add(group_id)
        return result

    def _action_matches(self, grant_action, queried):
        if grant_action == queried or grant_action == "*":
            return True
        if grant_action.endswith(".*"):
            return queried.startswith(grant_action[:-2])
        return False

    def _conditions_ok(self, conditions, context):
        for key, matcher in conditions.items():
            op = next(iter(matcher))
            operand = matcher[op]
            value = context.get(key)
            if op == "equals" and value != operand:
                return False
            if op == "in" and value not in operand:
                return False
            if op == "at_least" and (value is None or value < operand):
                return False
            if op == "at_most" and (value is None or value > operand):
                return False
        return True

    def grant(self, resource_id, subject, action, effect, *, subject_kind="principal", inheritable=True, conditions=None, priority=0):
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        if not isinstance(subject, str) or not subject:
            raise AccessError("subject must be a non-empty string")
        if effect not in _EFFECTS:
            raise AccessError("effect must be allow or deny")
        self._resources[resource_id]["grants"].append({
            "subject": subject,
            "subject_kind": subject_kind,
            "action": action,
            "effect": effect,
            "inheritable": inheritable,
            "conditions": conditions if conditions is not None else {},
        })

    def revoke(self, resource_id, subject, action, *, subject_kind="principal"):
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        grants = self._resources[resource_id]["grants"]
        before = len(grants)
        self._resources[resource_id]["grants"] = [g for g in grants if g["subject"] != subject]
        return len(self._resources[resource_id]["grants"]) != before

    def _chain(self, resource_id):
        chain = []
        current = resource_id
        while current is not None:
            chain.append(current)
            current = self._resources[current]["parent"]
        return chain

    def _resolve(self, principal, resource_id, action, context):
        groups = self._groups_for_principal(principal)
        roles = self._principal_roles.get(principal, set())
        allow_hit = None
        for distance, node in enumerate(self._chain(resource_id)):
            for g in self._resources[node]["grants"]:
                if g["subject_kind"] == "principal":
                    if g["subject"] != principal:
                        continue
                elif g["subject_kind"] == "role":
                    if g["subject"] not in roles:
                        continue
                else:
                    if g["subject"] not in groups:
                        continue
                if not self._action_matches(g["action"], action):
                    continue
                if not self._conditions_ok(g["conditions"], context or {}):
                    continue
                if g["action"] == action:
                    matched = "exact"
                elif g["action"] == "*":
                    matched = "any"
                else:
                    matched = "prefix"
                subject = "principal" if g["subject_kind"] == "principal" else "group"
                if allow_hit is None:
                    allow_hit = (node, distance, matched, subject, g["effect"])
        if allow_hit is None:
            return {"allowed": False, "decided_by": None, "effect": None, "matched": None,
                    "subject": None, "distance": None, "inherited": False}
        node, distance, matched, subject, effect = allow_hit
        return {"allowed": effect == "allow", "decided_by": node, "effect": effect, "matched": matched,
                "subject": subject, "distance": distance, "inherited": distance > 0}

    def check(self, principal, resource_id, action, context=None):
        if not isinstance(principal, str) or not principal:
            raise AccessError("principal must be a non-empty string")
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        if action not in self._action_set:
            raise AccessError("unknown action")
        return self._resolve(principal, resource_id, action, context)["allowed"]

    def explain(self, principal, resource_id, action, context=None):
        if not isinstance(principal, str) or not principal:
            raise AccessError("principal must be a non-empty string")
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        if action not in self._action_set:
            raise AccessError("unknown action")
        return self._resolve(principal, resource_id, action, context)

    def effective_permissions(self, principal, resource_id, context=None):
        if not isinstance(principal, str) or not principal:
            raise AccessError("principal must be a non-empty string")
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        allowed = [a for a in self._actions if self._resolve(principal, resource_id, a, context)["allowed"]]
        return sorted(allowed)

    def list_grants(self, resource_id):
        if resource_id not in self._resources:
            raise AccessError("unknown resource")
        return self._resources[resource_id]["grants"]

# Permission inheritance leak

Fix `/app/access_control.py`. It implements a hierarchical permission system that resolves access over a tree of resources where children inherit grants from their ancestors and grants may target principals, roles, or groups, but it currently leaks privileges and returns wrong decisions. Repair it so its behavior matches the contract below exactly, keeping the public API unchanged.

Use only the Python standard library. Do not read or write files, open sockets, start threads or subprocesses, or read wall-clock time. Keep all state inside each `AccessControl` instance; two instances never share state.

## API

```python
DEFAULT_ACTIONS = ("read", "write", "delete", "admin")

class AccessError(ValueError): ...

class AccessControl:
    def __init__(self, *, actions=DEFAULT_ACTIONS): ...
    def add_resource(self, resource_id, parent=None) -> None: ...
    def move_resource(self, resource_id, new_parent) -> None: ...
    def set_attribute(self, resource_id, key, value) -> None: ...
    def add_role(self, role_id) -> None: ...
    def assign_role(self, principal, role_id) -> None: ...
    def add_group(self, group_id) -> None: ...
    def add_member(self, group_id, member, member_kind="principal") -> None: ...
    def grant(self, resource_id, subject, action, effect, *, subject_kind="principal", inheritable=True, conditions=None, priority=0) -> None: ...
    def revoke(self, resource_id, subject, action, *, subject_kind="principal") -> bool: ...
    def check(self, principal, resource_id, action, context=None) -> bool: ...
    def explain(self, principal, resource_id, action, context=None) -> dict: ...
    def effective_permissions(self, principal, resource_id, context=None) -> list: ...
    def list_grants(self, resource_id) -> list: ...
```

Raise `AccessError` for every invalid input. Validate all arguments before changing any stored state. Throughout, a value is JSON-compatible when it is `None`, a boolean, a finite number, a string, a list of JSON-compatible values, or a dictionary with string keys and JSON-compatible values. Equality is type-strict: a boolean is never equal to a number, so `True` equals only `True` and never `1`, and two values are equal only when their types and contents agree.

## Actions

An action name is one or more non-empty segments joined by `.`, for example `read`, `repo.read`, or `repo.sub.read`. It may not contain `*` and may not have an empty segment (no leading dot, trailing dot, or `..`).

`actions` must be a non-empty list or tuple of unique action names. A bare string, an empty sequence, a duplicate, a non-string, a boolean, or any name containing `*` or an empty segment is invalid. Each instance keeps its own action set.

A grant's `action` is one of: `"*"`, an exact configured action, or a pattern `P.*` where `P` is one or more non-empty segments and contains no `*`. The pattern's prefix need not be a prefix of any configured action. Anything else is invalid.

A grant action matches a queried action `A` when it equals `A`, or it is `"*"`, or it is a pattern `P.*` and `A` has `P` as a proper segment prefix, meaning `A` split on `.` begins with `P`'s segments and has strictly more segments than `P`. So `repo.*` matches `repo.read` and `repo.sub.read`, but not `repo` and not `repository.read`.

## Configuration and structure

`resource_id`, `parent`, `new_parent`, `group_id`, `role_id`, `member`, `principal`, and `subject` are non-empty strings, and a boolean is not a string. `add_resource` rejects a duplicate `resource_id`, and a `parent` other than `None` must already exist. `move_resource` retargets a resource's parent: `new_parent` is `None`, which makes the resource a root, or an existing resource. A move whose `new_parent` is the resource itself or one of its descendants is rejected and leaves the tree unchanged.

## Resource attributes

`set_attribute(resource_id, key, value)` records an attribute on an existing resource. `key` is a non-empty string and `value` is any JSON-compatible value, stored as a deep copy so later mutation of the caller's value never changes stored state. Setting an existing key overwrites it.

Attributes inherit down the tree. The effective attributes of a resource map each key to the value defined on the nearest resource walking from the resource itself up through its ancestors: the resource's own value wins over an ancestor's, and a nearer ancestor wins over a farther one. A key with no value on the resource or any ancestor is absent from its effective attributes. Conditions may read these effective attributes (see Grants).

## Roles

`add_role(role_id)` registers a new role; a duplicate `role_id` is invalid. `assign_role(principal, role_id)` assigns an existing role to a principal; assigning a role that was not registered is invalid, and assigning the same role to the same principal twice changes nothing. A principal holds a role only when it has been assigned that role directly; roles do not nest and group membership does not confer a role.

## Groups

`add_group` registers a new group; a duplicate `group_id` is invalid. `add_member` adds a member to an existing group. `member_kind` is `"principal"` or `"group"`. A `"group"` member must already exist, and a membership edge that would make a group a member of itself directly or transitively is rejected. Adding the same member twice changes nothing. A principal belongs to a group when the group lists that principal directly, or when the group lists another group the principal belongs to. Membership is transitive through nested groups.

## Grants

`subject_kind` is `"principal"`, `"role"`, or `"group"`. A `"group"` subject must be an existing group and a `"role"` subject must be an existing role. `effect` is `"allow"` or `"deny"`. `inheritable` must be a `bool`. `priority` must be an integer and a boolean is not an integer; it may be negative and defaults to `0`. `conditions` is `None` or a dictionary mapping string keys to matchers; store a deep copy of it, and store `{}` when it is `None`.

A condition key is a non-empty string. A key that begins with `resource:` selects a resource attribute: the part after `resource:` is the attribute name and must be non-empty, and the matcher reads the queried resource's effective attributes. Any other key selects the query context.

A matcher is a dictionary with exactly one key. The leaf operators are:

- `equals` — operand is any JSON-compatible value; satisfied when the source value is present and equal.
- `not_equals` — operand is any JSON-compatible value; satisfied when the source value is present and not equal.
- `in` — operand is a list of JSON-compatible values; satisfied when the source value is present and equal to one of them.
- `not_in` — operand is a list of JSON-compatible values; satisfied when the source value is present and equal to none of them.
- `at_least` / `at_most` — operand is a finite number that is not a boolean; satisfied when the source value is present, is a number that is not a boolean, and is at least, or at most, the operand.
- `between` — operand is a list `[low, high]` of two finite non-boolean numbers with `low <= high`; satisfied when the source value is present, is a number that is not a boolean, and lies in the inclusive range.
- `exists` — operand is a boolean; satisfied when the source value is present and the operand is `True`, or absent and the operand is `False`. This is the only matcher an absent value can satisfy.

The combinators take matchers and combine them against the same source value:

- `all` — operand is a non-empty list of matchers; satisfied when every one is.
- `any` — operand is a non-empty list of matchers; satisfied when at least one is.
- `not` — operand is a single matcher; satisfied when that matcher is not.

A matcher whose operator is none of the above, or whose operand has the wrong shape, is invalid. Combinator operands are validated recursively. A grant applies under a context only when every one of its conditions is satisfied; a grant with empty conditions applies under any context. Every leaf matcher other than `exists` requires its source value to be present, so a missing context key or a missing resource attribute fails it.

A stored grant is identified by its `(subject, subject_kind, action, effect)` combination, where `action` is the stored grant action string. Granting the same combination again replaces its `inheritable` flag, `conditions`, and `priority` rather than adding a duplicate. Grants that differ in any of those four parts coexist.

`revoke(resource_id, subject, action, *, subject_kind="principal")` removes every grant on that resource whose stored action equals `action` and that matches `(subject, subject_kind)`, both effects, and only on that resource. Its `action` follows the same rule as a grant action. It returns `True` when it removed at least one grant and `False` otherwise.

## Resolution

`check`, `explain`, and `effective_permissions` reject an unknown resource and an invalid principal. `check` and `explain` reject an `action` that is not a configured action; neither `"*"` nor a pattern can be queried. `context` is `None` or a dictionary whose keys are strings and whose values are JSON-compatible; `None` means an empty context.

To resolve `(principal, resource_id, action)` under a context, consider every stored grant that applies. A grant applies when all of these hold: it targets the principal directly, or a role the principal holds, or a group the principal belongs to; the resource carrying it is the queried resource, or the grant is inheritable and the resource is an ancestor of the queried resource; its grant action matches the queried action; and its conditions are satisfied, where context-sourced conditions read the query context and resource-sourced conditions read the queried resource's effective attributes.

Rank each applying grant by the tuple `(priority, distance, subject_tier, action_rank)`, and the grant with the most favorable rank wins, where:

- `priority` is compared first and higher wins.
- `distance` is the number of hops from the queried resource to the resource carrying the grant (the queried resource is 0, its parent is 1, and so on); nearer wins.
- `subject_tier` orders a grant aimed at the principal directly ahead of one aimed at a role, and a role ahead of a group.
- `action_rank` orders an exact-action match ahead of every pattern, a `P.*` pattern with more prefix segments ahead of one with fewer, and any `P.*` pattern ahead of `"*"`.

Because `priority` is compared before `distance`, a higher-priority grant on a distant ancestor decides over a lower-priority grant on the queried resource. The applying grants that share the single most favorable tuple form the deciding set. If any grant in the deciding set has effect `"deny"`, the result is deny; otherwise it is allow. When no grant applies, the result is deny.

`check` returns the boolean decision. `explain` returns exactly:

```python
{"allowed": bool, "decided_by": str | None, "effect": "allow" | "deny" | None,
 "matched": "exact" | "prefix" | "any" | None, "subject": "principal" | "role" | "group" | None,
 "distance": int | None, "inherited": bool, "priority": int | None}
```

`decided_by` is the id of the resource carrying the deciding set, `effect` is the decided effect, `distance` is that resource's distance, and `priority` is the deciding set's priority. `matched` is `"exact"` when the deciding set matched the action exactly, `"prefix"` when it matched through a `P.*` pattern, and `"any"` when it matched through `"*"`. `subject` is `"principal"`, `"role"`, or `"group"` for the deciding set's subject kind. `inherited` is `True` when the deciding resource is an ancestor, meaning its distance is greater than 0. When no grant applies, `allowed` is `False`, `inherited` is `False`, and `decided_by`, `effect`, `matched`, `subject`, `distance`, and `priority` are `None`.

`effective_permissions(principal, resource_id, context=None)` returns the configured actions that resolve to allow for that principal on that resource under the context, as a new list sorted ascending.

## Listing

`list_grants(resource_id)` returns the grants stored on that resource only, never inherited ones, as deep copies sorted by `(subject_kind, subject, action, effect)`. Each grant is a dictionary with exactly the keys `subject`, `subject_kind`, `action`, `effect`, `inheritable`, `conditions`, and `priority`. Returned data and stored conditions never share mutable state with caller-provided objects.

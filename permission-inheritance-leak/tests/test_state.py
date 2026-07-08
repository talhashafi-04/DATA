import builtins
from contextlib import contextmanager, ExitStack
import functools
import importlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import sys
import sysconfig
import time
import types
import unittest
from unittest import mock


MODULE_PATH = Path("/app/access_control.py")
FORBIDDEN_MARKERS = ("/tests", "test_state", "hidden_data", "reward.txt", "ctrf.json")
DECISION_KEYS = {"allowed", "decided_by", "effect", "matched", "subject", "distance", "inherited", "priority"}
GRANT_KEYS = {"subject", "subject_kind", "action", "effect", "inheritable", "conditions", "priority"}
TESTCASE_SNAPSHOT = dict(unittest.TestCase.__dict__)
_ALLOWED_IMPORT_ROOTS = tuple(
    Path(path).resolve()
    for path in {
        sysconfig.get_paths().get("stdlib"),
        sysconfig.get_paths().get("platstdlib"),
    }
    if path
)


def _path_is_allowed_import(path):
    try:
        resolved = Path(os.fspath(path)).resolve()
    except (TypeError, ValueError, OSError):
        return False
    return any(resolved == root or root in resolved.parents for root in _ALLOWED_IMPORT_ROOTS)


def _is_write_mode(mode):
    return any(flag in mode for flag in ("w", "a", "x", "+"))


def assert_testcase_class_unmodified():
    current = unittest.TestCase.__dict__
    for name, original in TESTCASE_SNAPSHOT.items():
        if current.get(name) is not original:
            raise AssertionError(f"unittest.TestCase attribute was modified: {name}")
    added = set(current) - set(TESTCASE_SNAPSHOT)
    if added:
        raise AssertionError(f"unittest.TestCase attributes were added: {sorted(added)}")


class AccessControlTests(unittest.TestCase):
    maxDiff = None

    _GUARDED_METHODS = (
        "__init__",
        "add_resource",
        "move_resource",
        "set_attribute",
        "add_role",
        "assign_role",
        "add_group",
        "add_member",
        "grant",
        "revoke",
        "check",
        "explain",
        "effective_permissions",
        "list_grants",
    )

    def setUp(self):
        assert_testcase_class_unmodified()
        self.module = self.import_candidate()
        assert_testcase_class_unmodified()

    def import_candidate(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, source)
        spec = importlib.util.spec_from_file_location("access_control_under_test", MODULE_PATH)
        module = types.ModuleType("access_control_under_test")
        module.__file__ = str(MODULE_PATH)
        module.__loader__ = spec.loader
        module.__package__ = ""
        module.__spec__ = spec
        sys.modules.pop("access_control_under_test", None)
        sys.modules["access_control_under_test"] = module
        with self.guarded_candidate_execution():
            exec(compile(source, str(MODULE_PATH), "exec"), module.__dict__)
        for name in self._GUARDED_METHODS:
            original = getattr(module.AccessControl, name)
            setattr(module.AccessControl, name, self.guard_method(original))
        return module

    @contextmanager
    def guarded_candidate_execution(self):
        original_open = builtins.open
        original_import = builtins.__import__
        original_path_open = Path.open
        original_read_text = Path.read_text
        original_read_bytes = Path.read_bytes
        original_import_module = importlib.import_module
        os_blocked = (
            "fork",
            "forkpty",
            "execl",
            "execle",
            "execlp",
            "execv",
            "execve",
            "execvp",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnv",
            "spawnve",
            "spawnvp",
            "posix_spawn",
            "posix_spawnp",
        )
        subprocess_blocked = ("Popen", "run", "call", "check_call", "check_output")
        time_blocked = (
            "time",
            "time_ns",
            "monotonic",
            "monotonic_ns",
            "perf_counter",
            "perf_counter_ns",
            "process_time",
            "process_time_ns",
            "clock_gettime",
            "sleep",
        )

        def blocked(*_args, **_kwargs):
            raise AssertionError("candidate attempted forbidden side effect")

        def guarded_import(name, *args, **kwargs):
            if str(name).split(".", 1)[0] in {"ctypes", "socket", "subprocess", "threading", "_thread", "multiprocessing"}:
                blocked()
            return original_import(name, *args, **kwargs)

        def guarded_import_module(name, *args, **kwargs):
            if str(name).split(".", 1)[0] in {"ctypes", "socket", "subprocess", "threading", "_thread", "multiprocessing"}:
                blocked()
            return original_import_module(name, *args, **kwargs)

        def guarded_open(file, *args, **kwargs):
            mode = kwargs.get("mode", args[0] if args else "r")
            if isinstance(mode, str) and not _is_write_mode(mode) and _path_is_allowed_import(file):
                return original_open(file, *args, **kwargs)
            blocked()

        def guarded_path_open(self_path, *args, **kwargs):
            mode = kwargs.get("mode", args[0] if args else "r")
            if isinstance(mode, str) and not _is_write_mode(mode) and _path_is_allowed_import(self_path):
                return original_path_open(self_path, *args, **kwargs)
            blocked()

        def guarded_read_text(self_path, *args, **kwargs):
            if _path_is_allowed_import(self_path):
                return original_read_text(self_path, *args, **kwargs)
            blocked()

        def guarded_read_bytes(self_path, *args, **kwargs):
            if _path_is_allowed_import(self_path):
                return original_read_bytes(self_path, *args, **kwargs)
            blocked()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("builtins.open", guarded_open))
            stack.enter_context(mock.patch("builtins.__import__", guarded_import))
            stack.enter_context(mock.patch("io.open", guarded_open))
            stack.enter_context(mock.patch("pathlib.Path.open", guarded_path_open))
            stack.enter_context(mock.patch("pathlib.Path.read_text", guarded_read_text))
            stack.enter_context(mock.patch("pathlib.Path.read_bytes", guarded_read_bytes))
            stack.enter_context(mock.patch("pathlib.Path.write_text", blocked))
            stack.enter_context(mock.patch("pathlib.Path.write_bytes", blocked))
            stack.enter_context(mock.patch("os.open", blocked))
            stack.enter_context(mock.patch("os.popen", blocked))
            stack.enter_context(mock.patch("os.system", blocked))
            for name in os_blocked:
                if hasattr(os, name):
                    stack.enter_context(mock.patch(f"os.{name}", blocked))
            for name in subprocess_blocked:
                stack.enter_context(mock.patch(f"subprocess.{name}", blocked))
            stack.enter_context(mock.patch("importlib.import_module", guarded_import_module))
            for name in time_blocked:
                if hasattr(time, name):
                    stack.enter_context(mock.patch(f"time.{name}", blocked))
            yield

    def guard_method(self, method):
        @functools.wraps(method)
        def wrapped(instance, *args, **kwargs):
            try:
                with self.guarded_candidate_execution():
                    return method(instance, *args, **kwargs)
            finally:
                assert_testcase_class_unmodified()

        return wrapped

    # ---- helpers -------------------------------------------------------

    def make(self, actions=None):
        if actions is None:
            return self.module.AccessControl()
        return self.module.AccessControl(actions=actions)

    def tree(self, edges, actions=None):
        ac = self.make(actions)
        for resource_id, parent in edges:
            ac.add_resource(resource_id, parent)
        return ac

    def assert_access_error(self, func, *args, **kwargs):
        with self.assertRaises(self.module.AccessError):
            func(*args, **kwargs)

    def assert_decision(self, decision, *, allowed, decided_by, effect, matched, subject, distance, inherited, priority="__auto__"):
        self.assertEqual(set(decision), DECISION_KEYS)
        self.assertEqual(decision["allowed"], allowed)
        self.assertEqual(decision["decided_by"], decided_by)
        self.assertEqual(decision["effect"], effect)
        self.assertEqual(decision["matched"], matched)
        self.assertEqual(decision["subject"], subject)
        self.assertEqual(decision["distance"], distance)
        self.assertEqual(decision["inherited"], inherited)
        if priority == "__auto__":
            priority = None if decided_by is None else 0
        self.assertEqual(decision["priority"], priority)
        self.assertIsInstance(decision["allowed"], bool)
        self.assertIsInstance(decision["inherited"], bool)

    # ---- A. public surface and validation ------------------------------

    def test_public_surface_constants_and_signatures(self):
        """The exported names, error base class, default actions, and method signatures are the contract the agent must keep."""
        self.assertTrue(issubclass(self.module.AccessError, ValueError))
        self.assertEqual(self.module.DEFAULT_ACTIONS, ("read", "write", "delete", "admin"))
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.__init__).parameters),
            ["self", "actions"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.grant).parameters),
            ["self", "resource_id", "subject", "action", "effect", "subject_kind", "inheritable", "conditions", "priority"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.revoke).parameters),
            ["self", "resource_id", "subject", "action", "subject_kind"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.check).parameters),
            ["self", "principal", "resource_id", "action", "context"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.effective_permissions).parameters),
            ["self", "principal", "resource_id", "context"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.set_attribute).parameters),
            ["self", "resource_id", "key", "value"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.add_role).parameters),
            ["self", "role_id"],
        )
        self.assertEqual(
            list(inspect.signature(self.module.AccessControl.assign_role).parameters),
            ["self", "principal", "role_id"],
        )
        ac = self.make()
        ac.add_resource("root")
        ac.grant("root", "u", "read", "allow")
        self.assertEqual(ac.check("u", "root", "read"), True)
        self.assertEqual(set(ac.list_grants("root")[0]), GRANT_KEYS)

    def test_constructor_action_validation(self):
        """A configured action set bounds every query and wildcard expansion, so invalid action sets must be rejected up front."""
        self.assert_access_error(self.make, [])
        self.assert_access_error(self.make, "read")
        self.assert_access_error(self.make, ["read", "read"])
        self.assert_access_error(self.make, ["read", ""])
        self.assert_access_error(self.make, ["read", 7])
        self.assert_access_error(self.make, ["read", True])
        self.assert_access_error(self.make, ["read", "*"])
        self.assert_access_error(self.make, ["repo..read"])
        self.assert_access_error(self.make, ["repo.*"])
        self.assert_access_error(self.make, [".read"])
        ac = self.make(["read", "share"])
        ac.add_resource("r")
        ac.grant("r", "u", "share", "allow")
        self.assertEqual(ac.check("u", "r", "share"), True)
        self.assert_access_error(ac.check, "u", "r", "write")
        dotted = self.make(["repo.read", "repo.write"])
        dotted.add_resource("d")
        dotted.grant("d", "u", "repo.read", "allow")
        self.assertEqual(dotted.check("u", "d", "repo.read"), True)

    def test_add_resource_validation(self):
        """Resource identity and parent existence are validated so the inheritance tree stays well formed."""
        ac = self.make()
        self.assert_access_error(ac.add_resource, "")
        self.assert_access_error(ac.add_resource, 5)
        ac.add_resource("a")
        self.assert_access_error(ac.add_resource, "a")
        self.assert_access_error(ac.add_resource, "b", "missing")
        ac.add_resource("b", "a")
        self.assertEqual(ac.list_grants("b"), [])

    def test_grant_validation_rejects_bad_inputs(self):
        """Grants carry the privileges, so every field must be validated before any grant is stored."""
        ac = self.tree([("r", None)])
        self.assert_access_error(ac.grant, "missing", "u", "read", "allow")
        self.assert_access_error(ac.grant, "r", "", "read", "allow")
        self.assert_access_error(ac.grant, "r", "u", "fly", "allow")
        self.assert_access_error(ac.grant, "r", "u", "read", "permit")
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", inheritable="yes")
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", inheritable=1)
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", subject_kind="role")
        self.assert_access_error(ac.grant, "r", "g", "read", "allow", subject_kind="group")
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions=[])
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={1: "x"})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"k": float("inf")})
        self.assertEqual(ac.list_grants("r"), [])

    def test_grant_validation_happens_before_mutation(self):
        """A grant call that fails validation must leave stored grants untouched."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        self.assert_access_error(ac.grant, "r", "u", "read", "deny", conditions={"bad": float("nan")})
        grants = ac.list_grants("r")
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["effect"], "allow")

    def test_query_methods_validate_resource_principal_and_action(self):
        """Queries must reject unknown resources, bad principals, and the reserved wildcard action."""
        ac = self.tree([("r", None)])
        self.assert_access_error(ac.check, "u", "missing", "read")
        self.assert_access_error(ac.check, "", "r", "read")
        self.assert_access_error(ac.check, "u", "r", "fly")
        self.assert_access_error(ac.check, "u", "r", "*")
        self.assert_access_error(ac.explain, "u", "r", "*")
        self.assert_access_error(ac.effective_permissions, "", "r")
        self.assert_access_error(ac.effective_permissions, "u", "missing")
        self.assert_access_error(ac.list_grants, "missing")

    # ---- B. principal resolution core ----------------------------------

    def test_default_is_deny_when_no_grant_applies(self):
        """With no applicable grant anywhere on the chain the answer must be deny, not allow."""
        ac = self.tree([("org", None), ("doc", "org")])
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by=None, effect=None, matched=None, subject=None, distance=None, inherited=False,
        )

    def test_direct_allow_and_direct_deny(self):
        """A grant on the queried resource itself decides at distance zero."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "write", "deny")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assertEqual(ac.check("u", "r", "write"), False)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_deny_beats_allow_at_same_resource_and_tier(self):
        """When the same resource holds both an allow and a deny for the same subject and action, deny must win."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "deny")
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_specific_action_beats_wildcard_allow_when_specific_denies(self):
        """A specific deny on a resource must override a wildcard allow on the same resource for the same subject."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "*", "allow")
        ac.grant("r", "u", "read", "deny")
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assertEqual(ac.check("u", "r", "write"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )
        self.assert_decision(
            ac.explain("u", "r", "write"),
            allowed=True, decided_by="r", effect="allow", matched="any", subject="principal", distance=0, inherited=False,
        )

    def test_specific_action_beats_wildcard_deny_when_specific_allows(self):
        """A specific allow must override a wildcard deny on the same resource for the same subject."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "*", "deny")
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assertEqual(ac.check("u", "r", "write"), False)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_inherited_allow_from_ancestor(self):
        """An inheritable allow on an ancestor applies to descendants that have no nearer applying grant."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="org", effect="allow", matched="exact", subject="principal", distance=1, inherited=True,
        )

    def test_non_inheritable_ancestor_grant_does_not_leak_to_descendant(self):
        """A grant marked non-inheritable must not reach descendant resources; this is the core leak to fix."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=False)
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by=None, effect=None, matched=None, subject=None, distance=None, inherited=False,
        )

    def test_non_inheritable_grant_still_applies_on_its_own_resource(self):
        """A non-inheritable grant must still take effect on the exact resource it is defined on."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("doc", "u", "read", "allow", inheritable=False)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="doc", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_nearer_deny_overrides_farther_allow(self):
        """A deny on the resource must override an inheritable allow on an ancestor because the nearer resource decides."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        ac.grant("doc", "u", "read", "deny")
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by="doc", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_nearer_allow_overrides_farther_deny(self):
        """A nearer allow must override a farther deny; only the nearest deciding resource counts."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "deny", inheritable=True)
        ac.grant("doc", "u", "read", "allow")
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="doc", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_wildcard_on_child_decides_before_specific_on_parent(self):
        """A wildcard grant on the queried resource makes it the deciding resource, so a specific grant on the parent is never consulted."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "deny", inheritable=True)
        ac.grant("doc", "u", "*", "allow")
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="doc", effect="allow", matched="any", subject="principal", distance=0, inherited=False,
        )

    def test_grandparent_grant_inherits_across_two_levels(self):
        """Inheritable grants reach through multiple levels when nothing nearer decides; distance reflects the hop count."""
        ac = self.tree([("org", None), ("dept", "org"), ("team", "dept"), ("doc", "team")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="org", effect="allow", matched="exact", subject="principal", distance=3, inherited=True,
        )

    def test_closest_deciding_ancestor_wins_over_higher_ancestor(self):
        """When several ancestors carry grants, the closest deciding ancestor wins and higher ones are ignored."""
        ac = self.tree([("org", None), ("dept", "org"), ("doc", "dept")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        ac.grant("dept", "u", "read", "deny", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by="dept", effect="deny", matched="exact", subject="principal", distance=1, inherited=True,
        )

    def test_non_inheritable_middle_grant_is_skipped_but_higher_inheritable_applies(self):
        """A non-inheritable grant on a middle ancestor must be skipped for a deeper descendant, letting a higher inheritable grant decide."""
        ac = self.tree([("org", None), ("dept", "org"), ("doc", "dept")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        ac.grant("dept", "u", "read", "deny", inheritable=False)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="org", effect="allow", matched="exact", subject="principal", distance=2, inherited=True,
        )
        self.assertEqual(ac.check("u", "dept", "read"), False)

    def test_principal_isolation(self):
        """A grant to one principal must never affect another principal's decision."""
        ac = self.tree([("r", None)])
        ac.grant("r", "alice", "read", "allow")
        self.assertEqual(ac.check("alice", "r", "read"), True)
        self.assertEqual(ac.check("bob", "r", "read"), False)

    def test_action_isolation(self):
        """A specific grant for one action must not decide a different action."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assertEqual(ac.check("u", "r", "write"), False)
        self.assert_decision(
            ac.explain("u", "r", "write"),
            allowed=False, decided_by=None, effect=None, matched=None, subject=None, distance=None, inherited=False,
        )

    def test_inherited_wildcard_from_ancestor_reports_wildcard_match(self):
        """An inheritable wildcard allow on an ancestor grants the action and reports a wildcard match at the right distance."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "*", "allow", inheritable=True)
        self.assert_decision(
            ac.explain("u", "doc", "delete"),
            allowed=True, decided_by="org", effect="allow", matched="any", subject="principal", distance=1, inherited=True,
        )

    # ---- C. groups and subject precedence ------------------------------

    def test_group_grant_applies_to_member(self):
        """A grant to a group must apply to its principal members and report the group subject tier."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="group", distance=0, inherited=False,
        )

    def test_group_grant_does_not_apply_to_non_member(self):
        """A group grant must not affect a principal who is not a member of that group."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "alice")
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        self.assertEqual(ac.check("alice", "r", "read"), True)
        self.assertEqual(ac.check("bob", "r", "read"), False)

    def test_principal_grant_outranks_group_grant_at_same_resource(self):
        """At one resource a direct principal grant outranks a group grant for the same action, even when the group grant denies."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "deny", subject_kind="group")
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_distance_outranks_subject_tier(self):
        """A group grant on the queried resource decides before a principal grant on an ancestor, because distance dominates the subject tier."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("doc", "eng", "read", "deny", subject_kind="group")
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by="doc", effect="deny", matched="exact", subject="group", distance=0, inherited=False,
        )

    def test_subject_tier_outranks_action_tier(self):
        """At one resource a principal wildcard grant outranks a group grant that names the action, because the subject tier dominates the action tier."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "deny", subject_kind="group")
        ac.grant("r", "u", "*", "allow")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="any", subject="principal", distance=0, inherited=False,
        )

    def test_group_specific_beats_group_wildcard(self):
        """Within the group tier on one resource, a grant naming the action outranks a group wildcard grant."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "*", "allow", subject_kind="group")
        ac.grant("r", "eng", "read", "deny", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assertEqual(ac.check("u", "r", "write"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="group", distance=0, inherited=False,
        )

    def test_deny_overrides_across_multiple_groups_in_same_tier(self):
        """When a principal belongs to two groups granting the same action at the same tier, a deny from either group wins."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_group("ops")
        ac.add_member("eng", "u")
        ac.add_member("ops", "u")
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        ac.grant("r", "ops", "read", "deny", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="group", distance=0, inherited=False,
        )

    def test_transitive_group_membership(self):
        """Membership is transitive through nested groups, so a grant to an outer group reaches members of an inner group."""
        ac = self.tree([("r", None)])
        ac.add_group("staff")
        ac.add_group("eng")
        ac.add_member("staff", "eng", member_kind="group")
        ac.add_member("eng", "u")
        ac.grant("r", "staff", "read", "allow", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="group", distance=0, inherited=False,
        )

    def test_inherited_group_grant_through_resource_tree(self):
        """A group grant inherits down the resource tree like a principal grant when nothing nearer applies."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("org", "eng", "read", "allow", subject_kind="group", inheritable=True)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=True, decided_by="org", effect="allow", matched="exact", subject="group", distance=1, inherited=True,
        )

    def test_non_inheritable_group_grant_does_not_leak(self):
        """A non-inheritable group grant must not reach descendant resources."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("org", "eng", "read", "allow", subject_kind="group", inheritable=False)
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assertEqual(ac.check("u", "org", "read"), True)

    def test_group_membership_via_two_hops(self):
        """Membership resolves through two nesting hops before reaching the principal."""
        ac = self.tree([("r", None)])
        ac.add_group("all")
        ac.add_group("staff")
        ac.add_group("eng")
        ac.add_member("all", "staff", member_kind="group")
        ac.add_member("staff", "eng", member_kind="group")
        ac.add_member("eng", "u")
        ac.grant("r", "all", "write", "allow", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "write"), True)
        self.assertEqual(ac.check("stranger", "r", "write"), False)

    # ---- D. group and member validation, cycles ------------------------

    def test_add_group_validation(self):
        """Group identifiers must be unique non-empty strings."""
        ac = self.make()
        self.assert_access_error(ac.add_group, "")
        self.assert_access_error(ac.add_group, 9)
        ac.add_group("eng")
        self.assert_access_error(ac.add_group, "eng")

    def test_add_member_validation(self):
        """Membership edges must reference an existing group, a valid member kind, and an existing nested group."""
        ac = self.make()
        ac.add_group("eng")
        self.assert_access_error(ac.add_member, "missing", "u")
        self.assert_access_error(ac.add_member, "eng", "")
        self.assert_access_error(ac.add_member, "eng", "u", "role")
        self.assert_access_error(ac.add_member, "eng", "nogroup", "group")

    def test_add_member_rejects_self_cycle(self):
        """A group cannot be a nested member of itself."""
        ac = self.make()
        ac.add_group("eng")
        self.assert_access_error(ac.add_member, "eng", "eng", "group")

    def test_add_member_rejects_transitive_cycle(self):
        """A nested-group edge that would close a membership cycle must be rejected."""
        ac = self.tree([("r", None)])
        ac.add_group("a")
        ac.add_group("b")
        ac.add_group("c")
        ac.add_member("a", "b", member_kind="group")
        ac.add_member("b", "c", member_kind="group")
        self.assert_access_error(ac.add_member, "c", "a", "group")
        ac.add_member("c", "u")
        ac.grant("r", "a", "read", "allow", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), True)

    def test_idempotent_membership(self):
        """Adding the same member twice does not change membership."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), True)

    # ---- E. effective_permissions --------------------------------------

    def test_effective_permissions_sorted_subset(self):
        """effective_permissions returns the configured actions that resolve to allow, in sorted order."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "delete", "allow")
        self.assertEqual(ac.effective_permissions("u", "r"), ["delete", "read"])

    def test_effective_permissions_wildcard_with_carveout(self):
        """A wildcard allow grants every configured action except those a specific deny removes."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "*", "allow")
        ac.grant("r", "u", "delete", "deny")
        self.assertEqual(ac.effective_permissions("u", "r"), ["admin", "read", "write"])

    def test_effective_permissions_empty_when_nothing_allowed(self):
        """With no allowing grant the effective permission list is empty."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "deny")
        self.assertEqual(ac.effective_permissions("u", "r"), [])

    def test_effective_permissions_returns_fresh_list(self):
        """The returned permission list must be a fresh object that does not alias internal state."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        first = ac.effective_permissions("u", "r")
        first.append("delete")
        self.assertEqual(ac.effective_permissions("u", "r"), ["read"])

    def test_effective_permissions_respects_inheritance_and_non_inheritable(self):
        """effective_permissions honors inherited allows and skips non-inheritable ancestor grants."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        ac.grant("org", "u", "write", "allow", inheritable=False)
        self.assertEqual(ac.effective_permissions("u", "doc"), ["read"])
        self.assertEqual(ac.effective_permissions("u", "org"), ["read", "write"])

    def test_effective_permissions_mixes_group_and_principal(self):
        """effective_permissions combines group grants with a higher-ranked principal carve-out."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        ac.grant("r", "eng", "write", "allow", subject_kind="group")
        ac.grant("r", "u", "write", "deny")
        self.assertEqual(ac.effective_permissions("u", "r"), ["read"])

    # ---- F. revoke -----------------------------------------------------

    def test_revoke_removes_both_effects_for_exact_action(self):
        """Revoking a (subject, action) pair removes both its allow and deny entries and reports that something was removed."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "deny")
        self.assertEqual(ac.revoke("r", "u", "read"), True)
        self.assertEqual(ac.list_grants("r"), [])
        self.assertEqual(ac.check("u", "r", "read"), False)

    def test_revoke_returns_false_when_nothing_matches(self):
        """Revoking a pair with no stored grant must return False and change nothing."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(ac.revoke("r", "u", "write"), False)
        self.assertEqual(ac.revoke("r", "other", "read"), False)
        self.assertEqual(len(ac.list_grants("r")), 1)

    def test_revoke_affects_only_the_named_resource(self):
        """Revoking on one resource must not touch grants on its parent or its child."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        ac.grant("doc", "u", "read", "allow")
        self.assertEqual(ac.revoke("doc", "u", "read"), True)
        self.assertEqual(ac.list_grants("doc"), [])
        self.assertEqual(len(ac.list_grants("org")), 1)
        self.assertEqual(ac.check("u", "doc", "read"), True)

    def test_revoke_specific_action_leaves_other_action_and_wildcard(self):
        """Revoking one action must leave grants for other actions and wildcard grants intact."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "write", "allow")
        ac.grant("r", "u", "*", "allow")
        self.assertEqual(ac.revoke("r", "u", "read"), True)
        remaining = {(g["action"], g["effect"]) for g in ac.list_grants("r")}
        self.assertEqual(remaining, {("write", "allow"), ("*", "allow")})

    def test_revoke_wildcard_removes_only_wildcard_grants(self):
        """Revoking the wildcard action removes only wildcard grants and keeps specific-action grants."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "*", "deny")
        self.assertEqual(ac.revoke("r", "u", "*"), True)
        remaining = {(g["action"], g["effect"]) for g in ac.list_grants("r")}
        self.assertEqual(remaining, {("read", "allow")})

    def test_revoke_distinguishes_principal_from_group_subject(self):
        """Revoke must distinguish the subject kind so a principal revoke does not remove a like-named group grant."""
        ac = self.tree([("r", None)])
        ac.add_group("u")
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "allow", subject_kind="group")
        self.assertEqual(ac.revoke("r", "u", "read"), True)
        remaining = [(g["subject"], g["subject_kind"]) for g in ac.list_grants("r")]
        self.assertEqual(remaining, [("u", "group")])
        self.assertEqual(ac.revoke("r", "u", "read", subject_kind="group"), True)
        self.assertEqual(ac.list_grants("r"), [])

    def test_revoke_validates_inputs(self):
        """Revoke must validate the resource, subject, action, and subject kind like the other mutating calls."""
        ac = self.tree([("r", None)])
        self.assert_access_error(ac.revoke, "missing", "u", "read")
        self.assert_access_error(ac.revoke, "r", "", "read")
        self.assert_access_error(ac.revoke, "r", "u", "fly")
        self.assert_access_error(ac.revoke, "r", "u", "read", subject_kind="user")

    # ---- G. grant identity ---------------------------------------------

    def test_identical_grant_is_idempotent(self):
        """Granting the same subject, action, and effect twice must not create a duplicate entry."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(len(ac.list_grants("r")), 1)

    def test_allow_and_deny_for_same_action_coexist(self):
        """An allow and a deny for the same subject and action are distinct grants that both appear in the listing."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "deny")
        listed = {(g["action"], g["effect"]) for g in ac.list_grants("r")}
        self.assertEqual(listed, {("read", "allow"), ("read", "deny")})

    def test_principal_and_group_grant_with_same_name_coexist(self):
        """A principal grant and a group grant sharing a subject name are distinct grants."""
        ac = self.tree([("r", None)])
        ac.add_group("u")
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "allow", subject_kind="group")
        listed = {(g["subject"], g["subject_kind"]) for g in ac.list_grants("r")}
        self.assertEqual(listed, {("u", "principal"), ("u", "group")})

    def test_regrant_same_grant_updates_inheritable_and_conditions(self):
        """Re-granting the same subject, action, and effect updates its inheritable flag and conditions in place."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True, conditions={"v": {"equals": 1}})
        ac.grant("org", "u", "read", "allow", inheritable=False, conditions={"v": {"equals": 2}})
        grants = ac.list_grants("org")
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["inheritable"], False)
        self.assertEqual(grants[0]["conditions"], {"v": {"equals": 2}})
        # The updated grant now requires context {"v": 2} and is non-inheritable.
        self.assertEqual(ac.check("u", "org", "read", {"v": 2}), True)
        self.assertEqual(ac.check("u", "doc", "read", {"v": 2}), False)
        self.assertEqual(ac.check("u", "org", "read", {"v": 1}), False)

    # ---- H. deep copy and isolation ------------------------------------

    def test_grant_deep_copies_conditions_in(self):
        """Mutating the caller's conditions dict after a grant must not change the stored grant."""
        ac = self.tree([("r", None)])
        conditions = {"net": {"equals": {"cidr": ["10.0.0.0/8"]}}}
        ac.grant("r", "u", "read", "allow", conditions=conditions)
        conditions["net"]["equals"]["cidr"].append("0.0.0.0/0")
        stored = ac.list_grants("r")[0]["conditions"]
        self.assertEqual(stored, {"net": {"equals": {"cidr": ["10.0.0.0/8"]}}})

    def test_list_grants_schema_order_and_deep_copy_out(self):
        """list_grants returns deep-copied grant dicts with the exact key set, sorted, so callers cannot mutate internal state."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.grant("r", "bob", "write", "deny", inheritable=False, conditions={"k": {"in": [1]}})
        ac.grant("r", "alice", "read", "allow", inheritable=True)
        ac.grant("r", "eng", "read", "allow", subject_kind="group")
        grants = ac.list_grants("r")
        for g in grants:
            self.assertEqual(set(g), GRANT_KEYS)
        self.assertEqual(
            [(g["subject_kind"], g["subject"], g["action"], g["effect"]) for g in grants],
            [
                ("group", "eng", "read", "allow"),
                ("principal", "alice", "read", "allow"),
                ("principal", "bob", "write", "deny"),
            ],
        )
        self.assertEqual(grants[1]["conditions"], {})
        grants[2]["conditions"]["k"]["in"].append(2)
        self.assertEqual(ac.list_grants("r")[2]["conditions"], {"k": {"in": [1]}})

    def test_instances_do_not_share_state(self):
        """Separate AccessControl instances must keep fully independent resources, groups, and grants."""
        first = self.make()
        first.add_resource("r")
        first.add_group("eng")
        first.add_member("eng", "u")
        first.grant("r", "eng", "read", "allow", subject_kind="group")
        second = self.make()
        self.assert_access_error(second.list_grants, "r")
        self.assert_access_error(second.check, "u", "r", "read")
        second.add_resource("r")
        self.assertEqual(second.list_grants("r"), [])
        self.assertEqual(second.check("u", "r", "read"), False)
        self.assertEqual(first.check("u", "r", "read"), True)

    def test_distinct_action_sets_per_instance(self):
        """Each instance keeps its own configured action set; one instance's actions must not bleed into another."""
        custom = self.make(["read", "share"])
        custom.add_resource("r")
        custom.grant("r", "u", "share", "allow")
        self.assertEqual(custom.check("u", "r", "share"), True)
        default = self.make()
        default.add_resource("r")
        self.assert_access_error(default.check, "u", "r", "share")

    # ---- I. move_resource and cycles -----------------------------------

    def test_move_resource_changes_inheritance(self):
        """Re-parenting a resource changes which ancestor grants it inherits."""
        ac = self.tree([("a", None), ("b", None), ("doc", "a")])
        ac.grant("a", "u", "read", "allow", inheritable=True)
        ac.grant("b", "u", "read", "deny", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        ac.move_resource("doc", "b")
        self.assertEqual(ac.check("u", "doc", "read"), False)

    def test_move_resource_to_root_removes_inheritance(self):
        """Moving a resource to be a root (no parent) stops it from inheriting any ancestor grant."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), True)
        ac.move_resource("doc", None)
        self.assertEqual(ac.check("u", "doc", "read"), False)

    def test_move_resource_rejects_self_parent(self):
        """A resource cannot become its own parent; the structure must be unchanged after the rejected move."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assert_access_error(ac.move_resource, "doc", "doc")
        self.assertEqual(ac.check("u", "doc", "read"), True)

    def test_move_resource_rejects_descendant_parent(self):
        """Re-parenting a resource under one of its own descendants would create a cycle and must be rejected, leaving inheritance intact."""
        ac = self.tree([("org", None), ("dept", "org"), ("team", "dept")])
        ac.grant("org", "u", "read", "allow", inheritable=True)
        self.assert_access_error(ac.move_resource, "org", "team")
        self.assertEqual(ac.check("u", "team", "read"), True)
        self.assert_access_error(ac.move_resource, "org", "org")

    def test_move_resource_validates_targets(self):
        """move_resource must reject unknown resources and unknown new parents."""
        ac = self.tree([("org", None), ("doc", "org")])
        self.assert_access_error(ac.move_resource, "missing", "org")
        self.assert_access_error(ac.move_resource, "doc", "missing")

    def test_deep_chain_resolution_picks_first_decider(self):
        """Across a deep chain with several grants, resolution stops at the first deciding resource from the queried node upward."""
        ac = self.tree([
            ("l0", None), ("l1", "l0"), ("l2", "l1"), ("l3", "l2"), ("l4", "l3"),
        ])
        ac.grant("l0", "u", "read", "allow", inheritable=True)
        ac.grant("l2", "u", "read", "deny", inheritable=True)
        ac.grant("l3", "u", "*", "allow", inheritable=True)
        self.assert_decision(
            ac.explain("u", "l4", "read"),
            allowed=True, decided_by="l3", effect="allow", matched="any", subject="principal", distance=1, inherited=True,
        )
        self.assert_decision(
            ac.explain("u", "l2", "read"),
            allowed=False, decided_by="l2", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )

    # ---- J. conditional grants (context gating) ------------------------

    def test_conditional_grant_requires_matching_context(self):
        """A grant with conditions applies only when the query context provides matching values."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"env": {"equals": "prod"}})
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assertEqual(ac.check("u", "r", "read", {"env": "dev"}), False)
        self.assertEqual(ac.check("u", "r", "read", {"env": "prod"}), True)
        self.assert_decision(
            ac.explain("u", "r", "read", {"env": "prod"}),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_conditional_grant_requires_all_condition_keys(self):
        """Every key in a grant's conditions must be present and equal in the context for the grant to apply."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"env": {"equals": "prod"}, "region": {"equals": "us"}})
        self.assertEqual(ac.check("u", "r", "read", {"env": "prod"}), False)
        self.assertEqual(ac.check("u", "r", "read", {"env": "prod", "region": "eu"}), False)
        self.assertEqual(ac.check("u", "r", "read", {"env": "prod", "region": "us"}), True)
        self.assertEqual(ac.check("u", "r", "read", {"env": "prod", "region": "us", "extra": 1}), True)

    def test_empty_conditions_apply_regardless_of_context(self):
        """A grant with no conditions applies under any context, including none."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assertEqual(ac.check("u", "r", "read", {"anything": "here"}), True)

    def test_conditional_deny_falls_through_to_unconditional_allow(self):
        """A conditional deny that the context does not satisfy is excluded, leaving an unconditional allow to win; when the context satisfies it, the deny rejoins the deciding set and wins."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "read", "deny", conditions={"breakglass": {"equals": "on"}})
        self.assertEqual(ac.check("u", "r", "read"), True)
        self.assertEqual(ac.check("u", "r", "read", {"breakglass": "off"}), True)
        self.assertEqual(ac.check("u", "r", "read", {"breakglass": "on"}), False)
        self.assert_decision(
            ac.explain("u", "r", "read", {"breakglass": "on"}),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_conditional_exclusion_drops_to_group_tier(self):
        """When a conditional principal grant is excluded, a group grant at the same resource becomes the deciding set."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "u", "read", "allow", conditions={"mfa": {"equals": "yes"}})
        ac.grant("r", "eng", "read", "deny", subject_kind="group")
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assert_decision(
            ac.explain("u", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="group", distance=0, inherited=False,
        )
        self.assertEqual(ac.check("u", "r", "read", {"mfa": "yes"}), True)
        self.assert_decision(
            ac.explain("u", "r", "read", {"mfa": "yes"}),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_conditional_exclusion_changes_deciding_distance(self):
        """When a conditional grant on the queried resource is excluded, a farther inheritable grant decides instead."""
        ac = self.tree([("org", None), ("doc", "org")])
        ac.grant("doc", "u", "read", "allow", conditions={"shift": {"equals": "day"}})
        ac.grant("org", "u", "read", "deny", inheritable=True)
        self.assertEqual(ac.check("u", "doc", "read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "read"),
            allowed=False, decided_by="org", effect="deny", matched="exact", subject="principal", distance=1, inherited=True,
        )
        self.assertEqual(ac.check("u", "doc", "read", {"shift": "day"}), True)
        self.assert_decision(
            ac.explain("u", "doc", "read", {"shift": "day"}),
            allowed=True, decided_by="doc", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_context_validation(self):
        """A supplied context must be a dictionary with string keys and JSON-compatible values."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        self.assert_access_error(ac.check, "u", "r", "read", [])
        self.assert_access_error(ac.check, "u", "r", "read", {1: "x"})
        self.assert_access_error(ac.check, "u", "r", "read", {"k": float("inf")})
        self.assert_access_error(ac.explain, "u", "r", "read", {"k": float("nan")})
        self.assert_access_error(ac.effective_permissions, "u", "r", "not-a-dict")

    def test_effective_permissions_uses_context(self):
        """effective_permissions threads the context so conditional grants count only when satisfied."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow")
        ac.grant("r", "u", "write", "allow", conditions={"env": {"equals": "prod"}})
        self.assertEqual(ac.effective_permissions("u", "r"), ["read"])
        self.assertEqual(ac.effective_permissions("u", "r", {"env": "prod"}), ["read", "write"])

    def test_conditional_group_grant_gated_by_context(self):
        """A conditional group grant applies to members only when the context satisfies its conditions."""
        ac = self.tree([("r", None)])
        ac.add_group("eng")
        ac.add_member("eng", "u")
        ac.grant("r", "eng", "read", "allow", subject_kind="group", conditions={"tenant": {"equals": "acme"}})
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assertEqual(ac.check("u", "r", "read", {"tenant": "acme"}), True)

    def test_matcher_in_operator(self):
        """An 'in' matcher is satisfied when the context value is one of the listed values."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"region": {"in": ["us", "eu"]}})
        self.assertEqual(ac.check("u", "r", "read", {"region": "us"}), True)
        self.assertEqual(ac.check("u", "r", "read", {"region": "eu"}), True)
        self.assertEqual(ac.check("u", "r", "read", {"region": "ap"}), False)
        self.assertEqual(ac.check("u", "r", "read"), False)

    def test_matcher_at_least_and_at_most(self):
        """The 'at_least' and 'at_most' matchers compare numeric context values inclusively."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"level": {"at_least": 3}})
        ac.grant("r", "u", "write", "allow", conditions={"level": {"at_most": 3}})
        self.assertEqual(ac.check("u", "r", "read", {"level": 3}), True)
        self.assertEqual(ac.check("u", "r", "read", {"level": 5}), True)
        self.assertEqual(ac.check("u", "r", "read", {"level": 2}), False)
        self.assertEqual(ac.check("u", "r", "write", {"level": 3}), True)
        self.assertEqual(ac.check("u", "r", "write", {"level": 4}), False)

    def test_comparison_matcher_requires_real_number_context(self):
        """A comparison matcher is unsatisfied when the context value is missing, a boolean, or not a number."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"level": {"at_least": 1}})
        self.assertEqual(ac.check("u", "r", "read", {"level": True}), False)
        self.assertEqual(ac.check("u", "r", "read", {"level": "5"}), False)
        self.assertEqual(ac.check("u", "r", "read"), False)
        self.assertEqual(ac.check("u", "r", "read", {"level": 1}), True)

    def test_matcher_equality_distinguishes_bool_from_number(self):
        """Equality in 'equals' and 'in' treats booleans as distinct from numbers, so True never equals 1."""
        ac = self.tree([("r", None)])
        ac.grant("r", "u", "read", "allow", conditions={"flag": {"equals": 1}})
        ac.grant("r", "u", "write", "allow", conditions={"tag": {"in": [1, "x"]}})
        self.assertEqual(ac.check("u", "r", "read", {"flag": True}), False)
        self.assertEqual(ac.check("u", "r", "read", {"flag": 1}), True)
        self.assertEqual(ac.check("u", "r", "write", {"tag": True}), False)
        self.assertEqual(ac.check("u", "r", "write", {"tag": 1}), True)

    def test_matcher_structure_validation(self):
        """Each condition value must be a single-operator matcher with a valid operand."""
        ac = self.tree([("r", None)])
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"env": "prod"})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"env": {}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"env": {"equals": "prod", "in": ["prod"]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"env": {"matches": "prod"}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"lvl": {"at_least": "3"}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"lvl": {"at_least": True}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"r": {"in": "us"}})
        self.assertEqual(ac.list_grants("r"), [])

    # ---- K. hierarchical actions and prefix matching -------------------

    HIER = ("repo.read", "repo.write", "repo.admin", "ci.run", "repo.sub.read")

    def hier_tree(self, edges):
        ac = self.make(self.HIER)
        for resource_id, parent in edges:
            ac.add_resource(resource_id, parent)
        return ac

    def test_prefix_pattern_matches_within_namespace_only(self):
        """A 'P.*' grant applies to actions inside the P namespace and to no others."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "allow")
        self.assertEqual(ac.check("u", "r", "repo.read"), True)
        self.assertEqual(ac.check("u", "r", "repo.write"), True)
        self.assertEqual(ac.check("u", "r", "ci.run"), False)
        self.assert_decision(
            ac.explain("u", "r", "repo.read"),
            allowed=True, decided_by="r", effect="allow", matched="prefix", subject="principal", distance=0, inherited=False,
        )

    def test_exact_action_outranks_prefix_pattern(self):
        """An exact-action grant is more specific than a 'P.*' pattern, so an exact allow beats a pattern deny."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "deny")
        ac.grant("r", "u", "repo.read", "allow")
        self.assertEqual(ac.check("u", "r", "repo.read"), True)
        self.assertEqual(ac.check("u", "r", "repo.write"), False)
        self.assert_decision(
            ac.explain("u", "r", "repo.read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_deeper_prefix_outranks_shallower_prefix(self):
        """A longer 'P.*' prefix is more specific than a shorter one, so the deeper pattern decides."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "deny")
        ac.grant("r", "u", "repo.sub.*", "allow")
        self.assertEqual(ac.check("u", "r", "repo.sub.read"), True)
        self.assertEqual(ac.check("u", "r", "repo.read"), False)
        self.assert_decision(
            ac.explain("u", "r", "repo.sub.read"),
            allowed=True, decided_by="r", effect="allow", matched="prefix", subject="principal", distance=0, inherited=False,
        )

    def test_prefix_respects_segment_boundary(self):
        """A 'P.*' pattern must match only on whole-segment boundaries, never a mere string prefix."""
        ac = self.make(("repo.read", "repository.read"))
        ac.add_resource("r")
        ac.grant("r", "u", "repo.*", "allow")
        self.assertEqual(ac.check("u", "r", "repo.read"), True)
        self.assertEqual(ac.check("u", "r", "repository.read"), False)

    def test_wildcard_any_is_least_specific(self):
        """The '*' grant is the least specific match, so a 'P.*' pattern outranks it within its namespace."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "*", "allow")
        ac.grant("r", "u", "repo.*", "deny")
        self.assertEqual(ac.check("u", "r", "repo.read"), False)
        self.assertEqual(ac.check("u", "r", "ci.run"), True)
        self.assert_decision(
            ac.explain("u", "r", "repo.read"),
            allowed=False, decided_by="r", effect="deny", matched="prefix", subject="principal", distance=0, inherited=False,
        )
        self.assert_decision(
            ac.explain("u", "r", "ci.run"),
            allowed=True, decided_by="r", effect="allow", matched="any", subject="principal", distance=0, inherited=False,
        )

    def test_prefix_pattern_requires_proper_prefix(self):
        """A 'P.*' pattern does not match the namespace root action P itself."""
        ac = self.make(("repo", "repo.read"))
        ac.add_resource("r")
        ac.grant("r", "u", "repo.*", "allow")
        self.assertEqual(ac.check("u", "r", "repo.read"), True)
        self.assertEqual(ac.check("u", "r", "repo"), False)

    def test_deny_override_within_prefix_tier(self):
        """Two patterns of equal specificity for the action put both in the deciding set, so a deny wins."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "allow")
        ac.grant("r", "u", "repo.*", "deny")
        self.assertEqual(ac.check("u", "r", "repo.read"), False)

    def test_grant_action_pattern_validation(self):
        """Grant actions accept '*', exact configured actions, and well-formed 'P.*' patterns, and reject malformed ones."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "allow")
        ac.grant("r", "u", "*", "allow")
        ac.grant("r", "u", "repo.sub.*", "allow")
        self.assert_access_error(ac.grant, "r", "u", "repo.*.read", "allow")
        self.assert_access_error(ac.grant, "r", "u", ".*", "allow")
        self.assert_access_error(ac.grant, "r", "u", "repo..*", "allow")
        self.assert_access_error(ac.grant, "r", "u", "repo*", "allow")
        self.assert_access_error(ac.grant, "r", "u", "ci.config", "allow")

    def test_query_rejects_pattern_and_wildcard_actions(self):
        """Only exact configured actions can be queried; patterns and '*' are not queryable."""
        ac = self.hier_tree([("r", None)])
        self.assert_access_error(ac.check, "u", "r", "repo.*")
        self.assert_access_error(ac.check, "u", "r", "*")
        self.assert_access_error(ac.explain, "u", "r", "repo.sub.*")

    def test_revoke_pattern_removes_only_that_pattern(self):
        """Revoking a 'P.*' pattern removes only the pattern grants, leaving exact-action grants in place."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.read", "allow")
        ac.grant("r", "u", "repo.*", "allow")
        self.assertEqual(ac.revoke("r", "u", "repo.*"), True)
        remaining = [g["action"] for g in ac.list_grants("r")]
        self.assertEqual(remaining, ["repo.read"])
        self.assertEqual(ac.check("u", "r", "repo.read"), True)

    def test_effective_permissions_with_prefix_pattern(self):
        """effective_permissions expands a 'P.*' allow across exactly the namespace's configured actions."""
        ac = self.hier_tree([("r", None)])
        ac.grant("r", "u", "repo.*", "allow")
        ac.grant("r", "u", "repo.admin", "deny")
        self.assertEqual(
            ac.effective_permissions("u", "r"),
            ["repo.read", "repo.sub.read", "repo.write"],
        )

    def test_inherited_prefix_pattern_beats_nearer_wildcard(self):
        """Specificity is compared only within the nearest deciding resource: a nearer '*' decides before an inherited 'repo.*'."""
        ac = self.hier_tree([("org", None), ("doc", "org")])
        ac.grant("org", "u", "repo.*", "allow", inheritable=True)
        ac.grant("doc", "u", "*", "deny")
        self.assertEqual(ac.check("u", "doc", "repo.read"), False)
        self.assert_decision(
            ac.explain("u", "doc", "repo.read"),
            allowed=False, decided_by="doc", effect="deny", matched="any", subject="principal", distance=0, inherited=False,
        )


    # ---- L. roles (subject tier between principal and group) -----------

    def test_role_grant_applies_to_assigned_principal(self):
        """A grant to a role applies to principals assigned that role and reports the 'role' subject tier."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.assign_role("alice", "editor")
        ac.grant("r", "editor", "write", "allow", subject_kind="role")
        self.assert_decision(
            ac.explain("alice", "r", "write"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="role", distance=0, inherited=False,
        )
        self.assertEqual(ac.check("bob", "r", "write"), False)

    def test_role_grant_ignored_for_unassigned_principal(self):
        """A role grant must not affect a principal who has not been assigned that role."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.add_role("viewer")
        ac.assign_role("alice", "viewer")
        ac.grant("r", "editor", "write", "allow", subject_kind="role")
        self.assertEqual(ac.check("alice", "r", "write"), False)

    def test_group_membership_does_not_confer_role(self):
        """A role assigned to a name that also happens to be a group must not reach that group's members; only direct assignment confers a role."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_group("team")
        ac.add_member("team", "alice")
        ac.add_role("editor")
        ac.assign_role("team", "editor")
        ac.grant("r", "editor", "read", "allow", subject_kind="role")
        self.assertEqual(ac.check("alice", "r", "read"), False)
        self.assertEqual(ac.check("team", "r", "read"), True)

    def test_principal_tier_outranks_role_tier(self):
        """At one resource a direct principal grant outranks a role grant for the same action, so a principal deny beats a role allow."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.assign_role("alice", "editor")
        ac.grant("r", "editor", "write", "allow", subject_kind="role")
        ac.grant("r", "alice", "write", "deny")
        self.assert_decision(
            ac.explain("alice", "r", "write"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="principal", distance=0, inherited=False,
        )

    def test_role_tier_outranks_group_tier(self):
        """A role grant is more specific than a group grant at the same resource, so a role allow beats a group deny."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.assign_role("alice", "editor")
        ac.add_group("team")
        ac.add_member("team", "alice")
        ac.grant("r", "editor", "write", "allow", subject_kind="role")
        ac.grant("r", "team", "write", "deny", subject_kind="group")
        self.assert_decision(
            ac.explain("alice", "r", "write"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="role", distance=0, inherited=False,
        )

    def test_role_grant_requires_existing_role(self):
        """A grant with subject_kind 'role' must name a role that was registered with add_role."""
        ac = self.make()
        ac.add_resource("r")
        self.assert_access_error(ac.grant, "r", "ghost", "read", "allow", subject_kind="role")
        self.assertEqual(ac.list_grants("r"), [])

    def test_add_role_and_assign_validation(self):
        """Role registration and assignment validate identifiers and existence like the other registries."""
        ac = self.make()
        self.assert_access_error(ac.add_role, "")
        self.assert_access_error(ac.add_role, 5)
        ac.add_role("editor")
        self.assert_access_error(ac.add_role, "editor")
        self.assert_access_error(ac.assign_role, "alice", "ghost")
        self.assert_access_error(ac.assign_role, "", "editor")
        ac.assign_role("alice", "editor")
        ac.assign_role("alice", "editor")  # idempotent

    def test_role_deny_override_within_tier(self):
        """Two roles granting the same action at the same resource form one deciding set, so a deny from either wins."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.add_role("auditor")
        ac.assign_role("alice", "editor")
        ac.assign_role("alice", "auditor")
        ac.grant("r", "editor", "write", "allow", subject_kind="role")
        ac.grant("r", "auditor", "write", "deny", subject_kind="role")
        self.assertEqual(ac.check("alice", "r", "write"), False)

    def test_revoke_distinguishes_role_subject(self):
        """Revoke must distinguish the role subject kind so a role revoke does not remove a like-named principal grant."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.grant("r", "editor", "read", "allow", subject_kind="role")
        ac.grant("r", "editor", "read", "allow")  # principal named "editor"
        self.assertEqual(ac.revoke("r", "editor", "read", subject_kind="role"), True)
        remaining = ac.list_grants("r")
        self.assertEqual([g["subject_kind"] for g in remaining], ["principal"])

    # ---- M. grant priority (dominates distance and tier) ---------------

    def test_priority_overrides_distance(self):
        """A higher-priority inheritable ancestor grant decides over a nearer lower-priority grant, because priority is compared before distance."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.grant("child", "alice", "read", "deny")
        ac.grant("root", "alice", "read", "allow", priority=5)
        self.assert_decision(
            ac.explain("alice", "child", "read"),
            allowed=True, decided_by="root", effect="allow", matched="exact", subject="principal",
            distance=1, inherited=True, priority=5,
        )

    def test_higher_priority_deny_beats_nearer_allow(self):
        """A high-priority inheritable deny on an ancestor overrides a default-priority allow on the queried resource."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.grant("child", "alice", "read", "allow")
        ac.grant("root", "alice", "read", "deny", priority=3)
        self.assert_decision(
            ac.explain("alice", "child", "read"),
            allowed=False, decided_by="root", effect="deny", matched="exact", subject="principal",
            distance=1, inherited=True, priority=3,
        )

    def test_priority_tie_falls_back_to_distance(self):
        """When priorities tie, the nearer resource decides, so distance is the next comparison after priority."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.grant("child", "alice", "read", "allow", priority=2)
        ac.grant("root", "alice", "read", "deny", priority=2)
        self.assert_decision(
            ac.explain("alice", "child", "read"),
            allowed=True, decided_by="child", effect="allow", matched="exact", subject="principal",
            distance=0, inherited=False, priority=2,
        )

    def test_priority_overrides_subject_tier(self):
        """At one resource a higher-priority group grant beats a default-priority principal grant, because priority is compared before the subject tier."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_group("team")
        ac.add_member("team", "alice")
        ac.grant("r", "alice", "read", "allow")
        ac.grant("r", "team", "read", "deny", subject_kind="group", priority=4)
        self.assert_decision(
            ac.explain("alice", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="group",
            distance=0, inherited=False, priority=4,
        )

    def test_negative_priority_loses_to_default(self):
        """A negative-priority deny loses to a default-priority allow on the same resource for the same subject and action."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow")
        ac.grant("r", "alice", "read", "deny", priority=-1)
        self.assert_decision(
            ac.explain("alice", "r", "read"),
            allowed=True, decided_by="r", effect="allow", matched="exact", subject="principal",
            distance=0, inherited=False, priority=0,
        )

    def test_deny_override_within_same_priority_set(self):
        """An allow and a deny that tie on the full rank, including priority, both decide and the deny wins."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", priority=7)
        ac.grant("r", "alice", "read", "deny", priority=7)
        self.assert_decision(
            ac.explain("alice", "r", "read"),
            allowed=False, decided_by="r", effect="deny", matched="exact", subject="principal",
            distance=0, inherited=False, priority=7,
        )

    def test_priority_must_be_non_boolean_int(self):
        """priority must be an integer and a boolean is not accepted, since booleans are not a meaningful precedence."""
        ac = self.make()
        ac.add_resource("r")
        self.assert_access_error(ac.grant, "r", "alice", "read", "allow", priority=True)
        self.assert_access_error(ac.grant, "r", "alice", "read", "allow", priority=1.0)
        self.assert_access_error(ac.grant, "r", "alice", "read", "allow", priority="1")
        self.assertEqual(ac.list_grants("r"), [])
        ac.grant("r", "alice", "read", "allow", priority=-3)
        self.assertEqual(ac.list_grants("r")[0]["priority"], -3)

    def test_regrant_updates_priority(self):
        """Re-granting the same subject, action, and effect updates the stored priority in place rather than adding a duplicate."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", priority=1)
        ac.grant("r", "alice", "read", "allow", priority=9)
        grants = ac.list_grants("r")
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["priority"], 9)

    # ---- N. resource attributes and resource-sourced conditions --------

    def test_set_attribute_validation(self):
        """Attribute keys must be non-empty strings on a known resource and values must be JSON-compatible."""
        ac = self.make()
        self.assert_access_error(ac.set_attribute, "ghost", "k", 1)
        ac.add_resource("r")
        self.assert_access_error(ac.set_attribute, "r", "", 1)
        self.assert_access_error(ac.set_attribute, "r", 5, 1)
        self.assert_access_error(ac.set_attribute, "r", "k", {1, 2})
        ac.set_attribute("r", "k", 1)

    def test_set_attribute_overwrites_existing_key(self):
        """Setting an existing attribute key replaces its value, so conditions see only the latest value, not the old one."""
        ac = self.make()
        ac.add_resource("r")
        ac.set_attribute("r", "tier", 1)
        ac.set_attribute("r", "tier", 5)
        ac.grant("r", "alice", "read", "allow", conditions={"resource:tier": {"at_least": 5}})
        self.assertEqual(ac.check("alice", "r", "read"), True)
        ac.grant("r", "bob", "read", "allow", conditions={"resource:tier": {"equals": 1}})
        self.assertEqual(ac.check("bob", "r", "read"), False)

    def test_resource_id_and_principal_reject_boolean(self):
        """A boolean is not a string, so it is rejected as a resource_id for add_resource and as a principal for check and explain."""
        ac = self.make()
        self.assert_access_error(ac.add_resource, True)
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow")
        self.assert_access_error(ac.check, True, "r", "read")
        self.assert_access_error(ac.explain, True, "r", "read")

    def test_attribute_inherits_from_ancestor(self):
        """A resource-sourced condition reads the attribute inherited from an ancestor when the queried resource does not set it."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.set_attribute("root", "tier", 5)
        ac.grant("child", "alice", "read", "allow", conditions={"resource:tier": {"at_least": 3}})
        self.assertEqual(ac.check("alice", "child", "read"), True)

    def test_attribute_override_nearest_resource_wins(self):
        """When an attribute is set on both an ancestor and the queried resource, the queried resource's value is used."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.set_attribute("root", "tier", 5)
        ac.set_attribute("child", "tier", 1)
        ac.grant("child", "alice", "read", "allow", conditions={"resource:tier": {"at_least": 3}})
        self.assertEqual(ac.check("alice", "child", "read"), False)

    def test_resource_condition_missing_attribute_fails(self):
        """A resource-sourced condition fails when neither the resource nor any ancestor defines the attribute."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"resource:tier": {"at_least": 1}})
        self.assertEqual(ac.check("alice", "r", "read"), False)

    def test_inherited_grant_uses_queried_resource_attributes(self):
        """A grant inherited from an ancestor evaluates its resource-sourced condition against the queried resource's effective attributes, not the grant's resource."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.set_attribute("child", "zone", "eu")
        ac.grant("root", "alice", "read", "allow", inheritable=True, conditions={"resource:zone": {"equals": "eu"}})
        self.assertEqual(ac.check("alice", "child", "read"), True)
        self.assertEqual(ac.check("alice", "root", "read"), False)

    def test_resource_and_context_conditions_combined(self):
        """A grant carrying both a resource-sourced and a context-sourced condition applies only when both are satisfied."""
        ac = self.make()
        ac.add_resource("r")
        ac.set_attribute("r", "tier", 5)
        ac.grant("r", "alice", "read", "allow",
                 conditions={"resource:tier": {"at_least": 3}, "env": {"equals": "prod"}})
        self.assertEqual(ac.check("alice", "r", "read", {"env": "prod"}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"env": "dev"}), False)
        self.assertEqual(ac.check("alice", "r", "read"), False)

    def test_attribute_value_is_deep_copied(self):
        """A stored attribute must not share mutable state with the caller's value, so later mutation does not change decisions."""
        ac = self.make()
        ac.add_resource("r")
        tags = ["a"]
        ac.set_attribute("r", "tags", tags)
        tags.append("b")
        ac.grant("r", "alice", "read", "allow", conditions={"resource:tags": {"equals": ["a"]}})
        self.assertEqual(ac.check("alice", "r", "read"), True)

    # ---- O. extended matchers and combinators --------------------------

    def test_matcher_not_equals(self):
        """The 'not_equals' matcher needs a present value that is not equal to the operand."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"x": {"not_equals": 5}})
        self.assertEqual(ac.check("alice", "r", "read", {"x": 4}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"x": 5}), False)
        self.assertEqual(ac.check("alice", "r", "read", {}), False)

    def test_matcher_not_in(self):
        """The 'not_in' matcher needs a present value that equals none of the listed values."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"x": {"not_in": [1, 2]}})
        self.assertEqual(ac.check("alice", "r", "read", {"x": 3}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"x": 1}), False)
        self.assertEqual(ac.check("alice", "r", "read", {}), False)

    def test_matcher_between_inclusive(self):
        """The 'between' matcher accepts a number within the inclusive bounds and rejects non-numbers."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"n": {"between": [2, 4]}})
        self.assertEqual(ac.check("alice", "r", "read", {"n": 2}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"n": 4}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"n": 5}), False)
        self.assertEqual(ac.check("alice", "r", "read", {"n": True}), False)

    def test_matcher_exists(self):
        """The 'exists' matcher tests presence of the key, the only matcher that can be satisfied by an absent value."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"opt": {"exists": True}})
        ac.grant("r", "bob", "read", "allow", conditions={"opt": {"exists": False}})
        self.assertEqual(ac.check("alice", "r", "read", {"opt": 0}), True)
        self.assertEqual(ac.check("alice", "r", "read", {}), False)
        self.assertEqual(ac.check("bob", "r", "read", {}), True)
        self.assertEqual(ac.check("bob", "r", "read", {"opt": 1}), False)

    def test_combinator_all(self):
        """An 'all' combinator is satisfied only when every inner matcher on the same value is satisfied."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"lvl": {"all": [{"at_least": 2}, {"at_most": 8}]}})
        self.assertEqual(ac.check("alice", "r", "read", {"lvl": 5}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"lvl": 1}), False)
        self.assertEqual(ac.check("alice", "r", "read", {"lvl": 9}), False)

    def test_combinator_any(self):
        """An 'any' combinator is satisfied when at least one inner matcher on the same value is satisfied."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"role": {"any": [{"equals": "a"}, {"equals": "b"}]}})
        self.assertEqual(ac.check("alice", "r", "read", {"role": "a"}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"role": "c"}), False)

    def test_combinator_not(self):
        """A 'not' combinator inverts the satisfaction of its single inner matcher."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"team": {"not": {"in": ["x", "y"]}}})
        self.assertEqual(ac.check("alice", "r", "read", {"team": "z"}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"team": "x"}), False)

    def test_nested_combinators(self):
        """Combinators nest, so an 'all' of an 'any' and a 'not' evaluates recursively against the same value."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow",
                 conditions={"v": {"all": [{"any": [{"equals": 1}, {"equals": 2}]}, {"not": {"equals": 1}}]}})
        self.assertEqual(ac.check("alice", "r", "read", {"v": 2}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"v": 1}), False)
        self.assertEqual(ac.check("alice", "r", "read", {"v": 3}), False)

    def test_not_of_exists_matches_absence(self):
        """A 'not' wrapping 'exists' true is satisfied exactly when the key is absent."""
        ac = self.make()
        ac.add_resource("r")
        ac.grant("r", "alice", "read", "allow", conditions={"opt": {"not": {"exists": True}}})
        self.assertEqual(ac.check("alice", "r", "read", {}), True)
        self.assertEqual(ac.check("alice", "r", "read", {"opt": 1}), False)

    def test_matcher_and_combinator_validation(self):
        """Extended matchers and combinators are validated before any grant is stored, rejecting malformed shapes."""
        ac = self.make()
        ac.add_resource("r")
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"x": {"all": []}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"x": {"all": "nope"}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"x": {"any": [{"equals": 1, "in": [1]}]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"x": {"not": [{"equals": 1}]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"n": {"between": [4, 1]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"n": {"between": [1]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"n": {"between": [1, True]}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"opt": {"exists": 1}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"resource:": {"equals": 1}})
        self.assert_access_error(ac.grant, "r", "u", "read", "allow", conditions={"x": {"weird": 1}})
        self.assertEqual(ac.list_grants("r"), [])

    # ---- P. interactions across the layers -----------------------------

    def test_priority_role_and_attribute_together(self):
        """Priority, the role tier, and a resource-sourced condition combine: a high-priority role allow that the attribute satisfies overrides a nearer principal deny."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.add_role("ops")
        ac.assign_role("alice", "ops")
        ac.set_attribute("child", "tier", 9)
        ac.grant("child", "alice", "admin", "deny")
        ac.grant("root", "ops", "admin", "allow", subject_kind="role", inheritable=True,
                 priority=10, conditions={"resource:tier": {"at_least": 5}})
        self.assert_decision(
            ac.explain("alice", "child", "admin"),
            allowed=True, decided_by="root", effect="allow", matched="exact", subject="role",
            distance=1, inherited=True, priority=10,
        )

    def test_effective_permissions_with_priority_override(self):
        """effective_permissions reflects priority precedence, so a high-priority inherited wildcard allow overrides a nearer specific deny."""
        ac = self.make()
        ac.add_resource("root")
        ac.add_resource("child", "root")
        ac.grant("root", "alice", "*", "allow", inheritable=True, priority=5)
        ac.grant("child", "alice", "read", "deny")
        self.assertEqual(ac.effective_permissions("alice", "child"), ["admin", "delete", "read", "write"])

    def test_effective_permissions_with_roles_and_attributes(self):
        """effective_permissions combines role grants and resource-sourced conditions across the configured actions."""
        ac = self.make()
        ac.add_resource("r")
        ac.add_role("editor")
        ac.assign_role("alice", "editor")
        ac.set_attribute("r", "tier", 4)
        ac.grant("r", "editor", "read", "allow", subject_kind="role")
        ac.grant("r", "editor", "write", "allow", subject_kind="role", conditions={"resource:tier": {"at_least": 5}})
        self.assertEqual(ac.effective_permissions("alice", "r"), ["read"])

    def test_instances_isolate_roles_and_attributes(self):
        """Separate instances keep independent roles, role assignments, and resource attributes."""
        a = self.make()
        b = self.make()
        a.add_resource("r")
        b.add_resource("r")
        a.add_role("editor")
        a.assign_role("alice", "editor")
        a.set_attribute("r", "tier", 9)
        self.assert_access_error(b.grant, "r", "editor", "read", "allow", subject_kind="role")
        b.grant("r", "alice", "read", "allow", conditions={"resource:tier": {"exists": True}})
        self.assertEqual(b.check("alice", "r", "read"), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)

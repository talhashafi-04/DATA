"""
Correctness tests for atomic_write.sh.

Each test is fully independent: it creates its own temporary directory tree
for both target files and the transaction staging area, then tears them down.
Crash scenarios are simulated by manually constructing the on-disk transaction
directory state that the script would have left behind at a specific point in
the protocol, then invoking the script (with no arguments) to trigger recovery.
"""

import os
import shutil
import subprocess
import tempfile
import uuid

import pytest

SCRIPT = os.environ.get("ATOMIC_WRITE_SCRIPT", "/app/atomic_write.sh")
# Prefer /sandbox (non-sticky, world-writable) over /tmp so tests that run as
# ``nobody`` can unlink and replace staged targets.
_SANDBOX_BASE = "/sandbox" if os.path.isdir("/sandbox") else None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def run(*args, env_extra=None, cwd=None):
    """Run atomic_write.sh with the given arguments and return the CompletedProcess."""
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def run_as_nobody(*args, env_extra=None, cwd=None):
    """Run the script as user ``nobody`` so directory DAC permissions apply.

    The verifier often runs pytest as root; ``chmod`` on directories does not block
    root, so we defer to ``runuser`` where available (standard on Ubuntu Docker).
    """
    env_pairs = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": "/nonexistent",
    }
    env_pairs.update(env_extra or {})
    env_argv = [f"{k}={v}" for k, v in env_pairs.items()]
    return subprocess.run(
        ["runuser", "-u", "nobody", "--", "env"] + env_argv + [SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def run_default_txn_dir(*args, cwd=None):
    """Run the script without ATOMIC_TXN_DIR so /app/.transactions is used."""
    env = {**os.environ}
    env.pop("ATOMIC_TXN_DIR", None)
    return subprocess.run(
        [SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def write(path, content):
    """Write text content to path, creating parent directories as needed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


def read(path):
    """Return the text content of a file."""
    with open(path) as fh:
        return fh.read()


def read_bytes(path):
    """Return the raw bytes of a file."""
    with open(path, "rb") as fh:
        return fh.read()


class AtomicWriteFixture:
    """Per-test sandbox with its own work directory and transaction directory."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="aw_test_", dir=_SANDBOX_BASE)
        # Allow subprocesses running as ``nobody`` (permission-sensitive tests).
        os.chmod(self.root, 0o755)
        self.txn_dir = os.path.join(self.root, ".transactions")
        self.env = {"ATOMIC_TXN_DIR": self.txn_dir}

    def teardown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, *parts):
        """Return an absolute path rooted inside the sandbox."""
        return os.path.join(self.root, *parts)

    def run(self, *args):
        """Run the script with sandbox-scoped ATOMIC_TXN_DIR."""
        return run(*args, env_extra=self.env)

    def run_recovery(self):
        """Invoke the script with no arguments to trigger recovery only."""
        return run(env_extra=self.env)

    def run_recovery_as_nobody(self):
        """Same as ``run_recovery`` but as ``nobody`` (for permission-sensitive cases)."""
        return run_as_nobody(env_extra=self.env)


def _latest_txn_dir(txn_root):
    txn_dirs = [
        d for d in os.listdir(txn_root) if os.path.isdir(os.path.join(txn_root, d))
    ]
    assert txn_dirs, f"No transaction directories found in {txn_root}"
    return os.path.join(txn_root, sorted(txn_dirs)[-1])


def _create_pending_committed_txn_via_script(fx, targets_with_new_content):
    """Create a committed-but-not-applied txn using the script write path."""
    os.makedirs(fx.txn_dir, mode=0o777, exist_ok=True)
    os.chmod(fx.root, 0o777)
    os.chmod(fx.txn_dir, 0o777)

    blocked_parent = fx.path(f"blocked_{uuid.uuid4().hex[:8]}")
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)

    args = []
    for idx, (target_name, old_content, new_content) in enumerate(targets_with_new_content):
        target = os.path.join(blocked_parent, target_name)
        src = fx.path(f"src_{idx}_{uuid.uuid4().hex[:8]}.txt")
        write(target, old_content)
        write(src, new_content)
        args.append(f"{target}:{src}")

    os.chmod(blocked_parent, 0o555)
    run_as_nobody(*args, env_extra=fx.env)
    # Exit code may vary across implementations; what matters is that the
    # txn state remains for recovery (PREPARED/COMMITTED + staged content).
    txn_dirs = [
        d for d in os.listdir(fx.txn_dir) if os.path.isdir(os.path.join(fx.txn_dir, d))
    ]
    assert txn_dirs, (
        "Script must leave a committed transaction directory when apply fails; "
        "tests must not synthesize txn state."
    )
    txn_path = os.path.join(fx.txn_dir, sorted(txn_dirs)[-1])
    assert os.path.isfile(os.path.join(txn_path, "PREPARED"))
    assert os.path.isfile(os.path.join(txn_path, "COMMITTED"))
    return txn_path, blocked_parent


@pytest.fixture
def fx():
    f = AtomicWriteFixture()
    yield f
    f.teardown()


# ─────────────────────────────────────────────────────────────────────────────
# Basic correctness
# ─────────────────────────────────────────────────────────────────────────────


def test_basic_two_file_write(fx):
    """A successful two-file transaction leaves both targets with new content."""
    t1 = fx.path("file1.txt")
    t2 = fx.path("file2.txt")
    write(t1, "original 1")
    write(t2, "original 2")

    s1 = fx.path("src1")
    s2 = fx.path("src2")
    write(s1, "new content 1")
    write(s2, "new content 2")

    result = fx.run(f"{t1}:{s1}", f"{t2}:{s2}")

    assert result.returncode == 0
    assert read(t1) == "new content 1"
    assert read(t2) == "new content 2"


def test_write_new_file_that_does_not_yet_exist(fx):
    """The script must be able to create a target file that did not previously exist."""
    target = fx.path("brand_new.txt")
    src = fx.path("src")
    write(src, "created fresh")

    assert not os.path.exists(target)
    result = fx.run(f"{target}:{src}")

    assert result.returncode == 0
    assert read(target) == "created fresh"


def test_five_files_all_written_correctly(fx):
    """All five files in one transaction receive their new content."""
    targets = [fx.path(f"data{i}.txt") for i in range(5)]
    sources = [fx.path(f"src{i}") for i in range(5)]
    for i, (t, s) in enumerate(zip(targets, sources)):
        write(t, f"original {i}")
        write(s, f"new {i}")

    result = fx.run(*[f"{t}:{s}" for t, s in zip(targets, sources)])

    assert result.returncode == 0
    for i, t in enumerate(targets):
        assert read(t) == f"new {i}", f"file {i} has wrong content"


def test_empty_file_is_written_correctly(fx):
    """Writing a zero-byte source file must produce a zero-byte target."""
    target = fx.path("empty.txt")
    src = fx.path("src_empty")
    write(src, "")

    result = fx.run(f"{target}:{src}")

    assert result.returncode == 0
    assert os.path.exists(target)
    assert read(target) == ""


def test_binary_content_round_trips_correctly(fx):
    """Files with binary content (all 256 byte values) must be preserved exactly."""
    target = fx.path("binary.bin")
    src = fx.path("src_bin")
    payload = bytes(range(256))
    with open(src, "wb") as fh:
        fh.write(payload)

    result = fx.run(f"{target}:{src}")

    assert result.returncode == 0
    assert read_bytes(target) == payload


def test_target_in_nested_directory_is_created(fx):
    """The script must create any missing parent directories for target files."""
    target = fx.path("a", "b", "c", "deep.txt")
    src = fx.path("src")
    write(src, "nested")

    assert not os.path.isdir(fx.path("a"))
    result = fx.run(f"{target}:{src}")

    assert result.returncode == 0
    assert read(target) == "nested"


def test_overwriting_existing_target_preserves_mode_bits(fx):
    """Overwriting an existing target must keep its original permission bits."""
    target = fx.path("perm_target.txt")
    src = fx.path("perm_source.txt")
    write(target, "old")
    write(src, "new")
    os.chmod(target, 0o640)
    os.chmod(src, 0o777)

    before = os.stat(target).st_mode & 0o777
    result = fx.run(f"{target}:{src}")
    after = os.stat(target).st_mode & 0o777

    assert result.returncode == 0
    assert read(target) == "new"
    assert before == 0o640
    assert after == 0o640


# ─────────────────────────────────────────────────────────────────────────────
# Pre-commit error handling
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_source_file_rejects_and_preserves_originals(fx):
    """When a source file does not exist the script must exit non-zero and leave
    all already-existing target files untouched."""
    t1 = fx.path("keep.txt")
    write(t1, "original")

    nonexistent = fx.path("does_not_exist")
    result = fx.run(f"{t1}:{nonexistent}")

    assert result.returncode != 0
    assert read(t1) == "original"


def test_malformed_argument_without_colon_is_rejected(fx):
    """An argument with no ':' separator must cause a non-zero exit before staging."""
    target = fx.path("safe.txt")
    write(target, "untouched")

    result = fx.run("/no/colon/here")

    assert result.returncode != 0
    assert read(target) == "untouched"


def test_empty_target_argument_is_rejected_before_staging(fx):
    """``target:source`` with an empty target (``:source``) must fail before staging."""
    src = fx.path("only_source.txt")
    write(src, "body")
    kept = fx.path("kept.txt")
    write(kept, "unchanged")

    result = fx.run(f":{src}")

    assert result.returncode != 0
    assert read(kept) == "unchanged"
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Unexpected transaction dirs: {leftover}"


def test_empty_source_argument_is_rejected_before_staging(fx):
    """``target:`` with an empty source path must be rejected like a missing source."""
    target = fx.path("t.txt")
    write(target, "preserve")
    arg = f"{target}:"

    result = fx.run(arg)

    assert result.returncode != 0
    assert read(target) == "preserve"


def test_duplicate_target_paths_are_rejected_before_staging(fx):
    """Duplicate target paths in one invocation must fail before transaction staging."""
    target = fx.path("dup.txt")
    write(target, "original")
    src1 = fx.path("src1.txt")
    src2 = fx.path("src2.txt")
    write(src1, "one")
    write(src2, "two")

    result = fx.run(f"{target}:{src1}", f"{target}:{src2}")

    assert result.returncode != 0
    assert read(target) == "original"
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Duplicate-target reject should not leave txns: {leftover}"


def test_target_that_is_existing_directory_is_rejected_before_staging(fx):
    """A target path that is an existing directory must be rejected pre-commit."""
    target_dir = fx.path("existing_dir_target")
    os.makedirs(target_dir, exist_ok=True)
    src = fx.path("src_for_dir_target.txt")
    write(src, "payload")

    result = fx.run(f"{target_dir}:{src}")

    assert result.returncode != 0
    assert os.path.isdir(target_dir)
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Dir-target reject should not leave txns: {leftover}"


def test_cross_filesystem_target_is_rejected_before_staging(fx):
    """Cross-filesystem targets must be rejected before any transaction is created."""
    assert os.path.isdir("/dev/shm"), "/dev/shm must exist for cross-filesystem coverage"
    base_dev = os.stat(fx.root).st_dev
    shm_dev = os.stat("/dev/shm").st_dev
    assert (
        shm_dev != base_dev
    ), "Test environment must provide /dev/shm on a different filesystem"

    shm_name = f"aw_crossfs_{os.getpid()}_{uuid.uuid4().hex}.txt"
    shm_target = os.path.join("/dev/shm", shm_name)
    src = fx.path("src_cross_fs.txt")
    write(src, "payload")
    safe = fx.path("safe_kept.txt")
    write(safe, "unchanged")

    try:
        if os.path.lexists(shm_target):
            os.unlink(shm_target)

        result = fx.run(f"{shm_target}:{src}")

        assert result.returncode != 0
        assert read(safe) == "unchanged"
        assert not os.path.lexists(shm_target)
        if os.path.isdir(fx.txn_dir):
            leftover = [
                d
                for d in os.listdir(fx.txn_dir)
                if os.path.isdir(os.path.join(fx.txn_dir, d))
            ]
            assert leftover == [], f"cross-fs reject should not leave txns: {leftover}"
    finally:
        if os.path.lexists(shm_target):
            os.unlink(shm_target)


def test_source_symlink_is_rejected_before_staging(fx):
    """Source paths must be real files — symlinks must be rejected pre-commit."""
    real = fx.path("real_body.txt")
    write(real, "body")
    link_src = fx.path("link_as_source.txt")
    os.symlink(real, link_src)
    dest = fx.path("never_written.txt")

    result = fx.run(f"{dest}:{link_src}")

    assert result.returncode != 0
    assert not os.path.exists(dest)
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"symlink-source reject should not leave txns: {leftover}"


def test_target_symlink_is_rejected_before_staging(fx):
    """Writing through an existing symlink target path must fail pre-commit."""
    real = fx.path("symlink_via_target_actual.txt")
    write(real, "original")
    link_target = fx.path("symlink_via_target_link.txt")
    os.symlink(real, link_target)
    src = fx.path("new_payload.txt")
    write(src, "new")

    result = fx.run(f"{link_target}:{src}")

    assert result.returncode != 0
    assert read(real) == "original"
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"symlink-target reject should not leave txns: {leftover}"


def test_target_parent_symlink_component_is_rejected_before_staging(fx):
    """Existing symlink parent components in target path must be rejected."""
    real_parent = fx.path("real_parent_dir")
    os.makedirs(real_parent, exist_ok=True)
    symlink_parent = fx.path("symlink_parent_dir")
    os.symlink(real_parent, symlink_parent)
    src = fx.path("src_parent_symlink.txt")
    write(src, "payload")
    safe = fx.path("safe_parent_symlink.txt")
    write(safe, "unchanged")

    result = fx.run(f"{os.path.join(symlink_parent, 'child.txt')}:{src}")

    assert result.returncode != 0
    assert read(safe) == "unchanged"
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"parent-symlink reject should not leave txns: {leftover}"


def test_source_and_target_same_path_is_rejected_before_staging(fx):
    """Pairs where source and target resolve to the same path must be rejected."""
    same = fx.path("same.txt")
    write(same, "original")

    result = fx.run(f"{same}:{same}")

    assert result.returncode != 0
    assert read(same) == "original"
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Same-path reject should not leave txns: {leftover}"


def test_first_colon_separates_target_from_source_path_with_colons(fx):
    """Only the first ``:`` splits target and source; source paths may contain ``:``."""
    src = fx.path("deep", "a:b:segment.txt")
    write(src, "payload with colon path")
    out = fx.path("out.txt")

    result = fx.run(f"{out}:{src}")

    assert result.returncode == 0
    assert read(out) == "payload with colon path"


def test_no_staging_artefacts_left_on_pre_commit_error(fx):
    """A pre-commit failure must not leave any orphaned transaction directories."""
    result = fx.run(f"{fx.path('x')}:{fx.path('nonexistent')}")

    assert result.returncode != 0
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Orphaned transaction dirs: {leftover}"


def test_validation_failure_does_not_create_parent_directories(fx):
    """Parent dirs must not be created before validation fully passes."""
    nested_target = fx.path("must_not_exist", "deep", "file.txt")
    valid_src = fx.path("valid_src.txt")
    write(valid_src, "valid")
    bad_src = fx.path("missing_src.txt")

    result = fx.run(f"{nested_target}:{valid_src}", f"{fx.path('x')}:{bad_src}")

    assert result.returncode != 0
    assert not os.path.exists(fx.path("must_not_exist"))


# ─────────────────────────────────────────────────────────────────────────────
# Clean-up after success
# ─────────────────────────────────────────────────────────────────────────────


def test_transaction_directory_removed_after_successful_commit(fx):
    """No staging directories should remain in ATOMIC_TXN_DIR after a clean run."""
    t = fx.path("out.txt")
    s = fx.path("src")
    write(s, "hello")

    result = fx.run(f"{t}:{s}")

    assert result.returncode == 0
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"Orphaned transaction dirs after success: {leftover}"


def test_staging_layout_and_markers_exist_after_committed_when_apply_fails():
    """A real write path must produce txn_*/entries/<i> with staged+target and markers."""
    root = tempfile.mkdtemp(prefix="aw_layout_", dir=_SANDBOX_BASE)
    try:
        os.chmod(root, 0o777)
        txn_dir = os.path.join(root, "txn")
        os.makedirs(txn_dir, mode=0o777, exist_ok=True)
        os.chmod(txn_dir, 0o777)

        blocked_parent = os.path.join(root, "blocked_parent")
        os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
        target = os.path.join(blocked_parent, "out.txt")
        if os.path.exists(target):
            os.unlink(target)
        src = os.path.join(root, "src.txt")
        write(src, "new payload")

        # No write permission for nobody -> apply phase fails after COMMITTED.
        os.chmod(blocked_parent, 0o555)
        result = run_as_nobody(
            f"{target}:{src}",
            env_extra={"ATOMIC_TXN_DIR": txn_dir},
        )
        # Exit code may vary; validate txn state on disk.

        txn_dirs = [
            d for d in os.listdir(txn_dir) if os.path.isdir(os.path.join(txn_dir, d))
        ]
        assert txn_dirs, (
            "Script must leave a transaction directory when the apply phase fails "
            "(COMMITTED was written but rename was blocked by permissions)."
        )
        assert len(txn_dirs) == 1
        assert txn_dirs[0].startswith("txn_")

        txn_path = os.path.join(txn_dir, txn_dirs[0])
        assert os.path.isfile(os.path.join(txn_path, "PREPARED"))
        assert os.path.isfile(os.path.join(txn_path, "COMMITTED"))

        entry0 = os.path.join(txn_path, "entries", "0")
        assert os.path.isfile(os.path.join(entry0, "staged"))
        assert os.path.isfile(os.path.join(entry0, "target"))
        assert read(os.path.join(entry0, "target")) == target
        assert not os.path.exists(os.path.join(entry0, "orig_mode"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_relative_target_is_normalized_to_absolute_in_target_metadata():
    """Relative targets must be stored as absolute paths in entries/<i>/target."""
    root = tempfile.mkdtemp(prefix="aw_relmeta_", dir=_SANDBOX_BASE)
    try:
        os.chmod(root, 0o777)
        txn_dir = os.path.join(root, "txn")
        os.makedirs(txn_dir, mode=0o777, exist_ok=True)
        os.chmod(txn_dir, 0o777)
        blocked_parent = os.path.join(root, "blocked_parent")
        os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
        rel_target = os.path.join("blocked_parent", "out.txt")
        src = os.path.join(root, "src.txt")
        write(src, "new payload")
        write(os.path.join(root, rel_target), "old")

        os.chmod(blocked_parent, 0o555)
        run_as_nobody(
            f"{rel_target}:{src}",
            env_extra={"ATOMIC_TXN_DIR": txn_dir},
            cwd=root,
        )
        txn_dirs = [
            d for d in os.listdir(txn_dir) if os.path.isdir(os.path.join(txn_dir, d))
        ]
        assert txn_dirs, (
            "Script must leave a transaction directory when the apply phase fails "
            "(COMMITTED was written but rename was blocked by permissions)."
        )
        txn_path = os.path.join(txn_dir, sorted(txn_dirs)[-1])
        target_meta = read(os.path.join(txn_path, "entries", "0", "target"))
        assert target_meta == os.path.join(root, rel_target)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_default_atomic_txn_dir_is_used_when_env_unset():
    """When ATOMIC_TXN_DIR is unset, writes and recovery use /app/.transactions."""
    token = uuid.uuid4().hex[:10]
    root = f"/app/aw_default_{token}"
    target = os.path.join(root, "target.txt")
    src = os.path.join(root, "src.txt")
    blocked_parent = os.path.join(root, "blocked")
    blocked_target = os.path.join(blocked_parent, "out.txt")

    os.makedirs(root, mode=0o755, exist_ok=True)
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
    try:
        write(src, "payload")
        write(target, "old")
        write(blocked_target, "old blocked")

        # Normal default-path write should succeed.
        ok = run_default_txn_dir(f"{target}:{src}")
        assert ok.returncode == 0
        assert read(target) == "payload"

        # Force a committed-but-not-applied txn via real write path as nobody.
        os.chmod("/app/.transactions", 0o777)
        os.chmod(blocked_parent, 0o555)
        blocked_src = os.path.join(root, "blocked_src.txt")
        write(blocked_src, "blocked payload")
        committed = run_as_nobody(f"{blocked_target}:{blocked_src}")
        # Exit code may vary; validate txn state on disk.

        txn_dirs = [
            d
            for d in os.listdir("/app/.transactions")
            if d.startswith("txn_")
            and os.path.isdir(os.path.join("/app/.transactions", d))
        ]
        assert txn_dirs, "Expected staged transaction under /app/.transactions"
        txn_path = os.path.join("/app/.transactions", sorted(txn_dirs)[-1])
        assert os.path.isfile(os.path.join(txn_path, "PREPARED"))
        assert os.path.isfile(os.path.join(txn_path, "COMMITTED"))
        assert os.path.isfile(os.path.join(txn_path, "entries", "0", "staged"))
        assert os.path.isfile(os.path.join(txn_path, "entries", "0", "target"))

        # Recovery with no args and no env should resolve it.
        os.chmod(blocked_parent, 0o777)
        recovered = run_default_txn_dir()
        assert recovered.returncode == 0
        assert read(blocked_target) == "blocked payload"
        assert not os.path.exists(txn_path)
    finally:
        os.chmod(blocked_parent, 0o755)
        shutil.rmtree(root, ignore_errors=True)


def test_default_atomic_txn_dir_is_used_when_env_empty_string():
    """When ATOMIC_TXN_DIR is empty, writes and recovery use /app/.transactions."""
    token = uuid.uuid4().hex[:10]
    root = f"/app/aw_default_empty_{token}"
    target = os.path.join(root, "target.txt")
    src = os.path.join(root, "src.txt")
    blocked_parent = os.path.join(root, "blocked")
    blocked_target = os.path.join(blocked_parent, "out.txt")

    os.makedirs(root, mode=0o755, exist_ok=True)
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
    try:
        write(src, "payload empty env")
        write(target, "old")
        write(blocked_target, "old blocked")

        # Empty-string env var should still fall back to /app/.transactions.
        ok = run(f"{target}:{src}", env_extra={"ATOMIC_TXN_DIR": ""})
        assert ok.returncode == 0
        assert read(target) == "payload empty env"

        # Force a committed-but-not-applied txn via real write path as nobody.
        os.chmod("/app/.transactions", 0o777)
        os.chmod(blocked_parent, 0o555)
        blocked_src = os.path.join(root, "blocked_src.txt")
        write(blocked_src, "blocked payload empty env")
        run_as_nobody(
            f"{blocked_target}:{blocked_src}",
            env_extra={"ATOMIC_TXN_DIR": ""},
        )
        # Exit code may vary; validate txn state on disk.

        txn_dirs = [
            d
            for d in os.listdir("/app/.transactions")
            if d.startswith("txn_")
            and os.path.isdir(os.path.join("/app/.transactions", d))
        ]
        matching_txn = None
        for d in sorted(txn_dirs, reverse=True):
            candidate = os.path.join("/app/.transactions", d)
            target_record = os.path.join(candidate, "entries", "0", "target")
            if os.path.isfile(target_record) and read(target_record) == blocked_target:
                matching_txn = candidate
                break
        assert matching_txn, "Expected committed staged transaction under /app/.transactions"
        assert os.path.isfile(os.path.join(matching_txn, "PREPARED"))
        assert os.path.isfile(os.path.join(matching_txn, "COMMITTED"))
        assert os.path.isfile(os.path.join(matching_txn, "entries", "0", "staged"))

        # Recovery with no args and empty ATOMIC_TXN_DIR should resolve it.
        os.chmod(blocked_parent, 0o777)
        recovered = run(env_extra={"ATOMIC_TXN_DIR": ""})
        assert recovered.returncode == 0
        assert read(blocked_target) == "blocked payload empty env"
        assert not os.path.exists(matching_txn)
    finally:
        os.chmod(blocked_parent, 0o755)
        shutil.rmtree(root, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Crash simulation — no COMMITTED marker (must rollback)
# ─────────────────────────────────────────────────────────────────────────────


def test_recovery_rolls_back_transaction_with_no_prepared_marker(fx):
    """A transaction directory with no PREPARED marker (crash during staging)
    must be deleted on recovery; the target file must keep its original content."""
    txn, blocked_parent = _create_pending_committed_txn_via_script(
        fx, [("target.txt", "original", "new content")]
    )
    target = os.path.join(blocked_parent, "target.txt")
    os.unlink(os.path.join(txn, "PREPARED"))
    os.unlink(os.path.join(txn, "COMMITTED"))

    os.chmod(blocked_parent, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(target) == "original", "Rollback should leave original intact"
    assert not os.path.exists(txn), "Rolled-back transaction dir should be removed"


def test_recovery_rolls_back_transaction_with_prepared_but_no_committed(fx):
    """A transaction that reached PREPARED but not COMMITTED (crash between the two
    markers) must be rolled back; the target must keep its original content."""
    txn, blocked_parent = _create_pending_committed_txn_via_script(
        fx, [("target.txt", "original", "new content")]
    )
    target = os.path.join(blocked_parent, "target.txt")
    os.unlink(os.path.join(txn, "COMMITTED"))

    os.chmod(blocked_parent, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(target) == "original", "Rollback should leave original intact"
    assert not os.path.exists(txn), "Rolled-back transaction dir should be removed"


def test_rollback_does_not_affect_files_from_other_transactions(fx):
    """Rolling back one crashed (non-committed) transaction must not disturb
    target files that belong to a separate, already-applied transaction."""
    txn, blocked_parent = _create_pending_committed_txn_via_script(
        fx, [("crashed.txt", "original", "would-be new content")]
    )
    committed_target = fx.path("committed.txt")
    write(committed_target, "committed content")
    crashed_target = os.path.join(blocked_parent, "crashed.txt")
    os.unlink(os.path.join(txn, "COMMITTED"))

    os.chmod(blocked_parent, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(committed_target) == "committed content"
    assert read(crashed_target) == "original"


# ─────────────────────────────────────────────────────────────────────────────
# Crash simulation — COMMITTED marker present (must complete the write)
# ─────────────────────────────────────────────────────────────────────────────


def test_recovery_completes_single_pending_rename_after_committed(fx):
    """When COMMITTED is present and one staged file remains, recovery must apply
    it so the target gets the committed content."""
    txn, blocked_parent = _create_pending_committed_txn_via_script(
        fx, [("target.txt", "original", "committed content")]
    )
    target = os.path.join(blocked_parent, "target.txt")

    os.chmod(blocked_parent, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(target) == "committed content", "Recovery must apply committed content"
    assert not os.path.exists(txn), "Completed transaction dir should be removed"


def test_committed_recovery_preserves_txn_dir_when_rename_blocked_until_permissions_fixed(fx):
    """If a committed rename cannot complete (e.g. target directory not writable by
    the invoking user), the transaction directory must remain until a later
    invocation succeeds with sufficient permissions."""
    txn, parent = _create_pending_committed_txn_via_script(
        fx, [("out.txt", "original", "committed blob")]
    )
    target = os.path.join(parent, "out.txt")
    assert os.path.isdir(txn), "Staging dir must survive blocked initial apply"
    staged = os.path.join(txn, "entries", "0", "staged")
    assert os.path.isfile(staged), "Staged blob must still exist for retry"
    assert read(target) == "original"

    os.chmod(parent, 0o777)
    again = fx.run_recovery()
    assert again.returncode == 0
    assert read(target) == "committed blob"
    assert not os.path.exists(txn), "Txn dir should be removed once apply succeeds"


def test_recovery_of_committed_entry_preserves_existing_target_mode(fx):
    """Recovery preserves mode bits when txn state came from a real write path."""
    os.makedirs(fx.txn_dir, mode=0o777, exist_ok=True)
    os.chmod(fx.root, 0o777)
    os.chmod(fx.txn_dir, 0o777)

    blocked_parent = fx.path("recover_perm_parent")
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
    target = fx.path("recover_perm_parent", "recover_perm_target.txt")
    write(target, "old")
    os.chmod(target, 0o600)
    src = fx.path("recover_perm_source.txt")
    write(src, "new")

    os.chmod(blocked_parent, 0o555)
    first = run_as_nobody(f"{target}:{src}", env_extra=fx.env)
    # Exit code varies across valid implementations.

    txn_dirs = [
        d for d in os.listdir(fx.txn_dir) if os.path.isdir(os.path.join(fx.txn_dir, d))
    ]
    assert len(txn_dirs) == 1, (
        "Script must leave exactly one committed txn after blocked apply; "
        "tests must not synthesize txn state."
    )

    os.chmod(blocked_parent, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(target) == "new"
    assert (os.stat(target).st_mode & 0o777) == 0o600


def test_recovery_completes_partial_commit_leaves_already_applied_file_intact(fx):
    """When COMMITTED is present and only some staged files remain (others were
    already renamed before the crash), recovery must apply the remaining ones
    without corrupting the already-applied files."""
    txn, parent = _create_pending_committed_txn_via_script(
        fx,
        [
            ("file0.txt", "original 0", "committed 0"),
            ("file1.txt", "original 1", "committed 1"),
            ("file2.txt", "original 2", "committed 2"),
        ],
    )
    t0 = os.path.join(parent, "file0.txt")
    t1 = os.path.join(parent, "file1.txt")
    t2 = os.path.join(parent, "file2.txt")

    # Simulate partial crash: entry 0 already applied, entries 1/2 still pending.
    entry0 = os.path.join(txn, "entries", "0")
    os.chmod(parent, 0o777)
    shutil.move(os.path.join(entry0, "staged"), t0)
    assert not os.path.exists(os.path.join(entry0, "staged"))

    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(t0) == "committed 0"
    assert read(t1) == "committed 1", "Recovery must apply pending entry 1"
    assert read(t2) == "committed 2", "Recovery must apply pending entry 2"
    assert not os.path.exists(txn)


def test_recovery_handles_multiple_stale_transactions_independently(fx):
    """When ATOMIC_TXN_DIR contains multiple leftover transaction directories,
    each one is handled independently: committed ones applied, others rolled back."""
    txn_c, parent_c = _create_pending_committed_txn_via_script(
        fx, [("committed.txt", "old", "new committed")]
    )
    committed_target = os.path.join(parent_c, "committed.txt")

    txn_r, parent_r = _create_pending_committed_txn_via_script(
        fx, [("rolled_back.txt", "must stay", "must not appear")]
    )
    rolled_back_target = os.path.join(parent_r, "rolled_back.txt")
    os.unlink(os.path.join(txn_r, "COMMITTED"))  # make this one rollback-only

    os.chmod(parent_c, 0o777)
    os.chmod(parent_r, 0o777)
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(committed_target) == "new committed"
    assert read(rolled_back_target) == "must stay"
    assert not os.path.exists(txn_c)
    assert not os.path.exists(txn_r)


# ─────────────────────────────────────────────────────────────────────────────
# Recovery runs automatically on normal invocations
# ─────────────────────────────────────────────────────────────────────────────


def test_recovery_runs_automatically_before_a_normal_write(fx):
    """When a committed transaction is found during a normal (non-empty) invocation,
    recovery completes it before processing the new transaction."""
    txn_stale, parent = _create_pending_committed_txn_via_script(
        fx, [("stale.txt", "stale original", "stale committed")]
    )
    stale_target = os.path.join(parent, "stale.txt")
    os.chmod(parent, 0o777)

    new_target = fx.path("new.txt")
    src = fx.path("src")
    write(src, "brand new")

    result = fx.run(f"{new_target}:{src}")

    assert result.returncode == 0
    assert read(stale_target) == "stale committed", "Recovery should have completed stale txn"
    assert read(new_target) == "brand new", "New transaction should have been applied"
    assert not os.path.exists(txn_stale)


# ─────────────────────────────────────────────────────────────────────────────
# Idempotent recovery
# ─────────────────────────────────────────────────────────────────────────────


def test_running_recovery_twice_is_idempotent(fx):
    """Invoking recovery (no-arg run) on an already-clean staging directory must
    succeed without error and must not alter any target file."""
    target = fx.path("stable.txt")
    write(target, "stable content")

    fx.run_recovery()
    result = fx.run_recovery()

    assert result.returncode == 0
    assert read(target) == "stable content"


def test_no_arg_recovery_when_staging_directory_does_not_exist(fx):
    """No-arg recovery must succeed before ``ATOMIC_TXN_DIR`` exists (no-op scan)."""
    assert not os.path.exists(fx.txn_dir)
    result = fx.run_recovery()
    assert result.returncode == 0


def test_recovery_of_committed_txn_is_idempotent(fx):
    """If recovery is triggered twice for the same committed transaction (first run
    applied one rename, second run sees the others), the final state must be correct."""
    txn, parent = _create_pending_committed_txn_via_script(
        fx,
        [("idem0.txt", "old 0", "new 0"), ("idem1.txt", "old 1", "new 1")],
    )
    t0 = os.path.join(parent, "idem0.txt")
    t1 = os.path.join(parent, "idem1.txt")
    os.chmod(parent, 0o777)

    fx.run_recovery()
    result = fx.run_recovery()  # second run — txn dir should already be gone

    assert result.returncode == 0
    assert read(t0) == "new 0"
    assert read(t1) == "new 1"


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage: untested instruction requirements
# ─────────────────────────────────────────────────────────────────────────────


def test_source_is_directory_is_rejected_before_staging(fx):
    """A source that is a directory (not a regular file) must be rejected pre-commit."""
    src_dir = fx.path("source_dir")
    os.makedirs(src_dir, exist_ok=True)
    target = fx.path("never_written.txt")

    result = fx.run(f"{target}:{src_dir}")

    assert result.returncode != 0
    assert not os.path.exists(target)
    if os.path.isdir(fx.txn_dir):
        leftover = [
            d
            for d in os.listdir(fx.txn_dir)
            if os.path.isdir(os.path.join(fx.txn_dir, d))
        ]
        assert leftover == [], f"dir-source reject should not leave txns: {leftover}"


def test_txn_folder_root_contains_only_protocol_files_and_entries(fx):
    """Data files must live under entries/<i>/; only PREPARED, COMMITTED, and the
    entries/ directory may appear at the transaction folder root."""
    os.makedirs(fx.txn_dir, mode=0o777, exist_ok=True)
    os.chmod(fx.root, 0o777)
    os.chmod(fx.txn_dir, 0o777)

    blocked_parent = fx.path(f"blocked_{uuid.uuid4().hex[:8]}")
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
    target = os.path.join(blocked_parent, "out.txt")
    src = fx.path("src.txt")
    write(target, "old")
    write(src, "new payload")

    # Revoke write on parent so the move phase fails and the txn dir stays on disk.
    os.chmod(blocked_parent, 0o555)
    run_as_nobody(f"{target}:{src}", env_extra=fx.env)

    txn_dirs = [
        d for d in os.listdir(fx.txn_dir) if os.path.isdir(os.path.join(fx.txn_dir, d))
    ]
    assert txn_dirs, (
        "Script must leave a transaction directory when the apply phase fails."
    )
    txn_path = os.path.join(fx.txn_dir, sorted(txn_dirs)[-1])

    root_items = set(os.listdir(txn_path))
    allowed = {"PREPARED", "COMMITTED", "entries"}
    unexpected = root_items - allowed
    assert not unexpected, (
        f"Transaction folder root must contain only PREPARED, COMMITTED, and entries/; "
        f"found unexpected items: {unexpected}"
    )


def test_parent_dir_not_created_before_committed_marker(fx):
    """Parent directories must be created only just before COMMITTED is written.

    A manually constructed PREPARED-only transaction (simulating a crash that
    occurred after PREPARED was written but before mkdir -p + COMMITTED) must
    not have created the target parent directory.  Recovery of such a
    transaction (no COMMITTED -> rollback) must also leave the parent absent.
    """
    import shutil as _shutil

    nonexistent_parent = fx.path("new_parent_dir", "subdir")
    target = os.path.join(nonexistent_parent, "file.txt")
    src = fx.path("src_timing.txt")
    write(src, "payload")

    # Manually construct a PREPARED-only transaction (no COMMITTED).
    txn_path = os.path.join(fx.txn_dir, f"txn_timing_{uuid.uuid4().hex[:10]}")
    entry_dir = os.path.join(txn_path, "entries", "0")
    os.makedirs(entry_dir, exist_ok=True)
    _shutil.copy2(src, os.path.join(entry_dir, "staged"))
    write(os.path.join(entry_dir, "target"), target)
    write(os.path.join(txn_path, "PREPARED"), "PREPARED\n")
    # Deliberately omit COMMITTED to simulate a crash before mkdir -p + COMMITTED.

    assert not os.path.exists(nonexistent_parent), (
        "Parent directory must not exist before COMMITTED is written."
    )

    # Recovery must roll back (no COMMITTED) and must not create parent dirs.
    result = fx.run_recovery()

    assert result.returncode == 0
    assert not os.path.exists(nonexistent_parent), (
        "Rollback of a PREPARED-only txn must not create target parent directories."
    )
    assert not os.path.exists(txn_path), "Rolled-back transaction dir must be removed."


def test_recovery_exits_zero_and_continues_past_failed_moves(fx):
    """During recovery, if a committed entry's move fails (e.g. target directory is
    not writable by the invoking user), the script must still exit 0, must apply
    all entries whose moves can succeed, and must leave the transaction directory
    on disk for a future recovery run.

    This validates the instruction requirement: 'During recovery, if a move fails,
    the script must not exit non-zero. The script must continue through the remaining
    entries, leave any incomplete transaction folder for the next run, and exit 0
    when finished.'
    """
    os.makedirs(fx.txn_dir, mode=0o777, exist_ok=True)
    os.chmod(fx.root, 0o777)
    os.chmod(fx.txn_dir, 0o777)

    # Two target parents: one will remain blocked during recovery, one will be
    # opened so that its entry can succeed while the other fails.
    blocked_parent = fx.path(f"blocked_{uuid.uuid4().hex[:8]}")
    open_parent = fx.path(f"open_{uuid.uuid4().hex[:8]}")
    os.makedirs(blocked_parent, mode=0o755, exist_ok=True)
    os.makedirs(open_parent, mode=0o755, exist_ok=True)
    os.chmod(open_parent, 0o777)

    target0 = os.path.join(blocked_parent, "file0.txt")
    target1 = os.path.join(open_parent, "file1.txt")
    src0 = fx.path("src0.txt")
    src1 = fx.path("src1.txt")
    write(target0, "original 0")
    write(target1, "original 1")
    write(src0, "committed 0")
    write(src1, "committed 1")

    # Block both parents so the initial write-path apply phase fails, leaving a
    # committed-but-not-applied transaction on disk.
    os.chmod(blocked_parent, 0o555)
    os.chmod(open_parent, 0o555)
    run_as_nobody(f"{target0}:{src0}", f"{target1}:{src1}", env_extra=fx.env)

    txn_dirs = [
        d for d in os.listdir(fx.txn_dir)
        if os.path.isdir(os.path.join(fx.txn_dir, d))
    ]
    assert txn_dirs, (
        "Script must leave a committed transaction directory when apply fails; "
        "tests must not synthesize txn state."
    )
    txn_path = os.path.join(fx.txn_dir, sorted(txn_dirs)[-1])
    assert os.path.isfile(os.path.join(txn_path, "COMMITTED"))

    # Unblock only open_parent so that during recovery entry1 can be applied
    # but entry0 (blocked_parent still 0o555) cannot.
    os.chmod(open_parent, 0o777)

    result = fx.run_recovery_as_nobody()

    # The script must exit 0 even though one move failed.
    assert result.returncode == 0, (
        "Recovery must exit 0 even when some committed entry moves fail."
    )
    # The entry whose parent is writable must have been applied.
    assert read(target1) == "committed 1", (
        "Recovery must apply entries whose target directories are accessible."
    )
    # The entry whose parent is still blocked must not have been applied.
    assert read(target0) == "original 0", (
        "Recovery must not corrupt entries it cannot apply."
    )
    # The transaction directory must remain so the next run can retry the failed move.
    assert os.path.exists(txn_path), (
        "Transaction directory must be left on disk when not all moves succeeded."
    )

    # Cleanup: restore permissions so the fixture teardown can remove all dirs.
    os.chmod(blocked_parent, 0o755)

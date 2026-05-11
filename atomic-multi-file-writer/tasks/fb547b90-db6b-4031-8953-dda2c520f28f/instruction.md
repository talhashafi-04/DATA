**Task: atomic_write.sh**

You must write a shell script at /app/atomic_write.sh. The script must implement atomic multi-file writes — either every target file gets its new content, or none of them change. No in-between state.

**How the caller invokes it**

The caller will run it like this:

./atomic_write.sh target1:source1 target2:source2 ...

The script must parse each raw argument by splitting at the first colon. Everything before the first colon is the target path. Everything after the first colon is the source path — even if the source contains more colons. The script must return 0 on success and a non-zero value if any pre-commit check fails.

**Staging directory**

The caller will set ATOMIC_TXN_DIR to control where staging happens. If the caller leaves it empty or unset, the script must fall back to /app/.transactions.

For each run, the script must create a subdirectory inside the staging root. The name must start with txn_ followed by something unique — a timestamp plus PID works fine. Inside that subdirectory the script must create an entries/ directory. For each argument, indexed from zero, the script must create entries/<i>/. Inside that folder the script must write two files: staged, which is a byte-for-byte copy of the source, and target, which contains the absolute destination path where staged should eventually land. The script must normalize the target to an absolute path (relative targets resolve against the current working directory at invocation time) before writing target. Data files must live under entries/<i>/; only protocol marker files (for example PREPARED and COMMITTED) may appear at the transaction folder root.

**Commit sequence**

Once all staged copies are written, the script must create a PREPARED file and a COMMITTED file in the transaction folder before applying staged content. Once COMMITTED exists, the transaction is past the point of no return. The script must then walk through entries/<i>/ and move staged to the path stored in target. The transaction folder must stay on disk until every move is done. If a move fails after COMMITTED was written, the script must leave the folder on disk so the next run can resume from it.

**Preserving permissions on overwrite**

When the script moves a staged file onto a target that already exists, the script must read that target's permission bits before the move and restore them afterward. To support this across runs — including recovery — the script must write a third file inside entries/<i>/ called orig_mode. The script must write the existing target's octal permission bits into orig_mode at staging time, before anything is overwritten (e.g. 644). During the move step, if orig_mode exists, the script must read it and apply those bits with chmod after the rename. If the target does not exist yet, the script must not create orig_mode, and must leave the mode at whatever cp set.

**Recovery on startup**

Every time the script starts, before it reads any arguments, the script must scan ATOMIC_TXN_DIR for leftover transaction folders. For each one it finds, the script must check whether COMMITTED exists.

If COMMITTED exists, the script must walk entries/<i>/. For each subfolder that still contains a staged file, the script must move staged to the path in target, applying orig_mode if present. Once all moves are done, the script must delete the folder.

If COMMITTED is missing, the script must delete the whole transaction folder immediately without touching any target files.

During recovery, if a move fails, the script must not exit non-zero. The script must continue through the remaining entries, leave any incomplete transaction folder for the next run, and exit 0 when finished.

The caller will sometimes run the script with no arguments. The script must treat that as a recovery-only run and exit 0.

**Pre-commit validation**

Before the script creates any staging folder, the script must validate every argument. The script must bail out with a non-zero exit code and create nothing if any of the following is true:

- an argument has no colon
- the target side is empty
- the source side is empty
- the source does not exist or is not a regular file
- the source path is a symlink
- the target already exists as a directory
- the final target path is a symlink
- any existing parent component in the target path is a symlink (check existing components only; components that do not exist yet are validated when created)
- the same target appears more than once in the argument list
- the source and target resolve to the same file
- the target's filesystem differs from the staging directory's filesystem

If a target's parent directory does not exist, the script must create it with mkdir -p only after all validation passes and before applying staged files.

**Constraints**

You must implement this using only standard shell tools — no databases, no lock files, no external services. The script must be a single writer. The deliverable is one file at /app/atomic_write.sh and it must be executable.
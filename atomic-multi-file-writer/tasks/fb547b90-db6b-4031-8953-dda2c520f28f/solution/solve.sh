#!/usr/bin/env bash
# Reference solution: creates /app/atomic_write.sh

set -euo pipefail

cat > /app/atomic_write.sh << 'SCRIPT_EOF'
#!/usr/bin/env bash
# atomic_write.sh — atomic multi-file writer using filesystem primitives only.
#
# Usage:  atomic_write.sh [target1:source1 target2:source2 ...]
#
# On every invocation recovery runs first: committed transactions are completed,
# non-committed transactions are rolled back. With no arguments the script exits
# after recovery.
#
# Environment:
#   ATOMIC_TXN_DIR  Directory used for transaction staging (default: /app/.transactions).
#                   Must be on the same filesystem as all target files.

set -euo pipefail

TXN_DIR="${ATOMIC_TXN_DIR:-/app/.transactions}"

# Walk up from target path until an existing path component is found (used for
# same-filesystem checks before parent dirs are created).
nearest_existing_anchor() {
    local p="$1"
    while [[ ! ( -e "$p" || -L "$p" ) ]]; do
        local parent
        parent=$(dirname -- "$p")
        if [[ "$parent" == "$p" ]]; then
            printf '%s' "$p"
            return 0
        fi
        p="$parent"
    done
    printf '%s' "$p"
}

target_on_txn_fs() {
    local target_path="$1" expected_dev="$2"
    [[ -z "$target_path" ]] && return 1
    local anchor actual
    anchor="$(nearest_existing_anchor "$target_path")"
    [[ -z "$anchor" ]] && return 1
    actual="$(stat -c '%d' "$anchor")"
    [[ "$actual" == "$expected_dev" ]]
}

# ─────────────────────────────────────────────────────────────────────────────
# recover: scan TXN_DIR for leftover transaction directories and resolve them.
#
#   COMMITTED present → apply remaining staged files, then remove the txn dir
#                       (idempotent: staged files that are already gone were
#                        already renamed; we simply skip them).
#   COMMITTED absent  → remove the txn dir without touching any target file
#                       (rollback of a transaction that never committed).
# ─────────────────────────────────────────────────────────────────────────────
apply_entry() {
    local entry_dir="$1"
    local staged target mode_file mode_value txn_expected anchor actual
    staged="$entry_dir/staged"
    [[ -f "$staged" ]] || return 0
    target="$(cat "$entry_dir/target")"

    txn_expected="$(stat -c '%d' "$TXN_DIR")"
    anchor="$(nearest_existing_anchor "$target")"
    actual="$(stat -c '%d' "$anchor")"
    if [[ "$actual" != "$txn_expected" ]]; then
        return 1
    fi
    if [[ -L "$target" ]]; then
        return 1
    fi

    mkdir -p "$(dirname "$target")"
    actual="$(stat -c '%d' "$(dirname "$target")")"
    if [[ "$actual" != "$txn_expected" ]]; then
        return 1
    fi

    if ! mv "$staged" "$target"; then
        return 1
    fi
    mode_file="$entry_dir/orig_mode"
    if [[ -f "$mode_file" ]]; then
        mode_value="$(cat "$mode_file")"
        chmod "$mode_value" "$target"
    fi
}

recover() {
    [[ -d "$TXN_DIR" ]] || return 0

    local txn entry_dir target staged all_ok

    for txn in "$TXN_DIR"/*/; do
        [[ -d "$txn" ]] || continue

        if [[ -f "$txn/COMMITTED" ]]; then
            all_ok=true

            for entry_dir in "$txn/entries"/*/; do
                [[ -d "$entry_dir" ]] || continue

                if ! apply_entry "$entry_dir"; then
                    all_ok=false
                fi
            done

            # Only delete the transaction dir when every pending rename succeeded.
            # If a rename failed, leave it in place for the next recovery attempt.
            if $all_ok; then rm -rf "$txn"; fi
        else
            # Not committed — rollback by removing the entire staging directory.
            rm -rf "$txn"
        fi
    done
}

# ─────────────────────────────────────────────────────────────────────────────
# Always run recovery first, even when called with arguments.
# ─────────────────────────────────────────────────────────────────────────────
recover

[[ $# -eq 0 ]] && exit 0

mkdir -p "$TXN_DIR"
TXN_FS_DEV="$(stat -c '%d' "$TXN_DIR")"

# ─────────────────────────────────────────────────────────────────────────────
# Validate all arguments before staging anything.
# Any error here exits non-zero without creating a transaction directory.
# ─────────────────────────────────────────────────────────────────────────────
declare -a TARGETS SOURCES
declare -A SEEN_TARGETS

for arg in "$@"; do
    if [[ "$arg" != *:* ]]; then
        echo "atomic_write: argument must be in target:source format: '$arg'" >&2
        exit 1
    fi

    target="${arg%%:*}"
    source="${arg#*:}"

    if [[ -z "$target" ]]; then
        echo "atomic_write: empty target path in argument: '$arg'" >&2
        exit 1
    fi

    if [[ -L "$target" ]]; then
        echo "atomic_write: target path must not be a symlink: '$target'" >&2
        exit 1
    fi

    if [[ -d "$target" ]]; then
        echo "atomic_write: target path is an existing directory: '$target'" >&2
        exit 1
    fi

    if [[ -e "$target" && ! -f "$target" ]]; then
        echo "atomic_write: target path must be a regular file when it already exists: '$target'" >&2
        exit 1
    fi

    if [[ -L "$source" ]]; then
        echo "atomic_write: source must not be a symlink: '$source'" >&2
        exit 1
    fi

    if [[ ! -f "$source" ]]; then
        echo "atomic_write: source must be an existing regular file: '$source'" >&2
        exit 1
    fi

    if [[ "$(realpath -m -- "$target")" == "$(realpath -m -- "$source")" ]]; then
        echo "atomic_write: source and target resolve to the same path: '$target'" >&2
        exit 1
    fi

    if [[ -n "${SEEN_TARGETS[$target]+x}" ]]; then
        echo "atomic_write: duplicate target path in one invocation: '$target'" >&2
        exit 1
    fi
    SEEN_TARGETS["$target"]=1

    if ! target_on_txn_fs "$target" "$TXN_FS_DEV"; then
        echo "atomic_write: target not on same filesystem as ATOMIC_TXN_DIR: '$target'" >&2
        exit 1
    fi

    TARGETS+=("$target")
    SOURCES+=("$source")
done

# ─────────────────────────────────────────────────────────────────────────────
# Create the transaction directory and stage all source files.
# ─────────────────────────────────────────────────────────────────────────────
TXN_ID="txn_$(date +%s%N)_$$"
TXN_PATH="$TXN_DIR/$TXN_ID"
mkdir -p "$TXN_PATH/entries"

# If anything goes wrong before COMMITTED, remove the staging directory.
_cleanup() { rm -rf "$TXN_PATH"; }
trap _cleanup ERR

for idx in "${!TARGETS[@]}"; do
    entry="$TXN_PATH/entries/$idx"
    mkdir -p "$entry"
    if [[ -e "${TARGETS[$idx]}" ]]; then
        stat -c '%a' "${TARGETS[$idx]}" > "$entry/orig_mode"
    fi
    # Store the target path as a file (handles any path that has no embedded newlines,
    # which is the POSIX requirement for valid filenames).
    printf '%s' "${TARGETS[$idx]}" > "$entry/target"
    cp "${SOURCES[$idx]}" "$entry/staged"
done

# Pre-validate target parent directories before committing, so the apply phase
# cannot fail due to a missing directory.
for target in "${TARGETS[@]}"; do
    mkdir -p "$(dirname "$target")"
done

# ─────────────────────────────────────────────────────────────────────────────
# Write protocol markers.
# ─────────────────────────────────────────────────────────────────────────────

# PREPARED: all staged files are in place; the transaction could be rolled back.
printf 'PREPARED\n' > "$TXN_PATH/PREPARED"

# COMMITTED: point of no return — this transaction must now be applied in full.
printf 'COMMITTED\n' > "$TXN_PATH/COMMITTED"

# After COMMITTED we no longer want ERR to remove the staging directory;
# leave it in place for recovery if a rename fails.
trap - ERR

# ─────────────────────────────────────────────────────────────────────────────
# Apply staged files with atomic per-file renames.
# Each mv on the same filesystem is atomic, so observers always see either the
# old or the new content of any individual file, never a partial write.
# The full multi-file switch is not instantaneous, but recovery guarantees that
# the committed intent is eventually applied in its entirety.
# ─────────────────────────────────────────────────────────────────────────────
all_ok=true

for idx in "${!TARGETS[@]}"; do
    entry="$TXN_PATH/entries/$idx"
    if ! apply_entry "$entry"; then
        all_ok=false
    fi
done

# Remove the transaction directory only when every rename succeeded.
if $all_ok; then rm -rf "$TXN_PATH"; fi
SCRIPT_EOF

chmod +x /app/atomic_write.sh
echo "atomic_write.sh created at /app/atomic_write.sh"

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAW_DIR = "/app/data/raw"
OUT_DIR = "/app/data/normalized"
AUDIT_PATH = os.path.join(OUT_DIR, "audit.json")
HIDDEN_KAGGLE_DIR = Path("/tests/hidden_data/kaggle_character_encoding_examples")
APP_DIR = Path("/app")
NORMALIZER_SCRIPT = APP_DIR / "normalize_archive.py"
FORBIDDEN_DETECTOR_PACKAGES = {"chardet", "charset_normalizer"}
CANONICAL_ENCODINGS = {
    "ascii",
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16le",
    "utf-16be",
    "iso-8859-1",
    "iso-8859-2",
    "iso-8859-15",
    "cp1252",
    "windows-1251",
    "cp437",
    "mac_roman",
    "shift_jis",
    "big5",
}

EXPECTED_ENCODINGS = {
    "reports/fr/ledger_iso15.txt": {"iso-8859-15"},
    "reports/es/quotes_cp1252.txt": {"cp1252"},
    "reports/pt/names_latin1.txt": {"iso-8859-1"},
    "archives/gr/iliad_utf16.txt": {"utf-16"},
    "archives/ru/brief_utf16le.txt": {"utf-16le"},
    "archives/el/survey_utf16be.txt": {"utf-16be"},
    "legacy/mac/notes_macroman.txt": {"mac_roman"},
    "utf8/bom/modern_utf8_sig.txt": {"utf-8-sig"},
    "utf8/plain/log_utf8.txt": {"utf-8"},
    "mixed/dos/box_cp437.txt": {"cp437"},
    "mixed/jp/ticket_shiftjis.txt": {"shift_jis"},
    "mixed/cz/notice_iso2.txt": {"iso-8859-2"},
}

EXPECTED_FILES = sorted(EXPECTED_ENCODINGS)


def decode_expected_visible(relative_path):
    """Decode a visible raw fixture with its oracle encoding at assertion time."""
    raw = Path(raw_path(relative_path)).read_bytes()
    encoding = sorted(EXPECTED_ENCODINGS[relative_path])[0]
    return raw.decode(encoding)


HIDDEN_KAGGLE_CASES = {
    "hidden_case_01_utf8_label.txt": {
        "source": "die_ISO-8859-1.txt",
        "encodings": {"iso-8859-1", "cp1252"},
    },
    "hidden_case_02_windows1251_label.txt": {
        "source": "harpers_ASCII.txt",
        "encodings": {"ascii", "utf-8"},
    },
    "hidden_case_03_latin1_label.txt": {
        "source": "olaf_Windows-1251.txt",
        "encodings": {"windows-1251"},
    },
    "hidden_case_04_big5_label.txt": {
        "source": "portugal_ISO-8859-1.txt",
        "encodings": {"iso-8859-1", "cp1252"},
    },
    "hidden_case_05_cp1252_label.txt": {
        "source": "shisei_UTF-8.txt",
        "encodings": {"utf-8-sig"},
    },
    "hidden_case_06_iso8859_label.txt": {
        "source": "yan_BIG-5.txt",
        "encodings": {"big5"},
    },
}
HIDDEN_EXACT_FILES = {
    "hidden_case_02_windows1251_label.txt",
    "hidden_case_03_latin1_label.txt",
    "hidden_case_04_big5_label.txt",
    "hidden_case_05_cp1252_label.txt",
    "hidden_case_06_iso8859_label.txt",
}
HIDDEN_NEAR_EXACT_FILES = {"hidden_case_01_utf8_label.txt"}

AUDIT_FIELDS = {
    "path",
    "encoding",
    "byte_length",
    "char_count",
    "newline_style",
    "sha256_utf8",
}
def raw_path(relative_path):
    """Return the absolute source path for a relative archive member."""
    return os.path.join(RAW_DIR, *relative_path.split("/"))


def output_path(relative_path):
    """Return the absolute normalized path for a relative archive member."""
    return os.path.join(OUT_DIR, *relative_path.split("/"))


def read_output_bytes(relative_path):
    """Read normalized bytes for an archive member."""
    with open(output_path(relative_path), "rb") as f:
        return f.read()


def expected_utf8_bytes(relative_path):
    """Return the exact UTF-8 bytes expected after lossless decoding."""
    return decode_expected_visible(relative_path).encode("utf-8")


def load_audit():
    """Load the audit file as JSON after proving it is UTF-8 without a BOM."""
    with open(AUDIT_PATH, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "audit.json must not include a UTF-8 BOM."
    return json.loads(raw.decode("utf-8"))


def load_audit_from(path):
    """Load an audit file from an arbitrary normalizer output directory."""
    audit_path = Path(path) / "audit.json"
    raw = audit_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "audit.json must not include a UTF-8 BOM."
    return json.loads(raw.decode("utf-8"))


def newline_style(text):
    """Classify newline sequences using the schema required by the prompt."""
    crlf = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    lf = without_crlf.count("\n")
    cr = without_crlf.count("\r")
    styles = sum(count > 0 for count in (crlf, lf, cr))
    if styles > 1:
        return "MIXED"
    if crlf:
        return "CRLF"
    if cr:
        return "CR"
    return "LF"


def valid_decoded_texts(raw, encodings):
    """Return the possible Unicode strings for a set of acceptable encodings."""
    decoded = set()
    for encoding in encodings:
        decoded.add(raw.decode(encoding))
    return decoded


def is_nearly_expected_text(decoded_text, raw, encodings):
    """Allow tiny differences in long hidden prose while rejecting broad mojibake."""
    for expected in valid_decoded_texts(raw, encodings):
        if decoded_text == expected:
            return True
        max_len = max(len(decoded_text), len(expected))
        length_gap = abs(len(decoded_text) - len(expected))
        if length_gap > max(8, max_len // 5000):
            continue
        equal_positions = sum(1 for left, right in zip(decoded_text, expected) if left == right)
        differences = max_len - equal_positions
        if differences <= max(8, max_len // 5000):
            return True
    return False


def assert_reported_encoding_matches_output(raw, decoded_text, encoding):
    """Require the audit label to be canonical and consistent with the output text."""
    assert encoding in CANONICAL_ENCODINGS
    assert raw.decode(encoding) == decoded_text


def assert_hidden_audit_is_internally_consistent(raw, decoded_text, encoding):
    """Require hidden audit labels to be canonical and usable for the raw bytes."""
    assert encoding in CANONICAL_ENCODINGS
    raw.decode(encoding)


def test_output_tree_contains_exact_expected_files_only():
    """
    Verify that the solution recursively mirrors the raw archive and does not flatten,
    rename, omit, or add text files. Preserving relative paths is an explicit output
    requirement and prevents collisions between same-named files in different folders.
    """
    discovered = []
    for root, _, files in os.walk(OUT_DIR):
        for filename in files:
            if filename.endswith(".txt"):
                path = os.path.join(root, filename)
                discovered.append(os.path.relpath(path, OUT_DIR).replace(os.sep, "/"))
    assert sorted(discovered) == EXPECTED_FILES


def test_no_normalized_text_written_outside_normalized_tree():
    """
    Verify the solution does not scatter normalized text outputs elsewhere under
    /app. The prompt confines generated normalized files to /app/data/normalized/
    while allowing the original raw archive to remain under /app/data/raw/.
    """
    allowed_roots = {Path(RAW_DIR).resolve(), Path(OUT_DIR).resolve()}
    unexpected = []
    for path in APP_DIR.rglob("*.txt"):
        resolved = path.resolve()
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            unexpected.append(str(path))
    assert unexpected == []


def test_reusable_normalizer_script_exists():
    """
    Verify the reusable command-line normalizer required by the prompt was
    delivered. The hidden corpus test invokes this script on a separate tree.
    """
    assert NORMALIZER_SCRIPT.is_file()


def test_python_sources_avoid_automatic_detection_packages():
    """
    Check submitted Python sources for automatic encoding detector imports.
    The task requires using Python codecs plus byte/text analysis, so importing
    chardet or charset-normalizer would bypass the required implementation work.
    """
    imported_roots = set()
    for source_path in APP_DIR.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
    assert imported_roots.isdisjoint(FORBIDDEN_DETECTOR_PACKAGES)


@pytest.mark.parametrize("relative_path", EXPECTED_FILES)
def test_normalized_file_is_exact_utf8_without_bom(relative_path):
    """
    Validate the exact normalized byte stream for every archive member. This catches
    wrong single-byte choices, missing UTF-16 byte-order handling, UTF-8 BOM leakage,
    lost non-Latin text, and line-ending changes in one deterministic assertion.
    """
    actual = read_output_bytes(relative_path)
    assert not actual.startswith(b"\xef\xbb\xbf"), f"{relative_path} has a UTF-8 BOM."
    assert actual.decode("utf-8") == decode_expected_visible(relative_path)
    assert actual == expected_utf8_bytes(relative_path)


@pytest.mark.parametrize("relative_path", EXPECTED_FILES)
def test_normalized_text_has_no_corruption_markers(relative_path):
    """
    Check for common mojibake and replacement markers. These markers are strong
    evidence that bytes were decoded with a plausible but incorrect legacy codec.
    """
    text = read_output_bytes(relative_path).decode("utf-8")
    forbidden = ["\ufffd", "Ã", "Â", "¤", "\x00"]
    for marker in forbidden:
        assert marker not in text, f"{relative_path} contains corruption marker {marker!r}."


def test_audit_file_schema_and_sorting():
    """
    Verify the audit file uses the requested top-level schema, exact per-entry fields,
    and lexicographic path order. The audit is required so downstream jobs can inspect
    how each file was decoded without rereading the raw archive.
    """
    audit = load_audit()
    assert set(audit) == {"files"}
    assert isinstance(audit["files"], list)
    assert [entry["path"] for entry in audit["files"]] == EXPECTED_FILES
    for entry in audit["files"]:
        assert set(entry) == AUDIT_FIELDS


def test_audit_values_match_raw_and_normalized_files():
    """
    Verify the audit records factual metadata from both sides of the conversion.
    Byte lengths must come from the raw files, character counts from decoded text,
    newline styles from decoded content, and hashes from the emitted UTF-8 bytes.
    """
    entries = {entry["path"]: entry for entry in load_audit()["files"]}
    for relative_path in EXPECTED_FILES:
        entry = entries[relative_path]
        with open(raw_path(relative_path), "rb") as f:
            raw = f.read()
        normalized = read_output_bytes(relative_path)
        decoded_text = normalized.decode("utf-8")
        assert_reported_encoding_matches_output(raw, decoded_text, entry["encoding"])
        assert entry["byte_length"] == len(raw)
        assert entry["char_count"] == len(decoded_text)
        assert entry["newline_style"] == newline_style(decoded_text)
        assert entry["sha256_utf8"] == hashlib.sha256(normalized).hexdigest()


def test_raw_archive_was_not_modified():
    """
    Verify the raw inputs still decode with their original encodings. A solution that
    rewrites source files while producing correct outputs violates the prompt and can
    damage upstream auditability.
    """
    for relative_path, encodings in EXPECTED_ENCODINGS.items():
        with open(raw_path(relative_path), "rb") as f:
            raw = f.read()
        assert raw.decode(sorted(encodings)[0]) == decode_expected_visible(relative_path)


def test_hidden_kaggle_dataset_normalized_by_reusable_script(tmp_path):
    """
    Verify that the delivered reusable normalizer works on a hidden real-world
    encoding corpus as well as the visible generated archive. The hidden corpus
    adds ASCII, Windows-1251, Big5, UTF-8, and ISO-8859-1 files from Kaggle. This
    checks the CLI, output tree, UTF-8 validity, audit schema, and metadata on
    unseen files without duplicating every exact visible-oracle assertion.
    """
    script = NORMALIZER_SCRIPT
    assert script.is_file()
    assert HIDDEN_KAGGLE_DIR.is_dir(), "Hidden Kaggle dataset was not mounted."

    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "normalized"
    raw_dir.mkdir()

    for filename, case in HIDDEN_KAGGLE_CASES.items():
        shutil.copy2(HIDDEN_KAGGLE_DIR / case["source"], raw_dir / filename)

    subprocess.run(
        [sys.executable, str(script), str(raw_dir), str(out_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    audit_entries = {entry["path"]: entry for entry in load_audit_from(out_dir)["files"]}
    assert sorted(audit_entries) == sorted(HIDDEN_KAGGLE_CASES)

    for filename, case in HIDDEN_KAGGLE_CASES.items():
        encodings = case["encodings"]
        raw = (raw_dir / filename).read_bytes()
        output_path = out_dir / filename
        assert output_path.is_file(), f"{filename} was not normalized."
        actual = (out_dir / filename).read_bytes()
        decoded = actual.decode("utf-8")

        assert not actual.startswith(b"\xef\xbb\xbf"), f"{filename} has a UTF-8 BOM."
        assert decoded
        assert "\ufffd" not in decoded
        assert "\x00" not in decoded

        entry = audit_entries[filename]
        assert set(entry) == AUDIT_FIELDS
        assert entry["encoding"] in encodings
        if filename in HIDDEN_EXACT_FILES:
            assert decoded in valid_decoded_texts(raw, encodings)
            assert_reported_encoding_matches_output(raw, decoded, entry["encoding"])
        elif filename in HIDDEN_NEAR_EXACT_FILES:
            assert is_nearly_expected_text(decoded, raw, encodings)
            assert_hidden_audit_is_internally_consistent(raw, decoded, entry["encoding"])
        else:
            assert_hidden_audit_is_internally_consistent(raw, decoded, entry["encoding"])
        assert entry["byte_length"] == len(raw)
        assert entry["char_count"] == len(decoded)
        assert entry["newline_style"] == newline_style(decoded)
        assert entry["sha256_utf8"] == hashlib.sha256(actual).hexdigest()

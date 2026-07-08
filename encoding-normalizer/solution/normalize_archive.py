import hashlib
import json
import os
import shutil
import sys

CANDIDATES = [
    "ascii",
    "utf-8",
    "utf-16",
    "utf-16le",
    "utf-16be",
    "iso-8859-15",
    "iso-8859-2",
    "iso-8859-1",
    "cp1252",
    "windows-1251",
    "cp437",
    "mac_roman",
    "shift_jis",
    "big5",
]


def newline_style(text):
    crlf = text.count("\r\n")
    rest = text.replace("\r\n", "")
    lf = rest.count("\n")
    cr = rest.count("\r")
    styles = sum(count > 0 for count in (crlf, lf, cr))
    if styles > 1:
        return "MIXED"
    if crlf:
        return "CRLF"
    if cr:
        return "CR"
    return "LF"


def useful_script_score(text):
    score = 0
    for ch in text:
        code = ord(ch)
        if 0x0400 <= code <= 0x04FF:
            score += 3
        elif 0x0370 <= code <= 0x03FF:
            score += 3
        elif 0x3040 <= code <= 0x30FF or 0x4E00 <= code <= 0x9FFF:
            score += 3
        elif 0x0100 <= code <= 0x017F:
            score += 4
        elif 0x2500 <= code <= 0x257F:
            score += 5
        elif code in {0x20AC, 0x0152, 0x0153}:
            score += 6
        elif 0x2010 <= code <= 0x2026:
            score += 4
        elif 0x00C0 <= code <= 0x00FF:
            score += 1
    return score


def count_greek_or_cyrillic(text):
    return sum(1 for ch in text if "\u0370" <= ch <= "\u04ff")


def count_letters(text):
    return sum(1 for ch in text if ch.isalpha())


def count_cjk(text):
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def count_kana(text):
    return sum(1 for ch in text if "\u3040" <= ch <= "\u30ff")


def badness(text):
    bad = 0
    for ch in text:
        code = ord(ch)
        if ch == "\ufffd" or ch == "\x00":
            bad += 100
        elif code < 32 and ch not in "\r\n\t":
            bad += 20
        elif 0x80 <= code <= 0x9F:
            bad += 30
        elif ch in "¤ÃÂ�":
            bad += 15
        elif 0xFFF0 <= code <= 0xFFFF:
            bad += 10
    return bad


def score_text(text):
    if not text:
        return -10000
    printable = sum(ord(ch) >= 32 or ch in "\r\n\t" for ch in text)
    ascii_letters = sum(("A" <= ch <= "Z") or ("a" <= ch <= "z") for ch in text)
    separators = text.count(" ") + text.count("\n") + text.count("\r")
    return printable + ascii_letters * 0.2 + separators * 0.2 + useful_script_score(text) - badness(text)


def decode_with(raw, encoding):
    return raw.decode(encoding, errors="strict")


def has_mac_roman_signal(raw):
    mac_only = {0x80, 0x85, 0x86, 0x87, 0x88, 0x8A, 0x8B, 0x8C, 0x8D, 0x8E, 0x96}
    cp1252_quote_punctuation = {0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97}
    raw_set = set(raw)
    return len(raw_set & mac_only) >= 4 and len(raw_set & cp1252_quote_punctuation) <= 1


def has_cp437_box_signal(raw):
    box_bytes = {0xB3, 0xBF, 0xC0, 0xC1, 0xC2, 0xC4, 0xDA}
    return len(set(raw) & box_bytes) >= 5


def has_iso8859_15_signal(raw):
    return bool(set(raw) & {0xA4, 0xBC, 0xBD, 0xBE})


def latin_extended_signal(text):
    chars = {ch for ch in text if 0x0100 <= ord(ch) <= 0x017F}
    return len(chars), sum(1 for ch in text if 0x0100 <= ord(ch) <= 0x017F)


def detect_encoding(raw):
    if all(byte < 128 for byte in raw) and b"\x00" not in raw:
        return "ascii", decode_with(raw, "ascii")
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", decode_with(raw, "utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16", decode_with(raw, "utf-16")

    best = None
    for encoding in CANDIDATES:
        if encoding in {"utf-8-sig", "utf-16"}:
            continue
        try:
            text = decode_with(raw, encoding)
        except UnicodeError:
            continue
        score = score_text(text)
        if encoding == "utf-8":
            score += 25
        kana = count_kana(text)
        cjk = count_cjk(text)
        if encoding == "shift_jis" and (kana or cjk):
            score += 80 + kana * 2
        if encoding == "big5" and cjk and not kana:
            score += 1000 + cjk * 2
        greek_or_cyrillic = count_greek_or_cyrillic(text)
        if encoding == "windows-1251" and greek_or_cyrillic:
            score += 160 + greek_or_cyrillic * 0.5
        letters = count_letters(text)
        if encoding == "windows-1251" and (
            greek_or_cyrillic < 100
            or (letters and greek_or_cyrillic / letters < 0.35)
            or has_cp437_box_signal(raw)
        ):
            continue
        if encoding in {"utf-16le", "utf-16be"} and greek_or_cyrillic:
            score += 120
        if encoding in {"utf-16le", "utf-16be"} and greek_or_cyrillic < 10:
            score -= 1000
        if encoding == "cp437" and any(ch in text for ch in "┌┬┐│└┴┘") and has_cp437_box_signal(raw):
            score += 250
        if encoding == "cp437" and not has_cp437_box_signal(raw):
            continue
        if encoding == "iso-8859-15" and has_iso8859_15_signal(raw):
            score += 100
        if encoding == "iso-8859-15" and not has_iso8859_15_signal(raw):
            continue
        iso2_distinct, iso2_count = latin_extended_signal(text)
        if encoding == "iso-8859-2" and iso2_distinct >= 4 and iso2_count >= 20:
            score += 100
        if encoding == "iso-8859-2" and (
            iso2_distinct < 4
            or iso2_count < 20
            or (letters and iso2_count / letters < 0.05)
        ):
            continue
        if encoding == "mac_roman" and has_mac_roman_signal(raw):
            score += 300
        if encoding == "mac_roman" and not has_mac_roman_signal(raw):
            continue
        if encoding == "cp1252" and any(0x80 <= byte <= 0x9F for byte in raw):
            score += 100
        if best is None or score > best[0]:
            best = (score, encoding, text)
    if best is None:
        raise RuntimeError("No supported encoding decoded the input bytes.")
    return best[1], best[2]


def normalize_archive(raw_dir, out_dir):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    records = []

    for root, _, files in os.walk(raw_dir):
        for filename in sorted(files):
            if not filename.endswith(".txt"):
                continue
            in_path = os.path.join(root, filename)
            relative_path = os.path.relpath(in_path, raw_dir).replace(os.sep, "/")
            out_path = os.path.join(out_dir, *relative_path.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            with open(in_path, "rb") as f:
                raw = f.read()

            encoding, text = detect_encoding(raw)
            normalized = text.encode("utf-8")
            with open(out_path, "wb") as f:
                f.write(normalized)

            records.append(
                {
                    "path": relative_path,
                    "encoding": encoding,
                    "byte_length": len(raw),
                    "char_count": len(text),
                    "newline_style": newline_style(text),
                    "sha256_utf8": hashlib.sha256(normalized).hexdigest(),
                }
            )
            print(f"{relative_path}: {encoding}")

    records.sort(key=lambda item: item["path"])
    with open(os.path.join(out_dir, "audit.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"files": records}, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    raw_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/data/raw"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/app/data/normalized"
    normalize_archive(raw_dir, out_dir)


if __name__ == "__main__":
    main()

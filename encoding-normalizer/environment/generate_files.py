import os
import shutil

RAW = "/app/data/raw"
NORMALIZED = "/app/data/normalized"

if os.path.isdir(RAW):
    shutil.rmtree(RAW)
if os.path.isdir(NORMALIZED):
    shutil.rmtree(NORMALIZED)
os.makedirs(RAW, exist_ok=True)


def write_text(relative_path, text, encoding):
    path = os.path.join(RAW, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode(encoding))


texts = {
    "reports/fr/ledger_iso15.txt": (
        "Synthese financiere 2025\r\n"
        "Montant regle: 1 284,50 € pour l'œuvre imprimee.\r\n"
        "Le service achats confirme: delai, qualite, cout.\r\n"
        "Reference: FR-œ-€-015\r\n"
    )
    * 7,
    "reports/es/quotes_cp1252.txt": (
        "Cronica del archivo municipal\r\n"
        "“La verdad” llego tarde — pero llego integra.\r\n"
        "El ano senalado fue 1898; la senora Munoz dijo: ‘adelante…’\r\n"
        "Senal critica: ñ á í ó ú ¿ ¡\r\n"
    )
    * 6,
    "reports/pt/names_latin1.txt": (
        "Relatorio de nomes antigos\n"
        "Joao, Ines, Sebastiao e Tereza visitaram Sao Luis.\n"
        "A acao exigiu coracao, observacao e muita memoria.\n"
        "Marcador: ç ã õ é ê á\n"
    )
    * 6,
    "archives/gr/iliad_utf16.txt": (
        "The Iliad of Homer\n"
        "Sing, O goddess, the anger of Achilles son of Peleus.\n"
        "Hector answered with measured courage before the bronze gates.\n"
        "Marker: UTF16-BOM Ω Α Η\n"
    )
    * 6,
    "archives/ru/brief_utf16le.txt": (
        "Сводка архива без метки порядка байтов\r\n"
        "Москва хранит записи: январь, февраль, март.\r\n"
        "Контрольная строка: Ж щ ю я №\r\n"
    )
    * 6,
    "archives/el/survey_utf16be.txt": (
        "Αρχείο έρευνας χωρίς BOM\n"
        "Η Αθήνα κρατά σημειώσεις για γλώσσα και μνήμη.\n"
        "Σήμα ελέγχου: Ω ψ ξ έ\n"
    )
    * 6,
    "legacy/mac/notes_macroman.txt": (
        "Macintosh field notes\n"
        "Cafe creme in Zurich; Goteborg and Malmo were listed.\n"
        "Symbols from the old export: Ä Ö Ü ä ö ü å é ñ\n"
    )
    * 6,
    "utf8/bom/modern_utf8_sig.txt": (
        "Modern UTF-8 export with signature\n"
        "Emoji survives: 🚀; math survives: π≈3.14159; currency: €.\n"
        "Languages: français, español, ελληνικά.\n"
    )
    * 5,
    "utf8/plain/log_utf8.txt": (
        "Plain UTF-8 operational log\n"
        "No signature appears here, but the file contains café, Δ, and 東京.\n"
        "Status path: normalized/ready\n"
    )
    * 5,
    "mixed/dos/box_cp437.txt": (
        "DOS inventory screen\n"
        "┌────┬────┐\n"
        "│Café│OK  │\n"
        "└────┴────┘\n"
        "Marker: Ç ü é â ä à å ç ê ë è ï î ì Ä Å É\n"
    )
    * 5,
    "mixed/jp/ticket_shiftjis.txt": (
        "保守記録\n"
        "東京駅で受け取った切符を確認する。\n"
        "状態: 完了、担当: 山田、番号: SJIS-42\n"
    )
    * 6,
    "mixed/cz/notice_iso2.txt": (
        "Archivni oznameni\n"
        "Prilis zlutoucky kun upel dabelske ody.\n"
        "Kontrola znaku: ě š č ř ž ý á í é ů Ľ ľ Ť ť\n"
    )
    * 6,
}

encodings = {
    "reports/fr/ledger_iso15.txt": "iso-8859-15",
    "reports/es/quotes_cp1252.txt": "cp1252",
    "reports/pt/names_latin1.txt": "iso-8859-1",
    "archives/gr/iliad_utf16.txt": "utf-16",
    "archives/ru/brief_utf16le.txt": "utf-16le",
    "archives/el/survey_utf16be.txt": "utf-16be",
    "legacy/mac/notes_macroman.txt": "mac_roman",
    "utf8/bom/modern_utf8_sig.txt": "utf-8-sig",
    "utf8/plain/log_utf8.txt": "utf-8",
    "mixed/dos/box_cp437.txt": "cp437",
    "mixed/jp/ticket_shiftjis.txt": "shift_jis",
    "mixed/cz/notice_iso2.txt": "iso-8859-2",
}

for relative_path, text in texts.items():
    write_text(relative_path, text, encodings[relative_path])

print("Mixed encoding input files generated successfully.")
for root, _, files in os.walk(RAW):
    for filename in sorted(files):
        path = os.path.join(root, filename)
        relative = os.path.relpath(path, RAW)
        print(f"  {relative}: {os.path.getsize(path)} bytes")

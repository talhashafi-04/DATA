# Encoding Normalizer
You have a small text archive of some kind.
The files are old. They use different encodings. Make sure to convert them to UTF-8.
Maintain the structure of the folder. Also create a little audit file that records what happened.
## What To Do
Look in /app/data/raw/.
There are twelve .txt files in that tree. Some are located within subfolders.
Find every .txt file recursively. Decode each one. Then write the UTF-8 version to /app/data/normalized/.
Use the same relative path for the output file. To make it more clear, in this example the input file is located at /app/data/raw/reports/example.txt and the output at /app/data/normalized/reports/example.txt.
Use file names and folder names as paths only. Work out the encoding from the file content.
Read bytes from the file and work from those bytes. Create your own detector using Python codecs and byte or text checks of your own.
Avoid automatic detector packages like chardet or charset-normalizer.
Write the decoded text exactly. Keep line endings. Keep spaces. Keep punctuation. Keep symbols. Keep non-Latin text. Keep trailing newlines.
Write UTF-8 without a UTF-8 BOM.
Your program should process the following types of input:
- ASCII
- Western single-byte encodings
- Windows-1251 Cyrillic text
- UTF-8, with and without a BOM
- UTF-16 with a BOM
- UTF-16 little-endian without a BOM
- UTF-16 big-endian without a BOM
- DOS code-page text
- Shift_JIS text
- Big5 text
There are some old encodings that may appear similar. Use the most suitable canonical label, based on the actual content of the file. Even after decoding, the text should be correct.
Write this reusable script:
/app/normalize_archive.py
It must be run like this:
python3 /app/normalize_archive.py <raw_root> <normalized_root>
This command should normalize every .txt file under <raw_root> into <normalized_root>. It must follow the same rules and the same audit format.
## Audit File
Create:
/app/data/normalized/audit.json
Write it as UTF-8 JSON without a BOM.
The top-level JSON value has to be an object containing exactly one key:
files
The files value should be a list. Sort the list by path in lexicographic order.
Each file entry must contain exactly this field set:
- path: relative POSIX path to the normalized text file, like reports/example.txt
- encoding: canonical source encoding label
- byte_length: length of the original input file in bytes
- char_count: number of decoded Unicode characters before UTF-8 encoding
- newline_style: one of LF, CRLF, CR, or MIXED
- sha256_utf8: SHA-256 hex digest of the normalized UTF-8 bytes
Only use the following encoding labels:
ascii, utf-8, utf-8-sig, utf-16, utf-16le, utf-16be, iso-8859-1, iso-8859-2, iso-8859-15, cp1252, windows-1251, cp437, mac_roman, shift_jis, big5
## Rules
At first, /app/data/normalized/ might be absent. That is okay.
Write normalized text files only inside of /app/data/normalized/.
Leave everything inside /app/data/raw/ unchanged.
Keep the raw file names and raw file contents unchanged.

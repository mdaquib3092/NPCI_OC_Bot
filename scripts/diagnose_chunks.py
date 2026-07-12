
import os, sys
from pypdf import PdfReader

folder = sys.argv[1]  # circulars folder
empty, scanned, ok = [], [], []

for dirpath, _, files in os.walk(folder):
    for fn in files:
        if not fn.lower().endswith(".pdf"):
            continue
        path = os.path.join(dirpath, fn)
        try:
            text = "".join((p.extract_text() or "") for p in PdfReader(path).pages)
            chars = len(text.strip())
            if chars < 100:
                scanned.append((path, chars))   # scanned image PDF - OCR chahiye
            else:
                ok.append(path)
        except Exception as e:
            empty.append((path, str(e)))

print(f"OK: {len(ok)} | Scanned/empty: {len(scanned)} | Corrupt: {len(empty)}\n")
for p, c in scanned: print(f"  OCR needed ({c} chars): {p}")
for p, e in empty:   print(f"  CORRUPT: {p} -> {e}")
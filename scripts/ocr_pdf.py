# ocr_pdf.py
import os
import sys
import io
import fitz  # pymupdf
import pytesseract
from PIL import Image


def extract_text_with_ocr(path, dpi=300):
    doc = fitz.open(path)
    full_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img)
        full_text.append(text)
    doc.close()
    return "\n\n".join(full_text)


def has_text_already(path, min_chars=100):
    doc = fitz.open(path)
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return len(text.strip()) >= min_chars


def main():
    if len(sys.argv) < 2:
        print("Usage: python ocr_pdf.py <input_folder> [output_folder]")
        sys.exit(1)

    in_folder = sys.argv[1]
    out_folder = sys.argv[2] if len(sys.argv) > 2 else "Data/ocr_text"
    os.makedirs(out_folder, exist_ok=True)

    if not os.path.isdir(in_folder):
        print(f"ERROR: '{in_folder}' is not a valid folder.")
        sys.exit(1)

    files = [os.path.join(dp, f) for dp, _, fs in os.walk(in_folder)
              for f in fs if f.lower().endswith(".pdf")]

    print(f"Found {len(files)} PDFs in '{in_folder}'")
    print(f"Output will be saved to '{out_folder}'\n")

    if not files:
        print("No PDFs found - check the folder path.")
        return

    done, skipped, failed = 0, 0, 0

    for i, path in enumerate(files, 1):
        fname = os.path.basename(path)
        out_path = os.path.join(out_folder, fname + ".txt")

        if os.path.exists(out_path):
            skipped += 1
            continue

        print(f"[{i}/{len(files)}] {fname}", flush=True)

        try:
            if has_text_already(path):
                print("    -> already has text layer, copying that instead")
                doc = fitz.open(path)
                text = "".join(p.get_text() for p in doc)
                doc.close()
            else:
                print("    -> running OCR...")
                text = extract_text_with_ocr(path)

            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
            done += 1
            print(f"    -> saved ({len(text)} chars)")
        except Exception as e:
            failed += 1
            print(f"    -> FAILED: {e}")

    print("\n================ SUMMARY ================")
    print(f"Processed : {done}")
    print(f"Skipped   : {skipped} (already done)")
    print(f"Failed    : {failed}")
    print(f"Output folder: {out_folder}")


if __name__ == "__main__":
    main()
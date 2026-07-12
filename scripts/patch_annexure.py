# patch_annexure.py
import json

ANNEXURE_120 = """
[Circular: OC 120 | UPI Limit Standardization | Date: Oct 2021 | Section: Annexure A]

OC 120 Annexure A defines standardized UPI transaction limits across all ecosystem members:
- P2P and P2PM default limit: Rs 1,00,000 per transaction
- P2P/P2PM collect request limit: Rs 2,000
- P2M verified merchant: Rs 1,00,000 default; Rs 2,00,000 for specific categories (as per OC 82 and OC 96)
- P2M non-verified merchant (Share Intent link and pay): Rs 2,000
- P2M non-verified merchant offline (QR share and pay): Rs 2,000
Compliance deadline: 31 October 2021.
"""

path = "Data/extracted/120.json"
d = json.load(open(path))
d["text"] = d["text"] + "\n\n" + ANNEXURE_120
d["char_count"] = len(d["text"])
d["notes"] = "Annexure A manually reconstructed - OCR lost table values"
json.dump(d, open(path, "w"), indent=2, ensure_ascii=False)
print("Patched:", path)
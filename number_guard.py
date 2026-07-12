"""
Number-hallucination guard for the NPCI OC chatbot.

Problem: LLMs sometimes restate numbers/amounts incorrectly even when the
source text is completely correct (e.g. source says "Rs 10,000" but the
LLM's answer says "Rs 2,10,000" or swaps the currency symbol). This is a
generation-stage error, not a data-extraction error.

Fix: after generating an answer, extract every number that appears in it
and check whether that exact number (ignoring commas/currency symbols)
appears somewhere in the retrieved source context. If a number in the
answer does NOT appear in the source, flag it - the answer likely
contains a hallucinated figure.

Usage (in app.py, after generating an answer):

    from number_guard import check_numbers

    answer = generate_answer(question, context)
    unverified = check_numbers(answer, context)
    if unverified:
        # Option A: show a warning banner to the user
        # Option B: regenerate the answer once with an extra warning
        # Option C: strip/replace the unverified numbers
        print("WARNING - numbers not found in source:", unverified)
"""

import re

# Matches numbers with optional currency symbol/commas/decimals, e.g.
# "₹10,000", "5,00,000", "10000", "2.5", "5 lakh"
NUMBER_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)?\s*[\d][\d,]*(?:\.\d+)?(?:\s*(?:lakh|crore))?",
    re.IGNORECASE,
)

LAKH_CRORE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(lakh|crore)s?", re.IGNORECASE
)


def expand_lakh_crore(text: str) -> str:
    """Append the full digit-equivalent right after any 'X lakh'/'X crore'
    mention (e.g. '4.0 lakh' -> '4.0 lakh 400000'), so substring comparison
    works regardless of which format (words vs digits) the source or the
    answer happens to use for the same amount."""

    def repl(m):
        num = float(m.group(1))
        unit = m.group(2).lower()
        multiplier = 100000 if unit == "lakh" else 10000000
        value = int(round(num * multiplier))
        return f"{m.group(0)} {value}"

    return LAKH_CRORE_PATTERN.sub(repl, text)


def normalize_number(raw: str) -> str:
    """Strip currency symbols, commas, and whitespace so '₹10,000' and
    '10000' compare as equal. '£' is included because OCR frequently corrupts
    the '₹' glyph into a visually similar '£' in the source text."""
    cleaned = re.sub(r"[₹$€£]|rs\.?|inr", "", raw, flags=re.IGNORECASE)
    cleaned = cleaned.replace(",", "").strip().lower()
    return cleaned


def check_numbers(answer: str, source_context: str) -> list:
    """Return the list of numeric tokens in `answer` that do NOT appear
    (in normalized form) anywhere in `source_context`. An empty list
    means every number in the answer was verified against the source.
    """
    normalized_source = normalize_number(expand_lakh_crore(source_context))

    # Numbers that are OC-citation references (e.g. "OC 181", "(OC 220)")
    # are document references, not monetary/quantity figures — mask them
    # out first so they're never mistaken for hallucinated amounts.
    masked_answer = re.sub(r"\bOC\s*\d+[A-Z]?\b", "OC_REF", answer, flags=re.IGNORECASE)

    found_in_answer = NUMBER_PATTERN.findall(masked_answer)
    unverified = []

    for raw_num in found_in_answer:
        norm = normalize_number(raw_num)
        # Skip trivial/short numbers (e.g. a lone "1" from "(OC 1)") -
        # these cause too many false positives to be worth checking.
        digits_only = re.sub(r"\D", "", norm)
        
        # Hardened safety check: Allow small numbers IF they represent critical
        # transaction values (e.g., 50, 100, 200, 500) or percentages (e.g., 1.1, 0.5)
        is_critical_small_num = norm in ["50", "100", "200", "500", "1.1", "0.5"]
        
        if len(digits_only) < 3 and not is_critical_small_num:
            continue
        if norm not in normalized_source:
            unverified.append(raw_num.strip())

    return unverified


# Every amount in the NPCI/UPI corpus is in Indian Rupees. Rupees appear as
# "₹", "Rs", or "INR" — and OCR frequently corrupts the "₹" glyph into a
# visually similar "£". All of these are treated as the SAME currency, so the
# model correctly writing "₹" is never flagged against an OCR-mangled "£" in
# the source. Only a genuinely different currency ($ or €) counts as a swap.
FOREIGN_SYMBOLS = ["$", "€"]


def check_currency_symbols(answer: str, source_context: str) -> list:
    """Detect a real currency swap: the answer introducing a foreign currency
    ($ or €) that the source doesn't actually use.

    check_numbers() strips currency symbols before comparing, so "€5,000" in
    the answer normalizes to "5000" and matches source "₹5,000" (same digits)
    — the symbol swap goes undetected even though it's a real error. This
    catches that. Rupee forms (₹/Rs/INR and the OCR artifact £) are all
    equivalent and never flagged, so an OCR-mangled "£" in the source can't
    cause a false positive against a correct "₹" in the answer.
    """
    foreign_in_answer = {s for s in FOREIGN_SYMBOLS if s in answer}
    if not foreign_in_answer:
        return []

    foreign_in_source = {s for s in FOREIGN_SYMBOLS if s in source_context}
    wrong_symbols = foreign_in_answer - foreign_in_source
    if wrong_symbols:
        wrong = ", ".join(sorted(wrong_symbols))
        return [
            f"answer uses {wrong}, which does not appear in the source "
            f"(NPCI circulars are in ₹/Rs) — likely a currency error"
        ]
    return []


if __name__ == "__main__":
    # Quick self-test using the OC 226A case that motivated this guard.
    source = (
        "the per-transaction limit for On-Device Biometric Authentication "
        "(fingerprint, face, etc.) in UPI is hereby enhanced from ₹ 5,000 "
        "to ₹ 10,000, effective 07 August 2026."
    )
    bad_answer = "The limit was raised from €5,000 to €210,000."
    good_answer = "The limit was raised from ₹5,000 to ₹10,000."
    # OCR corrupted the ₹ glyph into £ in this source — a correct ₹ answer
    # must NOT be flagged against it.
    ocr_source = "the limit is enhanced from £ 5,000 to £ 10,000 effective 2026."

    print("Bad answer unverified numbers:", check_numbers(bad_answer, source))
    print("Good answer unverified numbers:", check_numbers(good_answer, source))
    print("Bad answer currency check:", check_currency_symbols(bad_answer, source))
    print("Good answer currency check:", check_currency_symbols(good_answer, source))
    print("OCR-£ source, ₹ answer (should be [] — no false positive):",
          check_currency_symbols(good_answer, ocr_source))
    print("OCR-£ source, ₹ answer numbers (should be []):",
          check_numbers(good_answer, ocr_source))
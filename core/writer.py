"""Builds the answer object.

Two ways:
- deterministic builders for limits, codes, refusals and similar: numbers, dates and quotes come
  straight from reviewed facts, so no model can mistype them;
- an LLM writer for summaries, definitions and general questions: it returns JSON from numbered
  evidence passages, and the checker verifies it before anything is shown.
"""

import difflib
import re

from . import phrases as ph
from .reference import build_reference, clause_for
from .answer import Answer, Cell, Citation, Line, Obligation, Row
from .evidence.documents import EvidencePack


# ---------------------------------------------------------------- helpers
class _Citations:
    """Collects citations, one per distinct (document, quote)."""

    def __init__(self, stores):
        self.stores, self.items, self._index = stores, [], {}

    def add(self, doc_id: str, quote: str, page: str = "", context: str = "", clause: str = "") -> str:
        key = (doc_id, quote)
        if key not in self._index:
            row = self.stores.by_doc.get(doc_id, {})
            oc = row.get("oc_number", "") or ("CC" if row.get("series") == "CC" else "")
            ref = build_reference(row, page, clause or (clause_for(quote, context) if context else ""))
            c = Citation(f"c{len(self.items) + 1}", oc, doc_id, row.get("title", ""), quote,
                         row.get("issue_date", ""), page, ref)
            self.items.append(c)
            self._index[key] = c.id
        return self._index[key]


def _oc_text(oc: str) -> str:
    if oc == "CC":
        return "UPI Consolidated Circular"
    return f"OC {oc}" if oc else ""


def _date_text(lang: str, date: str) -> str:
    return ph.t(lang, "effective", date=ph.fmt_date(date)) if date else ""


def _fact_cell(lang: str, cites: _Citations, f: dict, mcc_list: list = None) -> Cell:
    bits = []
    if mcc_list:
        bits.append("MCC " + ", ".join(mcc_list))
    bits.append(_oc_text(f["source_oc"]))
    d = _date_text(lang, f["effective_date"])
    if d:
        bits.append(d)
    text = f"{ph.fmt_value(f['value'], f['unit'])} ({'; '.join(b for b in bits if b)})"
    return Cell(text=text, value=float(f["value"]), unit=f["unit"], effective_date=f["effective_date"],
                source_oc=f["source_oc"], citation_id=cites.add(f["source_doc_id"], f["quote"], f.get("page", "")),
                fact_id=f["fact_id"])


def _group_cells(lang: str, cites: _Citations, facts: list) -> list:
    """One cell per distinct (value, source, date); facts that differ only by MCC share a cell."""
    groups = {}
    for f in facts:
        groups.setdefault((f["value"], f["source_doc_id"], f["effective_date"]), []).append(f)
    cells = []
    for fs in groups.values():
        cell = _fact_cell(lang, cites, fs[0], [x["mcc"] for x in fs if x["mcc"]] or None)
        for x in fs[1:]:
            cid = cites.add(x["source_doc_id"], x["quote"], x.get("page", ""))
            if cid != cell.citation_id and cid not in cell.more_citation_ids:
                cell.more_citation_ids.append(cid)
        cells.append(cell)
    return cells


def _status_for(facts: list) -> str:
    return "verified" if facts and all(f["review_status"] == "human_verified" for f in facts) else "unverified_facts"


def _meta(stores, plan, **extra) -> dict:
    return {"intent": plan.intent, "build_id": stores.build_id, "corpus_as_of": stores.corpus_as_of, **extra}


# ------------------------------------------------------- limit and code answers
def limit_answer(stores, plan, ev, answer_type: str = "limit_table", prefix: str = "") -> Answer:
    lang = plan.language
    cites = _Citations(stores)
    rows, earlier, used = [], [], []
    bank_row = False
    for r in ev.rows:
        if r.status == "no_oc_sets_this":
            closed = any(f.get("closed_by_doc_id") for f in r.earlier)
            bank_count = r.kind == "per_24h_count" and r.direction == "send"   # banks manage how many transactions a user may send
            note = ph.t(lang, "row_withdrawn" if closed else "bank_managed" if bank_count else "no_oc_sets_this")
            if closed and bank_count:
                note = f"{note}. {ph.t(lang, 'bank_managed')}"
            bank_row = bank_row or (bank_count and plan.limit_kind == "per_24h_count" and plan.direction != "receive")
            rows.append(Row(label=r.label, status="withdrawn" if closed else "no_oc_sets_this", note=note))
            for f in r.earlier:                      # a withdrawn limit: shown, never as the current one
                cell = _fact_cell(lang, cites, f)
                earlier.append(Line(ph.t(lang, "withdrawn", text=f"{r.label}: {cell.text}"), [cell.citation_id]))
                if f.get("closed_by_doc_id"):
                    cid = cites.add(f["closed_by_doc_id"], f["closed_by_quote"], f.get("closed_by_page", ""),
                                    clause=f.get("closed_by_clause", ""))
                    ref = next(c.reference for c in cites.items if c.id == cid)
                    earlier.append(Line(ph.t(lang, "closed_by", ref=ref), [cid]))
            continue
        status = "set" if r.status == "set" else "unconfirmed"
        cells = _group_cells(lang, cites, r.facts)
        note = " | ".join(dict.fromkeys(f["conditions"] for f in r.facts if f["conditions"]))[:300]
        if status == "unconfirmed":
            note = (ph.t(lang, "unconfirmed") + ": " + note).strip(": ")
        rows.append(Row(label=r.label, status=status, cells=cells, note=note))
        used.extend(r.facts)
        for f in r.earlier:
            cell = _fact_cell(lang, cites, f)
            key = "withdrawn" if f["status"] == "withdrawn" else "earlier"
            line = Line(ph.t(lang, key, text=f"{r.label}: {cell.text}"), [cell.citation_id])
            if all(line.text != e.text for e in earlier):
                earlier.append(line)
    first = next((r for r in rows if r.status == "set" and r.cells), None)
    asked = _history_match(plan, ev, rows, cites)
    if bank_row:
        verdict = prefix + ph.t(lang, "bank_managed")
    elif asked:
        verdict = prefix + asked
    elif first:
        verdict = f"{prefix}{first.label}: " + " / ".join(c.text for c in first.cells) + "."
    else:
        verdict = prefix + ph.t(lang, "no_facts")
    details = [Line(ph.t(lang, ev.hint))] if ev.hint else []
    ans = Answer(answer_type=answer_type, language=lang, verdict=verdict, status=_status_for(used), table=rows,
                 details=details, earlier=earlier, citations=cites.items, meta=_meta(stores, plan))
    if ev.unverified:
        ans.notice = ph.t(lang, "dev_unverified")
    if bank_row:
        ans.notice = (ph.t(lang, "bank_managed") + " " + ans.notice).strip()
    return ans


def _history_match(plan, ev, rows, cites):
    """If the question names an amount that an earlier (superseded) fact had, say so directly."""
    from .checker import free_text_numbers

    nums = set(free_text_numbers(plan.question or ""))
    if not nums:
        return ""
    for r, row in zip(ev.rows, rows):
        if r.status != "set" or not row.cells:
            continue
        for f in r.earlier:
            if str(int(float(f["value"]))) in nums and f["value"] not in {c["value"] for c in r.facts}:
                old = _fact_cell(plan.language, cites, f)
                return ph.t(plan.language, "history_verdict", label=r.label, old=old.text,
                            new=" / ".join(c.text for c in row.cells))
    return ""


def code_answer(stores, plan, ev) -> Answer:
    lang = plan.language
    fam = "MCC" if ev.family == "mcc" else "Purpose code"
    if ev.outcome == "specific_rule":
        return limit_answer(stores, plan, ev.limit, "limit_table", prefix=f"{fam} {ev.code}: ")
    cites = _Citations(stores)
    if ev.outcome == "reverse":
        if not ev.reverse:
            return Answer("code_result", lang, ph.t(lang, "code_unknown_reverse"), "not_found", meta=_meta(stores, plan))
        details = [Line(f"MCC {mcc}: {cat}", [cites.add(f["source_doc_id"], f["quote"], f.get("page", ""))]) for mcc, cat, f in ev.reverse]
        return Answer("code_result", lang, "; ".join(f"{cat}: MCC {mcc}" for mcc, cat, _f in ev.reverse),
                      _status_for([f for _m, _c, f in ev.reverse]), details=details, citations=cites.items,
                      meta=_meta(stores, plan))
    if ev.outcome == "mention_only":
        docs = sorted({m["source_doc_id"] for m in ev.mentions})
        details = []
        for m in ev.mentions[:6]:
            cid = cites.add(m["source_doc_id"], m["quote"])
            details.append(Line(f"{_oc_text(m['oc_number'])}: {m['quote'][:200]}", [cid]))
        return Answer("code_result", lang, ph.t(lang, "code_mention_only", family=fam, code=ev.code, n=len(docs)),
                      "verified", details=details, citations=cites.items, meta=_meta(stores, plan))
    return Answer("code_result", lang, ph.t(lang, "code_not_mentioned", family=fam, code=ev.code), "not_found",
                  notice=ph.t(lang, "corpus_as_of", date=stores.corpus_as_of), meta=_meta(stores, plan))


# ------------------------------------------------------------ simple answers
def refusal(stores, plan, kind: str) -> Answer:
    key = {"bank": "refusal_bank", "advice": "refusal_advice"}.get(kind, "refusal_scope")
    return Answer("refusal", plan.language, ph.t(plan.language, key), "not_found", meta=_meta(stores, plan, reason=kind))


def clarify(stores, plan) -> Answer:
    return Answer("clarify", plan.language, ph.t(plan.language, "clarify_limit"), "not_found",
                  chips=list(ph.t(plan.language, "chips_limit")), meta=_meta(stores, plan))


def not_public(stores, plan, row: dict) -> Answer:
    title = row["title"] if "not shown" not in row["title"] else ""
    tpart = ph.t(plan.language, "not_public_title", title=title) if title else ""
    return Answer("not_public", plan.language, ph.t(plan.language, "not_public", oc=row["oc_number"], title=tpart),
                  "not_found", meta=_meta(stores, plan, doc_id=row["doc_id"]))


def oc_not_found(stores, plan, oc: str) -> Answer:
    return Answer("not_found", plan.language, ph.t(plan.language, "oc_not_found", oc=oc), "not_found",
                  notice=ph.t(plan.language, "corpus_as_of", date=stores.corpus_as_of), meta=_meta(stores, plan))


def not_found(stores, plan, thin: int = 0) -> Answer:
    notice = ph.t(plan.language, "corpus_as_of", date=stores.corpus_as_of)
    if thin:
        notice = ph.t(plan.language, "thin", n=thin) + " " + notice
    return Answer("not_found", plan.language, ph.t(plan.language, "not_found"), "not_found", notice=notice,
                  meta=_meta(stores, plan))


def passages(stores, plan, pack: EvidencePack, reason_key: str = "passages", limit: int = 3) -> Answer:
    cites = _Citations(stores)
    details, seen = [], set()
    ordered = sorted(pack.items, key=lambda e: e.doc_id in seen)  # keep ranking; one passage per document first
    firsts, rest = [], []
    for e in pack.items:
        (rest if e.doc_id in seen else firsts).append(e)
        seen.add(e.doc_id)
    for e in (firsts + rest)[:limit]:
        quote = " ".join(e.text.split())[:300]
        cid = cites.add(e.doc_id, quote, e.page, e.text)
        details.append(Line(f"{_oc_text(e.oc_number)} ({e.title}): {quote[:170]}", [cid]))
    return Answer("passages", plan.language, ph.t(plan.language, reason_key), "partially_verified", details=details,
                  citations=cites.items, notice=ph.t(plan.language, "corpus_as_of", date=stores.corpus_as_of),
                  meta=_meta(stores, plan))


# ---------------------------------------------------------------- LLM writer
SYSTEM = """You answer questions about NPCI UPI Operating Circulars (OCs) using ONLY the numbered EVIDENCE passages.
Return a single JSON object and nothing else.

Rules:
- Use only the evidence. If it does not answer the question, return {{"answer_type": "not_found"}}.
- Copy every amount, percentage, date, count, MCC code and OC number exactly as written in the evidence. Never convert, round or recompute.
- Report what the circular says. Do not give advice.
- Every statement carries "evidence": the id of the passage it comes from, such as "E2". A "quote" is optional; if you give one it must be copied exactly from that passage.
- If a later circular changes an earlier rule, state the current rule first and put the earlier rule under "earlier".
- A passage marked WITHDRAWN is no longer in force: say that it was withdrawn and do not present it as the current rule.
- Write the text fields in {language}. Keep quotes in the original wording.
- Be brief: at most 3 details and 3 obligations, and an "earlier" item only if a later circular changed the rule; every text under 25 words. Skip letterhead, addresses and signatures. Output compact JSON with no indentation or blank lines.

JSON shape:
{{
  "answer_type": "summary" | "definition" | "general" | "not_found",
  "verdict": "one sentence answer",
  "details": [{{"text": "...", "evidence": "E1"}}],
  "obligations": [{{"who": "...", "what": "...", "by": "deadline or empty", "evidence": "E1"}}],
  "earlier": [{{"text": "...", "evidence": "E2"}}]
}}
For a summary of one circular fill "obligations" (who must do what, by when) and use "details" for what it says, its effective date and related OCs. A summary must state the key amounts, counts and deadlines the circular contains, written as digits as in the circular.
Write Hindi words in Roman letters only (for example "limit badhakar ₹5 lakh kar di gayi hai"); never use Devanagari script."""


def evidence_block(pack: EvidencePack) -> str:
    def head(e):
        ref = "UPI Consolidated Circular" if e.oc_number == "CC" else f"OC {e.oc_number or '-'}"
        flag = " | WITHDRAWN (no longer in force)" if getattr(e, "status", "") == "withdrawn" else ""
        return f"[{e.id}] {ref} | {e.title} | {e.issue_date}{flag}"
    return "\n\n".join(f"{head(e)}\n{e.text}" for e in pack.items)


def llm_messages(plan, pack: EvidencePack, feedback: str = "") -> tuple:
    lang = "Hinglish (Roman Hindi mixed with English)" if plan.language == "hinglish" else "English"
    kind = {"OC_LOOKUP": "summary", "DEFINITION": "definition"}.get(plan.intent, "general")
    user = f"QUESTION: {plan.question}\nExpected answer_type: {kind}\n\nEVIDENCE:\n{evidence_block(pack)}"
    if feedback:
        user += f"\n\nYour previous answer was rejected: {feedback}\nFix exactly that and return the JSON again."
    return SYSTEM.format(language=lang), user


def _sentences(text: str) -> list:
    """Quotable units: a table row stays whole; running text is split into sentences."""
    out = []
    for block in text.split("\n"):
        if block.strip().startswith("|"):
            row = re.sub(r"\s+", " ", block).strip()
            if not re.fullmatch(r"[|\-\s:]+", row):          # skip the |---|---| separator line
                out.append(row)
        elif block.strip():
            flat = re.sub(r"\s+", " ", block).strip()
            out.extend(x.strip() for x in re.split(r"(?<=[.;:!?])\s+(?=[A-Z0-9(\"'‘“])", flat) if len(x.strip()) > 8)
    return out


def auto_quote(statement: str, evidence_text: str, max_chars: int = 320) -> str:
    """The sentence(s) of the evidence that best support a statement: highest word overlap, plus any
    sentence that holds a number the statement uses. Always real text from the passage."""
    from .checker import free_text_numbers, quote_numbers

    sents = _sentences(evidence_text)
    if not sents:
        return " ".join(evidence_text.split())[:max_chars]
    words = {w for w in re.findall(r"[a-z0-9]+", statement.lower()) if len(w) > 2}
    nums = set(free_text_numbers(statement))
    best = max(sents, key=lambda x: len(words & set(re.findall(r"[a-z0-9]+", x.lower()))))
    chosen = [best]
    for n in nums:
        if n not in quote_numbers(best):
            holder = next((x for x in sents if n in quote_numbers(x)), None)
            if holder and holder not in chosen:
                chosen.append(holder)
    chosen.sort(key=sents.index)                       # keep the circular's own order (the checker needs it)
    return " ... ".join(c[:max_chars] for c in chosen)


def locate_quote(statement: str, cited, pack: EvidencePack):
    """(quote, evidence item it comes from). The model cites one passage, but a number it uses may sit in
    another passage of the same circular. Each passage is tried on its own, so a quote is always one
    contiguous piece of one passage; the passage that supports most of the statement's numbers wins."""
    from .checker import free_text_numbers, quote_numbers

    nums = set(free_text_numbers(statement))
    words = {w for w in re.findall(r"[a-z0-9]+", statement.lower()) if len(w) > 2}
    best, best_score = (auto_quote(statement, cited.text), cited), (-1, -1)
    for e in [cited] + [x for x in pack.items if x.doc_id == cited.doc_id and x is not cited]:
        q = auto_quote(statement, e.text)
        score = (len(nums & quote_numbers(q)), len(words & set(re.findall(r"[a-z0-9]+", q.lower()))))
        if score > best_score:
            best, best_score = (q, e), score
    return best


def answer_from_json(stores, plan, pack: EvidencePack, data: dict) -> Answer:
    """Turn the model's JSON into an Answer. Raises ValueError if the structure is wrong."""
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    atype = data.get("answer_type")
    if atype == "not_found":
        return not_found(stores, plan, thin=pack.coverage_docs if pack.coverage_docs <= 2 else 0)
    if atype not in ("summary", "definition", "general"):
        raise ValueError(f"unknown answer_type {atype!r}")
    verdict = (data.get("verdict") or "").strip()
    if not verdict:
        raise ValueError("empty verdict")
    cites = _Citations(stores)

    def line(item):
        ev = pack.by_id(str(item.get("evidence", "")).strip())
        if ev is None:
            raise ValueError(f"unknown evidence id {item.get('evidence')!r}")
        quote = " ".join(str(item.get("quote", "")).split())
        statement = " ".join(str(item.get(k, "")) for k in ("text", "what", "who", "by"))
        if not quote or " ".join(ev.text.split()).lower().find(quote.lower()) < 0:
            quote, ev = locate_quote(statement, ev, pack)    # not copied exactly: use the circular's own sentence
        return cites.add(ev.doc_id, quote, ev.page, ev.text)

    details = [Line(str(i.get("text", "")).strip(), [line(i)]) for i in data.get("details") or []]
    earlier = [Line(ph.t(plan.language, "earlier", text=str(i.get("text", "")).strip()), [line(i)])
               for i in data.get("earlier") or []]
    obligations = [Obligation(str(i.get("who", "")).strip(), str(i.get("what", "")).strip(),
                              str(i.get("by", "") or "").strip(), [line(i)]) for i in data.get("obligations") or []]
    ans = Answer(atype, plan.language, verdict, "verified", details=details, earlier=earlier, obligations=obligations,
                 citations=cites.items, meta=_meta(stores, plan))
    if pack.coverage_docs and pack.coverage_docs <= 2 and plan.intent in ("GENERAL", "DEFINITION"):
        ans.notice = ph.t(plan.language, "thin", n=pack.coverage_docs)
    return ans


# ------------------------------------------------------------ quote snapping
def snap_quotes(ans: Answer, pack: EvidencePack, min_ratio: float = 0.88) -> None:
    """Models often copy a quote with small slips (quote style, a dropped word). If a quote is not an
    exact piece of its evidence but one close piece is (similarity >= min_ratio), replace the quote by
    that real text, so what is shown is always the source's own wording. Quotes with no close match are
    left alone and the checker rejects them."""
    from .checker import _norm, _quote_in

    for c in ans.citations:
        texts = [e.text for e in pack.items if e.doc_id == c.doc_id]
        flat = lambda x: " ".join(x.split()).lower()
        if any(flat(c.quote) in flat(t) for t in texts):
            continue                                              # already the source's own wording
        if re.search(r"\.\.\.|…", c.quote) and any(_quote_in(_norm(t), c.quote) for t in texts):
            continue                                              # parts joined with "...", each exact
        target = _norm(c.quote)
        n = max(3, len(c.quote.split()))
        best, best_ratio = None, 0.0
        for t in texts:
            words = t.split()
            for size in (n - 1, n, n + 1, n + 2):
                for i in range(0, max(1, len(words) - size + 1)):
                    cand = " ".join(words[i:i + size])
                    r = difflib.SequenceMatcher(None, _norm(cand), target).ratio()
                    if r > best_ratio:
                        best, best_ratio = cand, r
        if best and best_ratio >= min_ratio:
            c.quote = best

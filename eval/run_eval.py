"""Run the gold set through the pipeline and score it against the M2 gates.

    ALLOW_UNVERIFIED_FACTS=1 python -m eval.run_eval              # facts auto_checked (development)
    python -m eval.run_eval --no-llm                              # deterministic paths only
    python -m eval.run_eval --only L01,M03                        # a few questions

Writes eval/report.md and exits non-zero if a gate fails.
"""

import argparse
import csv
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.checker import quote_numbers  # noqa: E402
from core.config import Settings  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402

HERE = os.path.dirname(__file__)
GOLD = os.path.join(HERE, "gold_set.csv")
REPORT = os.path.join(HERE, "report.md")


def numbers_in(text: str) -> set:
    return quote_numbers(text)


def score(row: dict, ans) -> dict:
    """Return a dict of check name -> True/False/None (None: not applicable)."""
    text = ans.text() + "\n" + "\n".join(c.quote for c in ans.citations)
    visible = numbers_in(ans.text())
    current_only = numbers_in("\n".join([ans.verdict, ans.notice]
                                        + [r.label + " " + " ".join(c.text for c in r.cells) for r in ans.table]
                                        + [l.text for l in ans.details] + [o.what for o in ans.obligations]))
    expected = [v for v in row["expected_values"].split(";") if v]
    forbidden = [v for v in row["forbidden_values"].split(";") if v]
    allowed_types = row["answer_type"].split("|")
    docs = [d for d in row["expected_docs"].split(";") if d]
    checks = {
        "answer_type": ans.answer_type in allowed_types,
        "values": all(v in visible for v in expected) if expected else None,
        "forbidden": not any(v in current_only for v in forbidden) if forbidden else None,   # earlier lines may show old figures
        "docs": all(any(alt in ans.cited_doc_oc_numbers() or alt in text for alt in d.split("|")) for d in docs) if docs else None,
        "refusal": (ans.answer_type == "refusal") if row["must_refuse"] else None,
        "clarify": (ans.answer_type == "clarify") if row["must_clarify"] else None,
        "notice": (row.get("notice", "").lower() in (ans.notice or "").lower()) if row.get("notice") else None,
        "checker": (ans.meta.get("checker", {}).get("ok", True)),
    }
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-vectors", action="store_true")
    args = ap.parse_args(argv)

    settings = Settings.from_env()
    if args.no_llm:
        settings = Settings(**{**settings.__dict__, "llm_provider": "none"})
    pipeline = Pipeline(settings=settings)
    if args.no_vectors:
        from core.evidence.search import Searcher

        pipeline._searcher = Searcher(pipeline.stores, use_vectors=False)

    with open(GOLD, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    skipped = 0
    if args.no_llm:
        skipped = sum(1 for r in rows if r['needs_llm'])
        rows = [r for r in rows if not r['needs_llm']]
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted]

    results, failures = [], []
    for row in rows:
        t0 = time.perf_counter()
        ans = pipeline.answer(row["question"])
        checks = score(row, ans)
        ok = all(v is not False for v in checks.values())
        results.append((row, ans, checks, ok, time.perf_counter() - t0))
        if not ok:
            failures.append((row, ans, [k for k, v in checks.items() if v is False]))
        print(f"{'PASS' if ok else 'FAIL'} {row['id']} [{ans.answer_type}] {row['question'][:60]}"
              + ("" if ok else "  <- " + ",".join(k for k, v in checks.items() if v is False)))

    def rate(name):
        vals = [c[name] for _, _, c, _, _ in results if c[name] is not None]
        return (sum(vals), len(vals))

    lat = sorted(t for *_, t in results)
    p50 = lat[len(lat) // 2] if lat else 0
    lines = ["# Gold set report", "", f"Questions: {len(results)} · passed: {sum(1 for r in results if r[3])}"
             + (f" · skipped (need an LLM): {skipped}" if skipped else ""), "",
             "| Check | Passed | Of |", "|---|---|---|"]
    for name in ("answer_type", "values", "forbidden", "docs", "refusal", "clarify", "notice", "checker"):
        a, b = rate(name)
        lines.append(f"| {name} | {a} | {b} |")
    lines += ["", f"Latency p50: {p50:.2f}s · max {max(lat) if lat else 0:.2f}s",
              f"LLM: {settings.llm_provider} {settings.model if settings.llm_provider != 'none' else ''}",
              f"Facts: {'including unverified (development)' if settings.allow_unverified_facts else 'human-verified only'}", ""]
    if failures:
        lines += ["## Failures", ""]
        for row, ans, bad in failures:
            lines.append(f"- **{row['id']}** {row['question']}  → `{ans.answer_type}` failed: {', '.join(bad)}")
            lines.append(f"  - verdict: {ans.verdict[:200]}")
            if ans.meta.get("checker", {}).get("reasons"):
                lines.append(f"  - checker: {ans.meta['checker']['reasons'][:3]}")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n{sum(1 for r in results if r[3])}/{len(results)} passed; report: {REPORT}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

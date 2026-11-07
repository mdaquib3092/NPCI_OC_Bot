"""Retrieval hit@k on eval/retrieval_set.csv: is the expected OC among the retrieved passages?

    python -m eval.run_retrieval [--no-vectors] [--k 8]

Rows with no expected OC (questions the circulars cannot answer) are not scored.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import Settings  # noqa: E402
from core.evidence import facts as fev  # noqa: E402
from core.evidence.search import Searcher  # noqa: E402
from core.router import route  # noqa: E402
from core.stores import Stores  # noqa: E402

SET = os.path.join(os.path.dirname(__file__), "retrieval_set.csv")
GATE = 0.90


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-vectors", action="store_true")
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args(argv)
    stores = Stores(Settings(llm_provider="none", allow_unverified_facts=True))
    searcher = Searcher(stores, use_vectors=not args.no_vectors)
    rows = [r for r in csv.DictReader(open(SET, newline="", encoding="utf-8")) if r["expected_oc_number"]]
    hits, misses, by_facts = 0, [], 0
    scored = []
    for r in rows:
        plan = route(r["question"])
        if plan.intent in ("LIMIT", "CODE_LOOKUP") and (fev.limit_evidence(stores, plan) is not None):
            by_facts += 1                       # answered from reviewed facts, not by search
            continue
        scored.append(r)
    rows = scored
    for r in rows:
        pack = searcher.search(r["question"], top_k=args.k)
        got = {e.oc_number for e in pack.items}
        if r["expected_oc_number"] in got:
            hits += 1
        else:
            misses.append((r["question"], r["expected_oc_number"], sorted(got)))
    rate = hits / len(rows)
    print(f"{by_facts} questions are answered from facts and not scored here")
    print(f"hit@{args.k}: {hits}/{len(rows)} = {rate:.1%} (gate {GATE:.0%})")
    for q, exp, got in misses:
        print(f"  MISS expected {exp}: {q[:70]}  got {got[:6]}")
    return 0 if rate >= GATE else 1


if __name__ == "__main__":
    sys.exit(main())

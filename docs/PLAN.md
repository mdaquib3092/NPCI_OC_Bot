# Road to pilot and launch

| | |
|---|---|
| Status | Working plan, started 2026-11-05 |
| Where we are | Data pipeline, answering pipeline, references, interface, feedback and CI are built. About 75% ready for a private pilot, 60% for a public launch (see the table in section 1) |
| Rule | Quality first: nothing is called ready until its exit criterion is met and measured |

## 1. Readiness today

| Area | Ready | Main gap |
|---|---|---|
| Data pipeline | 90% | Missing OCs; page numbers for scanned multi-page circulars |
| Limits and MCC answers | 85% | Facts not human-verified |
| Router and search | 80% | No reranker; multilingual embeddings untested |
| Model-written answers | 85% | All 21 model-written gold answers pass with qwen3:8b (2026-11-06); local model still takes about 1 minute |
| Interface and feedback | 75% | Not yet checked in a real browser or on a phone |
| Testing and eval | 65% | 101 gold questions, all pass (80 model-free, 21 with qwen3:8b) |
| Docs, CI, repo | 80% | Nothing committed yet; license undecided |
| Launch (hosting, pilot) | 25% | Not started |

## 2. Phases

### Phase A: make the answers trustworthy
| # | Task | Who | Exit criterion |
|---|---|---|---|
| A1 | Verify the 82 facts with `facts_review.xlsx` and import (`python -m ingest.review import`) | Owner | 0 facts `auto_checked`; `Needs change` rows fixed. **Done 2026-11-07: all 82 verified (`OC120-P2P-collect` is `withdrawn` by Consolidated Circular clause 2.16)** |
| A2 | Decide the two doubtful facts (OC 82 blanket verified-merchant limit; OC 61 withdrawn) | Owner | Both resolved in the sheet. Done in the 2026-11-07 review |
| A3 | Grow the gold set to about 100 questions with the owner's real questions | Me, then owner | 100 questions, expected values taken from verified facts |
| A4 | Add the missing circulars (OC 72, 86, 181A, 103, 235) and any member-only ones found | Owner (PDFs or CSV), me (build) | Coverage report shows them present or `not_public` |
| A5 | Second reviewer checks a sample (10 to 15 facts) | Owner finds the person | Sample agrees with the first review |

### Phase B: make it fast and deployable
| # | Task | Who | Exit criterion |
|---|---|---|---|
| B1 | Hosted model: Groq key, then compare `gpt-oss-20b` and `120b` with local `qwen3:8b` on the gold set | Owner (key), me | p50 latency ≤ 8 s, same pass rate |
| B2 | Lighter embeddings for the host (ONNX MiniLM instead of PyTorch) so the app fits a small free instance; re-run the retrieval check | Me (needs permission to download the ONNX model) | Retrieval hit@8 ≥ 90%, memory fits the host |
| B3 | Deploy to Streamlit Community Cloud with secrets, build id visible | Me, owner approves | Public test URL works |
| B4 | Check the interface in a real browser and on a phone width; fix layout | Me, but the preview launcher in this app fails to start Python ("failed to make path absolute", seen on 2026-11-05 with both Anaconda and the project venv), so the owner should run `streamlit run app.py` once and send screenshots, or fix the launcher's folder access | Screenshots reviewed, no layout problems |
| B5 | Page numbers for scanned multi-page circulars (per-page OCR alignment) | Me | References carry a page for scanned circulars |

### Phase C: pilot
| # | Task | Who | Exit criterion |
|---|---|---|---|
| C1 | 5 to 10 UPI professionals use it for a week with feedback buttons | Owner | At least 80% helpful; no wrong or stale limit reported |
| C2 | Turn every 👎 into a gold question and fix its cause | Me | Regression set grows; gates stay green |
| C3 | Choose and apply the license; public README; disclaimer wording | Owner decides, me edit | Repo ready to share |

### Phase D: launch and next release
OC browser with supersession timeline, compare two circulars, "as of date" questions, automated fetching of new circulars (respecting NPCI's robots.txt), and other rails (IMPS, RuPay, BBPS, RBI). Specified in the PRD (R2 and R3).

## 3. Release gates (unchanged, measured by `eval/`)
Exact amounts on limit and code questions 100%; a superseded or withdrawn limit shown as current 0; every shown answer has quotes found in its source 100%; correct refusal or not-found on out-of-scope and absent data at least 95%; search hit@8 at least 90%; p50 latency at most 8 s; pilot helpful rating at least 80%.

## 4. Order of work
1. Done 2026-11-05: plan written; gold set grown from 42 to 101 questions (80 need no model: all pass); an advice refusal and an IPO-to-capital-markets mapping added. Next without input: B5 (page numbers for scanned circulars) and fixes for any model-dependent failures.
2. Done 2026-11-06/07: all 101 gold questions pass (21 model-written ones with qwen3:8b); the facts review is imported (81 of 82 verified, so the model-free gold set passes without the dev switch).
3. Next without input from the owner: (a) cite Consolidated Circular clause 2.16 on the withdrawn P2P collect line; (b) B5 page numbers for scanned circulars; (c) grow the gold set with 20 more P2P/P2M/limit questions from the verified facts and check that "earlier" lines are correct; (d) update `docs/M2_PLAN.md` section 11 with the 101/101 result.
4. Needs the owner: A4 missing PDFs (OC 72, 86, 181A, 103, 235); B1 Groq key; run `streamlit run app.py` and send screenshots (B4); C3 license; second reviewer (A5); the source of the "20 debit transactions" rule.
5. After B1: B2, B3, then the pilot (C1).

## 5. Decisions the owner still has to make
Groq key (yes or no), license (MIT vs permission-to-fork), hosting path (Streamlit Cloud first), whether to commit the current work (recommended now), and who is the second reviewer.

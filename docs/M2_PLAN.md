# M2 plan: the answering pipeline

| | |
|---|---|
| Status | **WP0 to WP6 built; WP7 (model experiments) in progress** (see section 9) |
| Date | 2026-10-22 |
| Depends on | M0 and M1 (registry, chunks, index, facts, code mentions, patches) |
| Specs | `docs/FSD.md` sections 4 to 7 and 11, `docs/ARCHITECTURE.md` sections 2 to 5 |

## 1. Goal and exit criteria

Turn a question into a checked answer object: **router → evidence → writer → checker → answer**, in a new `core/` package, with the old `app.py` logic replaced.

M2 is done when (FSD 11.3, measured on the trial gold set):

| Gate | Threshold |
|---|---|
| Exact-number correctness on limit and code questions | 100% |
| A superseded limit shown as current | 0 |
| Every shown answer has quotes that exist in the cited source | 100% |
| Correct refusal / not-found for out-of-scope or absent data | ≥ 95% |
| Retrieval hit@10 on general questions | ≥ 90% |
| Latency p50 | ≤ 8 s |

## 2. What M2 can already rely on

| Asset | State |
|---|---|
| `Data/registry.csv` | 246 documents: 239 readable, plus 7 `not_public` rows (OC 141E, 230, 230A, 233, 236, 237, 238: listed by NPCI, no PDF) |
| `Data/chunks.jsonl` + `Data/chroma_db/` | 4,004 chunks, same ids in both |
| `Data/facts.csv` | 81 facts (limits for P2P, P2PM, P2M, UPI Lite, biometric), quotes verified against the text; **0 human-verified so far** |
| `Data/code_mentions.csv` | 45 MCCs, 25 purpose codes; the three outcomes via `ingest.codes.lookup` |
| Local LLMs (Ollama) | `qwen3:8b`, `qwen3:14b`, `llama3` installed; no Groq key in the environment |
| Eval | `eval/gold_set.csv` (42 answer questions) and `eval/retrieval_set.csv` (56 retrieval questions, 52 with an expected OC) |
| Gaps | OC 72, 86, 181A missing from the corpus; facts cover limits only, so other topics use the general path |

Two environment notes: `venv` lacks `openai` and `groq` (anaconda has them), so WP1 installs them into `venv`; and until facts are human-verified, development needs a clearly named switch (`ALLOW_UNVERIFIED_FACTS=1`, default off) so the pipeline can be built and tested before the review is finished.

## 3. Design decisions for M2

1. **Facts-backed answers are built in code, not by the model.** For limit and code questions the table, numbers, dates and quotes come straight from fact rows. The LLM may only add a short verdict sentence and phrasing. This is the strongest protection against wrong numbers: the model never has the chance to type one.
2. **The LLM writes the free-text answers** (OC summaries, definitions, general questions) as JSON, from evidence only; the checker then verifies it.
3. **Fail closed.** One regeneration with the failure reason, then source passages. A failed answer is never shown.
4. **Rules before models.** Routing is rule-based; the LLM labels the intent only when the rules are unsure.
5. **General path always on.** A specialised path that finds nothing falls through to hybrid search, so unexpected questions still get a grounded answer or an honest "not found".

## 4. Work packages

Order matters: the gold set and harness come first, so every later step is measured.

### WP0: Gold set and eval harness (first)
- `eval/gold_set.csv`: about 40 questions, columns `id, question, language, intent, expected_oc, expected_values, must_refuse, must_clarify, notes`. Covers: the owner's five examples, P2P/P2PM/P2M limits (all three kinds), MCC present / MCC with no limit / MCC absent (1520), UPI Lite limits (current and earlier), biometric limit, OC summaries, definitions (UPI Circle), thin topic (MDR), bank-specific limit, out-of-scope, ambiguous "limit", Hinglish variants, and each of the 5 known retrieval misses.
- `eval/run_eval.py`: runs the pipeline, scores the gates above, writes `eval/report.md` and fails (non-zero) below threshold.
- Expected values come only from `human_verified` facts or from page-image checks; the owner's real questions (5 to 10 more) are added when provided.
- **Done when:** the harness runs end to end against a stub pipeline and reports 0%.

### WP1: Foundations (`core/`)
- `core/config.py` (env settings), `core/answer.py` (answer dataclasses, JSON schema from ARCHITECTURE 4.5, status values), `core/llm.py` (one OpenAI-compatible client for Groq and Ollama; JSON output; retries; maps rate-limit, timeout and connection errors to a fallback; reasoning suppression per model).
- `core/stores.py`: loads registry, facts, code mentions, chunks once; applies the human-verified filter (and the dev switch).
- **Done when:** unit tests cover schema validation, store loading and error mapping.

### WP2: Normalise and route
- `core/normalize.py`: OC id forms (`oc 76 a`, `OC-76A`), amounts, Hinglish lexicon (kya, kitna, hai, abhi, pehle, bolta, batao ...), term spelling.
- A question about an OC whose registry row is `not_public` routes to the `not_public` answer (no retrieval, no LLM): the OC exists, the title as NPCI lists it, and the statement that its text is not public.
- `core/router.py`: ordered rules (FSD 4.2): out-of-scope pre-check, `OC_LOOKUP`, `CODE_LOOKUP`, `LIMIT`, `DEFINITION`, `GENERAL`; returns a `Plan` with slots (`oc_number`, `txn_type`, `limit_kind`, `code`, `language`). "limit" with no transaction type returns `clarify`.
- **Done when:** a table of about 60 phrasings (English and Hinglish) routes correctly in unit tests.

### WP3: Evidence
- `core/evidence/facts.py`: transaction type → all limit kinds, current first and earlier labelled; **kinds the circulars do not set are returned as "No OC sets this"** (for example the daily amount a user may *send* by P2P is not in any indexed OC; only credit-received limits are). Handles `direction` and `merchant_type`; `unclear` rows are never served.
- `core/evidence/codes.py`: the three outcomes for an MCC or purpose code, plus reverse lookup by category name.
- `core/evidence/documents.py`: OC lookup (registry row plus its chunks in order, capped); a `not_public` row returns only the registry row.
- `core/evidence/search.py`: BM25 + vectors with RRF (the old `hybrid_search.py` was folded in and removed), add a cross-encoder reranker, drop chunks that contradict a verified fact, build the evidence pack with caps and a coverage note.
- **Done when:** retrieval hit@10 on the gold set is measured; facts and code paths return exact rows for the gold limit and MCC questions.

### WP4: Writer
- `core/writer.py`: templates per answer type (summary, definition, general, not_found, refusal, clarify) and the JSON-only prompt; deterministic builders for `limit_table` and `code_result` (WP3 rows to answer object, no model numbers); optional model-written verdict sentence in the user's language.
- Fixed English and Hinglish phrases for the `not_public` answer, headings, "No OC sets this", "not mentioned in any indexed circular", disclaimers.
- **Done when:** golden-output tests for the facts-backed answers match exactly.

### WP5: Checker
- `core/checker.py` implementing FSD CH-1 to CH-7: schema, quote is a substring of its evidence (whitespace and rupee-glyph normalised), every number in the text appears in a cited quote or fact row (Indian grouping, lakh and crore handled), cited OC and MCC codes exist in the evidence, no superseded item labelled current, one regeneration, then fallback to passages.
- Replaced `number_guard.py` (which appended warnings instead of failing closed; removed).
- **Done when:** tests reject a wrong number, a fake quote, a stale-as-current claim and a missing citation, and pass the golden answers.

### WP6: Pipeline and a thin UI hook
- `core/pipeline.py`: `answer(question, history, settings) -> Answer`, with clarify, refusal, not-found and fallback paths; optional in-memory cache keyed by normalised question and build id.
- `app.py` shrinks to a shim that calls the pipeline and shows the validated answer plainly. The answer card, chips and feedback design is M3.
- **Done when:** scenarios S1 to S11 (FSD 2.2) run through the shim.

### WP7: Model and retrieval experiments (measured on the gold set)
- LLM for the free-text paths: `qwen3:14b`, `qwen3:8b`, `llama3` locally; `gpt-oss-20b` and `gpt-oss-120b` on Groq if a key is provided. Compare JSON adherence, checker pass rate, faithfulness, latency.
- Embeddings: current `all-MiniLM-L6-v2` against a multilingual model (for Hinglish) on hit@10.
- Reranker model and its CPU latency (matters on a free host).
- **Done when:** a short comparison table is written to `eval/report.md` and the defaults are set.

## 5. Order, dependencies, parallel work

```
WP0 ──► WP1 ──► WP2 ──► WP3 ──► WP4 ──► WP5 ──► WP6 ──► WP7 ──► tune and gate
                 └── WP2 and the evidence for facts (WP3) can overlap once WP1 is done
```
WP4 (facts-backed builders) and WP5 (checker) can be developed in parallel after WP3; WP7 needs WP6.

## 6. Risks and what handles them

| Risk | Handling |
|---|---|
| Facts not human-verified yet | Dev-only switch; the release gate requires verified facts; the unverified count is shown in the build report |
| Free-tier LLM rate limits or slow local models | Facts-backed answers need no LLM; fallback to passages; optional cache |
| Model does not return valid JSON | Schema validation, one retry, then fallback; model chosen by WP7 |
| Reranker too slow on a free host | Measure in WP7; make it optional by setting |
| Checker rejects good answers | Report rejection reasons in the eval and tune normalisation, not the thresholds |
| Facts cover limits only | Everything else goes through the general path with the same checker; honest "not found" when evidence is thin |
| OCR errors in documents without patches | The checker only accepts numbers present in a verified fact or in a quote; a coverage report lists documents with suspect characters for a page-image check |

## 7. Decisions needed from the owner

1. **Dev switch for unverified facts:** OK to build and test on `auto_checked` facts behind `ALLOW_UNVERIFIED_FACTS=1`, with release blocked until they are verified? (Recommended: yes.)
2. **Groq:** may WP7 use a Groq API key for the `gpt-oss` comparison? The environment currently has none, and local Ollama alone is enough to start. (Recommended: start local; add Groq later only if you provide a key.)
3. **More real questions:** 5 to 10 additional questions from your real work for the gold set, with the answer you expect if you know it.
4. **Latency target:** keep 8 seconds, or relax for the first version on a local model?
5. **Missing OCs:** if you can add the PDFs for OC 72, 86 and 181A (and 103), the P2PM and P2P limit history becomes complete. Not blocking.

## 8. Suggested first steps (once approved)

1. WP0: write the first 40 gold questions and the harness (about one session).
2. WP1: `core/` skeleton, install `openai` and `groq` into `venv`, tests green.
3. WP2 and WP3 for the facts and code paths, because they cover the owner's core need (limits and MCCs) and are fully deterministic.

## 9. Status (2026-10-22)

| Work package | State |
|---|---|
| WP0 gold set and harness | Done: `eval/gold_set.csv` (42 questions), `eval/run_eval.py`, `eval/show.py` |
| WP1 foundations | Done: `core/config.py`, `answer.py`, `llm.py`, `stores.py`, `phrases.py` |
| WP2 router | Done: every gold question routes to its expected intent (unit-tested) |
| WP3 evidence | Done: facts (limit rows, MCC and category rows, superseded chains), codes, documents, hybrid search. A reranker is not added yet (WP7) |
| WP4 writer, WP5 checker | Done: deterministic builders for facts-backed answers; JSON prompt and parser for model-written answers; checker with quote, amount, number, OC-reference and citation rules |
| WP6 pipeline and app shim | Done: `core/pipeline.py`; `app.py` is a thin shell; the old app is `app_legacy.py` |
| WP7 model and retrieval experiments | In progress: local `qwen3:8b` first run on the model-written questions; no Groq key yet; embedding and reranker comparison not started |

Results so far (facts auto-checked, development switch on):
- The 35 gold questions that need no model (limits, MCC lookups, history, not-public, not-found, refusals, clarify) all pass.
- 129 unit tests pass (router, checker, evidence, pipeline with a fake model, review import, registry, facts).
- Bugs found and fixed by the gold set and tests: the checker rejected OC references that appear only in fact notes; the word "emi" inside "premium" matched the collections category; a model that joined quote parts with "..." was rejected although each part was exact (now allowed when every part is found in order).

Still open: facts are not human-verified, so the release gates cannot be claimed yet; latency of the local model (about 25 seconds for one summary with `qwen3:8b`) is above the 8-second target; the OC 76C table was patched from the page image and the build must be re-run to refresh chunks and the index.

## 10. Update (2026-10-23)

Added since section 9: page and clause references on every citation, the completed interface with feedback, CI, removal of the legacy code, the Consolidated Circular (withdrawn OCs and its clauses), query synonyms, and a retrieval check (`eval/run_retrieval.py`, hit@8 97.5% on search-answered questions). Still open: model quality and speed for model-written answers (4 of 7 pass with local `qwen3:8b`, about 100 s each), an embedding or reranker comparison, a Groq comparison (needs a key), page numbers for multi-page scanned circulars, and human verification of the facts.

## 11. Local model comparison (2026-10-23, facts auto-checked, 7 model-written gold questions)

| Design | `qwen3:8b` | `qwen3:14b` |
|---|---|---|
| Model asked to copy exact quotes | 4 of 7, p50 103 s | 3 of 7, p50 100 s |
| Model gives only an evidence id; the system attaches the passage's own sentence (table rows kept whole) | 6 of 7, p50 63 s (the failure is the thin MDR topic, now accepted as a safe outcome) | 6 of 7, p50 105 s; the one failure (a number held in a table row) was fixed and re-tested: 7 of 7 |

Findings: the failures were quote copying and verbose JSON, not understanding. With system-attached quotes both models pass; `qwen3:8b` is about 40% faster, so it is the local default (`OLLAMA_MODEL=qwen3:14b` to switch). Every wrong number is still caught by the checker and replaced by source passages. Local speed (about one minute) remains far above the 8-second target; a hosted model is needed for that. Not yet compared: Groq `gpt-oss` (needs a key), a larger Qwen (needs a download), embedding and reranker options.

### 11.1 Result on 2026-11-06 (qwen3:8b, 101 gold questions)

All 101 gold questions pass: 80 need no model, 21 are model-written. The last three failures were a table quote whose parts were not kept in the circular's order (D08), a Hinglish answer written in Devanagari (D01, now rejected by the checker and ruled out in the prompt) and a summary that left out the key counts (D09, fixed by a page-image transcription of the OC 181B table). Local p50 is still about one minute; the 8-second target needs a hosted model.

### 11.2 Withdrawn facts and what NPCI does not say (2026-11-07)

- A withdrawn fact can name the document that ended it (`closed_by_doc_id`, `closed_by_clause`, `closed_by_page`, `closed_by_quote`). The build checks that the quote is in that document, and the answer shows a "Why it is no longer in force" line with its own citation (P2P collect: Consolidated Circular clause 2.16; OC 61: Annexure G, serial 22).
- For the count of transactions a user can send in 24 hours, the answer says that no indexed OC sets it and that the circulars neither fix it nor say who should manage it. Other sources such as bank sites are deliberately not used: answers come from NPCI OCs only.

# NPCI Reader: Technical Architecture

| | |
|---|---|
| Status | **v0.5: data layer, pipeline, references, UI, feedback and CI built (sections 14 to 19)** |
| Date | 2026-10-22 |
| Scope | MVP trial (private), designed so R2/R3 plug in without a rewrite |
| Depends on | `docs/PRD.md` (v0.1) |
| Next | `docs/FSD.md` (detailed behaviour for the MVP trial) |

## 1. Goals of the architecture

1. **Correct first.** Every figure shown must trace to a quote in a source OC; anything unverified is not presented as an answer.
2. **Simple to run and review.** Plain files in Git for the data that people must review; one command to rebuild.
3. **General, not only the sample questions.** Specialised paths (facts, code lookup) make known question types exact, but a general retrieval path always exists so *any* question about the OCs can be attempted and answered honestly.
4. **UI-independent.** All logic lives in a Python package that the Streamlit app merely calls, so another frontend or an API can reuse it.
5. **Measurable.** Each build and each change is scored against a gold set; a drop blocks the change.

## 2. System overview

```
BUILD TIME (offline, run by the maintainer)

 PDFs ──► extract ──► text + tables ──► draft facts / registry (LLM-assisted)
                                              │
                         human review ◄───────┘
                              │
              data/registry.csv   data/facts.csv   data/code_mentions.csv
                              │
 text ─► chunk + enrich(registry) ─► data/chunks.jsonl ─► build/index (BM25 + vectors)
                                              │
                                      build id + validation report

RUN TIME (every question)

 question ─► normalize ─► ROUTER ─► evidence path
                                     ├─ OC_LOOKUP   registry + that OC's chunks
                                     ├─ LIMIT       facts.csv (transaction type → limit kind)
                                     ├─ CODE_LOOKUP code_mentions.csv + facts.csv
                                     ├─ DEFINITION  hybrid search, definition-biased
                                     └─ GENERAL     hybrid search + rerank (always available)
                          ─► supersession filter ─► evidence pack (capped)
                          ─► LLM WRITER (JSON only) ─► CHECKER ─► answer object
                                                           │ fail
                                                           └─► fallback: show source passages
                          ─► UI renders answer card
```

## 3. Components

| Component | Responsibility | Input → Output | Tech |
|---|---|---|---|
| `ingest.extract` | PDF to text, tables as Markdown, OCR fallback | PDF → text JSON | PyMuPDF, pytesseract (cached) |
| `ingest.registry` | Validate and load the OC registry | `registry.csv` → typed records | pandas / csv |
| `ingest.facts` | Draft facts from text for review; validate reviewed facts | text → draft rows; CSV → validated rows | LLM (build time only) + deterministic checks |
| `ingest.chunk` | Split text, keep tables whole, attach registry metadata | text + registry → `chunks.jsonl` | Python |
| `ingest.index` | Build BM25 and vector indexes from `chunks.jsonl` only | chunks → `build/` | rank-bm25, ChromaDB, sentence-transformers |
| `core.normalize` | Case, spacing, OC-id forms, Hinglish lexicon | text → normalized text | Python |
| `core.router` | Decide the intent and extract parameters | text → `Plan` | Rules first; small LLM classification only when rules are unsure |
| `core.evidence` | Fetch and rank evidence for a plan; apply supersession | `Plan` → `EvidencePack` | Registry/facts lookups, hybrid search, reranker |
| `core.writer` | Ask the LLM to write the answer from evidence only | `EvidencePack` → JSON | OpenAI-compatible client (Groq or Ollama) |
| `core.checker` | Verify quotes, numbers, citations; compute status | JSON + evidence → verified answer or fallback | Pure Python, deterministic |
| `core.answer` | The answer object and its rendering contract | → `Answer` | dataclasses |
| `app.py` | Streamlit UI | `Answer` → screen | Streamlit |
| `eval/` | Gold set, runner, report | gold set → metrics | Python |

## 4. Data contracts

All data that humans review is plain CSV or JSONL in Git. Generated artefacts live in `build/` and are not committed.

### 4.1 `registry.csv` (one row per OC document)
`doc_id, oc_number, series, title, issue_date, effective_date, domain, category, status, supersedes, superseded_by, source_file, notes`
- `oc_number` includes any suffix (`76A`). `series` separates the UPI OC series from the joint IMPS "Operation Circular" series (`UPI` | `IMPS_UPI`), so two documents numbered 99 never collide.
- `doc_id` is unique and stable; `oc_number` is not required to be unique across series.
- `domain` starts as `UPI`; future rails add values without schema change.
- `status`: `current | superseded | partially_superseded | informational`.

### 4.2 `facts.csv` (reviewed structured facts: limits and timelines)
`fact_id, domain, txn_type, limit_kind, mcc, category_name, value, unit, conditions, effective_date, end_date, source_oc, source_doc_id, page, quote, status, superseded_by_fact, review_status, reviewer, reviewed_on`
- `txn_type`: `P2P | P2PM | P2M | UPI_LITE | AUTOPAY | INTERNATIONAL | ...`
- `limit_kind`: `per_txn_amount | per_24h_amount | per_24h_count | collect_per_txn | ...`
- `mcc` is empty for P2P; used only for P2M and merchant-category rules.
- `review_status`: `drafted | auto_checked | human_verified`. Only `human_verified` rows are served in the MVP.
- Rule: `quote` must appear verbatim (whitespace-normalised) in the text of `source_doc_id`. Enforced at build time.

### 4.3 `code_mentions.csv` (everything the OCs say about a code)
`code_family, code, name, oc_number, source_doc_id, rule_type, quote, effective_date`
- `code_family`: `mcc | purpose_code | ...`; `rule_type`: `limit | requirement | mention_only`.
- Powers the three outcomes in PRD FR-3a: specific rule, mentioned without a rule, not mentioned anywhere.

### 4.4 `chunks.jsonl`
`chunk_id, doc_id, oc_number, series, title, issue_date, status, supersedes, superseded_by, category, chunk_type (text|table), page, chunk_text`
- Metadata is copied from the registry at build time, never guessed from filenames.

### 4.5 Answer object (writer output, validated by the checker)
```json
{
  "answer_type": "limit_table | summary | definition | not_found | clarify | refusal",
  "language": "en | hinglish",
  "verdict": "one line",
  "details": [{"text": "...", "citation_ids": ["c1"]}],
  "current_vs_earlier": [{"label": "current|superseded", "text": "...", "citation_ids": ["c2"]}],
  "table": [{"row": "...", "value": "...", "status": "set|no_oc_sets_this", "citation_ids": ["c3"]}],
  "obligations": [{"who": "...", "what": "...", "by": "...", "citation_ids": ["c4"]}],
  "citations": [{"id": "c1", "oc_number": "...", "title": "...", "quote": "...", "doc_id": "..."}],
  "follow_up_chips": ["..."]
}
```
The checker adds `status` (`verified | partially_verified | not_found`) and the build id; the UI never trusts unvalidated writer text.

## 5. Query flow in detail

### 5.1 Router (rules first)
Ordered checks; first match wins, and the plan carries parameters.

| Order | Intent | Trigger examples |
|---|---|---|
| 1 | `OUT_OF_SCOPE` pre-check | obvious non-UPI topics; confirmed again after retrieval |
| 2 | `OC_LOOKUP` | "OC 185A", "circular 76B", "OC-76" |
| 3 | `CODE_LOOKUP` | "MCC 7407", "purpose code 25", "which MCC for jewellery" |
| 4 | `LIMIT` | limit words plus a transaction type ("P2P limit", "UPI Lite limit", "P2M limit") |
| 5 | `DEFINITION` | "what is X", "X kya hai", "meaning of X" |
| 6 | `GENERAL` | everything else (also the fallback when a specialised path finds nothing) |

- Hinglish handled by a small lexicon (kya, kitna, hai, bolta, batao, limit, abhi, pehle ...) in `core.normalize`; the router also accepts an LLM classification when rules are unsure.
- A specialised path that returns nothing **falls through to GENERAL** instead of ending the conversation, so unexpected questions still get a grounded attempt.

### 5.2 Evidence
- `OC_LOOKUP`: registry row plus all chunks of that `doc_id`, in document order, capped.
- `LIMIT`: all `human_verified` fact rows for the transaction type, grouped by `limit_kind`, current first and superseded second. Missing kinds are returned as `no_oc_sets_this`.
- `CODE_LOOKUP`: `code_mentions` plus matching facts; the outcome is one of `specific_rule`, `mention_only`, `not_mentioned`.
- `DEFINITION`/`GENERAL`: BM25 and vector search fused (RRF), then a cross-encoder reranker, then the **supersession filter** (drop chunks of superseded documents unless the question is historical, but keep a one-line pointer to what replaced them).
- Evidence packs are capped by chunk count and characters so a free-tier model never overflows.

### 5.3 Writer
- Receives the evidence only, with numbered citation ids, and must return the JSON in 4.5.
- Temperature 0. The prompt forbids outside knowledge and restates "copy figures exactly".
- For `LIMIT` and `CODE_LOOKUP`, the **numbers come from the facts rows**, and the checker confirms the writer reproduced them exactly.

### 5.4 Checker (deterministic)
1. JSON validates against the schema.
2. Every `citation.quote` is a substring of the cited evidence (after whitespace normalisation).
3. Every number in `verdict`, `details`, `table`, `obligations` appears in a cited quote or facts row (Indian grouping and "lakh/crore" forms normalised).
4. Every OC number mentioned is present in the evidence.
5. No text claims "current" for a superseded document.
6. On failure: regenerate once with the failure reason; if it fails again, return the **fallback** (raw passages plus a short message). Never show the failed answer.

### 5.5 Clarify and abstain
- `clarify` is returned only when the readings are mutually exclusive (PRD section 7.3), with buttons.
- `not_found` states plainly what was searched and that no wrong answer will be given; it also reports thin coverage (for example "only a few circulars mention this").

## 6. Repository layout

```
core/            normalize.py router.py evidence/ writer.py checker.py answer.py llm.py config.py
ingest/          extract.py registry.py facts.py chunk.py index.py build.py
data/            registry.csv facts.csv code_mentions.csv chunks.jsonl review_log.csv
build/           (generated, ignored) indexes + build_info.json
eval/            gold_set.csv run_eval.py report.md
tests/           unit tests for router, checker, normalize, registry validation
app.py           thin Streamlit UI
docs/            PRD.md ARCHITECTURE.md FSD.md
scripts/         one-off utilities
```
`data/raw_pdfs/` and extracted text stay outside Git as today.

## 7. What happens to today's code

| Today | Fate |
|---|---|
| `app.py` (1000 lines) | Split: logic moves to `core/`, UI stays thin |
| `config.py` ACRONYM_TO_OC | Replaced by registry plus a small `glossary.csv`; hand-coded chains removed |
| `app.py` SUPERSESSION_CHAINS, LIMIT_KEYWORD_TO_OC | Removed; driven by registry and facts |
| `hybrid_search.py` | Kept, moved to `core/evidence/`, reads `chunks.jsonl`, adds reranker |
| `number_guard.py` | Absorbed into `core/checker.py` (fail-closed, not appended warnings) |
| `rebuild_corpus.py`, `extract.py`, `chunk.py`, `embed.py` | Consolidated under `ingest/` with one `build.py` |
| `src/rank_bm25.py` | Removed; use the pinned `rank-bm25` package |
| `Data/chat_history.json` | Removed; history lives in the browser session only |
| `oc_scrapper/` | Moved to `scripts/` or kept separate; documented in the README |

## 8. Build pipeline and gates

`python -m ingest.build` runs: extract → validate registry → validate facts/code_mentions (quote must exist in source) → chunk with registry metadata → build indexes → write `build/build_info.json` (build id, corpus date, counts) → run the eval.

**The build fails** if: a document extracts to near-empty text, a chunk lacks `doc_id` or title/date, a `human_verified` fact's quote is not in its source, two documents share a `doc_id`, or the eval gates fall below threshold.

## 9. Runtime configuration, failure modes, security

| Topic | Design |
|---|---|
| LLM | One OpenAI-compatible interface; provider chosen by environment (`LLM_PROVIDER=groq|ollama`). Rate-limit and connection errors map to the fallback, never a blank screen |
| Secrets | Environment or the host's secrets store only; none in the repo |
| History/privacy | `st.session_state` only; no server-side question storage; feedback stores answer id and reason, not user text, unless the user adds a comment |
| Prompt injection | Retrieved text is data; the checker refuses outputs that cite things not in evidence |
| Caching | Optional in-memory cache keyed by normalised question and build id to save free-tier calls |
| Observability | Build id in every answer; failure categories counted locally; no personal data in logs |

## 10. Testing and evaluation

- **Unit tests:** OC-id parsing (`76A`, `OC-76`, `IMPS` series), router intents, checker (wrong number, fake quote, stale claim), registry/facts validators.
- **Gold set:** `eval/gold_set.csv` with `question, intent, expected_oc, expected_values, must_refuse, notes`; about 40 questions for the MVP trial, growing to about 120.
- **Metrics:** hit@10, exact-number correctness, current-vs-superseded correctness, quote validity, correct refusal, latency.
- **CI:** GitHub Actions runs unit tests and the eval on every change; thresholds from PRD section 10 block merges.

## 11. Decisions (ADR log)

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| ADR-1 | Registry, facts and code mentions are CSV in Git | Human-reviewable diffs, contributor friendly, no database to host | Data outgrows spreadsheets |
| ADR-2 | Keep ChromaDB plus BM25 for the MVP | Already built; minimal change while data work dominates | Hosting move (for example Cloudflare) or index size issues |
| ADR-3 | Writer returns JSON; UI renders only validated JSON | Makes quote and number checking mechanical | A model cannot follow the schema reliably |
| ADR-4 | Logic in `core/`, UI thin | Allows other frontends and an API (R3) | Never expected |
| ADR-5 | A general retrieval path is always present | Users will ask many more kinds of questions than the samples | Never |
| ADR-6 | Only `human_verified` facts are served | Compliance risk; drafts are not trusted | After a second reviewer and an automated audit exist |
| ADR-7 | Specialised path failing falls through to general search | Avoids dead ends on unexpected questions | Fall-through produces unsafe answers in eval |

## 12. Extension points

- **R2:** OC browser and timeline read `registry.csv`; compare uses chunks of two `doc_id`s; historical queries add an `as_of` filter on facts and registry dates.
- **R3:** an `ingest.fetch` module adds new PDFs (respecting robots.txt), the `domain` column carries IMPS/RuPay/BBPS/RBI, and `core` is exposed through a small HTTP API.

## 13. Open technical questions (resolved in FSD or by eval)

1. Embedding model: keep `all-MiniLM-L6-v2` or switch to a multilingual model (decided by Hinglish hit@10).
2. Reranker model and its CPU latency on the free host.
3. Which free-tier LLM reliably returns the JSON schema (compare gpt-oss-20b, 120b, local qwen3).
4. Whether OCR quality (for example "₹" read as "£") needs a correction pass before facts are drafted.

## 14. As built in M0 (differences from the sections above)

- **Folder name.** Reviewed data lives in `Data/` (not `data/`): macOS file systems are case-insensitive, so two folders differing only in case would collide in Git. Files: `Data/registry.csv`, `Data/review_log.csv`, `Data/chunks.jsonl`, `Data/build_info.json`, `Data/coverage_report.md`, `Data/dedupe_report.csv`. `facts.csv` and `code_mentions.csv` arrive in M1.
- **Text cache.** `Data/text_cache/<content_hash>.json` (local, not in Git) holds extracted text per PDF, keyed by file hash so nothing depends on filenames.
- **Registry columns.** `doc_id, oc_number, series, domain, reference, title, issue_date, effective_date, fy, category, status, supersedes, superseded_by, source_file, content_hash, text_source, page_count, char_count, review_status, needs_review, notes`.
- **doc_id and series.** `UPI-76B`, `IMPS_UPI-99`, `RUPAY-19A`, `PD-2025-26-001`, `SOP-2020-21-01`. Series seen: UPI, IMPS_UPI, RUPAY, PD (self-attestation notices), GEN, CERT, IS, SOP.
- **Review state.** Every row starts as `review_status=drafted` with `needs_review` flags (for example `date_check`, `title_from_text`, `supersession_seeded`). Manual corrections are recorded in `Data/review_log.csv`. A document that truly carries no date is marked `date_unknown_confirmed`.
- **Supersession is seeded, not verified.** `supersedes`/`superseded_by` were seeded from the hand-written chains of the first app and flagged `supersession_seeded`; they must be verified against the circular text in M1.
- **Chunk fields** also include `domain` and `chunk_type`; `page` is not yet populated.
- **Index.** Still ChromaDB at `Data/chroma_db/`, rebuilt into an empty directory each time (old segment folders can no longer pile up). BM25 is built in memory from `chunks.jsonl` at app start.
- **Gates implemented:** registry (unique ids, non-empty title/date, valid supersession references, valid status), chunks (unique ids, metadata present, every readable document yields chunks), indexed count equals chunk count. Unreadable source files are warnings listed in the coverage report.
- **Legacy app.** `app.py` still runs unchanged apart from reading `issue_date`, and chat history now lives only in the browser session. It is replaced by `core/` in M2.

## 15. As built in M1 (facts, codes, patches)

- **Facts file:** `Data/facts.csv`, one row per limit statement. Columns: `fact_id, domain, txn_type, limit_kind, direction, merchant_type, mcc, category_name, value, unit, conditions, effective_date, end_date, source_oc, source_doc_id, quote, status, superseded_by_fact, review_status, reviewer, reviewed_on, notes`.
  - `txn_type`: P2P, P2PM, P2M, UPI_LITE, UPI_LITE_X, ON_DEVICE_BIOMETRIC. `limit_kind`: per_txn_amount, per_24h_amount, per_24h_count, per_month_amount, collect_per_txn, qr_share_pay_per_txn, max_balance.
  - `direction` separates limits on sending from limits on credit received (OC 181 and OC 192 are inward-credit limits). `merchant_type`: verified, non_verified_offline, specific_categories, all.
  - `status`: `current`, `superseded` (points at the replacing fact), or `unclear` (needs a domain decision; never served).
  - Build gates: the quote must be found in the source text (after patches); the number must be visible in the quote; superseded rows need a target; `human_verified` needs a reviewer and date.
- **Supersession is tracked per fact, not per document.** The first app's hand-written chains were guesses and some were wrong (for example OC 138B is dated after OC 169 and does not change limits). They were cleared. Document-level supersession is kept only where a circular says so (OC 206A supersedes OC 206 for BGGD only).
- **Manual patches** (`Data/manual_patches/<doc_id>.txt`, see `ingest/patches.py`): `[REPLACE]`, `[REPLACE_AFTER: marker]`, or append. Nine documents were corrected from page images because OCR misread amounts, the rupee sign or whole tables (examples: OC 169A "₹5,000" read as "25,000"; OC 226A "₹5,000 to ₹10,000" read as "€5,000 to 210,000"; OC 185A MCC 8071 read as 8077; the OC 185B and OC 120 tables were scrambled).
- **Code mentions:** `Data/code_mentions.csv` is generated on every build. `rule_type` is `limit` only when a reviewed fact exists for that code; wording alone never produces `limit`. `ingest.codes.lookup` returns the three outcomes `specific_rule`, `mention_only`, `not_mentioned`.
- **Review flow:** `python -m ingest.review export` writes `Data/review/facts_review.xlsx`; the owner marks each row; `python -m ingest.review import <file> --reviewer "Name"` sets `human_verified`. Only that import can do so.
- **Coverage report** now lists facts by status, MCC and purpose-code counts, and circulars that other circulars cite but the corpus does not contain.

## 16. Circulars that exist but are not public

- Registry status `not_public`: the row has no `source_file` or `content_hash`, no chunks, and no facts. It carries the OC number, FY, and the title exactly as NPCI lists it (or "(title not shown on NPCI's list)"). `issue_date` is blank and marked `date_unknown_confirmed`.
- Build rules: `not_public` rows survive a rebuild (they are not orphans); they are skipped by chunking, indexing, fact checks and the code scan; the validator raises an error if a PDF with the same OC number later appears ("remove the not_public row"); the coverage report has a section listing them.
- Runtime: an `OC_LOOKUP` on such a row returns answer type `not_public` (see FSD S11).
- Known set (checked on NPCI's UPI circular page on 2026-10-22, FY 2025-26 and 2026-27 only): OC 141E, 230, 230A, 233, 236, 237, 238. Older years were not checked; add rows as they are found.

## 17. As built in M2 (the answering pipeline)

Package `core/` (UI-independent), used by `app.py`:

| Module | What it does |
|---|---|
| `config.py` | `Settings` from environment: `LLM_PROVIDER` (`ollama` / `groq` / `none`), models, caps, `ALLOW_UNVERIFIED_FACTS` (development only, default off) |
| `normalize.py`, `router.py` | OC ids in many forms, MCC and purpose codes, English/Hinglish detection; ordered rules: out of scope, bank-specific, code lookup, OC lookup / limit, clarify, definition, general. Returns a `Plan` |
| `stores.py` | Loads registry, facts (only `human_verified` unless the dev switch is on), code mentions, chunks, build info |
| `evidence/facts.py` | Limit rows per transaction type (every limit kind; kinds no OC sets are returned as `no_oc_sets_this`), category and MCC rows, superseded chains, code outcomes (`specific_rule`, `mention_only`, `not_mentioned`, reverse lookup) |
| `evidence/documents.py`, `evidence/search.py` | One circular's chunks in order; hybrid search (BM25 + vectors, reciprocal rank fusion, BM25-only if the index is missing) |
| `writer.py` | Deterministic builders for limits, codes, refusals, clarify, not-public, not-found, passages; the JSON prompt and parser for model-written answers |
| `checker.py` | Quote must be found in its source (an `...` joins parts in order); table amounts must be visible in their quote; free-text numbers must appear in a cited quote; OC numbers must exist in the evidence; model statements need citations |
| `llm.py` | One OpenAI-compatible client for Groq and Ollama, JSON-only, errors mapped to kinds |
| `pipeline.py` | `Pipeline.answer(question)`: route, evidence, write, check, fall back. A model answer gets one regeneration with the checker's reasons, then source passages |
| `phrases.py` | Fixed English and Hinglish wording, Indian digit grouping (`₹1,00,000`), dates |

Decisions:
- Limit and code answers contain **no model-written numbers**: values, dates and quotes come straight from fact rows, and the checker re-verifies each cell against its quote.
- A facts-backed answer that fails the checker becomes a plain "not found" (never an unverified table). A model-written answer that fails twice becomes passages.
- A `LIMIT` question with no facts falls through to search and the model, so unexpected questions still get a grounded answer or an honest "not found".
- `unclear` facts are shown only as an "Unconfirmed" row with their conditions; they are never presented as the limit.
- `app.py` is now a thin shell (chat, sources, status); the previous app is kept as `app_legacy.py` until M3 replaces it.

Evaluation: `eval/gold_set.csv` (42 questions), `python -m eval.run_eval [--no-llm]`, `python -m eval.show "question"`, report in `eval/report.md`.

## 18. The UPI Consolidated Circular and withdrawn OCs

- `UPI-CC-01` (series `CC`, issued 18 September 2026, version 1.0, 54 pages, native text) is in the registry. It incorporates the OCs issued up to **31 July 2026**; later OCs (for example 239) are outside it.
- Its Annexure G lists 43 OCs that "stand withdrawn by NPCI with immediate effect". 36 are in the corpus and now have registry status `withdrawn` (they stay searchable; answers that use them say they are withdrawn). Seven are not in the corpus: 20, 21, 35, 50, 86, 87, 89. This replaced the guessed supersession chains with a real source.
- Facts: new status `withdrawn` (OC 61's 10-transactions-per-24-hours P2P limit); OC 185's hospitals and education limit is `superseded` by the Annexure to OC 185A, which restates it; one new fact from section 7.2 (P2PM categorisation threshold of ₹1 lakh expected monthly inward UPI transactions, consistent with OC 192).
- The Consolidated Circular does not restate the limit tables; it points to "applicable limits" per MCC. Limits therefore stay with the OCs that are not withdrawn (76C, 120, 169A, 181B, 185A, 185B, 192, 226A).
- Runtime: a withdrawn limit appears only as a "Withdrawn" line; an `OC_LOOKUP` on a withdrawn OC adds a notice; the writer prompt marks withdrawn passages.

## 19. References, interface, feedback, CI and clean-up

- **References.** Chunks and facts carry a `page`; a citation carries `reference`, built by `core/reference.py` as document (OC number or "UPI Consolidated Circular"), issue date, nearest numbered clause (for example `clause 14.24.4`) and page. Pages are known for text PDFs and single-page documents; for multi-page scanned circulars (OCR text is one block) the page is left out rather than guessed. Every answer shown must carry citations with a reference.
- **Interface (`app.py`).** Answer card (verdict, coloured status, limits table, obligations, collapsible earlier or withdrawn rules, sources with reference and exact quote, footer with corpus date and build id), clarify and example buttons, 👍/👎 with reasons, session-only history, mobile-friendly. Headless tests drive it with Streamlit's `AppTest`.
- **Feedback (`core/feedback.py`).** Posts to a Google Form; without the user's consent only the answer type, build id, rating, reason and comment are sent (no question or answer text).
- **Search.** `core/evidence/synonyms.py` appends the circulars' own wording to the search query (for example "AutoPay interoperability" adds "port mandate", "view mandate", "MIC"); it replaces the old hand-written acronym-to-OC table and is meant to grow.
- **CI.** `.github/workflows/ci.yml` runs the unit tests and the model-free gold set.
- **Removed** (replaced by `core/` and `eval/`): `app_legacy.py`, `number_guard.py`, `config.py`, `hybrid_search.py`, `eval_retrieval.py`, `eval_ab_hybrid.py`, `build_regression_set.py` and the old retrieval-only result files. The 56 retrieval questions live on as `eval/retrieval_set.csv`.

Gate status (development facts): unit tests 139 pass; gold set without a model 35 of 35; search hit@8 on the questions answered by search 97.5% (39 of 40; gate 90%).

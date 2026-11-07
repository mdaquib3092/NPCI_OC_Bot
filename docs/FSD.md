# NPCI Reader: Functional Specification (FSD): MVP Trial

| | |
|---|---|
| Status | **Draft v0.1: for owner review** |
| Date | 2026-10-22 |
| Scope | **MVP trial** (private). R2/R3 are outlined, not specified |
| Depends on | `docs/PRD.md` v0.1, `docs/ARCHITECTURE.md` v0.1 |
| Rule | Nothing here is built until the owner approves this document |

Requirement ids (FR-n) refer to the PRD. "Shall" marks a testable requirement.

---

## 1. MVP trial scope

**In scope (narrow but deep)**
1. OC lookup and structured summary (FR-1, FR-2)
2. Current limits for P2P / P2PM / P2M, all three limit kinds (FR-3, FR-3b)
3. Code lookups: MCC (and purpose codes) with the three outcomes (FR-3a)
4. Definitions of terms (FR-4)
5. Citations with exact quotes, current-vs-earlier, clarify/abstain, fail-closed checker (FR-5 to FR-8)
6. English and Hinglish input and output (FR-9)
7. Streamlit UI with answer card, feedback reasons, session-only history (FR-10 to FR-13)
8. One-command build with validation, and an eval run (FR-17)

**General retrieval stays on.** Users will ask more kinds of questions than the examples; anything not matched by a specialised path goes to the general path and is answered honestly or refused.

**Out of scope for the trial:** OC browser, compare, historical "as of" queries, automation, other rails, document upload, API, login.

**Trial data scope.** The registry covers *all* indexed documents. Reviewed facts are built first for the limits topics (P2P, P2PM, P2M, UPI Lite) and for every MCC mentioned in the corpus; other topics use the general path until their facts are added.

**Trial exit criteria:** the quality gates in section 11 pass on the trial gold set (about 40 questions).

## 2. Users and flows

### 2.1 Main flow
1. User opens the app and sees a short welcome with four example questions and the disclaimer.
2. User types a question (English or Hinglish) and sends it.
3. The app shows a progress state, then an **answer card** (or a clarification with buttons, or a not-found message).
4. User may expand the sources, rate the answer with a reason, or ask a follow-up.

### 2.2 Example behaviours (acceptance scenarios)

| # | User asks | Expected |
|---|---|---|
| S1 | "OC 185A kya bolta hai?" | Structured summary of OC 185A: what it says, who acts, what to do, effective date, status, related OCs, quote(s) |
| S2 | "P2P limit kya hai?" | Table with three rows (per-txn amount, 24h amount, 24h count); each row has a value with OC and date, or "No OC sets this" |
| S3 | "P2M limit for MCC 7407" | The rule for that MCC with OC and quote, or "OC mentions this MCC but sets no limit", or "No indexed OC mentions MCC 7407" |
| S4 | "MCC 1520 ki limit?" | Currently "No indexed OC mentions MCC 1520" (after a data audit confirms the PDFs do not contain it) |
| S5 | "What is UPI Circle?" | Plain definition from OC 201/201A with quote |
| S6 | "MDR limit in depth explain karo" | Grounded answer from what exists plus a clear statement of how thinly the OCs cover it |
| S7 | "Mere account ki daily limit?" | States that bank/app-level limits are not in the OCs; may show NPCI-level limits if relevant |
| S8 | "Who is NPCI's CEO?" | Refusal: outside the indexed OCs |
| S9 | "limit kya hai" (no type) | Clarify with buttons: P2P / P2M / UPI Lite / Other |
| S11 | "OC 233 kya bolta hai?" (an OC NPCI lists but does not publish) | Answer type `not_public`: states that the OC exists, shows its title if listed, and says NPCI has not made the PDF public so it cannot be summarised; no guessing |
| S10 | A question whose answer figure cannot be verified | No generated answer; the source passages are shown with an explanatory line |

## 3. Data specification

Schemas are in `ARCHITECTURE.md` section 4. Rules below are the functional requirements on that data.

### 3.1 Registry (`data/registry.csv`)
- **R-1** Every indexed document shall have exactly one row with unique `doc_id`.
- **R-2** `oc_number` shall keep letter suffixes (`76A`) and shall not be inferred from a document that only references another circular (administrative notices have a blank `oc_number` until resolved by a person).
- **R-3** Joint IMPS/UPI "Operation Circular" documents shall use `series=IMPS_UPI` so they never merge with the UPI series.
- **R-4** `title`, `issue_date`, `status` shall be non-empty for every readable row (a document that carries no date is marked `date_unknown_confirmed` by a person); `supersedes/superseded_by` shall reference existing rows.
- **R-5** The first version of the registry is drafted by script and an LLM from the PDFs (title and dates), then reviewed by the owner and logged in `review_log.csv`.

### 3.2 Facts (`data/facts.csv`)
- **F-1** A fact has one `txn_type`, one `limit_kind`, an optional `mcc`, a `value`/`unit`, an `effective_date`, and a verbatim `quote` from `source_doc_id` with `page`.
- **F-2** Only `human_verified` rows are served.
- **F-3** Superseded facts remain in the file with `status=superseded` and `superseded_by_fact` set; they are shown only as "earlier".
- **F-4** For each `txn_type` the system shall know the set of limit kinds it expects (P2P/P2PM/P2M: the three kinds plus collect); a kind with no fact is reported as "No OC sets this", not omitted.
- **F-5** Build-time validation: the quote shall be found in the source text; the value shall appear in the quote.

### 3.3 Code mentions (`data/code_mentions.csv`)
- **C-1** Built by scanning every document for MCC patterns and listed purpose codes; each hit becomes a row with `rule_type` (`limit | requirement | mention_only`) and the surrounding quote.
- **C-2** The audit report lists every code found and every document where the scan found none, so the maintainer can spot table content the extractor missed.

### 3.4 Chunks and index
- **K-1** Chunks inherit registry metadata at build time.
- **K-2** Tables are kept whole where possible; larger tables split by rows with the header repeated.
- **K-3** Overlap shall not cross a table boundary.
- **K-4** BM25 and vector indexes are built only from `chunks.jsonl`, so they cannot disagree.

### 3.5 Data quality gates (build fails if violated)
| Check | Rule |
|---|---|
| Empty extraction | No document under the minimum text threshold unless explicitly marked `unreadable` in the registry (and then shown in the coverage report) |
| Metadata | 100% of chunks have `doc_id`, `title`, `issue_date`, `status` |
| Facts | All `human_verified` quotes found in their source |
| Duplicates | No duplicate `doc_id` or `chunk_id` |
| Coverage report | Counts by series/year and list of known gaps are generated and shown in the UI footer link |

## 4. Query understanding (router)

### 4.1 Normalisation
- Lowercase for matching; keep original text for the writer.
- OC forms: `OC 76`, `oc-76`, `OC76A`, `circular no. 76 A` all map to `76A`/`76`.
- Hinglish lexicon: a small file `core/lexicon.py` maps common words (kya, kitna, hai, bolta, batao, abhi, pehle, kab, kaun) to intents/slots; the language of the reply follows the language of the question.
- Spelling variants of key terms (P2P, P2M, UPI Lite, AutoPay, UDIR, MCC) are accepted case-insensitively.

### 4.2 Intent rules
Applied in the order of ARCHITECTURE 5.1. For each intent the router extracts a `Plan`:
```
Plan { intent, oc_number?, txn_type?, limit_kind?, code?, code_family?, term?, language, confidence }
```
- **RT-1** If an explicit OC number is present, `OC_LOOKUP` wins unless the sentence is clearly a limit/code question about that OC (the plan then keeps `oc_number` as a filter).
- **RT-2** A limit question without a transaction type triggers clarification (S9); with a type, all limit kinds are returned.
- **RT-3** A code question with no number ("which MCC for jewellery") is a reverse lookup against `code_mentions` names.
- **RT-4** If confidence is low, the router may ask the LLM for a one-word intent label; the label is validated against the allowed list.
- **RT-5** A specialised path with empty evidence falls through to `GENERAL`.

### 4.3 Out-of-scope handling
- Pre-check rejects obviously unrelated questions (for example finance, sports, personal data); the final decision is also made after retrieval: if evidence scores are below threshold, the answer is `not_found`/`refusal`, not a guess.

## 5. Evidence retrieval

- **EV-1 (`OC_LOOKUP`)** If the registry row has status `not_public`, return only that row (no chunks) and the answer type is `not_public`. Otherwise return the registry row and all chunks of the document, in order, up to the cap. If the document is a superseded one, include the superseding document's title and summary line.
- **EV-2 (`LIMIT`)** Return facts for the `txn_type`, grouped by `limit_kind`; current rows first, superseded rows labelled. For unknown kinds return explicit `no_oc_sets_this`.
- **EV-3 (`CODE_LOOKUP`)** Return `code_mentions` and linked facts; compute the outcome: `specific_rule | mention_only | not_mentioned`. Never infer a rule for `not_mentioned` (PRD D9 pending: default is to say "not mentioned").
- **EV-4 (`DEFINITION`/`GENERAL`)** Hybrid search: BM25 top 20 and vector top 20 (cosine distance cutoff configurable), fused with reciprocal rank fusion, then reranked; keep the top N (default 8).
- **EV-5 (supersession)** Drop chunks whose document is superseded unless no current document covers the topic; always include a pointer to what replaced it.
- **EV-6 (caps)** The evidence pack is limited by chunk count and total characters (defaults: 12 chunks, 12,000 characters); tables are never cut mid-row.
- **EV-7 (coverage honesty)** The pack carries a `coverage` note (number of documents that mention the topic) so the writer can say "only N circulars mention this".

## 6. Answer generation

### 6.1 Writer contract
- **W-1** The writer receives: language, the question, the plan, and the evidence pack with citation ids; it shall return only the JSON in ARCHITECTURE 4.5.
- **W-2** Instructions: use only evidence; copy numbers, dates, codes and OC numbers exactly; do not advise; put current rule first and earlier rules second; say "not found" when the evidence does not answer.
- **W-3** For `LIMIT`/`CODE_LOOKUP` the table rows are filled from fact rows; the writer adds only the verdict sentence and notes.
- **W-4** Temperature 0; bounded output length; a reasoning-suppression flag per model if needed.

### 6.2 Answer types and layout
| Type | Content |
|---|---|
| `summary` | verdict (one line); what it says; who must act; what to do; effective date/deadline; status; related OCs; sources |
| `limit_table` | verdict; three-row table; current vs earlier; sources |
| `code_result` | outcome label; rule or statement; sources |
| `definition` | one-sentence definition; short details; sources |
| `not_found` | what was searched; coverage note; suggestion to check NPCI |
| `clarify` | one question and buttons |
| `refusal` | polite reason (out of scope / not advice / bank-specific limit) |
| `not_public` | OC number, title as NPCI lists it, and the statement that the circular exists but its text is not public |

### 6.3 Language
- **L-1** The reply language follows the question (English or Hinglish).
- **L-2** Numbers, currency symbols, OC numbers, MCC codes and quotes are never translated or reformatted.

## 7. Checker (fail closed)

The checker implements ARCHITECTURE 5.4. Functional requirements:
- **CH-1** Reject if JSON is invalid or has unknown fields.
- **CH-2** Each citation quote shall be a substring of its evidence chunk or fact quote (whitespace and OCR-symbol normalisation: `₹`/`Rs`/`£`).
- **CH-3** Each number in verdict/details/table/obligations shall appear in a cited quote or fact row. Number comparison normalises Indian digit grouping and lakh/crore. Short numbers are not skipped when they are limits, counts, or percentages.
- **CH-4** Each OC number/MCC code in the text shall exist in the evidence.
- **CH-5** Text shall not label a superseded document as current.
- **CH-6** On failure: one regeneration with the failure reason; then fallback to passages. A failed answer is never displayed.
- **CH-7** Status: `verified` if all claims have verified citations; `partially_verified` if some detail lines were removed because they failed (the verdict itself passed); `not_found` for no-evidence answers.

## 8. User interface

### 8.1 Screens and components
1. **Chat screen** (single page): welcome panel (when empty), message list, input box.
2. **Answer card** (per assistant message): verdict; status badge; table or details; "Earlier rule" section (collapsed by default if long); sources with exact quotes (expandable); footer line (corpus as of date, build id, unofficial disclaimer).
3. **Clarify card**: question plus buttons; clicking a button sends the follow-up automatically.
4. **Feedback**: 👍 / 👎 with reason chips (Wrong number, Outdated circular, Incomplete, Unclear) and an optional comment.
5. **Sidebar**: new chat, recent chats (this browser session only), model selector (dev only), coverage/about link, disclaimer.

### 8.2 States
Loading ("Searching circulars..."), success, clarification, not found, refusal, LLM unavailable (falls back to passages), data/index missing (clear setup message).

### 8.3 Behaviour rules
- **UI-1** Mobile first: single column, readable tables (horizontal scroll or stacked rows), tap targets at least 44 px.
- **UI-2** Chat history lives in the browser session only; "New chat" and "Delete chat" clear it. No shared server file.
- **UI-3** The UI renders only the validated answer object; it shall not display raw model text.
- **UI-4** Accessibility: keyboard order, sufficient contrast, labels on buttons, status not conveyed by colour alone.
- **UI-5** The disclaimer is visible on first load and in each answer footer.

## 9. Feedback and privacy

- **P-1** No login; no cookies beyond the framework's session.
- **P-2** User questions are not stored on the server. Feedback records: answer type, build id, reason category, optional comment, timestamp. If the user chooses to include the question text, they do so explicitly (default off).
- **P-3** Feedback goes to the existing Google Form endpoint (configurable), failing silently for the user but logged locally.

## 10. Operations and configuration

| Setting | Source | Default |
|---|---|---|
| `LLM_PROVIDER` | env | `groq` in deploy, `ollama` locally |
| `GROQ_API_KEY` | env / host secrets | none |
| `MODEL_NAME` | env | chosen by eval |
| `EMBED_MODEL`, `RERANK_MODEL` | env | chosen by eval |
| `TOP_K`, `MAX_EVIDENCE_CHARS` | env | 8, 12000 |
| `FEEDBACK_URL` | env | existing form |

- **Op-1** `python -m ingest.build` produces everything and prints a validation summary; exit code is non-zero on any gate failure.
- **Op-2** `python -m eval.run_eval` prints the metrics table and writes `eval/report.md`.
- **Op-3** Errors from the LLM (rate limit, timeout, network) are mapped to user-readable messages and the passages fallback.

## 11. Testing and quality gates

### 11.1 Unit tests
OC-id normalisation; router intents (English and Hinglish); registry and facts validators; evidence supersession filter; checker (wrong number, fake quote, stale-as-current, missing citation); answer-object schema.

### 11.2 Gold set (trial)
`eval/gold_set.csv`: `id, question, language, intent, expected_oc, expected_values, must_refuse, must_clarify, notes`. About 40 questions covering every type in PRD section 5, including the five owner examples, thin-topic (MDR), not-mentioned (an MCC absent from the corpus), bank-specific limit, out-of-scope, and Hinglish variants.

### 11.3 Metrics and trial gates
| Metric | Gate |
|---|---|
| Exact-number correctness (limit/code questions) | 100% |
| Superseded shown as current | 0 |
| Quote validity (all answers) | 100% |
| Correct refusal / not-found on out-of-scope and absent data | ≥ 95% |
| Retrieval hit@10 (general questions) | ≥ 90% |
| Latency p50 on target host | ≤ 8 s |

### 11.4 Review protocol
Facts and code mentions: drafted with LLM assistance; automatically checked (quote in source); then verified by the owner and recorded in `data/review_log.csv` (who, what, when). A second reviewer is recommended for a sample (PRD D6).

## 12. Delivery plan for the MVP trial

| Milestone | Work | Exit |
|---|---|---|
| M0 Foundation | Registry, fix empty/blank extractions, metadata in chunks, one-command build, remove shared history file, vendored BM25 | Data gates pass; coverage report generated |
| M1 Facts | Draft/review limits facts; code-mention scan and audit; confirm MCC 1520 and MDR outcomes | `human_verified` facts for P2P/P2PM/P2M/UPI Lite; audit report reviewed |
| M2 Pipeline | `core/` router, evidence, writer, checker; model selection by eval | Unit tests green; pipeline gates met on gold set |
| M3 UI | Answer card, clarify, feedback, states, mobile layout | Walkthrough of scenarios S1 to S10 |
| M4 Evaluation | Full gold set run, error analysis, fixes, report | All trial gates pass; report saved in `eval/report.md` |

Then: closed pilot (5 to 10 users), public R1 (after license and hosting decisions D1/D2).

## 13. Out of scope but planned (outline)

- **R2:** OC browser (search/filter/timeline from registry), compare two `doc_id`s, historical "as of" facts, topic deep-dives.
- **R3:** `ingest.fetch` for new PDFs (robots.txt respected), other domains via `domain`, HTTP API over `core/`, optional document upload.

## 14. Open items for the owner

1. Approve scope of the trial (section 1) and the gates (section 11).
2. D6: second reviewer for facts and gold set.
3. D9: for an MCC not mentioned anywhere, say only "not mentioned" (default) or also quote a general rule when an OC explicitly covers unlisted codes.
4. D5: weekly time, to turn the milestones into dates.
5. D1/D2 can wait until after the trial.

# NPCI Reader: Product Requirements Document (PRD)

| | |
|---|---|
| Status | **Draft v0.1: for owner review** |
| Date | 2026-10-22 |
| Owner | Md Aquib |
| Basis | Owner's questionnaire answers (`NPCI_Reader_PRD_Questionnaire`), repo analysis, design discussion |
| Next document | FSD (Functional/Technical Specification), written only after this PRD is approved |

Items marked **[ASSUMED]** were not answered in the questionnaire; the suggested default was used. Items marked **[DECISION]** need an explicit owner decision (see section 14).

---

## 1. Vision and purpose

**One line:** A trustworthy assistant that tells people working in UPI exactly what NPCI's Operating Circulars (OCs) say, what must be done, by when, and where it is written, and says "I don't have this" instead of guessing.

**Why it exists**
- NPCI has issued hundreds of OCs, many of which amend or supersede earlier ones. Tracking what is current, what changed, and what is required is slow and error-prone.
- Today a person must open PDFs, find the latest version in a chain, and read tables by hand.

**Owner's intent (Q1)**
- A real, working, open-source product by an individual builder (IIT alumnus, working professional), shared publicly (LinkedIn) to support networking and collaboration.
- Implication: the product must be *demonstrably correct* and *polished*. Published accuracy results and a clean public repository are part of the deliverable, not extras.

## 2. Goals and non-goals

### Goals
1. **Correct limits, correct summaries, correct references** (owner's definition of v1, Q39).
2. Help a user understand *what NPCI wants, what to build or change, and when*, with references (Q3).
3. Always show where an answer comes from (OC number and exact quote).
4. Never present a wrong, stale, or unverified figure as fact.
5. Be usable on web and mobile, in English and Hinglish.
6. Be open source with a clear, working contribution and update process.

### Non-goals (v1)
- Advice or recommendations ("what should we do?"). The bot reports what the OC says (Q7).
- Answers from anything outside the indexed OCs (Q10).
- Other rails and regulators: IMPS, RuPay, BBPS, RBI circulars (later, Q6).
- User document upload and comparison (not requested; default is later, Q8).
- Login, accounts, or server-side user history (Q24).
- Legal or penalty calculation.

## 3. Users and jobs to be done (Q2, Q3)

| Persona | Typical need |
|---|---|
| Developer / integrator | "What does the OC require us to change in the API or flow, and by when?" |
| Product manager | "What is the current limit or rule for X, and what changed?" |
| QA / compliance tester | "What exact rule do I test against, and which OC says so?" |
| Business owner / head | "Does this circular affect us, and what is the deadline?" |
| Company teams (PSPs, aggregators, TPAPs) | Quick, referenced answers shared across the team |

**Core job:** *"Give me the correct, current rule or summary, with its source, quickly."*

## 4. Scope and release plan

The owner's v1 bar (Q39): *correct limits, correct summary, correct reference.* The OC browser (Q23) and compare (Q21) are wanted but are not part of that bar, so they are scheduled after R1.

| Release | Contents |
|---|---|
| **R1 (MVP)** | Chat Q&A over UPI OCs: OC summary/lookup, current limits, definitions, citations with quotes, current-vs-earlier handling, clarify-then-abstain, English + Hinglish, web/mobile, feedback with reasons, session-only history, disclaimers, public evaluation report |
| **R2** | OC browser (search, filter, supersession timeline), compare two OCs ("OC 181 vs 181B"), historical "as of date" questions, topic deep-dives |
| **R3** | Automated ingestion of new circulars (respecting NPCI's robots.txt), additional domains (IMPS, RuPay, BBPS, RBI), public API, optional document upload |

[DECISION D3] Owner replied "Haa" to compare; this PRD schedules it in R2 unless moved up.

## 5. What users will ask: question types

 five sample questions (Q5) and the existing eval set.These question are basic example, it is doesn't represent that only for these questions chatbot was design, more about what type of question may bot can get and it need to answer al.

| Type | Example | Expected behaviour | Corpus check (2026-10-22) |
|---|---|---|---|
| OC lookup / summary | "OC 185A kya bolta hai?" | Structured summary of that exact OC | OC 185A is in the index (15 chunks) |
| Code lookup (MCC and similar) | "MCC 1520 ki limit kya hai?" (MCC 1520 is only an example; the class covers **every MCC**, plus purpose codes and other code families) | Exact rule for that code from a structured code table, with source OC; if no OC mentions the code, say exactly that | MCC data is scattered across ~36 OCs and only ~45 distinct codes are mentioned, mostly in running text rather than one table. "1520" appears in no indexed chunk, so today's correct answer for it is "not mentioned in any OC" |
| Definition | "What is UPI Circle?" | Plain explanation grounded in OC text | Covered by OC 201/201A (and an unnumbered file) |
| Deep dive | "MDR limit in depth explain karo" | Grounded explanation of everything the OCs say about MDR | **Only 5 chunks mention MDR; "merchant discount rate" appears 0 times.** Likely a thin topic; bot must say how little the OCs cover |
| Current limits | "Current P2P and P2M limits?" | Current figures, effective dates, what they replaced | Needs supersession handling (OC 120, 181B, etc.) |
| Obligation / deadline | "What must PSPs do under OC X and by when?" | Who, what, effective date | New capability (see FR-2) |
| History | "What was the limit in 2021?" | Figure valid at that time | R2 |
| Exists but not public | "What does OC 233 say?" | "OC 233 exists (title as NPCI lists it), but NPCI has not made its PDF public, so I cannot summarise it" | OC 141E, 230, 230A, 233, 236, 237, 238 are listed by NPCI without a PDF |
| Out of scope | "Who is NPCI's CEO?" | Polite refusal, no guessing | Present in eval set |

These two corpus findings become acceptance tests: the bot must handle "MCC 1520" and "MDR" honestly, and the data team must check whether the PDFs contain more than the extractor captured.

## 6. Functional requirements (product level)

Priority: **P0** = R1 must-have, **P1** = R2, **P2** = R3. Detailed behaviour is specified in the FSD.

### Answering
- **FR-1 (P0) Explicit OC lookup.** "OC 185A", "circular 76B" return that circular's summary. Variants (`OC-76`, `OC 76 A`) resolve correctly. Unnumbered or ambiguous documents are never silently attributed to another OC.
- **FR-1b (P0) Circulars that exist but are not public.** NPCI lists some OCs with no PDF ("Please get in touch with your bank"). The registry records them with status `not_public`. For such an OC the bot says it exists, gives the title NPCI lists (if any), and states plainly that its text is not publicly available, so it cannot summarise it or quote limits from it. It never guesses the content. These OCs also appear in listing answers, marked as member-only.
- **FR-2 (P0) Structured summary.** Every summary states: *what it says; who must act; what must be done; effective date / deadline; current or superseded; related OCs; source.* This addresses the owner's core need (Q3).
- **FR-3 (P0) Current limits and rules.** Limits and numeric rules come from reviewed structured facts (FSD) and always show the circular, the effective date, and what was replaced. Limits are organised by **transaction type first**:
  - **P2P / P2PM (person to person, person to merchant by default):** limits depend on transaction type and mode (for example per-transaction amount, 24-hour amount or count, collect request). **No MCC is involved.**
  - **P2M (merchant payments):** limits can depend on the merchant category, so the **MCC dimension applies only here** (and in a few specific flows such as purpose-coded payments).
  - Other limit holders: UPI Lite, AutoPay, international, and similar products, each with its own rules.
  A limit question therefore resolves in order: transaction type, then limit kind, then optional MCC/category.
  - **All three limit kinds are answered together.** A general limit question ("P2P limit kya hai?") returns, in one compact table: (a) per-transaction amount, (b) 24-hour total amount, (c) 24-hour transaction count. The user is not asked which one they meant; if the user names one kind, that kind is shown first.
  - **Each kind has a status:** the value with its OC and effective date, or "No OC sets this" when the circulars are silent (for example, a limit set by banks rather than NPCI). A cell is never left blank or guessed.
- **FR-3b (P0) Whose limit.** The bot only knows limits that NPCI circulars set for the ecosystem. Limits set by an individual bank or app ("meri account ki limit") are not in the OCs; for such questions the answer states this plainly and does not guess.
- **FR-3a (P0) Code lookups (merchant payments).** For any MCC (and other code families such as purpose codes), which are relevant to P2M and not to P2P, the answer comes from a structured code table built from all OCs: code, category name, applicable limit/rule, effective date, status, source OC and quote. The bot must distinguish three outcomes: *the OC sets a specific rule for this code*; *the OC mentions the code but sets no limit*; *no indexed OC mentions this code*. In the third case it never invents a rule. It may point to the general limit rule only when an OC explicitly says that rule applies to codes not listed [DECISION D9]. Reverse lookups ("which MCC is jewellery?") use the same table.
- **FR-4 (P0) Definitions.** Terms (UPI Circle, UDIR, TPAP, ...) are explained from the OCs, not general knowledge.
- **FR-5 (P0) Citations.** Every answer lists the OC number(s) and the exact supporting quote (Q18). No quote means no claim.
- **FR-6 (P0) Current vs earlier.** If a rule changed, the answer gives the current rule first and the earlier one clearly labelled as superseded (Q20).
- **FR-7 (P0) Clarify, then abstain.** Ambiguous question: ask which meaning the user wants (buttons, Q17). Clear question but no data: state that the data is not available and that a wrong answer will not be given (Q16).
- **FR-8 (P0) Verification gate.** Any figure that cannot be matched to a source quote is not shown as an answer; the source passage is shown instead.
- **FR-9 (P0) Language.** Input and output in English or Hinglish (Q9). Figures, OC numbers, and quotes are never translated or altered.
- **FR-10 (P0) Answer length.** One-line verdict plus short details (Q19). Longer detail is available on expansion.

### Experience
- **FR-11 (P0) Web, mobile-friendly UI** (Q22), no login, history only within the user's own browser session (Q24).
- **FR-12 (P0) Feedback** with reason categories: wrong number, outdated circular, incomplete, unclear (Q26).
- **FR-13 (P0) Trust signals.** Each answer shows a status (verified / partially verified / not found), the corpus "as of" date, and the unofficial-tool disclaimer.
- **FR-14 (P1) OC browser.** Search, filter by year/category/status, and a supersession timeline (Q23).
- **FR-15 (P1) Compare** two circulars side by side (Q21).
- **FR-16 (P1) Historical queries** with an explicit "as of" date (Q20).

### Content operations
- **FR-17 (P0) Manual corpus update** with a documented, one-command rebuild and validation (Q12).
- **FR-18 (P2) Automated ingestion** with robots.txt compliance (Q12, Q13).
- **FR-19 (P2) Additional domains** without redesign (Q6): the data model carries a `domain` field from day one.

## 7. Answer behaviour policy

1. **Grounded only.** Everything stated must be supported by an indexed OC. Outside the corpus: refuse (Q10).
2. **Reports, does not advise** (Q7). The bot may say "OC 181B requires X by <date>"; it does not say "you should do X".
3. **Clarify only when readings are mutually exclusive** (Q16, Q17). If a question has a small fixed set of related answers (for example "P2P limit": per transaction, 24-hour amount, 24-hour count) the bot answers all of them in one table instead of asking. It asks a short clarification only when the readings point to different things (for example "limit" with no transaction type, or an OC number that exists in two series).
4. **Fail closed** (see FR-8). A wrong confident answer is the worst outcome; "not found" is acceptable.
5. **Supersession is explicit.** Superseded figures are never mixed into the current answer.
6. **Honest coverage.** If a topic is thinly covered (as with MDR) the answer says so.

**Answer anatomy**
```
Verdict (one line, current rule)
Status: Verified from source | Partially verified | Not found
What changed: earlier rule, labelled superseded (if any)
Who must act / by when (for summaries)
Sources: OC number, title, exact quote
Footer: corpus as of <date> · unofficial, verify with NPCI
```

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Accuracy | See section 10 quality gates |
| Latency [ASSUMED] | Typical answer within ~8 s on the free tier; clear progress state while waiting |
| Cost [ASSUMED] | Run on free tiers (Q27/Q28 give no budget); must degrade gracefully on rate limits |
| Privacy [ASSUMED] | No login, no server-side storage of user questions; only user-submitted feedback is stored. A single shared history file on the server is **not** acceptable |
| Security | No secrets in the repo; keys via environment/secrets only; uploaded or retrieved text is treated as data, never as instructions |
| Accessibility [ASSUMED] | Keyboard navigable, readable contrast, usable on a ~375 px wide phone |
| Reliability | If the LLM is unavailable, show source passages instead of failing blank |
| Reproducibility | One command rebuilds data and index; each build has an id shown in the UI |

## 9. Content and data requirements

- **Coverage (Q11):** target is essentially all public UPI OCs. "All" is defined in the FSD as *every OC publicly available*, with a published list of known gaps.
- **Known gaps today:** about 14% of chunks have no OC number, five documents extracted to almost nothing (including OC 58 and parts of OC 76B and 99), and titles/dates/supersession metadata are missing from every chunk. These must be fixed before R1.
- **Sources (Q13, Q14):** public circulars only. The README states how files were obtained, including the Wayback Machine route.
- **Updates (Q12):** manual now; automated later, honouring NPCI's robots.txt.
- **Metadata (registry):** each OC carries number, title, issue date, effective date, status, supersedes/superseded-by, category, domain, source file.
- **Structured facts:** limits, timelines, and effective dates are extracted into a reviewed facts table (FSD).
- **Review protocol (Q15):** two steps. (1) Claude-assisted extraction and automated checks, including confirming every fact's quote exists in the source PDF text. (2) Manual review by the owner. Because the owner is the only human reviewer, the review log (who checked what, when) is kept in the repo. [DECISION D6]

## 10. Quality, evaluation, and success metrics

Quality is the first priority; release is gated on these (the thresholds are [ASSUMED] because Q4 and Q31-Q33 were not answered):

| Gate | Threshold |
|---|---|
| Exact-number correctness on limits questions | 100% |
| Superseded circular presented as current | 0 |
| Every answer has a quote present in the cited source | 100% |
| Correct refusal on out-of-scope questions | ≥ 95% |
| Retrieval hit@10 on gold set | ≥ 90% |
| Helpful rating in pilot | ≥ 80% (pilot of 5-10 users) |

- **Gold set:** about 120 questions across the types in section 5, answers verified (owner plus a second reviewer if available). It includes the owner's five Q5 questions.
- **Baseline:** the current stored eval shows about 71% OC hit rate and 73% faithfulness on 56 questions; this is the number to beat.
- **Public evidence:** the eval results are published in the README as part of the project's credibility.

**Project success (proposed):** a public demo link, a working open-source repo with contribution guide, and a published accuracy report. Vanity metrics (stars, impressions) are tracked but are not release gates.

## 11. Open source, licensing, and positioning

- **Public repository** with README, architecture notes, evaluation report, contribution guide, and clear disclaimer that it is unofficial and not affiliated with NPCI.
- **[DECISION D1] License conflict.** The owner wants forks to require permission (Q27) and may sell later. The repository currently has the MIT license, which lets anyone fork, modify, and use commercially with no permission. These cannot both be true. Options: keep MIT (maximum adoption, no control); AGPL-3.0 (open, but forks must stay open); a source-available non-commercial license (permission for commercial use, but not "open source" by OSI definition). Decide before the public launch.
- **Content rights:** circular text belongs to NPCI. The project redistributes only what is publicly available, attributes NPCI, and avoids implying endorsement.

## 12. Hosting and technology constraints

- Owner's preference: Streamlit Community Cloud or Cloudflare free tier (Q27); LLM via both Groq and local Ollama (Q28).
- **[DECISION D2]** Streamlit cannot run on Cloudflare Pages/Workers, and the current stack (Python, vector store, local embedding model) does not run there either. Plan: R1 on Streamlit Community Cloud; keep the core logic in a framework-independent package behind a simple API, so a Cloudflare-hosted frontend remains possible later.
- Groq's free tier is rate-limited; the product must handle rate-limit errors cleanly.

## 13. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A wrong limit/deadline is acted on | High (compliance) | Fail closed, quote verification, reviewed facts, clear disclaimer, published accuracy |
| Stale circular shown as current | High | Registry-driven supersession, gate "0 stale" |
| Extraction misses table content (e.g. MCC 1520) | High | Re-extract and audit tables; completeness report |
| LLM-only review is not independent | Medium | Deterministic quote matching plus manual sampling |
| Single maintainer / limited time | Medium | Small R1, strict gates, documented processes |
| Free-tier limits and outages | Medium | Fallback to passages, caching, graceful errors |
| Licensing/IP of NPCI content | Medium | Public-only content, attribution, disclaimer |
| Prompt injection from document text | Medium | Treat retrieved text as data; verifier on output |

## 14. Open decisions and assumptions

### Open decisions (owner)
| # | Decision | Recommendation |
|---|---|---|
| D1 | License (permission-to-fork vs open) | Decide before launch; AGPL-3.0 if "open but forks stay open" is the intent |
| D2 | Hosting path | Streamlit Cloud for R1; API-ready core for Cloudflare later |
| D3 | Compare feature in R1 or R2 | R2 |
| D4 | Monthly budget | ₹0 (free tiers) until stated |
| D5 | Weekly time and target date | State hours/week and a target launch date so the plan can be sized |
| D6 | Second reviewer for facts and gold set | Strongly recommended (one UPI-domain peer, even for a sample) |
| D7 | Store user questions for improvement? | No; only anonymous feedback |
| D8 | "Scope limited to PCs only" (Q10) | Read as "OCs only" |
| D9 | For an MCC no OC mentions, may the bot quote the general limit rule? | Only if an OC explicitly states the general rule covers unlisted codes; otherwise say "not mentioned" |
| D10 | Is an external MCC master list (code to name) in scope? | No for R1: names come only from OCs; revisit in R2 |

### Assumptions used for unanswered questions
Q4 success metrics, Q8 no upload in v1, Q25 clean minimal look, Q29 cloud LLM acceptable (public data only), Q30 Python, Q31 zero tolerance on limits/dates, Q32 ~120-question gold set, Q33 5-10 person pilot, Q34 current non-affiliation disclaimer, Q35 no raw question storage, Q36 MIT for now (see D1), Q37-Q38 solo part-time, Q40 no extra exclusions.

## Appendix A: Traceability (questionnaire to PRD)

| Q | Owner's answer (short) | Where it lands |
|---|---|---|
| 1 | Open-source working product, shared on LinkedIn for networking | Sections 1, 10, 11 |
| 2 | Developers, PMs, QA, business, companies (Razorpay, Juspay) | Section 3 |
| 3 | Quick summaries; what NPCI asked, when, with references | FR-2, FR-5 |
| 5 | Five sample questions | Section 5, gold set |
| 6 | UPI now; IMPS, RuPay, BBPS, RBI later | Section 4, FR-19 |
| 7 | Report what OC says only | Section 7 |
| 9 | English and Hinglish | FR-9 |
| 10 | Only what is in OCs | Section 7 |
| 11 | Almost all circulars | Section 9 |
| 12-14 | Manual now, automate later; mention Wayback; public only | Section 9, FR-17/18 |
| 15 | Claude first, owner second | Section 9 review protocol |
| 16-18 | Clarify first, then say data not available; quotes | FR-5, FR-7 |
| 19-21 | One-line verdict; history yes; compare yes | FR-10, FR-16, FR-15 |
| 22-24, 26 | Web/mobile; chat + OC browser; no login; reason feedback | FR-11, FR-12, FR-14 |
| 27-28 | Streamlit/Cloudflare; GitHub public; Groq and Ollama | Section 11, 12 |
| 39 | Correct limits, summary, references | Section 4 (R1) |

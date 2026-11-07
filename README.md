# NPCI UPI OC Assistant

An unofficial, open-source, educational RAG (Retrieval-Augmented Generation) chatbot for exploring NPCI's publicly available **UPI Operating Circulars (OCs)**. Ask natural-language questions like "What is the current UPI Lite wallet limit?" or "Summarize OC 220" and get grounded answers with OC citations.

> ⚠️ **Disclaimer:** This is an independent, educational project. It is **not affiliated with, endorsed by, or officially connected to the National Payments Corporation of India (NPCI)**. All circular content is sourced from NPCI's own publicly available website. This tool may be incomplete or outdated — always verify against official NPCI/URCS sources before making any compliance, product, or business decision.

## Features

- **Answers with proper references.** Every answer lists its sources with the exact quote and a reference a reader can look up, for example `UPI Consolidated Circular (18 Sep 2026), clause 14.24.4, p. 22` or `OC 185B (28 Aug 2025), p. 2`.
- **Limits and MCC lookups come from reviewed facts, not from a model.** A table of every limit kind (per transaction, collect, QR, 24-hour, monthly, credit received) with its OC and effective date; kinds no circular sets are shown as "No indexed OC sets this". Earlier and withdrawn limits are labelled.
- **Fail closed.** A model-written answer (summaries, definitions, general questions) is shown only if a checker verifies that every quote is in the cited circular, every number appears in a quote, and every OC it mentions exists in the evidence. Otherwise the user gets source passages, never an unverified answer.
- **Withdrawn and member-only circulars are known.** OCs withdrawn by the UPI Consolidated Circular are flagged; OCs NPCI lists without a public PDF are reported as existing but not readable.
- **English and Hinglish**, clarifying buttons for ambiguous questions, refusals for out-of-scope and bank-specific questions, and anonymous 👍/👎 feedback with reasons (question text is sent only if the user agrees).
- **Pluggable LLM**: local Ollama (default), Groq, or none (limits and codes still work).
- Chat history stays in the browser session; nothing is stored on the server.

## Architecture

```
PDF (public circulars, kept locally)
  → python -m ingest.build         (extract → registry → chunks → facts + code scan → gates → index)
  → Data/registry.csv, facts.csv, code_mentions.csv, chunks.jsonl, chroma_db/
  → core/pipeline.py: router → evidence → writer → checker   (app.py is a thin Streamlit UI)
```

**Runtime (`core/`):** `router.py` (what is being asked), `evidence/` (facts, codes, documents, hybrid search), `writer.py` (deterministic builders and the model prompt), `checker.py` (verification), `pipeline.py`, `llm.py`, `phrases.py`, `reference.py`, `feedback.py`.

**Offline (`ingest/`):** `extract.py`, `headers.py`, `registry.py`, `chunk.py`, `patches.py`, `facts.py`, `codes.py`, `not_public.py`, `index.py`, `build.py`, `review.py`.

**Evaluation (`eval/`):** `gold_set.csv` with `run_eval.py` (answers), `retrieval_set.csv` with `run_retrieval.py` (search hit rate), `show.py` (print one answer).

Design documents: [`docs/PRD.md`](docs/PRD.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/FSD.md`](docs/FSD.md), [`docs/M2_PLAN.md`](docs/M2_PLAN.md). One-off utilities are in [`scripts/`](scripts/).

## Data Sourcing

Circular PDFs are public NPCI documents, collected either manually from NPCI's public website or from the Internet Archive's Wayback Machine (see `oc_scrapper/`), not by crawling npci.org.in directly. Raw PDFs are not included in this repository. The reviewed registry, the chunks, and the pre-built vector index (`Data/chroma_db/`) are committed, since that's all the deployed app needs to run.

## Setup

### 1. Environment

```bash
conda create -n npci-oc-tool python=3.11 -y
conda activate npci-oc-tool
pip install -r requirements.txt
```

System dependencies (for OCR, only needed if re-running extraction on scanned PDFs):

```bash
brew install tesseract poppler
```

### 2. Choose an LLM backend

Limits, MCC lookups and refusals are answered from reviewed facts in code and need **no** model. The model is used only for summaries, definitions and general questions, and its answer is shown only if the checker verifies its quotes and numbers. Set the backend with environment variables:

```bash
# Local, private, no key (default): install Ollama, then
ollama pull qwen3:8b
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen3:8b

# or Groq (cloud)
export LLM_PROVIDER=groq
export GROQ_API_KEY="your-key-here"

# or no model at all: facts-backed answers still work, other questions show source passages
export LLM_PROVIDER=none
```

Only facts a person has marked `human_verified` are served. While you are developing, `export ALLOW_UNVERIFIED_FACTS=1` also serves the auto-checked ones (the app then shows a warning).

## Running the Full Pipeline

Only needed if you're adding new circulars or changing extraction/chunking logic. If you're just running the app against the existing index, skip to **Running the App**.

```bash
pip install -r requirements-dev.txt      # includes pytest
python -m ingest.build                   # full build (extract → registry → chunk → gates → index)
python -m ingest.build --skip-index      # data only, no embedding model (fast)
python -m pytest -q tests                # unit tests
python -m eval.run_eval --no-llm         # gold set (answers that need no model)
python -m eval.run_retrieval             # search hit rate
```

How it works:
- PDFs go in `Data/raw_pdfs/upi/` (not in Git). New PDFs are added to `Data/registry.csv` as `drafted` rows; **review them** (title, date, OC number, supersession) and record corrections in `Data/review_log.csv`.
- The build **stops** if a gate fails (empty title or date, broken supersession reference, duplicate id, a readable document with no chunks). Warnings list unreadable source files.
- `Data/coverage_report.md` shows what is covered and the known gaps (including circulars cited by others but missing from the corpus); `Data/build_info.json` carries the build id.
- **Facts (limits)** live in `Data/facts.csv`. Each has an exact quote that the build checks against the circular text. Review them with `python -m ingest.review export`, mark the sheet, then `python -m ingest.review import <file> --reviewer "Your name"`; only `human_verified` facts are served.
- **Circulars NPCI lists but does not publish** (member-only): list them in a CSV (`oc_number,title,fy`) and run `python -m ingest.not_public <file.csv>`; the chatbot will say they exist but are not public.
- OCR can misread amounts and tables. Where that happened, a transcription from the page image is stored in `Data/manual_patches/<doc_id>.txt` (see `ingest/patches.py`).

| Change | What to run |
|---|---|
| Added new PDFs | `python -m ingest.build`, then review the new registry rows |
| Changed chunking/cleaning logic | `python -m ingest.build` |
| Changed embedding model | `python -m ingest.build` (edit `ingest/paths.py`) |
| Only changed `app.py` (UI/logic) | Nothing, just restart the app |

## Running the App

```bash
# with the env vars from step 2 exported
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`). The sidebar shows the build id, how recent the circulars are, and the model in use.

The answering code lives in `core/` (`router.py`, `evidence/`, `writer.py`, `checker.py`, `pipeline.py`). Check it against the gold set with `python -m eval.run_eval` (add `--no-llm` to test only the model-free paths); `python -m eval.show "your question"` prints one answer.

## Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub (the `.gitignore` excludes `raw_pdfs/`, `extracted/`, and local chat history — only the pre-built index is committed).
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub repo, set the main file to `app.py`.
3. Under **Advanced settings → Secrets**, add (cloud hosting must use Groq — it can't run a local Ollama model):
   ```toml
   LLM_PROVIDER = "groq"
   GROQ_API_KEY = "your-key-here"
   ```
4. Deploy.

**Known limitation:** Streamlit Community Cloud's free tier uses an ephemeral filesystem — in-app chat history (`Data/chat_history.json`) resets on redeploy/restart. Feedback submitted via the Google Form integration persists externally and is unaffected.

## Feedback

Every assistant response has 👍/👎 buttons with an optional comment box. Feedback is logged to a Google Sheet via a Google Form submission (no billing/API key required for this feature).

## License

MIT — see [LICENSE](LICENSE).

## Contributing

This is a community, open-source project. Contributions of newly collected OCs (added to `Data/manifest.csv` with corresponding PDFs — collected manually, in line with NPCI's `robots.txt`), bug fixes, and feature improvements are welcome via pull request.

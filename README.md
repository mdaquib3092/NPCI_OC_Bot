# NPCI UPI OC Assistant

An unofficial, open-source, educational RAG (Retrieval-Augmented Generation) chatbot for exploring NPCI's publicly available **UPI Operating Circulars (OCs)**. Ask natural-language questions like "What is the current UPI Lite wallet limit?" or "Summarize OC 220" and get grounded answers with OC citations.

> ⚠️ **Disclaimer:** This is an independent, educational project. It is **not affiliated with, endorsed by, or officially connected to the National Payments Corporation of India (NPCI)**. All circular content is sourced from NPCI's own publicly available website. This tool may be incomplete or outdated — always verify against official NPCI/URCS sources before making any compliance, product, or business decision.

## Features

- **Hybrid retrieval** — BM25 keyword search + dense vector search fused with Reciprocal Rank Fusion (`hybrid_search.py`), so identifier-dense text (e.g. `OC 181B`, `MCC 7407`, `P2PM`) and paraphrased/conceptual queries both retrieve well
- **Pluggable LLM backend** — run against **Groq** (cloud) or a local **Ollama** model, selected via `LLM_PROVIDER` in `config.py`. Ollama keeps everything on-device (privacy) with no API key or rate limits
- LLM-generated summaries and Q&A, grounded only in retrieved context
- **Number-fidelity guard** (`number_guard.py`) — flags any figure or currency symbol in an answer that doesn't match the source text, to catch misstated compliance limits
- OC-number-aware retrieval (e.g. "summarize OC 220" fetches the full circular, not just top-k chunks)
- Domain acronym/term routing (UDIR, ODR, AFA, TPAP, P2PM, UPI Lite, AutoPay, …) mapped to the defining OC families in `config.py`, incl. supersession-chain awareness so "current limit" queries surface the latest circular
- "List all OCs in \<year\>" structured metadata queries
- Multi-conversation chat sidebar with persistent history
- File attach (PDF/DOCX) — the uploaded document is used as extra context for that question
- 👍/👎 feedback with optional comments, logged to Google Sheets

## Architecture

```
PDF (manually collected)
  → generate_manifest.py → extract.py → chunk.py → embed.py   (offline pipeline)
  → Data/chroma_db/ (vector index) + Data/chunks.jsonl (BM25 source)
  → app.py  (Streamlit chatbot: hybrid retrieval + LLM generation)
```

**Core (runtime):**

| Module | Purpose |
|---|---|
| `app.py` | Streamlit chatbot UI — hybrid retrieval, acronym/OC routing, generation |
| `config.py` | Central config: LLM backend selection, acronym→OC map, model lists |
| `hybrid_search.py` | BM25 + vector retrieval fused with Reciprocal Rank Fusion |
| `number_guard.py` | Post-generation check that figures/currencies match the source |

**Offline pipeline (rebuild the index):**

| Script | Purpose |
|---|---|
| `generate_manifest.py` | Scans `Data/raw_pdfs/` and builds `Data/manifest.csv` (OC number, FY, category) |
| `extract.py` | Extracts text from each PDF (reusing OCR cache from `scripts/ocr_pdf.py` for scanned docs) |
| `chunk.py` | Splits text into overlapping chunks, strips administrative boilerplate |
| `embed.py` | Embeds chunks (sentence-transformers) into a persistent ChromaDB index |
| `rebuild_corpus.py` | One-command runner for the four steps above, with duplicate detection |

**Evaluation:**

| Script | Purpose |
|---|---|
| `eval_retrieval.py` | Retrieval hit-rate + answer-faithfulness against `eval_test_set.csv` |
| `eval_ab_hybrid.py` | A/B compares pure-vector vs hybrid retrieval |
| `build_regression_set.py` | Turns 👎 feedback exports into regression-test candidates |

One-off maintenance/debug utilities live in [`scripts/`](scripts/).

## Data Sourcing

Circular PDFs are **manually downloaded** from NPCI's public website (not scraped), out of respect for NPCI's `robots.txt`, which disallows automated crawling by unnamed/custom bots. Raw PDFs are not included in this repository — only the pre-built vector index (`Data/chroma_db/`) is committed, since that's all the deployed app needs to run.

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

The backend is set by `LLM_PROVIDER` in `config.py` (override with an env var). Pick one:

**Option A — Groq (cloud, fast):** sign up at [console.groq.com](https://console.groq.com), create an API key, then:

```bash
export LLM_PROVIDER=groq
export GROQ_API_KEY="your-key-here"
```

The free tier is rate-limited (8,000 tokens/minute); use a paid tier for sustained traffic.

**Option B — Ollama (local, private, no key, no rate limits):** install [Ollama](https://ollama.com), pull a model, then:

```bash
ollama pull qwen3:14b          # or qwen3:8b for less RAM
export LLM_PROVIDER=ollama     # this is the default
export OLLAMA_MODEL=qwen3:14b  # optional; matches config.py default
```

Retrieval always runs locally (sentence-transformers + ChromaDB); only answer generation uses the selected backend.

## Running the Full Pipeline

Only needed if you're adding new circulars or changing extraction/chunking logic. If you're just running the app against the existing index, skip to **Running the App**.

```bash
# 1. Build the manifest (OC number, title, date, category) from raw_pdfs/
python generate_manifest.py

# 2. Extract text from each PDF (OCR fallback for scanned documents)
python extract.py

# 3. Chunk text into overlapping segments, stripping boilerplate
python chunk.py

# 4. Embed chunks into a searchable ChromaDB index
python embed.py

# 5. (Optional) Evaluate retrieval accuracy against eval_test_set.csv
python eval_retrieval.py
```

**When to re-run which step:**

| Change | Steps to re-run |
|---|---|
| Added new PDFs | 1 → 2 → 3 → 4 |
| Changed chunking/cleaning logic | 3 → 4 |
| Changed embedding model | 4 |
| Only changed `app.py` (UI/logic) | None — just restart the app |

## Running the App

```bash
# with the backend env vars from step 2 already exported
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`). The active backend and model are shown in the sidebar under **⚙️ Settings & info**.

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

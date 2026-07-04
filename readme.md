# NPCI UPI OC Assistant

An unofficial, open-source, educational RAG (Retrieval-Augmented Generation) chatbot for exploring NPCI's publicly available **UPI Operating Circulars (OCs)**. Ask natural-language questions like "What is the current UPI Lite wallet limit?" or "Summarize OC 220" and get grounded answers with OC citations.

> ⚠️ **Disclaimer:** This is an independent, educational project. It is **not affiliated with, endorsed by, or officially connected to the National Payments Corporation of India (NPCI)**. All circular content is sourced from NPCI's own publicly available website. This tool may be incomplete or outdated — always verify against official NPCI/URCS sources before making any compliance, product, or business decision.

## Features

- Semantic search over indexed UPI Operating Circulars
- LLM-generated summaries and Q&A, grounded only in retrieved context (no hallucination by design)
- OC-number-aware retrieval (e.g. "summarize OC 220" fetches the full circular, not just top-k chunks)
- Domain acronym recognition (UDIR, ODR, AFA, TPAP, etc.)
- "List all OCs in \<year\>" structured metadata queries
- Multi-conversation chat sidebar with persistent history
- File attach (PDF/DOCX) support via native Streamlit chat input
- 👍/👎 feedback with optional comments, logged to Google Sheets
- Selectable LLM model (Groq free tier)

## Architecture

```
PDF (manually collected) → extract.py → chunk.py → embed.py → app.py (Streamlit chatbot)
```

| Script | Purpose |
|---|---|
| `generate_manifest.py` | Scans `Data/raw_pdfs/` and builds `Data/manifest.csv` (OC number, title, date, category) |
| `extract.py` | Extracts text from each PDF (with OCR fallback for scanned documents) |
| `chunk.py` | Splits text into overlapping chunks, strips administrative boilerplate |
| `embed.py` | Embeds chunks (sentence-transformers) into a persistent ChromaDB index |
| `app.py` | Streamlit chatbot UI — retrieval + Groq LLM generation |
| `eval_retrieval.py` | Measures retrieval hit-rate against a golden test set |
| `inspect_oc.py` | Debug tool to inspect indexed content for a specific OC number |

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

### 2. Get a free Groq API key

Sign up at [console.groq.com](https://console.groq.com) and create an API key.

```bash
export GROQ_API_KEY="your-key-here"
```

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
export GROQ_API_KEY="your-key-here"
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

## Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub (the `.gitignore` excludes `raw_pdfs/`, `extracted/`, and local chat history — only the pre-built index is committed).
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub repo, set the main file to `app.py`.
3. Under **Advanced settings → Secrets**, add:
   ```toml
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

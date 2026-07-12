"""
Phase 5 (v2): Chatbot-style app for NPCI UPI OC search + summarization.

Reads:  Data/chroma_db/  (built by embed.py)
Uses:   Groq API (free tier) for answer generation

Two retrieval modes, auto-detected from the query:
1. "Summary of OC 76" / "explain OC 220" -> fetch ALL chunks for that OC
   number and ask the LLM to summarize them.
2. "What is the current UPI Lite limit?" -> semantic search across all
   chunks, retrieve top-k, ask the LLM to answer grounded in those chunks
   and cite OC numbers.

Setup:
    1. Get a free API key from https://console.groq.com
    2. Set it as an environment variable before running:
         export GROQ_API_KEY="your-key-here"
    3. streamlit run app.py

Run:
    streamlit run app.py
"""

import json
import os
import re
import uuid
from datetime import datetime

import chromadb
import requests
import streamlit as st
from chromadb.utils import embedding_functions
from groq import Groq
from openai import OpenAI  # OpenAI-compatible client — used for the local Ollama backend

from number_guard import check_numbers, check_currency_symbols
from config import (
    ACRONYM_TO_OC,
    GROQ_MODEL,
    AVAILABLE_MODELS,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_MODELS,
)
from hybrid_search import HybridSearcher

# Resolve which model list + default apply for the active backend.
if LLM_PROVIDER == "ollama":
    ACTIVE_MODELS = OLLAMA_MODELS
    DEFAULT_MODEL = OLLAMA_MODEL
else:
    ACTIVE_MODELS = AVAILABLE_MODELS
    DEFAULT_MODEL = GROQ_MODEL

CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
CHAT_HISTORY_PATH = os.path.join("Data", "chat_history.json")

# Google Forms feedback submission (no API key/billing needed — this is a
# plain HTTP POST to the form's public submission endpoint)
FEEDBACK_FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSdwb6PqtjVbBNRnBZqmzhF6rA4MztuvrideAgnxBFv39WBfHA/formResponse"
)
FEEDBACK_ENTRY_IDS = {
    "session_id": "entry.2058716435",
    "question": "entry.1688293492",
    "answer": "entry.1835707990",
    "feedback": "entry.2108472519",
    "comment": "entry.1008379228",
}


def submit_feedback(session_id: str, question: str, answer: str, feedback: str, comment: str = ""):
    """POST feedback to the Google Form, which auto-populates the linked Sheet."""
    payload = {
        FEEDBACK_ENTRY_IDS["session_id"]: session_id,
        FEEDBACK_ENTRY_IDS["question"]: question,
        FEEDBACK_ENTRY_IDS["answer"]: answer,
        FEEDBACK_ENTRY_IDS["feedback"]: feedback,
        FEEDBACK_ENTRY_IDS["comment"]: comment,
    }
    try:
        requests.post(FEEDBACK_FORM_URL, data=payload, timeout=5)
        return True
    except requests.RequestException:
        return False


@st.dialog("Add feedback")
def feedback_dialog(session_id: str, question: str, answer: str, feedback_label: str):
    st.write(f"You're submitting: **{feedback_label}**")
    comment = st.text_area("Anything you'd like to add? (optional)", key="feedback_comment_box")
    if st.button("Submit feedback", type="primary"):
        submit_feedback(session_id, question, answer, feedback_label, comment)
        st.toast("Thanks for the feedback!")
        st.rerun()

st.set_page_config(page_title="NPCI UPI OC Assistant", page_icon="🔍", layout="centered")

CUSTOM_CSS = """
<style>
/* Overall app background */
.stApp {
    background-color: #FAFAF8;
}

/* Chat message bubbles */
[data-testid="stChatMessage"] {
    padding: 14px 18px;
    border-radius: 16px;
    margin-bottom: 10px;
    max-width: 100%;
}

/* Hide default avatar emojis for a cleaner, minimal look */
[data-testid*="Avatar"] {
    display: none !important;
}
[data-testid="stChatMessage"] > div:first-child {
    display: none !important;
}
[data-testid="stChatMessage"]:has(> div > [data-testid="stChatMessageAvatarUser"]) {
    background-color: #E8EDFB;
    margin-left: auto;
    max-width: 75%;
}
[data-testid="stChatMessage"]:has(> div > [data-testid="stChatMessageAvatarAssistant"]) {
    background-color: #FFFFFF;
    border: 1px solid #EDEDE8;
    margin-right: auto;
    max-width: 75%;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background-color: #F5F4F0;
    border-right: 1px solid #E8E7E1;
}

/* Recent-chat list — small, muted text like Claude's sidebar */
[data-testid="stSidebar"] button {
    text-align: left !important;
    justify-content: flex-start !important;
    background-color: transparent;
    border: none;
    font-size: 0.82rem;
    color: #6B6B66 !important;
    font-weight: 400;
    padding: 6px 10px;
}
[data-testid="stSidebar"] button:hover {
    background-color: #EAE9E3;
    border-radius: 8px;
    color: #2D2A26 !important;
}

/* (Popover CSS removed — using Streamlit's native chat_input file attach instead) */

/* "New chat" primary button — accent color */
[data-testid="stSidebar"] button:first-of-type {
    background-color: #2D2A26;
    color: white !important;
    border-radius: 10px;
    font-weight: 500;
}
[data-testid="stSidebar"] button:first-of-type:hover {
    background-color: #44403A;
}

/* Title area */
h1 {
    font-size: 1.6rem !important;
}

/* Chat input box */
[data-testid="stChatInput"] textarea {
    border-radius: 12px;
}

/* Attach ("+") button — kept in normal document flow, directly above
   chat_input, since Streamlit doesn't support truly inline buttons within
   chat_input itself. */

/* Sources expander — subtle, small text */
[data-testid="stExpander"] {
    font-size: 0.85rem;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

SYSTEM_PROMPT = """You are an assistant that answers questions about NPCI UPI \
Operating Circulars (OCs) using ONLY the excerpts provided in the context below.

Rules:
- Answer only from the provided context. If the answer isn't in the context, \
say so clearly — do not guess or use outside knowledge.
- CRITICAL — NUMBERS MUST BE COPIED EXACTLY: When stating any amount, limit, \
percentage, or date, copy it character-for-character from the source text. \
Never recalculate, round, reformat, or convert a numeric value, and never \
change a currency symbol (₹ stays ₹ — do not write $ or €). If you are not \
completely certain of an exact figure, quote the surrounding sentence \
verbatim instead of restating just the number.
- IGNORE administrative boilerplate entirely: salutations ("Dear Sir/Madam", \
"Dear Members"), addressee lines ("All Members", "All Member Banks"), \
"Subject:" lines, letterhead/reference numbers, signature blocks ("Yours \
faithfully", "Regards", "Authorized Signatory", designations). Extract and \
synthesize ONLY the substantive policy/rule content — limits, deadlines, \
procedures, obligations.
- Always cite the OC number(s) you are drawing from, e.g. "(OC 220)".
- If multiple OCs address the same topic, prefer the most recent one, but \
mention the earlier ones too if relevant (e.g. "OC 88 originally set this at \
X; OC 220 later revised it to Y").
- Summarize and paraphrase in your own words rather than copying long \
passages verbatim from the context — EXCEPT for exact numbers, amounts, and \
dates, which must always match the source precisely as stated above.
- The context below is authoritative and current, regardless of any dates \
mentioned in it (including dates like 2025 or 2026). Never refuse to answer \
or express doubt about a circular's existence because its date seems "in \
the future" relative to your own training — the context provided is the \
ground truth for this task, not your training data.
- Keep answers concise and well-structured (use bullet points for lists of \
key points).
- End with a brief reminder that this is based on publicly available \
circulars only and should be verified against official NPCI/URCS sources.
"""


def load_all_sessions():
    if not os.path.isfile(CHAT_HISTORY_PATH):
        return {}
    try:
        with open(CHAT_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_all_sessions(sessions):
    os.makedirs(os.path.dirname(CHAT_HISTORY_PATH), exist_ok=True)
    with open(CHAT_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


def make_session_title(first_message: str) -> str:
    title = first_message.strip().replace("\n", " ")
    return title[:50] + ("..." if len(title) > 50 else "")


@st.cache_resource
def load_collection():
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL_NAME
    )
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)


@st.cache_resource
def load_llm_client():
    """Return an LLM client for the active backend, or None if unconfigured.

    Both backends expose the same OpenAI-style `.chat.completions.create()`
    interface, so downstream code (context_is_relevant / generate_answer) is
    provider-agnostic apart from a couple of provider-specific request params.
    """
    if LLM_PROVIDER == "ollama":
        # Ollama's OpenAI-compatible endpoint ignores the API key, but the SDK
        # requires a non-empty value.
        return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("GROQ_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        return None
    return Groq(api_key=api_key)


def extract_oc_number_from_query(query: str) -> str:
    """Detect an explicit OC or circular number reference in the user's query,
    e.g. 'OC 76', 'OC-220', 'circular 120', 'circular no. 185A'."""
    patterns = [
        r"\bOC[\s\-]?0*(\d+[A-Z]?)\b",
        r"\bCircular[\s\-]?No\.?[\s\-]?0*(\d+[A-Z]?)\b",
        r"\bCircular[\s\-]?0*(\d+[A-Z]?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


# Domain acronyms/terms whose full meaning embeddings don't always capture
# well — map them directly to the OC number(s) that define them. Values are
# imported from config.py.



def _acronym_pattern(term: str) -> str:
    """Word-boundary pattern for a term; allow flexible whitespace/hyphens
    between words so 'upi lite' also matches 'UPI-LITE' / 'UPI  Lite'."""
    parts = [re.escape(p) for p in term.split()]
    return r"\b" + r"[\s\-]+".join(parts) + r"\b"


def extract_acronym_ocs(query: str) -> list:
    """Return the OC-number list for the most specific acronym/term matched in
    the query. Longest key first, so 'upi lite' wins over a shorter overlapping
    key rather than a generic one grabbing it. Empty list if nothing matches."""
    lower = query.lower()
    for term in sorted(ACRONYM_TO_OC, key=len, reverse=True):
        if re.search(_acronym_pattern(term), lower):
            return ACRONYM_TO_OC[term]
    return []


# Generic "what is the P2P/P2M limit" queries often don't surface OC 120 or
# OC 181/181B within semantic top-k (chain-expansion only helps if one of
# those is ALREADY retrieved) — so directly route these to OC 120, which
# holds the actual default Rs 1,00,000 P2P/P2M limit in its Annexure A.
LIMIT_KEYWORD_TO_OC = {
    # 120 = per-transaction standardised limit (Rs 1,00,000, Annexure A);
    # 181B = CURRENT 24-hr P2P count/cumulative limit (50 txns). The earlier
    # OC 181 (25 txns) is deliberately excluded — including the superseded
    # figure alongside the current one makes the LLM cite the stale number.
    ("p2p", "limit"): ["120", "181B"],
    ("p2m", "limit"): ["120"],
    ("peer to peer", "limit"): ["120", "181B"],
}


def extract_limit_keyword_ocs(query: str) -> list:
    lower = query.lower()
    for keywords, ocs in LIMIT_KEYWORD_TO_OC.items():
        if all(kw in lower for kw in keywords):
            return ocs
    return []


def detect_listing_year(query: str) -> str:
    """Detect 'list all OCs in <year>' style queries — these need a full
    metadata scan, not semantic top-k search."""
    lower = query.lower()
    if any(word in lower for word in ["list", "all oc", "how many", "which oc"]):
        year_match = re.search(r"\b(20\d{2})\b", query)
        if year_match:
            return year_match.group(1)
    return ""


def list_ocs_by_year(collection, year: str):
    """Full scan of all indexed chunks, deduped by OC number, filtered by year
    appearing in the date field.

    NOTE: previously filtered with where={"category": "UPI"} — but no chunk
    in this corpus ever has category == "UPI" (categories are things like
    "limits", "disputes", "product", etc., or "uncategorised"). That filter
    silently excluded the entire corpus. Removed — no category filter needed
    since every document here is already UPI-related.
    """
    all_data = collection.get(limit=100000)
    seen = {}
    for meta in all_data.get("metadatas", []):
        oc = meta.get("oc_number", "")
        date = meta.get("date", "")
        if year in date and oc not in seen:
            seen[oc] = meta.get("title", "")
    return seen


def retrieve_by_oc_number(collection, oc_numbers, limit: int = 50, max_chunks: int = 40):
    """Fetch all chunks for one OC number or a family of them.

    Accepts a single OC string or a list (ordered most-current/authoritative
    first). Chunks are sorted by that priority order and then by chunk index,
    so each document reads in order and the latest circular comes first.
    Total chunks are capped (max_chunks) so a multi-OC family fetch can't blow
    the LLM token budget — the most-current OC's chunks survive the cap first.
    ChromaDB's .get() does not guarantee ordering, hence the explicit sort."""
    if isinstance(oc_numbers, str):
        oc_numbers = [oc_numbers]
    if not oc_numbers:
        return [], []

    where = (
        {"oc_number": oc_numbers[0]}
        if len(oc_numbers) == 1
        else {"oc_number": {"$in": oc_numbers}}
    )
    results = collection.get(where=where, limit=limit * len(oc_numbers))
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    ids = results.get("ids", [])

    priority = {oc: i for i, oc in enumerate(oc_numbers)}

    def sort_key(item):
        _doc, meta, _id = item
        oc = meta.get("oc_number", "")
        # chunk_id format is "{oc_number}_{index}" — sort by the numeric index
        try:
            idx = int(_id.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            idx = 0
        return (priority.get(oc, len(oc_numbers)), idx)

    combined = sorted(zip(docs, metas, ids), key=sort_key)[:max_chunks]
    docs = [c[0] for c in combined]
    metas = [c[1] for c in combined]
    return docs, metas


DISTANCE_THRESHOLD = 0.8  # cosine distance cutoff — chunks weaker than this are dropped

# Upper bound on how many chunks get concatenated into the LLM context.
# Keeps the prompt within the token budget (esp. Groq free-tier TPM limits)
# even when a full forced OC is merged with semantic results.
MAX_CONTEXT_CHUNKS = 24


# Known supersession chains — when semantic search surfaces ANY member of
# one of these chains, we inject the missing members (especially the
# latest) so "what is the CURRENT limit" queries don't stop at an older,
# superseded circular just because it embedded closer to the query.
SUPERSESSION_CHAINS = [
    ["82", "127", "185", "185A", "185B"],
    ["76", "76A", "76B", "76C"],
    ["138", "138A", "138B", "169", "169A"],
    ["151", "151A"],
    ["184", "184A", "184B"],
    ["181", "181A", "181B"],
    ["70", "72", "192"],
    ["115", "115A", "115B", "115C", "115D", "115E"],
    ["141", "141B", "141D"],
    ["163", "163A"],
    ["193", "193A", "193B", "193C"],
    ["201", "201A", "201B"],
    ["208", "208A", "208B", "208C"],
]
_CHAIN_LOOKUP = {oc: chain for chain in SUPERSESSION_CHAINS for oc in chain}


def expand_with_chain(collection, docs, metas, max_extra: int = 4):
    """If any retrieved chunk's oc_number is part of a known supersession
    chain, fetch one representative chunk for each OTHER member of that
    chain (that isn't already present) and append it to the results."""
    present_ocs = {m.get("oc_number", "") for m in metas}
    chains_hit = {
        tuple(_CHAIN_LOOKUP[oc]) for oc in present_ocs if oc in _CHAIN_LOOKUP
    }
    if not chains_hit:
        return docs, metas

    missing = []
    for chain in chains_hit:
        for oc in chain:
            if oc not in present_ocs:
                missing.append(oc)
                present_ocs.add(oc)  # avoid adding the same oc twice

    added = 0
    for oc in missing:
        if added >= max_extra:
            break
        result = collection.get(where={"oc_number": oc}, limit=1)
        if result.get("documents"):
            docs = list(docs) + [result["documents"][0]]
            metas = list(metas) + [result["metadatas"][0]]
            added += 1

    return docs, metas


@st.cache_resource
def load_hybrid_searcher():
    return HybridSearcher()


def retrieve_semantic(collection, query: str, n_results: int = 10):
    """Retrieve top chunks using hybrid search (BM25 + Vector RRF) fused ranking."""
    searcher = load_hybrid_searcher()
    docs, metas = searcher.search(collection, query, top_k=n_results)
    if not docs:
        return [], []
    docs, metas = expand_with_chain(collection, list(docs), list(metas))
    return docs, metas


def build_context(docs, metas) -> str:
    parts = []
    for doc, meta in zip(docs, metas):
        oc = meta.get("oc_number", "N/A")
        title = meta.get("title", "")
        supersedes = meta.get("supersedes", "")
        superseded_by = meta.get("superseded_by", "")
        header = f"[OC {oc} — {title}"
        if supersedes:
            header += f" | supersedes: OC {supersedes}"
        if superseded_by:
            header += f" | superseded_by: OC {superseded_by} (this OC is NOT the latest)"
        header += "]"
        parts.append(f"{header}\n{doc}")
    return "\n\n---\n\n".join(parts)


# Thinking/reasoning suppression: local reasoning models (e.g. qwen3) emit a
# hidden <think>…</think> block that would otherwise consume the token budget
# (starving short-max_tokens calls) and leak into the visible answer. Append a
# suppression hint for Ollama and strip any residual block as a safety net.
_THINK_SUFFIX = " /no_think" if LLM_PROVIDER == "ollama" else ""


def _provider_extra() -> dict:
    """Provider-specific request params. Groq's gpt-oss models need
    reasoning_effort=low so hidden reasoning doesn't eat the token budget;
    Ollama's OpenAI endpoint doesn't accept that param."""
    if LLM_PROVIDER == "groq":
        return {"extra_body": {"reasoning_effort": "low"}}
    return {}


def strip_think(text: str) -> str:
    if not text:
        return text
    # remove complete <think>...</think> blocks and any unterminated leader
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def context_is_relevant(client, query: str, context: str, model: str = DEFAULT_MODEL) -> bool:
    """Quick self-check: does the retrieved context actually contain
    information needed to answer the question? Catches cases that pass the
    distance threshold numerically but aren't genuinely on-topic.

    Biased toward "relevant" (fail open) unless the model gives an
    unambiguous negative — a false "not relevant" is worse UX than
    occasionally letting a borderline case through to generation, since the
    main SYSTEM_PROMPT already instructs the model to say so if it can't
    answer from context.
    """
    check_prompt = (
        "You will see a QUESTION and some CONTEXT excerpts from NPCI circulars. "
        "Decide if the context contains information that substantively "
        "addresses the question (not just administrative/header text). "
        "Respond with ONLY the single word YES or NO as your final answer, "
        "with no other text before or after it.\n\n"
        f"QUESTION: {query}\n\nCONTEXT:\n{context[:3000]}" + _THINK_SUFFIX
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": check_prompt}],
            temperature=0,
            max_tokens=200,  # headroom for reasoning models that emit hidden tokens
            **_provider_extra(),
        )
        reply = strip_think(response.choices[0].message.content or "").strip().upper()

        if "YES" in reply:
            return True
        if "NO" in reply:
            return False
        # Ambiguous/empty reply — default to relevant rather than blocking
        return True
    except Exception:
        return True  # fail open — don't block the answer if the check itself errors


def clean_llm_html(text: str) -> str:
    """Some models occasionally emit raw HTML tags (e.g. <br>) when formatting
    lists — Streamlit's markdown doesn't render these by default, so they'd
    show up as literal text. Convert the common ones to proper line breaks."""
    if not text:
        return text
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p\s*>", "\n", text, flags=re.IGNORECASE)
    return text


def generate_answer(client, query: str, context: str, history, model: str = DEFAULT_MODEL):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # include prior turns for conversational follow-ups
    for turn in history[-6:]:
        messages.append(turn)
    messages.append(
        {
            "role": "user",
            "content": f"Context from NPCI circulars:\n\n{context}\n\nQuestion: {query}"
            + _THINK_SUFFIX,
        }
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,  # was 0.2 — numeric/factual answers should not be sampled
            max_tokens=800,
            **_provider_extra(),
        )
        answer = clean_llm_html(strip_think(response.choices[0].message.content))

        # Number-hallucination guard: flag any figure in the answer that
        # doesn't actually appear in the retrieved source context (e.g. the
        # model restating "₹10,000" as "₹2,10,000"), and separately flag any
        # currency symbol swap (e.g. "₹" becoming "€") which check_numbers
        # alone can miss since it strips symbols before comparing digits.
        unverified = check_numbers(answer, context)
        currency_issues = check_currency_symbols(answer, context)

        if unverified or currency_issues:
            warning_parts = []
            if unverified:
                warning_parts.append(f"figures not matched in source: {', '.join(unverified)}")
            if currency_issues:
                warning_parts.append("; ".join(currency_issues))
            answer += (
                f"\n\n⚠️ **Unverified content:** {' | '.join(warning_parts)} — "
                f"please cross-check against the official OC document before "
                f"relying on this."
            )
        return answer
    except Exception as e:
        error_str = str(e)
        if LLM_PROVIDER == "ollama" and (
            "Connection" in error_str or "refused" in error_str.lower() or "not found" in error_str.lower()
        ):
            return (
                f"⚠️ Couldn't reach the local Ollama model `{model}` at "
                f"{OLLAMA_BASE_URL}. Make sure Ollama is running (`ollama serve`) "
                f"and the model is pulled (`ollama pull {model}`)."
            )
        if "model_permission_blocked" in error_str or "403" in error_str:
            return (
                f"⚠️ The model `{model}` is blocked on your Groq account. "
                f"Enable it at https://console.groq.com/settings/limits, or "
                f"switch to a different model in the sidebar under "
                f"'⚙️ Settings & info'."
            )
        if "rate_limit" in error_str.lower() or "429" in error_str:
            return (
                "⚠️ Rate limit reached on the Groq free tier. Please wait a "
                "moment and try again."
            )
        return f"⚠️ Something went wrong generating the answer: {error_str[:300]}"


def main():
    if not os.path.isdir(CHROMA_DIR):
        st.error("No index found. Run `python embed.py` first.")
        return

    collection = load_collection()
    llm_client = load_llm_client()

    if llm_client is None:
        # Only reachable on the Groq backend without a key (Ollama needs none).
        st.warning(
            "GROQ_API_KEY not set. Get a free key from https://console.groq.com "
            "and run:\n\n`export GROQ_API_KEY=\"your-key-here\"`\n\n"
            "then restart the app. Showing raw search results for now."
        )

    # ---- Load all sessions from disk once per app run ----
    if "all_sessions" not in st.session_state:
        st.session_state.all_sessions = load_all_sessions()

    if "current_session_id" not in st.session_state:
        if st.session_state.all_sessions:
            # open the most recently updated session by default
            most_recent = max(
                st.session_state.all_sessions.items(),
                key=lambda kv: kv[1].get("updated_at", ""),
            )
            st.session_state.current_session_id = most_recent[0]
        else:
            new_id = str(uuid.uuid4())
            st.session_state.all_sessions[new_id] = {
                "title": "New chat",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "display_history": [],  # list of [role, content, sources]
                "llm_history": [],      # list of {"role":..., "content":...} for LLM context
            }
            st.session_state.current_session_id = new_id

    session_id = st.session_state.current_session_id
    session = st.session_state.all_sessions[session_id]

    # ---- Sidebar: conversation list + new chat ----
    with st.sidebar:
        with st.expander("🔍 NPCI UPI OC Assistant", expanded=False):
            st.caption(
                "Unofficial, educational tool. Not affiliated with or endorsed "
                "by NPCI. Always verify against official NPCI/URCS sources "
                "before making compliance or production decisions."
            )

        if st.button("➕ New chat", use_container_width=True):
            new_id = str(uuid.uuid4())
            st.session_state.all_sessions[new_id] = {
                "title": "New chat",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "display_history": [],
                "llm_history": [],
            }
            st.session_state.current_session_id = new_id
            save_all_sessions(st.session_state.all_sessions)
            st.rerun()

        st.markdown("---")
        st.caption("Recent chats")

        sorted_sessions = sorted(
            st.session_state.all_sessions.items(),
            key=lambda kv: kv[1].get("updated_at", ""),
            reverse=True,
        )
        for sid, sdata in sorted_sessions:
            label = sdata.get("title", "New chat")
            is_current = sid == session_id
            if st.button(
                ("● " if is_current else "") + label,
                key=f"session_{sid}",
                use_container_width=True,
            ):
                st.session_state.current_session_id = sid
                st.rerun()

        st.markdown("---")

        with st.expander("⚙️ Settings & info"):
            st.write(
                "Ask natural questions about NPCI UPI Operating Circulars. "
                "For a full document summary, mention the OC number directly "
                "(e.g. 'summarize OC 220')."
            )
            if (
                "selected_model" not in st.session_state
                or st.session_state.selected_model not in ACTIVE_MODELS
            ):
                st.session_state.selected_model = DEFAULT_MODEL
            st.session_state.selected_model = st.selectbox(
                "Model",
                options=list(ACTIVE_MODELS.keys()),
                format_func=lambda m: ACTIVE_MODELS[m],
                index=list(ACTIVE_MODELS.keys()).index(st.session_state.selected_model),
            )
            st.caption(f"Backend: **{LLM_PROVIDER}**")
            st.write(f"**Indexed chunks:** {collection.count()}")
            if st.button("🗑️ Delete this chat"):
                del st.session_state.all_sessions[session_id]
                save_all_sessions(st.session_state.all_sessions)
                if "current_session_id" in st.session_state:
                    del st.session_state["current_session_id"]
                st.rerun()

        with st.expander("📄 Terms & Conditions"):
            st.markdown(
                """
**Unofficial, educational tool.** This assistant is an independent, \
open-source project. It is **not affiliated with, endorsed by, or \
officially connected to the National Payments Corporation of India \
(NPCI)** in any way.

**Data source.** All circular content indexed by this tool is sourced \
from NPCI's own publicly available website \
([npci.org.in](https://www.npci.org.in)). Circulars are Operating \
Circulars (OCs) that NPCI has published in the public domain for its \
member banks, PSPs, and TPAPs. No content is sourced from paywalled, \
member-only, or restricted portals (e.g. URCS).

**No warranty of accuracy or completeness.** The corpus may be \
incomplete, outdated, or contain extraction errors (e.g. from OCR on \
scanned documents). This tool does not guarantee that all published \
circulars are indexed, or that indexed content reflects the most \
current version of a circular.

**Not a substitute for official verification.** Before making any \
compliance, product, or business decision, always verify directly \
against NPCI's official website or the URCS portal, or consult your \
organization's compliance team.

**No liability.** The creator(s) of this tool accept no liability for \
decisions made based on its output. Use at your own discretion.

**Attribution to NPCI.** NPCI is the source and rights-holder of all \
underlying circular content referenced by this tool. This tool merely \
indexes and summarizes publicly available material for educational \
and research convenience.
                """
            )

    # ---- Welcome message for empty/new chats ----
    if not session["display_history"]:
        st.markdown(
            """
### 👋 Welcome to the NPCI UPI OC Assistant

I'm your assistant for exploring NPCI's publicly available **UPI Operating Circulars (OCs)**. Ask me things like:

- **"What is the current UPI Lite wallet limit?"**
- **"Summary of OC 220"**
- **"What is UDIR?"**
- **"List of OCs in 2025"**

I'll answer using the indexed circulars and always cite the OC number I'm drawing from. You can also attach a circular PDF/DOCX using the 📎 icon in the input box below.

*Unofficial, educational tool — always verify against official NPCI/URCS sources.*
            """
        )

    # ---- Render past turns of the current session ----
    for idx, (role, content, sources) in enumerate(session["display_history"]):
        with st.chat_message(role):
            st.markdown(content)
            if sources:
                with st.expander("Sources"):
                    for s in sources:
                        if isinstance(s, dict):
                            st.markdown(f"**OC {s['oc']}** — {s['title']}")
                            st.caption(s["excerpt"])
                        else:
                            st.caption(s)  # backward-compat for older sessions
            if role == "assistant":
                prev_question = (
                    session["display_history"][idx - 1][1] if idx > 0 else ""
                )
                fb_col1, fb_col2, _ = st.columns([1, 1, 10])
                with fb_col1:
                    if st.button("👍", key=f"fb_up_{session_id}_{idx}"):
                        feedback_dialog(session_id, prev_question, content, "👍 Helpful")
                with fb_col2:
                    if st.button("👎", key=f"fb_down_{session_id}_{idx}"):
                        feedback_dialog(session_id, prev_question, content, "👎 Not helpful")

    # ---- Chat input with native file attach (paperclip icon inside the
    # input box itself — requires Streamlit >= 1.41.0) ----
    chat_value = st.chat_input(
        "Ask about UPI circulars — e.g. 'Summary of OC 76' or 'current UPI Lite limit'",
        accept_file=True,
        file_type=["pdf", "docx"],
    )

    query = None
    uploaded_file = None
    if chat_value:
        query = chat_value.text
        if chat_value.files:
            uploaded_file = chat_value.files[0]
            st.session_state.pending_upload = uploaded_file

    if query:
        with st.chat_message("user"):
            st.markdown(query)
        session["display_history"].append(("user", query, None))

        # Auto-title the session from the first message
        if session["title"] == "New chat":
            session["title"] = make_session_title(query)

        listing_year = detect_listing_year(query)

        explicit_oc = extract_oc_number_from_query(query)
        if explicit_oc:
            target_ocs = [explicit_oc]
        else:
            target_ocs = extract_acronym_ocs(query)

        if listing_year:
            with st.spinner("Scanning full corpus..."):
                oc_map = list_ocs_by_year(collection, listing_year)
            if oc_map:
                lines = [f"- **OC {oc}** — {title}" for oc, title in sorted(oc_map.items())]
                answer = (
                    f"Found {len(oc_map)} circular(s) with '{listing_year}' in the date "
                    f"field, based on a full scan of the indexed corpus:\n\n" + "\n".join(lines)
                )
            else:
                answer = (
                    f"No circulars found with '{listing_year}' in the date field in the "
                    f"indexed corpus. Note: dates are auto-extracted from filenames and may "
                    f"be incomplete or missing for some circulars — this is not a guarantee "
                    f"that no such circular exists."
                )
            sources = []
            with st.chat_message("assistant"):
                st.markdown(answer)
            session["display_history"].append(("assistant", answer, sources))
            session["updated_at"] = datetime.now().isoformat()
            save_all_sessions(st.session_state.all_sessions)
            return

        with st.chat_message("assistant"):
            thinking_placeholder = st.empty()
            thinking_placeholder.markdown("_Thinking..._")

            if target_ocs:
                docs, metas = retrieve_by_oc_number(collection, target_ocs)
                if not docs:
                    docs, metas = retrieve_semantic(collection, query)
            else:
                docs, metas = retrieve_semantic(collection, query)

            # Generic "P2P/P2M limit" queries need OC 120's Annexure A — the
            # standardised-limits TABLE (e.g. Rs 1,00,000 per P2P transaction).
            # That table lives in ONE specific chunk, so fetching a single
            # arbitrary chunk (or skipping because some other chunk of 120 was
            # already retrieved) misses it, and the LLM then anchors on an
            # unrelated figure (e.g. the Rs 2,000 QR-share-&-pay sub-limit).
            # Fetch the FULL forced OC(s) and place them FIRST so the limits
            # table survives the context cap, then append the semantic results
            # (deduped) for the surrounding detail (24-hr limits, exclusions).
            force_ocs = extract_limit_keyword_ocs(query)
            if force_ocs:
                f_docs, f_metas = retrieve_by_oc_number(collection, force_ocs)
                seen = set(f_docs)
                merged_docs = list(f_docs)
                merged_metas = list(f_metas)
                for d, m in zip(docs, metas):
                    if d not in seen:
                        seen.add(d)
                        merged_docs.append(d)
                        merged_metas.append(m)
                docs, metas = merged_docs[:MAX_CONTEXT_CHUNKS], merged_metas[:MAX_CONTEXT_CHUNKS]

            if not docs:
                answer = "I couldn't find any relevant circulars for this question in the indexed corpus."
                sources = []
            else:
                context = build_context(docs, metas)
                seen_ocs = set()
                sources = []
                for doc, m in zip(docs, metas):
                    oc = m.get("oc_number", "N/A")
                    if oc in seen_ocs:
                        continue
                    seen_ocs.add(oc)
                    excerpt = doc.strip().replace("\n", " ")[:220]
                    sources.append(
                        {
                            "oc": oc,
                            "title": m.get("title", ""),
                            "excerpt": excerpt + ("..." if len(doc.strip()) > 220 else ""),
                        }
                    )

                if llm_client:
                    selected_model = st.session_state.get("selected_model", DEFAULT_MODEL)
                    if context_is_relevant(llm_client, query, context, model=selected_model):
                        answer = generate_answer(
                            llm_client,
                            query,
                            context,
                            session["llm_history"],
                            model=selected_model,
                        )
                        session["llm_history"].append({"role": "user", "content": query})
                        session["llm_history"].append({"role": "assistant", "content": answer})
                    else:
                        answer = (
                            "I found some circulars that came up in search, but on review "
                            "they don't substantively address this question. I don't have "
                            "a reliable answer for this in the indexed corpus — please "
                            "check the official NPCI/URCS sources directly."
                        )
                        sources = []
                else:
                    answer = "**Relevant excerpts (LLM not configured):**\n\n" + "\n\n".join(
                        f"**OC {m.get('oc_number')}** — {m.get('title')}\n\n{d[:400]}..."
                        for d, m in zip(docs, metas)
                    )

            thinking_placeholder.markdown(answer)
            if sources:
                with st.expander("Sources"):
                    for s in sources:
                        if isinstance(s, dict):
                            st.markdown(f"**OC {s['oc']}** — {s['title']}")
                            st.caption(s["excerpt"])
                        else:
                            st.caption(s)

        session["display_history"].append(("assistant", answer, sources))
        session["updated_at"] = datetime.now().isoformat()
        save_all_sessions(st.session_state.all_sessions)


if __name__ == "__main__":
    main()
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

CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
GROQ_MODEL = "openai/gpt-oss-20b"  # fast, free-tier friendly (llama-3.1-8b-instant is deprecated)
AVAILABLE_MODELS = {
    "openai/gpt-oss-20b": "GPT-OSS 20B (fast, recommended default)",
    "openai/gpt-oss-120b": "GPT-OSS 120B (more capable, slower)",
}
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
passages verbatim from the context.
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
def load_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)


def extract_oc_number_from_query(query: str) -> str:
    """Detect an explicit OC number reference in the user's query, e.g. 'OC 76', 'OC-220'."""
    match = re.search(r"\bOC[\s\-]?0*(\d+[A-Z]?)\b", query, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return ""


# Domain acronyms whose full meaning embeddings don't always capture well —
# map them directly to the OC number that defines them.
ACRONYM_TO_OC = {
    "udir": "165",
    "odr": "145",
    "afa": "151",
    "tpap": "159",
}


def extract_acronym_oc(query: str) -> str:
    lower = query.lower()
    for acronym, oc in ACRONYM_TO_OC.items():
        if re.search(rf"\b{acronym}\b", lower):
            return oc
    return ""


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
    appearing in the date field."""
    all_data = collection.get(where={"category": "UPI"}, limit=100000)
    seen = {}
    for meta in all_data.get("metadatas", []):
        oc = meta.get("oc_number", "")
        date = meta.get("date", "")
        if year in date and oc not in seen:
            seen[oc] = meta.get("title", "")
    return seen


def retrieve_by_oc_number(collection, oc_number: str, limit: int = 50):
    """Fetch all chunks belonging to a specific OC number."""
    results = collection.get(where={"oc_number": oc_number}, limit=limit)
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    return docs, metas


def retrieve_semantic(collection, query: str, n_results: int = 6):
    results = collection.query(
        query_texts=[query], n_results=n_results, where={"category": "UPI"}
    )
    return results["documents"][0], results["metadatas"][0]


def build_context(docs, metas) -> str:
    parts = []
    for doc, meta in zip(docs, metas):
        oc = meta.get("oc_number", "N/A")
        title = meta.get("title", "")
        parts.append(f"[OC {oc} — {title}]\n{doc}")
    return "\n\n---\n\n".join(parts)


def generate_answer(client, query: str, context: str, history, model: str = GROQ_MODEL):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # include prior turns for conversational follow-ups
    for turn in history[-6:]:
        messages.append(turn)
    messages.append(
        {
            "role": "user",
            "content": f"Context from NPCI circulars:\n\n{context}\n\nQuestion: {query}",
        }
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=800,
    )
    return response.choices[0].message.content


def main():
    if not os.path.isdir(CHROMA_DIR):
        st.error("No index found. Run `python embed.py` first.")
        return

    collection = load_collection()
    groq_client = load_groq_client()

    if groq_client is None:
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
            if "selected_model" not in st.session_state:
                st.session_state.selected_model = GROQ_MODEL
            st.session_state.selected_model = st.selectbox(
                "Model",
                options=list(AVAILABLE_MODELS.keys()),
                format_func=lambda m: AVAILABLE_MODELS[m],
                index=list(AVAILABLE_MODELS.keys()).index(st.session_state.selected_model),
            )
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
                        st.caption(s)
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

        oc_number = extract_oc_number_from_query(query)
        if not oc_number:
            oc_number = extract_acronym_oc(query)

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

            if oc_number:
                docs, metas = retrieve_by_oc_number(collection, oc_number)
                if not docs:
                    docs, metas = retrieve_semantic(collection, query)
            else:
                docs, metas = retrieve_semantic(collection, query)

            if not docs:
                answer = "I couldn't find any relevant circulars for this question in the indexed corpus."
                sources = []
            else:
                context = build_context(docs, metas)
                sources = sorted(
                    {f"OC {m.get('oc_number', 'N/A')} — {m.get('title', '')}" for m in metas}
                )

                if groq_client:
                    answer = generate_answer(
                        groq_client,
                        query,
                        context,
                        session["llm_history"],
                        model=st.session_state.get("selected_model", GROQ_MODEL),
                    )
                    session["llm_history"].append({"role": "user", "content": query})
                    session["llm_history"].append({"role": "assistant", "content": answer})
                else:
                    answer = "**Relevant excerpts (LLM not configured):**\n\n" + "\n\n".join(
                        f"**OC {m.get('oc_number')}** — {m.get('title')}\n\n{d[:400]}..."
                        for d, m in zip(docs, metas)
                    )

            thinking_placeholder.markdown(answer)
            if sources:
                with st.expander("Sources"):
                    for s in sources:
                        st.caption(s)

        session["display_history"].append(("assistant", answer, sources))
        session["updated_at"] = datetime.now().isoformat()
        save_all_sessions(st.session_state.all_sessions)


if __name__ == "__main__":
    main()
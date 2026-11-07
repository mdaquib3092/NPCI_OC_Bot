"""NPCI UPI OC Assistant: Streamlit interface over core.pipeline.

All answering logic lives in core/. This file collects the question, calls the pipeline and shows
the validated answer: verdict, status, table, earlier or withdrawn rules, obligations, sources with
exact quotes and references, feedback. Chat history stays in the user's browser session only.

    streamlit run app.py
"""

import os
import uuid

import streamlit as st

# Streamlit Cloud keeps secrets in st.secrets; the core reads the environment.
try:
    for _k in ("LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_MODEL", "ALLOW_UNVERIFIED_FACTS", "FEEDBACK_URL"):
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

from core import feedback as fb  # noqa: E402
from core import phrases as ph  # noqa: E402
from core.config import Settings  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402

st.set_page_config(page_title="NPCI UPI OC Assistant", page_icon="🔍", layout="centered")

STATUS = {
    "verified": ("Verified from source", "#1a7f37"),
    "partially_verified": ("Passages only: not verified as an answer", "#9a6700"),
    "unverified_facts": ("Facts not yet human-verified (development)", "#9a6700"),
    "not_found": ("Not found in the indexed circulars", "#6e7781"),
}
EXAMPLES = ["What is the P2P limit?", "Limit for MCC 5944", "Summarize OC 226A", "What is UPI Circle?",
            "AutoPay interoperability kya hai?"]

st.markdown(
    """<style>
    .verdict {font-size: 1.12rem; font-weight: 600; line-height: 1.5; margin-bottom: .25rem;}
    .badge {display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: .78rem; color: #fff;}
    @media (max-width: 640px) {.verdict {font-size: 1rem;}}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline(settings=Settings.from_env())


def show_table(a: dict) -> None:
    lang = a["language"]
    rows = []
    for r in a["table"]:
        if r["cells"]:
            value, note = "  \n".join(c["text"] for c in r["cells"]), r["note"]
        else:
            value, note = (r["note"] or ph.t(lang, "no_oc_sets_this")), ""
        rows.append({"Limit": r["label"], "Value": value, "Notes": note})
    st.table(rows)


def show_answer(a: dict) -> None:
    label, colour = STATUS.get(a["status"], (a["status"], "#6e7781"))
    st.markdown(f"<div class='verdict'>{a['verdict']}</div>"
                f"<span class='badge' style='background:{colour}'>{label}</span>", unsafe_allow_html=True)
    if a["table"]:
        show_table(a)
    for o in a["obligations"]:
        st.markdown(f"- **{o['who']}**: {o['what']}" + (f" _(by {o['by']})_" if o["by"] else ""))
    for line in a["details"]:
        st.markdown(f"- {line['text']}")
    if a["earlier"]:
        with st.expander(f"Earlier or withdrawn rules ({len(a['earlier'])})"):
            for line in a["earlier"]:
                st.markdown(f"- {line['text']}")
    if a["notice"]:
        st.caption(a["notice"])
    if a["citations"]:
        with st.expander(f"Sources ({len(a['citations'])})"):
            for c in a["citations"]:
                st.markdown(f"**{c['reference'] or 'OC ' + c['oc_number']}**  \n{c['title']}")
                st.caption(f"“{c['quote']}”")
    meta = a["meta"]
    st.caption(f"Circulars indexed up to {meta.get('corpus_as_of', '')} · build {meta.get('build_id', '')} · "
               + ph.t(a["language"], "disclaimer"))


def feedback_widget(i: int, m: dict) -> None:
    if m.get("feedback_sent"):
        st.caption("Thanks for the feedback.")
        return
    c1, c2, _ = st.columns([1, 1, 8])
    if c1.button("👍", key=f"up_{i}"):
        m["pending_feedback"] = "👍"
    if c2.button("👎", key=f"down_{i}"):
        m["pending_feedback"] = "👎"
    if m.get("pending_feedback"):
        with st.form(key=f"fb_{i}"):
            reason = st.selectbox("What was wrong?" if m["pending_feedback"] == "👎" else "Anything to add?",
                                  [""] + fb.REASONS)
            comment = st.text_input("Comment (optional)")
            share = st.checkbox("Include my question and the answer text so the developer can look at it")
            if st.form_submit_button("Send feedback"):
                payload = fb.build_payload(st.session_state.session_id, m["pending_feedback"], reason, comment,
                                           m["a"], m["q"], share)
                fb.submit(payload)
                m["feedback_sent"] = True
                st.rerun()


def ask(question: str) -> None:
    ans = get_pipeline().answer(question).to_dict()
    st.session_state.messages.append({"q": question, "a": ans})


def main() -> None:
    pipeline = get_pipeline()
    s = pipeline.stores
    st.session_state.setdefault("messages", [])        # this browser session only; nothing is stored on the server
    st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])

    with st.sidebar:
        st.markdown("### NPCI UPI OC Assistant")
        st.caption("Unofficial, educational. Not affiliated with NPCI. Always verify with official NPCI sources.")
        if st.button("New chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        st.caption(f"Circulars indexed up to **{s.corpus_as_of}** · build `{s.build_id}`")
        st.caption(f"Model: {pipeline.settings.llm_provider} "
                   + (pipeline.settings.model if pipeline.llm.enabled else "(off: limits and codes still work)"))
        if pipeline.settings.allow_unverified_facts:
            st.warning("Development mode: facts are not human-verified.")
        with st.expander("About the data"):
            st.markdown("Answers come only from the indexed public NPCI UPI Operating Circulars and the UPI Consolidated "
                        "Circular. A few circulars are listed by NPCI as member-only: the assistant knows they exist but "
                        "cannot read them. Limits shown come from reviewed facts, each with its source quote.")

    st.title("NPCI UPI OC Assistant")
    if not st.session_state.messages:
        st.markdown("Ask about NPCI's UPI Operating Circulars, in English or Hinglish. For example:")
        cols = st.columns(2)
        for n, ex in enumerate(EXAMPLES):
            if cols[n % 2].button(ex, key=f"ex_{n}", use_container_width=True):
                st.session_state.pending = ex
                st.rerun()

    clicked = None
    for i, m in enumerate(st.session_state.messages):
        with st.chat_message("user"):
            st.markdown(m["q"])
        with st.chat_message("assistant"):
            show_answer(m["a"])
            if m["a"]["chips"] and i == len(st.session_state.messages) - 1:
                cols = st.columns(len(m["a"]["chips"]))
                for col, chip in zip(cols, m["a"]["chips"]):
                    if col.button(chip, key=f"chip_{i}_{chip}"):
                        clicked = chip
            feedback_widget(i, m)

    question = (st.chat_input("Ask about UPI circulars, e.g. 'P2P limit kya hai?' or 'Summary of OC 226A'")
                or clicked or st.session_state.pop("pending", None))
    if question:
        with st.spinner("Searching circulars..."):
            ask(question)
        st.rerun()


if __name__ == "__main__":
    main()

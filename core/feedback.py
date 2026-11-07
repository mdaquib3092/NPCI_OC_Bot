"""Anonymous feedback to a Google Form. The question and answer text are sent only if the user ticks the box."""

import os

REASONS = ["Wrong number", "Outdated circular", "Incomplete", "Unclear", "Other"]
DEFAULT_FORM = ("https://docs.google.com/forms/d/e/1FAIpQLSdwb6PqtjVbBNRnBZqmzhF6rA4MztuvrideAgnxBFv39WBfHA/formResponse")
ENTRY_IDS = {
    "session_id": "entry.2058716435", "question": "entry.1688293492", "answer": "entry.1835707990",
    "feedback": "entry.2108472519", "comment": "entry.1008379228",
}


def form_url() -> str:
    return os.environ.get("FEEDBACK_URL", DEFAULT_FORM)


def build_payload(session_id: str, rating: str, reason: str, comment: str, answer: dict,
                  question: str = "", share_text: bool = False) -> dict:
    """What gets sent. Without consent there is no question text and no answer text."""
    meta = f"[{answer.get('answer_type')}] build {answer.get('meta', {}).get('build_id', '')}"
    shown = f"{meta}\n{answer.get('verdict', '')}" if share_text else meta
    return {
        ENTRY_IDS["session_id"]: session_id,
        ENTRY_IDS["question"]: question if share_text else "(not shared)",
        ENTRY_IDS["answer"]: shown,
        ENTRY_IDS["feedback"]: f"{rating}: {reason}" if reason else rating,
        ENTRY_IDS["comment"]: comment or "",
    }


def submit(payload: dict, timeout: float = 5.0) -> bool:
    import requests

    try:
        requests.post(form_url(), data=payload, timeout=timeout)
        return True
    except requests.RequestException:
        return False

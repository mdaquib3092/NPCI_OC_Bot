"""Print an answer in plain text: python -m eval.show "question" """
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.pipeline import Pipeline  # noqa: E402


def render(a) -> str:
    out = [f"[{a.answer_type} | {a.status} | {a.meta.get('intent')}] {a.verdict}"]
    for r in a.table:
        vals = " / ".join(c.text for c in r.cells) if r.cells else r.note
        out.append(f"  - {r.label} [{r.status}]: {vals}")
        if r.cells and r.note and r.status not in ("no_oc_sets_this", "withdrawn"):
            out.append(f"      note: {r.note[:160]}")
    for l in a.details:
        out.append(f"  * {l.text}")
    for o in a.obligations:
        out.append(f"  > {o.who}: {o.what} (by {o.by or '-'})")
    for l in a.earlier:
        out.append(f"  ~ {l.text}")
    if a.chips:
        out.append("  chips: " + " | ".join(a.chips))
    if a.notice:
        out.append("  notice: " + a.notice)
    for c in a.citations:
        out.append(f"  [{c.id}] {c.reference or 'OC ' + c.oc_number}: \"{c.quote[:100]}\"")
    return "\n".join(out)


if __name__ == "__main__":
    p = Pipeline()
    for q in sys.argv[1:]:
        print("Q:", q)
        print(render(p.answer(q)), "\n")

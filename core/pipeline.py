"""question -> route -> evidence -> writer -> checker -> Answer.

    pipeline = Pipeline()
    answer = pipeline.answer("P2P limit kya hai?")

Everything that can go wrong ends in a safe answer (a refusal, a not-found message or
source passages); a model-written answer is shown only if the checker passes it.
"""

import time

from . import phrases as ph
from . import writer
from .answer import Answer
from .checker import check
from .config import Settings
from .evidence import facts as fev
from .evidence.documents import document_evidence
from .evidence.search import Searcher
from .llm import LLMClient, LLMError
from .router import route
from .stores import Stores


class Pipeline:
    def __init__(self, stores: Stores = None, llm: LLMClient = None, settings: Settings = None, searcher=None):
        self.settings = settings or (stores.settings if stores else Settings.from_env())
        self.stores = stores or Stores(self.settings)
        self.llm = llm or LLMClient(self.settings)
        self._searcher = searcher

    @property
    def searcher(self) -> Searcher:
        if self._searcher is None:
            self._searcher = Searcher(self.stores)
        return self._searcher

    # ------------------------------------------------------------------
    def answer(self, question: str, history: list = None) -> Answer:
        started = time.time()
        plan = route(question)
        ans = self._answer(plan)
        ans.meta["latency_ms"] = int((time.time() - started) * 1000)
        ans.meta["plan"] = {k: v for k, v in plan.__dict__.items() if v and k != "question"}
        return ans

    def _answer(self, plan) -> Answer:
        s = self.stores
        if plan.intent == "OUT_OF_SCOPE":
            return writer.refusal(s, plan, "scope")
        if plan.intent == "ADVICE":
            return writer.refusal(s, plan, "advice")
        if plan.intent == "BANK_SPECIFIC":
            return writer.refusal(s, plan, "bank")
        if plan.intent == "CLARIFY":
            return writer.clarify(s, plan)
        if plan.intent == "CODE_LOOKUP":
            ev = fev.code_evidence(s, plan)
            return self._checked_facts(plan, writer.code_answer(s, plan, ev))
        if plan.intent == "LIMIT":
            ev = fev.limit_evidence(s, plan)
            if ev is not None:
                return self._checked_facts(plan, writer.limit_answer(s, plan, ev))
            plan.intent = "GENERAL"          # no facts for this: fall through to search
            plan.term = plan.term or plan.question
        if plan.intent == "OC_LOOKUP":
            return self._oc_lookup(plan)
        return self._free_text(plan, self.searcher.search(plan.question))

    # ------------------------------------------------------------------
    def _checked_facts(self, plan, ans: Answer) -> Answer:
        """Facts-backed answers are built in code; the checker still verifies quotes and amounts."""
        sources = [(f["source_doc_id"], f["quote"]) for f in self.stores.all_facts]
        sources += [(m["source_doc_id"], m["quote"]) for m in self.stores.codes]
        sources += [(f["closed_by_doc_id"], f["closed_by_quote"]) for f in self.stores.all_facts if f.get("closed_by_doc_id")]
        reviewed = [f"{f['conditions']} {f['notes']}" for f in self.stores.all_facts]
        result = check(ans, sources, reviewed)
        ans.meta["checker"] = {"ok": result.ok, "reasons": result.reasons}
        if result.ok:
            return ans
        return writer.not_found(self.stores, plan)   # never show an unverified table

    def _oc_lookup(self, plan) -> Answer:
        rows = self.stores.find_oc(plan.oc_numbers[0])
        if not rows:
            return writer.oc_not_found(self.stores, plan, plan.oc_numbers[0])
        row = rows[0]
        if row["status"] == "not_public":
            return writer.not_public(self.stores, plan, row)
        pack = document_evidence(self.stores, row)
        if not pack.items:
            return writer.oc_not_found(self.stores, plan, plan.oc_numbers[0])
        ans = self._free_text(plan, pack)
        if row["status"] == "withdrawn":
            note = ph.t(plan.language, "oc_withdrawn", oc=row["oc_number"])
            ans.notice = (note + " " + ans.notice).strip()
        return ans

    def _free_text(self, plan, pack) -> Answer:
        s = self.stores
        if not pack.items:
            return writer.not_found(s, plan)
        if not self.llm.enabled:
            return writer.passages(s, plan, pack, "llm_down")
        sources = [(e.doc_id, e.text) for e in pack.items]
        feedback = ""
        for _attempt in range(2):                     # one regeneration, then fall back
            system, user = writer.llm_messages(plan, pack, feedback)
            try:
                data = self.llm.complete_json(system, user)
                ans = writer.answer_from_json(s, plan, pack, data)
            except LLMError as e:
                if e.kind in ("invalid_json",):
                    feedback = "the reply was not valid JSON"
                    continue
                return writer.passages(s, plan, pack, "llm_down")
            except ValueError as e:
                feedback = str(e)
                continue
            if ans.answer_type == "not_found":
                return ans
            writer.snap_quotes(ans, pack)
            result = check(ans, sources)
            ans.meta["checker"] = {"ok": result.ok, "reasons": result.reasons}
            ans.meta["model"] = s.settings.model
            if result.ok:
                return ans
            feedback = "; ".join(result.reasons[:4])
        fallback = writer.passages(s, plan, pack)
        fallback.meta["checker"] = {"ok": False, "reasons": [feedback]}
        return fallback

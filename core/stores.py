"""Loads the reviewed data once: registry, facts, code mentions, chunks, build info."""

import json
import os
import re
from collections import defaultdict

from ingest import codes as codes_mod
from ingest import facts as facts_mod
from ingest import paths, registry as registry_mod

from .config import Settings


class Stores:
    def __init__(self, settings: Settings = None, data_dir: str = None):
        self.settings = settings or Settings.from_env()
        d = data_dir or paths.DATA
        self.registry = registry_mod.load(os.path.join(d, "registry.csv"))
        self.by_doc = {r["doc_id"]: r for r in self.registry}
        self.all_facts = facts_mod.load(os.path.join(d, "facts.csv"))
        if self.settings.allow_unverified_facts:
            self.facts = list(self.all_facts)
        else:
            self.facts = facts_mod.servable(self.all_facts)
        self.facts_by_id = {f["fact_id"]: f for f in self.all_facts}
        self.codes = codes_mod.load(os.path.join(d, "code_mentions.csv"))
        self.chunks = []
        self.chunks_by_doc = defaultdict(list)
        chunks_path = os.path.join(d, "chunks.jsonl")
        if os.path.isfile(chunks_path):
            with open(chunks_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        c = json.loads(line)
                        self.chunks.append(c)
                        self.chunks_by_doc[c["doc_id"]].append(c)
        info_path = os.path.join(d, "build_info.json")
        self.build_info = json.load(open(info_path, encoding="utf-8")) if os.path.isfile(info_path) else {}

    # ------------------------------------------------------------------
    @property
    def build_id(self) -> str:
        return self.build_info.get("build_id", "")

    @property
    def corpus_as_of(self) -> str:
        return self.build_info.get("corpus_as_of", "")

    @property
    def unverified_facts_in_use(self) -> bool:
        return any(f["review_status"] != "human_verified" for f in self.facts)

    def find_oc(self, oc_number: str) -> list:
        """Registry rows for an OC number. UPI series first; other series only if no UPI row."""
        rows = [r for r in self.registry if r["oc_number"].upper() == oc_number.upper()]
        upi = [r for r in rows if r["series"] in ("UPI", "IMPS_UPI")]
        return upi or rows

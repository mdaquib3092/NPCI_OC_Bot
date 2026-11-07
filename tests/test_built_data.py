"""Checks on the committed build output; skipped if the data is not present."""
import json
import os

import pytest

from ingest import paths, registry

pytestmark = pytest.mark.skipif(not os.path.isfile(paths.REGISTRY_PATH), reason="registry not built")


def test_registry_passes_its_own_gate():
    errors = [i for i in registry.validate(registry.load()) if i[0] == "error"]
    assert errors == []


def test_every_chunk_has_registry_metadata():
    rows = {r["doc_id"]: r for r in registry.load()}
    with open(paths.CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            assert c["doc_id"] in rows
            assert c["title"] and c["status"]
            assert c["issue_date"] or "date_unknown_confirmed" in rows[c["doc_id"]]["needs_review"]

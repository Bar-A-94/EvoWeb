"""The paper's terms for a dataset row: request (not turn), backward (not regression), R<k> (not T<k>).

The generator prompts (*.js) are kept exactly as they were run, so their output uses the old terms;
assemble_dataset.py and audit_parts.py pass every row through paper_terms(). Only fields no model
reads are touched (keys, check kinds, graph ids, and the metadata prose listed in TEXT_FIELDS); the
requests and the judge's checks stay byte-identical. Idempotent.
"""

from __future__ import annotations

import re

KEYS = {"copied_from_turn": "copied_from_request", "introduced_in_turn": "introduced_in_request"}
VALUES = {"regression": "backward", "Regression": "Backward"}  # kind, task_category.subcategories
GRAPH_ID = re.compile(r"\bT(10|[1-9])\b")
TEXT_FIELDS = {"target_app_summary", "rule", "label", "what", "records_gist", "feature_rationale"}
# "turn" meaning a user request in that prose; the verb ("a tracker that turns ...") stays.
TEXT = [
    (re.compile(r"\bturn(s?) (?=\d)"), r"request\1 "),
    (re.compile(r"\b(four|nine|later|late) turn(s?)\b"), r"\1 request\2"),
]


def paper_terms(o, key: str | None = None):
    if isinstance(o, dict):
        return {KEYS.get(k, k): paper_terms(v, k) for k, v in o.items()}
    if isinstance(o, list):
        return [paper_terms(x, key) for x in o]
    if not isinstance(o, str):
        return o
    if key in ("kind", "subcategories"):
        return VALUES.get(o, o)
    if key in ("id", "from", "to"):
        return GRAPH_ID.sub(r"R\1", o)
    if key in TEXT_FIELDS:
        o = GRAPH_ID.sub(r"R\1", o)
        for pat, rep in TEXT:
            o = pat.sub(rep, o)
    return o

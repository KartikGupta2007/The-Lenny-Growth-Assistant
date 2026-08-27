"""Recognise an explicit request for an artifact.

Deliberate keyword matching, not an LLM classifier: it is predictable, free,
and a normal question must never accidentally become a 1,250-word essay.
"""

from __future__ import annotations

import re

from app.constants import ARTIFACT_HTML, ARTIFACT_MARKDOWN, ArtifactType

_ESSAY = re.compile(
    r"\b(ship\s*30|write\s+(me\s+)?(an?\s+)?(essay|post|article)|essay\s+about)\b",
    re.IGNORECASE,
)
_HTML = re.compile(
    r"\b(landing\s*page|html\s*(page|artifact)?|web\s*page|dashboard|"
    r"one[-\s]?pager|build\s+(me\s+)?a\s+page)\b",
    re.IGNORECASE,
)


def detect_artifact_request(question: str) -> ArtifactType | None:
    """Which artifact the question asks for, or None for a normal answer."""
    if _ESSAY.search(question):
        return ARTIFACT_MARKDOWN
    if _HTML.search(question):
        return ARTIFACT_HTML
    return None

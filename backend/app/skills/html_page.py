"""HTML/CSS artifact skill (PRD section 12).

Produces a self-contained HTML fragment. The output is sanitised before it is
stored or returned -- the model is asked for safe markup, never trusted to
produce it.
"""

from __future__ import annotations

from app.agent.prompts import build_evidence
from app.errors import ModelError
from app.models.base import Message, ModelProvider
from app.retrieval import RetrievedChunk

SYSTEM_PROMPT = """You build a single self-contained HTML fragment about \
product and growth, using only the evidence supplied, which comes from \
transcripts of Lenny's Podcast.

Output:
- One HTML fragment: a `<style>` block followed by the markup.
- No `<html>`, `<head>` or `<body>` wrapper, no markdown fence, no commentary.
- Style it with CSS in that `<style>` block, or inline `style` attributes.
- No JavaScript, no `<script>`, no event handler attributes, no external \
resources of any kind. They are stripped before rendering and will simply \
disappear.

Rules:
- Every claim must come from the evidence. Do not invent facts, quotes, \
guests or statistics.
- Attribute ideas to the guest who said them, by name."""


async def generate_html_page(
    provider: ModelProvider, brief: str, chunks: list[RetrievedChunk]
) -> str:
    """Build the fragment. Returns raw HTML -- the caller sanitises it."""
    prompt = (
        f"Evidence:\n\n{build_evidence(chunks)}\n\nBuild: {brief}"
    )
    html = await provider.generate(
        SYSTEM_PROMPT, [Message(role="user", content=prompt)]
    )
    # Models often fence code even when told not to.
    cleaned = html.strip().removeprefix("```html").removeprefix("```").removesuffix("```").strip()
    if "<" not in cleaned:
        raise ModelError("The artifact came back without any markup.")
    return cleaned

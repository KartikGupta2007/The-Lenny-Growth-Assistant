"""The grounding prompt and the evidence block handed to the model."""

from __future__ import annotations

from app.retrieval import RetrievedChunk

SYSTEM_PROMPT = """You answer questions about product and growth using only the \
evidence supplied below, which comes from transcripts of Lenny's Podcast.

Rules:
- Answer from the supplied evidence only. Do not use outside knowledge.
- Do not invent facts, quotes, guests, episodes, or URLs.
- Cite the evidence you used with its source number, like [1] or [2], when you \
make a factual claim.
- Say what the evidence does not cover rather than filling the gap. If it does \
not support an answer, say so plainly.
- Distinguish what a guest asserts from what is established.
- Be direct and practical. No preamble."""

# Returned verbatim when retrieval finds too little to work with. Deterministic
# on purpose: no model call, so no chance of an unsupported answer.
INSUFFICIENT_EVIDENCE_ANSWER = (
    "I don't have enough information in Lenny's Podcast transcripts to answer "
    "that confidently."
)


def build_evidence(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as numbered sources.

    Source numbers are 1-based and match the order of `Answer.sources`, so a
    [2] in the model's text maps to a source the backend owns. Database ids are
    left out -- the model has no use for them.
    """
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        lines = [f"[{number}]", f"Episode: {chunk.title}"]
        if chunk.guest:
            lines.append(f"Guest: {chunk.guest}")
        lines.append(f"Content:\n{chunk.content}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_user_message(question: str, chunks: list[RetrievedChunk]) -> str:
    """The question plus its evidence, as one turn."""
    return f"Evidence:\n\n{build_evidence(chunks)}\n\nQuestion: {question}"

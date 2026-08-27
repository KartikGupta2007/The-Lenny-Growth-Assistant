"""Ship 30 for 30 essay skill (PRD section 11).

Produces a ~1,250-word Markdown essay grounded in the retrieved transcripts.
"""

from __future__ import annotations

from app.agent.prompts import build_evidence
from app.errors import ModelError
from app.models.base import Message, ModelProvider
from app.retrieval import RetrievedChunk

TARGET_WORDS = 1250

SYSTEM_PROMPT = f"""You write Ship 30 for 30 style essays about product and \
growth, using only the evidence supplied, which comes from transcripts of \
Lenny's Podcast.

Structure:
- Open with a hook: one sharp sentence that earns the next one.
- Build one argument from start to finish, in Markdown.
- Use `##` headings to mark the turns in that argument.
- Use bullets only where a list genuinely reads better than prose.
- Use **bold** sparingly, for the ideas a skimmer must not miss.
- End with a section giving one specific action the reader can take this week.

Rules:
- About {TARGET_WORDS} words.
- Every claim must come from the evidence. Do not invent facts, quotes, \
guests, episodes or statistics.
- Attribute ideas to the guest who said them, by name.
- Where the evidence is thin, write less rather than filling the gap.
- Markdown only. No preamble, no meta-commentary about the essay."""


async def generate_ship30_essay(
    provider: ModelProvider, topic: str, chunks: list[RetrievedChunk]
) -> str:
    """Write the essay. Returns Markdown."""
    prompt = (
        f"Evidence:\n\n{build_evidence(chunks)}\n\n"
        f"Write the essay on: {topic}"
    )
    essay = await provider.generate(
        SYSTEM_PROMPT, [Message(role="user", content=prompt)]
    )
    if len(essay.split()) < 200:
        raise ModelError("The essay came back too short to be usable.")
    return essay

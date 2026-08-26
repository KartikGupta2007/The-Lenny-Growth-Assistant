"""Split a transcript into retrieval-sized chunks.

Approach: pack whole paragraphs into a chunk until it reaches the target size,
then carry the tail of that chunk into the next one so a passage split across
a boundary is still retrievable from either side. A paragraph longer than the
target on its own is split into overlapping windows -- one transcript in the
corpus has no paragraph breaks at all.

Words stand in for tokens. A real tokeniser would be more precise, but it
would also be another dependency for a bound that only needs to be roughly
right: chunks sit well inside the embedding model's context either way.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class TranscriptChunk:
    index: int
    text: str
    content_hash: str
    word_count: int


def chunk_transcript(
    text: str, *, target_words: int, overlap_words: int
) -> list[TranscriptChunk]:
    """Chunk `text`, preserving document order."""
    overlap = max(0, min(overlap_words, target_words - 1))
    pieces: list[str] = []
    buffer: list[str] = []
    carried = 0  # words at the head of `buffer` carried over from the last chunk

    def flush() -> None:
        nonlocal buffer, carried
        if len(buffer) <= carried:  # nothing new since the last chunk
            return
        pieces.append(" ".join(buffer))
        buffer = buffer[-overlap:] if overlap else []
        carried = len(buffer)

    for paragraph in PARAGRAPH_BREAK.split(text):
        words = paragraph.split()
        if not words:
            continue

        if len(words) > target_words:
            flush()
            buffer, carried = [], 0
            pieces.extend(_windows(words, target_words, overlap))
            continue

        if buffer and len(buffer) + len(words) > target_words:
            flush()
        buffer.extend(words)

    flush()

    return [
        TranscriptChunk(
            index=index,
            text=piece,
            content_hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
            word_count=len(piece.split()),
        )
        for index, piece in enumerate(pieces)
    ]


def _windows(words: list[str], size: int, overlap: int) -> list[str]:
    """Overlapping windows over one oversized paragraph.

    The last window is aligned to the end of the paragraph rather than stepped
    past it, which avoids a final sliver already contained in its predecessor.
    """
    step = max(1, size - overlap)
    out: list[str] = []
    start = 0
    while start < len(words):
        out.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
        start += step
    return out

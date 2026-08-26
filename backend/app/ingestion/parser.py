"""Read one transcript file: metadata, cleaned text, content hash."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import frontmatter

# `Casey Winters (00:12):` and bare `(01:19):` continuation markers.
SPEAKER_TIMESTAMP = re.compile(r"^(?P<speaker>[^\n(]{1,80}?)\s*\((?:\d{1,2}:){1,2}\d{2}\):", re.M)
BARE_TIMESTAMP = re.compile(r"^\((?:\d{1,2}:){1,2}\d{2}\):\s*", re.M)
BLANK_LINES = re.compile(r"\n{3,}")
TRAILING_SPACE = re.compile(r"[ \t]+$", re.M)

TRANSCRIPT_HEADING = "## Transcript"


class TranscriptError(Exception):
    """A transcript file could not be parsed."""


@dataclass(frozen=True)
class ParsedTranscript:
    source_path: str
    title: str
    guest: str | None
    source_url: str | None
    publish_date: date | None
    text: str
    # sha256 of the raw file, so any source edit changes it.
    content_hash: str


def parse_transcript(path: Path, source_path: str) -> ParsedTranscript:
    """Parse a transcript file.

    Raises TranscriptError for anything unreadable, so the caller can log it
    and carry on with the rest of the corpus.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TranscriptError(f"cannot read {source_path}: {exc}") from exc

    try:
        post = frontmatter.loads(raw)
    except Exception as exc:  # any YAML problem
        raise TranscriptError(f"malformed frontmatter in {source_path}: {exc}") from exc

    text = clean_text(post.content)
    if not text:
        raise TranscriptError(f"no transcript body in {source_path}")

    return ParsedTranscript(
        source_path=source_path,
        title=_title(post, source_path),
        guest=_clean_value(post.get("guest")),
        # A handful of episodes carry a Spotify link instead of a YouTube one.
        source_url=_clean_value(post.get("youtube_url"))
        or _clean_value(post.get("spotify_url")),
        publish_date=_publish_date(post.get("publish_date")),
        text=text,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def clean_text(body: str) -> str:
    """Normalise a transcript body without rewriting what was said.

    Drops the leading title/heading block, the timestamp markers that carry no
    meaning for retrieval, and inconsistent whitespace. Speaker names are kept
    -- who said something is part of the answer.
    """
    if TRANSCRIPT_HEADING in body:
        body = body.split(TRANSCRIPT_HEADING, 1)[1]

    body = body.replace(" ", " ").replace("\r\n", "\n")
    body = BARE_TIMESTAMP.sub("", body)
    body = SPEAKER_TIMESTAMP.sub(lambda m: f"{m.group('speaker').strip()}:", body)
    body = TRAILING_SPACE.sub("", body)
    body = BLANK_LINES.sub("\n\n", body)
    return body.strip()


def _title(post: frontmatter.Post, source_path: str) -> str:
    """Frontmatter title, else the `# ` heading, else the episode directory."""
    title = _clean_value(post.get("title"))
    if title:
        return title
    for line in post.content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(source_path).parent.name


def _clean_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _publish_date(value: object) -> date | None:
    """YAML usually parses the date for us; accept a string too."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None

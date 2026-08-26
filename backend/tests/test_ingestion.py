"""Ingestion: discovery, parsing, cleaning, chunking, incremental refresh.

Fixture transcripts, never the real repository -- the suite must not depend on
GitHub being up. Nothing here calls Ollama: embeddings are a later phase and
chunks are written with a NULL embedding.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db import models
from app.ingestion.chunker import chunk_transcript
from app.ingestion.loader import discover_transcripts
from app.ingestion.parser import TranscriptError, clean_text, parse_transcript
from app.ingestion.sync import ingest

TRANSCRIPT = """---
guest: Casey Winters
title: Why most product managers are unprepared
youtube_url: https://www.youtube.com/watch?v=WlRfyEpAKxw
publish_date: 2023-04-14
keywords:
- growth
- retention
---

# Why most product managers are unprepared

## Transcript

Casey Winters (00:00):
Retention is the single most important thing for growth.

Lenny (00:12):
Say more about that.

(02:22):
This episode is brought to you by a sponsor.

Casey Winters (03:50):
Cohort curves tell you whether the product is working.
"""


def write_transcript(root: Path, slug: str, body: str = TRANSCRIPT) -> Path:
    """Create episodes/<slug>/transcript.md under `root`."""
    path = root / "episodes" / slug / "transcript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def make_settings(**overrides: object) -> Settings:
    import os

    base: dict[str, object] = {
        "_env_file": None,
        "database_url": os.environ["DATABASE_URL"],
        "app_env": "test",
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_finds_every_transcript(self, tmp_path: Path) -> None:
        for slug in ("casey-winters", "brian-chesky"):
            write_transcript(tmp_path, slug)

        found = discover_transcripts(tmp_path)

        assert [p.parent.name for p in found] == ["brian-chesky", "casey-winters"]

    def test_order_is_stable(self, tmp_path: Path) -> None:
        """Chunk indexes and reruns depend on a deterministic order."""
        for slug in ("zoe", "adam", "mira"):
            write_transcript(tmp_path, slug)

        assert discover_transcripts(tmp_path) == discover_transcripts(tmp_path)

    def test_ignores_everything_that_is_not_a_transcript(
        self, tmp_path: Path
    ) -> None:
        """The repository also holds index/, scripts/ and READMEs."""
        write_transcript(tmp_path, "casey-winters")
        (tmp_path / "README.md").write_text("# repo")
        (tmp_path / "CLAUDE.md").write_text("# agent notes")
        (tmp_path / "index").mkdir()
        (tmp_path / "index" / "retention.md").write_text("# retention")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "fetch.sh").write_text("#!/bin/sh")
        (tmp_path / "episodes" / "casey-winters" / "notes.md").write_text("nope")

        found = discover_transcripts(tmp_path)

        assert [p.name for p in found] == ["transcript.md"]

    def test_empty_repository_yields_nothing(self, tmp_path: Path) -> None:
        assert discover_transcripts(tmp_path) == []


# ---------------------------------------------------------------------------
# Parsing and metadata
# ---------------------------------------------------------------------------


class TestParsing:
    def test_extracts_provenance(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "casey-winters")

        parsed = parse_transcript(path, "episodes/casey-winters/transcript.md")

        assert parsed.title == "Why most product managers are unprepared"
        assert parsed.guest == "Casey Winters"
        assert parsed.source_url == "https://www.youtube.com/watch?v=WlRfyEpAKxw"
        assert parsed.publish_date == date(2023, 4, 14)
        assert parsed.source_path == "episodes/casey-winters/transcript.md"

    def test_content_hash_is_the_sha256_of_the_file(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "casey-winters")

        parsed = parse_transcript(path, "episodes/casey-winters/transcript.md")

        expected = hashlib.sha256(TRANSCRIPT.encode()).hexdigest()
        assert parsed.content_hash == expected
        assert len(parsed.content_hash) == 64

    def test_content_hash_changes_with_the_source(self, tmp_path: Path) -> None:
        first = parse_transcript(
            write_transcript(tmp_path, "a"), "episodes/a/transcript.md"
        )
        second = parse_transcript(
            write_transcript(tmp_path, "b", TRANSCRIPT + "\nOne more line.\n"),
            "episodes/b/transcript.md",
        )

        assert first.content_hash != second.content_hash

    def test_missing_optional_metadata_is_none(self, tmp_path: Path) -> None:
        """Four episodes have no YouTube URL and three no publish date."""
        body = "---\nguest: Someone\ntitle: A talk\n---\n\n## Transcript\n\nHello there.\n"
        path = write_transcript(tmp_path, "sparse", body)

        parsed = parse_transcript(path, "episodes/sparse/transcript.md")

        assert parsed.source_url is None
        assert parsed.publish_date is None
        assert parsed.guest == "Someone"

    def test_spotify_url_is_used_when_there_is_no_youtube_url(
        self, tmp_path: Path
    ) -> None:
        body = (
            "---\nguest: G\ntitle: T\nspotify_url: https://open.spotify.com/x\n"
            "---\n\n## Transcript\n\nWords.\n"
        )
        path = write_transcript(tmp_path, "spotify", body)

        parsed = parse_transcript(path, "episodes/spotify/transcript.md")

        assert parsed.source_url == "https://open.spotify.com/x"

    def test_title_falls_back_to_the_heading(self, tmp_path: Path) -> None:
        """One episode has no title in its frontmatter."""
        body = "---\nguest: G\n---\n\n# Heading title\n\n## Transcript\n\nWords.\n"
        path = write_transcript(tmp_path, "untitled", body)

        parsed = parse_transcript(path, "episodes/untitled/transcript.md")

        assert parsed.title == "Heading title"

    def test_title_falls_back_to_the_directory(self, tmp_path: Path) -> None:
        body = "---\nguest: G\n---\n\n## Transcript\n\nWords.\n"
        path = write_transcript(tmp_path, "eoy-review", body)

        parsed = parse_transcript(path, "episodes/eoy-review/transcript.md")

        assert parsed.title == "eoy-review"

    def test_unparseable_date_is_dropped_not_guessed(self, tmp_path: Path) -> None:
        body = "---\nguest: G\ntitle: T\npublish_date: 'not a date'\n---\n\n## Transcript\n\nW.\n"
        path = write_transcript(tmp_path, "baddate", body)

        assert parse_transcript(path, "episodes/baddate/transcript.md").publish_date is None


class TestInvalidTranscripts:
    def test_empty_file_is_rejected(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "empty", "")

        with pytest.raises(TranscriptError, match="no transcript body"):
            parse_transcript(path, "episodes/empty/transcript.md")

    def test_frontmatter_with_no_body_is_rejected(self, tmp_path: Path) -> None:
        path = write_transcript(tmp_path, "headonly", "---\nguest: G\ntitle: T\n---\n")

        with pytest.raises(TranscriptError, match="no transcript body"):
            parse_transcript(path, "episodes/headonly/transcript.md")

    def test_malformed_frontmatter_is_rejected(self, tmp_path: Path) -> None:
        path = write_transcript(
            tmp_path, "broken", "---\nguest: [unclosed\n---\n\n## Transcript\n\nHi.\n"
        )

        with pytest.raises(TranscriptError):
            parse_transcript(path, "episodes/broken/transcript.md")

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TranscriptError, match="cannot read"):
            parse_transcript(tmp_path / "nope.md", "episodes/nope/transcript.md")

    def test_a_transcript_with_no_frontmatter_still_parses(
        self, tmp_path: Path
    ) -> None:
        """Body-only is degraded, not invalid."""
        path = write_transcript(tmp_path, "plain", "## Transcript\n\nJust words here.\n")

        parsed = parse_transcript(path, "episodes/plain/transcript.md")

        assert parsed.text == "Just words here."
        assert parsed.guest is None
        assert parsed.title == "plain"


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------


class TestCleaning:
    def test_drops_the_heading_block(self) -> None:
        cleaned = clean_text("# Episode title\n\n## Transcript\n\nThe body.")

        assert cleaned == "The body."

    def test_keeps_the_speaker_and_drops_the_timestamp(self) -> None:
        cleaned = clean_text("## Transcript\n\nCasey Winters (00:12):\nRetention matters.")

        assert cleaned == "Casey Winters:\nRetention matters."

    def test_handles_hour_length_timestamps(self) -> None:
        cleaned = clean_text("## Transcript\n\nLenny (01:02:03):\nStill going.")

        assert cleaned == "Lenny:\nStill going."

    def test_removes_bare_continuation_markers(self) -> None:
        cleaned = clean_text("## Transcript\n\n(02:22):\nA sponsor read.")

        assert cleaned == "A sponsor read."

    def test_collapses_excess_blank_lines(self) -> None:
        cleaned = clean_text("## Transcript\n\nOne.\n\n\n\n\nTwo.")

        assert cleaned == "One.\n\nTwo."

    def test_strips_trailing_whitespace_and_nbsp(self) -> None:
        cleaned = clean_text("## Transcript\n\nOne.   \nTwo three.")

        assert cleaned == "One.\nTwo three."

    def test_wording_is_preserved(self) -> None:
        """Cleaning normalises formatting; it must not rewrite what was said."""
        said = "Retention is the single most important thing for growth."
        cleaned = clean_text(f"## Transcript\n\nCasey Winters (00:00):\n{said}")

        assert said in cleaned

    def test_body_without_the_heading_is_kept(self) -> None:
        assert clean_text("Just a body.") == "Just a body."


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def words(count: int, token: str = "word") -> str:
    return " ".join(f"{token}{i}" for i in range(count))


class TestChunking:
    def test_short_text_is_one_chunk(self) -> None:
        chunks = chunk_transcript("A short transcript.", target_words=600, overlap_words=80)

        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].text == "A short transcript."
        assert chunks[0].word_count == 3

    def test_empty_text_yields_no_chunks(self) -> None:
        assert chunk_transcript("", target_words=600, overlap_words=80) == []
        assert chunk_transcript("   \n\n  ", target_words=600, overlap_words=80) == []

    def test_indexes_are_contiguous_and_ordered(self) -> None:
        text = "\n\n".join(words(50, f"p{n}_") for n in range(30))

        chunks = chunk_transcript(text, target_words=100, overlap_words=20)

        assert [c.index for c in chunks] == list(range(len(chunks)))
        assert len(chunks) > 1

    def test_document_order_is_preserved(self) -> None:
        paragraphs = [f"paragraph number {n} content" for n in range(40)]

        chunks = chunk_transcript("\n\n".join(paragraphs), target_words=20, overlap_words=5)

        joined = " ".join(c.text for c in chunks)
        positions = [joined.index(f"paragraph number {n} ") for n in range(40)]
        assert positions == sorted(positions)

    def test_consecutive_chunks_overlap(self) -> None:
        text = "\n\n".join(words(40, f"p{n}_") for n in range(20))

        chunks = chunk_transcript(text, target_words=100, overlap_words=25)

        assert len(chunks) > 2
        for previous, following in zip(chunks, chunks[1:]):
            tail = previous.text.split()[-25:]
            assert following.text.split()[:25] == tail

    def test_no_overlap_when_configured_to_zero(self) -> None:
        text = "\n\n".join(words(40, f"p{n}_") for n in range(10))

        chunks = chunk_transcript(text, target_words=100, overlap_words=0)

        seen = [w for c in chunks for w in c.text.split()]
        assert len(seen) == len(set(seen))

    def test_chunks_respect_the_target_size(self) -> None:
        text = "\n\n".join(words(70, f"p{n}_") for n in range(30))

        chunks = chunk_transcript(text, target_words=200, overlap_words=40)

        # A chunk may end slightly past the target to finish a paragraph.
        assert all(c.word_count <= 200 + 70 for c in chunks)
        assert all(c.word_count > 0 for c in chunks)

    def test_an_oversized_paragraph_is_split(self) -> None:
        """One transcript in the corpus has no paragraph breaks at all."""
        chunks = chunk_transcript(words(1000), target_words=300, overlap_words=50)

        assert len(chunks) > 1
        assert all(c.word_count <= 300 for c in chunks)
        assert chunks[-1].text.split()[-1] == "word999"

    def test_oversized_paragraph_windows_overlap(self) -> None:
        chunks = chunk_transcript(words(700), target_words=300, overlap_words=50)

        for previous, following in zip(chunks, chunks[1:]):
            assert set(previous.text.split()) & set(following.text.split())

    def test_no_chunk_is_wholly_contained_in_its_predecessor(self) -> None:
        """A trailing sliver would be a duplicate with a new index."""
        chunks = chunk_transcript(words(610), target_words=300, overlap_words=50)

        for previous, following in zip(chunks, chunks[1:]):
            assert not set(following.text.split()) <= set(previous.text.split())

    def test_no_empty_chunks(self) -> None:
        text = "One.\n\n\n\nTwo.\n\n   \n\nThree."

        chunks = chunk_transcript(text, target_words=5, overlap_words=1)

        assert all(c.text.strip() for c in chunks)

    def test_content_hash_is_per_chunk(self) -> None:
        chunks = chunk_transcript(words(500), target_words=100, overlap_words=0)

        hashes = [c.content_hash for c in chunks]
        assert len(set(hashes)) == len(hashes)
        assert all(len(h) == 64 for h in hashes)

    def test_chunking_is_deterministic(self) -> None:
        text = "\n\n".join(words(60, f"p{n}_") for n in range(25))

        first = chunk_transcript(text, target_words=200, overlap_words=40)
        second = chunk_transcript(text, target_words=200, overlap_words=40)

        assert [c.content_hash for c in first] == [c.content_hash for c in second]


# ---------------------------------------------------------------------------
# Incremental ingestion, against the database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ingestion_env(migrated_database: str, tmp_path: Path, monkeypatch):
    """A fake repository plus a session factory, cleaned up afterwards.

    sync_repository is stubbed so the suite never contacts GitHub.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        "app.ingestion.sync.sync_repository", lambda settings, force=False: repo
    )

    engine = create_async_engine(migrated_database, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def clear() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents"))

    await clear()
    try:
        yield repo, factory
    finally:
        await clear()
        await engine.dispose()


async def run_ingest(factory, **kwargs):
    return await ingest(make_settings(), session_factory=factory, **kwargs)


class TestIngestion:
    async def test_creates_documents_and_chunks(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        write_transcript(repo, "casey-winters")

        result = await run_ingest(factory)

        assert result.created == 1
        assert result.chunks_written >= 1
        async with factory() as session:
            document = (
                await session.execute(select(models.Document))
            ).scalar_one()
            assert document.source_path == "episodes/casey-winters/transcript.md"
            assert document.title == "Why most product managers are unprepared"
            assert document.guest == "Casey Winters"
            assert document.publish_date == date(2023, 4, 14)
            assert document.content_hash
            assert document.last_ingested_at is not None

    async def test_chunk_order_and_provenance(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        body = TRANSCRIPT.replace(
            "Cohort curves tell you whether the product is working.",
            "\n\n".join(words(200, f"p{n}_") for n in range(6)),
        )
        write_transcript(repo, "long-one", body)

        await run_ingest(factory)

        async with factory() as session:
            chunks = (
                (
                    await session.execute(
                        select(models.Chunk).order_by(models.Chunk.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
        assert len(chunks) > 1
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert all(c.content_hash for c in chunks)
        assert len({c.document_id for c in chunks}) == 1

    async def test_embeddings_are_left_null(self, ingestion_env) -> None:
        """Embedding generation is the next phase."""
        repo, factory = ingestion_env
        write_transcript(repo, "casey-winters")

        await run_ingest(factory)

        async with factory() as session:
            filled = (
                await session.execute(
                    select(func.count())
                    .select_from(models.Chunk)
                    .where(models.Chunk.embedding.isnot(None))
                )
            ).scalar_one()
        assert filled == 0

    async def test_unchanged_transcript_is_skipped(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        write_transcript(repo, "casey-winters")
        first = await run_ingest(factory)

        second = await run_ingest(factory)

        assert first.created == 1
        assert second.skipped == 1
        assert second.created == 0
        assert second.chunks_written == 0

    async def test_changed_transcript_is_reprocessed(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        write_transcript(repo, "casey-winters")
        await run_ingest(factory)
        async with factory() as session:
            before = (
                await session.execute(select(models.Document.content_hash))
            ).scalar_one()

        write_transcript(
            repo,
            "casey-winters",
            TRANSCRIPT.replace("Retention is", "Activation is"),
        )
        result = await run_ingest(factory)

        assert result.updated == 1
        assert result.created == 0
        async with factory() as session:
            document = (await session.execute(select(models.Document))).scalar_one()
            chunk_count = (
                await session.execute(select(func.count()).select_from(models.Chunk))
            ).scalar_one()
        assert document.content_hash != before
        assert chunk_count == result.chunks_written, "chunks are replaced, not appended"

    async def test_removed_transcript_is_cleaned_up(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        write_transcript(repo, "casey-winters")
        write_transcript(repo, "brian-chesky")
        await run_ingest(factory)

        (repo / "episodes" / "brian-chesky" / "transcript.md").unlink()
        result = await run_ingest(factory)

        assert result.removed == 1
        async with factory() as session:
            paths = (
                (await session.execute(select(models.Document.source_path)))
                .scalars()
                .all()
            )
            orphans = (
                await session.execute(
                    select(func.count())
                    .select_from(models.Chunk)
                    .where(
                        models.Chunk.document_id.notin_(select(models.Document.id))
                    )
                )
            ).scalar_one()
        assert paths == ["episodes/casey-winters/transcript.md"]
        assert orphans == 0, "chunks must not outlive their document"

    async def test_unreadable_transcript_does_not_stop_the_run(
        self, ingestion_env
    ) -> None:
        repo, factory = ingestion_env
        write_transcript(repo, "good")
        write_transcript(repo, "bad", "")

        result = await run_ingest(factory)

        assert result.failed == 1
        assert result.created == 1
        async with factory() as session:
            paths = (
                (await session.execute(select(models.Document.source_path)))
                .scalars()
                .all()
            )
        assert paths == ["episodes/good/transcript.md"]

    async def test_limit_processes_only_the_first_n(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        for slug in ("a-one", "b-two", "c-three", "d-four"):
            write_transcript(repo, slug)

        result = await run_ingest(factory, limit=2)

        assert result.created == 2
        async with factory() as session:
            paths = (
                (
                    await session.execute(
                        select(models.Document.source_path).order_by(
                            models.Document.source_path
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert paths == [
            "episodes/a-one/transcript.md",
            "episodes/b-two/transcript.md",
        ]

    async def test_limit_does_not_prune_the_rest_of_the_corpus(
        self, ingestion_env
    ) -> None:
        """A limited run must not mistake un-visited transcripts for removed."""
        repo, factory = ingestion_env
        for slug in ("a-one", "b-two", "c-three"):
            write_transcript(repo, slug)
        await run_ingest(factory)

        result = await run_ingest(factory, limit=1)

        assert result.removed == 0
        async with factory() as session:
            count = (
                await session.execute(select(func.count()).select_from(models.Document))
            ).scalar_one()
        assert count == 3

    async def test_uses_the_configured_chunk_size(self, ingestion_env) -> None:
        repo, factory = ingestion_env
        write_transcript(
            repo, "big", TRANSCRIPT + "\n\n" + "\n\n".join(words(100, f"p{n}_") for n in range(20))
        )

        result = await ingest(
            make_settings(chunk_target_tokens=120, chunk_overlap_tokens=20),
            session_factory=factory,
        )

        async with factory() as session:
            sizes = (
                (
                    await session.execute(
                        select(models.Chunk.chunk_metadata["word_count"].as_integer())
                    )
                )
                .scalars()
                .all()
            )
        assert result.chunks_written > 5
        assert max(sizes) <= 120 + 100

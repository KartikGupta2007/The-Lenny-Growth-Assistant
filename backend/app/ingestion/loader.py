"""Fetch the transcript repository and find the transcripts in it."""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path

import httpx

from app.config import Settings
from app.constants import BACKEND_DIR
from app.logging_config import get_logger

logger = get_logger(__name__)

# The repository stores one transcript per episode directory. Everything else
# in it -- index/, scripts/, README.md -- is not a transcript.
TRANSCRIPT_GLOB = "episodes/*/transcript.md"


class RepositoryError(Exception):
    """The transcript repository could not be fetched or read."""


def cache_dir(settings: Settings) -> Path:
    """Where the downloaded repository lives.

    Relative paths resolve against backend/, so the command behaves the same
    from the repository root or from backend/.
    """
    configured = Path(settings.transcript_cache_dir)
    return configured if configured.is_absolute() else BACKEND_DIR / configured


def sync_repository(settings: Settings, *, force: bool = False) -> Path:
    """Download and extract the transcript repository; return its root.

    Reuses an existing extraction unless `force` is set, so ingestion can be
    rerun without re-downloading 8 MB every time.
    """
    destination = cache_dir(settings)
    existing = _find_root(destination)

    if existing is not None and not force:
        logger.info("transcript_cache_hit", path=str(existing))
        return existing

    url = (
        f"https://codeload.github.com/{settings.transcript_repo}"
        f"/tar.gz/{settings.transcript_repo_ref}"
    )
    logger.info("transcript_download_started", repo=settings.transcript_repo)

    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as archive:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
                response.raise_for_status()
                for block in response.iter_bytes():
                    archive.write(block)
            archive.flush()
            with tarfile.open(archive.name) as tar:
                # filter="data" rejects absolute paths and traversal entries.
                tar.extractall(destination, filter="data")
    except httpx.HTTPError as exc:
        raise RepositoryError(f"Could not download {url}: {exc}") from exc
    except (tarfile.TarError, OSError) as exc:
        raise RepositoryError(f"Could not extract the repository: {exc}") from exc

    root = _find_root(destination)
    if root is None:
        raise RepositoryError(
            f"No '{TRANSCRIPT_GLOB.split('/')[0]}' directory found in the "
            f"extracted repository under {destination}"
        )

    logger.info("transcript_download_complete", path=str(root))
    return root


def _find_root(destination: Path) -> Path | None:
    """Locate the extracted repository by the directory it must contain.

    GitHub names the archive's top directory after the repo and ref; looking
    for the episodes directory instead means the name can change without
    breaking ingestion.
    """
    if not destination.exists():
        return None
    if (destination / "episodes").is_dir():
        return destination
    for candidate in sorted(destination.iterdir()):
        if candidate.is_dir() and (candidate / "episodes").is_dir():
            return candidate
    return None


def discover_transcripts(root: Path) -> list[Path]:
    """Every transcript file, in a stable order."""
    return sorted(root.glob(TRANSCRIPT_GLOB))

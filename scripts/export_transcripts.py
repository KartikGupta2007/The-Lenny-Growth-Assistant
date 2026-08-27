#!/usr/bin/env python3
"""Export coding-agent transcripts to agent-transcripts/, with secrets redacted.

Claude Code stores each session as JSONL under ~/.claude/projects/<slug>/.
Those files contain real API keys and database URLs, so they are never copied
verbatim. This writes the conversation -- prompts and the agent's replies --
as Markdown, with every credential pattern replaced.

    python scripts/export_transcripts.py

Tool call payloads are summarised rather than included: they are the bulk of
the bytes and the least readable part. The prompts and replies are what show
the engineering decisions, the failed attempts and the corrections.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "agent-transcripts"
SESSIONS = (
    Path.home()
    / ".claude/projects"
    / "-Users-kartikgupta-Desktop-Self-Self-Made-Projects-The-Lenny-Growth-Assistant"
)

# Every pattern here must be replaced before anything is written to disk.
REDACTIONS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "sk-ant-REDACTED"),
    (re.compile(r"npg_[A-Za-z0-9]{8,}"), "npg_REDACTED"),
    (re.compile(r"ep-[a-z0-9-]+\.[a-z0-9-]*\.?[a-z0-9-]*\.aws\.neon\.tech"), "REDACTED.neon.tech"),
    (re.compile(r"(postgresql(?:\+\w+)?://)[^:\s/@]+:[^@\s]+@"), r"\1USER:PASSWORD@"),
    (re.compile(r"(ANTHROPIC_API_KEY\s*=\s*)\S+"), r"\1REDACTED"),
    (re.compile(r"(DATABASE_URL\s*=\s*)\S+"), r"\1REDACTED"),
    # Local paths carry the machine's username; not secret, but not useful.
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "~"),
]

MAX_BLOCK_CHARS = 6000


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def blocks(content: object) -> list[str]:
    """Readable text from a message, summarising tool traffic."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text" and part.get("text", "").strip():
            out.append(part["text"])
        elif kind == "tool_use":
            out.append(f"_[tool: {part.get('name', 'unknown')}]_")
        elif kind == "tool_result":
            out.append("_[tool result omitted]_")
    return out


def export(path: Path) -> tuple[Path, int] | None:
    turns: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        for text in blocks(message.get("content")):
            text = text.strip()
            if not text or text.startswith("_[tool"):
                if text.startswith("_[tool"):
                    turns.append(text)
                continue
            if len(text) > MAX_BLOCK_CHARS:
                text = text[:MAX_BLOCK_CHARS] + "\n\n_[…truncated]_"
            turns.append(f"### {role.capitalize()}\n\n{text}")

    if not turns:
        return None

    body = redact("\n\n".join(turns))
    target = OUT / f"{path.stem}.md"
    target.write_text(
        f"# Agent transcript — session `{path.stem}`\n\n"
        "Exported by `scripts/export_transcripts.py`. Credentials are redacted; "
        "tool payloads are omitted for readability.\n\n---\n\n" + body,
        encoding="utf-8",
    )
    return target, len(turns)


def main() -> None:
    if not SESSIONS.is_dir():
        sys.exit(f"No session directory at {SESSIONS}")
    OUT.mkdir(exist_ok=True)

    for path in sorted(SESSIONS.glob("*.jsonl")):
        result = export(path)
        if result is None:
            continue
        target, turns = result
        print(f"  {target.name}  {turns} turns  {target.stat().st_size // 1024} KB")

    # Nothing leaves this script unredacted.
    leaked = []
    for written in OUT.glob("*.md"):
        text = written.read_text(encoding="utf-8")
        for pattern, _ in REDACTIONS[:3]:
            if pattern.search(text):
                leaked.append(f"{written.name}: {pattern.pattern}")
    if leaked:
        sys.exit("REDACTION FAILED:\n" + "\n".join(leaked))
    print("  redaction verified: no credential patterns remain")


if __name__ == "__main__":
    main()

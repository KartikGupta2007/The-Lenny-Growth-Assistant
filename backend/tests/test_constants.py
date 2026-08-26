"""Cross-language constant contract.

``frontend/src/constants.ts`` mirrors part of ``backend/app/constants.py``:
provider ids, error codes and route paths are shared contracts, and changing
one side alone breaks the pair silently -- the UI would simply stop matching a
code, or request a route that no longer exists.

These tests parse the TypeScript file and assert the two agree, so the drift
is caught here rather than in the browser.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from app.constants import (
    API_PREFIX,
    BACKEND_DIR,
    ERROR_HTTP,
    ERROR_VALIDATION,
    LLMProviderId,
    ProviderKind,
    ROUTE_HEALTH,
    ROUTE_PROVIDERS,
)
from app.errors import AppError

FRONTEND_CONSTANTS = BACKEND_DIR.parent / "frontend" / "src" / "constants.ts"


@pytest.fixture(scope="module")
def frontend_source() -> str:
    if not FRONTEND_CONSTANTS.exists():  # pragma: no cover - checkout layout
        pytest.skip(f"{FRONTEND_CONSTANTS} not present")
    return FRONTEND_CONSTANTS.read_text(encoding="utf-8")


def parse_string_array(source: str, name: str) -> list[str]:
    """Read ``export const NAME = ['a', 'b'] as const;``."""
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S)
    assert match, f"{name} not found in constants.ts"
    return re.findall(r"'([^']+)'", match.group(1))


def parse_string_record(source: str, name: str) -> dict[str, str]:
    """Read ``export const NAME[: Type] = {{ key: 'value', ... }}[ as const];``."""
    match = re.search(
        rf"export const {name}(?::[^=]+)? = \{{(.*?)^\}}", source, re.S | re.M
    )
    assert match, f"{name} not found in constants.ts"
    return dict(re.findall(r"(\w+):\s*\n?\s*'([^']*)'", match.group(1)))


def backend_error_codes() -> set[str]:
    """Every code the API can emit."""
    codes = {AppError.code, ERROR_VALIDATION, ERROR_HTTP}
    stack = list(AppError.__subclasses__())
    while stack:
        subclass = stack.pop()
        codes.add(subclass.code)
        stack.extend(subclass.__subclasses__())
    return codes


class TestProviderContract:
    def test_provider_ids_match(self, frontend_source: str) -> None:
        assert parse_string_array(frontend_source, "PROVIDER_IDS") == list(
            get_args(LLMProviderId)
        )

    def test_provider_kinds_match(self, frontend_source: str) -> None:
        assert parse_string_array(frontend_source, "PROVIDER_KINDS") == list(
            get_args(ProviderKind)
        )

    def test_every_kind_has_a_label(self, frontend_source: str) -> None:
        """A missing label would render an empty badge."""
        labels = parse_string_record(frontend_source, "PROVIDER_KIND_LABELS")

        assert set(labels) == set(get_args(ProviderKind))
        assert all(labels.values())


class TestErrorCodeContract:
    def test_frontend_knows_every_backend_error_code(
        self, frontend_source: str
    ) -> None:
        """The UI cannot branch on a code it does not have a name for."""
        frontend_codes = set(
            parse_string_record(frontend_source, "ERROR_CODES").values()
        )

        missing = backend_error_codes() - frontend_codes
        assert not missing, f"ERROR_CODES in constants.ts is missing: {sorted(missing)}"

    def test_codes_are_unique(self, frontend_source: str) -> None:
        codes = list(parse_string_record(frontend_source, "ERROR_CODES").values())

        assert len(codes) == len(set(codes)), "duplicate error code"


class TestRouteContract:
    def test_endpoints_match_the_registered_routes(
        self, frontend_source: str
    ) -> None:
        endpoints = parse_string_record(frontend_source, "ENDPOINTS")

        assert endpoints["health"] == ROUTE_HEALTH
        assert endpoints["providers"] == f"{API_PREFIX}{ROUTE_PROVIDERS}"

    def test_endpoints_are_absolute(self, frontend_source: str) -> None:
        """A relative path would resolve against the page, not the API."""
        endpoints = parse_string_record(frontend_source, "ENDPOINTS")

        assert all(path.startswith("/") for path in endpoints.values())


class TestBackendConstantsHygiene:
    def test_settings_defaults_do_not_alias_the_constant(self) -> None:
        """Each Settings instance must get its own list."""
        from app.config import Settings

        first = Settings(_env_file=None)
        second = Settings(_env_file=None)
        first.cors_origins.append("http://mutated.test")

        assert "http://mutated.test" not in second.cors_origins


def test_no_stray_env_reads_outside_config() -> None:
    """Only config.py may touch the environment (PRD section 17)."""
    offenders: list[Path] = []
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        if path.name == "config.py":
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"os\.environ|os\.getenv", source):
            offenders.append(path.relative_to(BACKEND_DIR))

    assert not offenders, f"environment read outside config.py: {offenders}"

"""Artifacts: sanitisation, generation, persistence and access.

Sanitisation gets the most attention here -- generated HTML is untrusted, and
this is the layer that decides what is allowed to be stored at all.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.artifacts import sanitize_html
from app.config import Settings
from app.constants import ARTIFACT_HTML, ARTIFACT_MARKDOWN
from app.errors import ModelError
from app.main import create_app
from app.models.base import Message, ModelProvider
from app.retrieval import RetrievalResult, RetrievedChunk
from app.skills import generate_html_page, generate_ship30_essay

USER_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
USER_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


class TestScriptRemoval:
    def test_script_element_and_its_body_are_removed(self) -> None:
        out = sanitize_html('<script>alert("x")</script><p>keep</p>')

        assert "script" not in out.lower()
        assert "alert" not in out, "the body must go, not just the tag"
        assert "<p>keep</p>" in out

    def test_uppercase_and_spaced_script_tags_are_removed(self) -> None:
        for markup in (
            "<SCRIPT>alert(1)</SCRIPT>",
            "< script >alert(1)</ script >",
            '<script type="text/javascript">alert(1)</script>',
        ):
            out = sanitize_html(markup)
            assert "alert" not in out, markup

    def test_self_closing_script_is_removed(self) -> None:
        assert "src" not in sanitize_html('<script src="https://evil.example/x.js"/>')

    def test_other_executable_elements_are_removed(self) -> None:
        for markup in (
            '<object data="x.swf"></object>',
            '<embed src="x.swf">',
            "<applet code=x></applet>",
            "<noscript>hidden</noscript>",
            '<template><script>alert(1)</script></template>',
        ):
            out = sanitize_html(markup)
            assert "<object" not in out and "<embed" not in out
            assert "<applet" not in out and "alert" not in out

    def test_iframes_cannot_be_nested_inside_an_artifact(self) -> None:
        out = sanitize_html('<iframe src="https://evil.example"></iframe><p>hi</p>')

        assert "iframe" not in out
        assert "<p>hi</p>" in out


class TestEventHandlers:
    @pytest.mark.parametrize(
        "markup",
        [
            '<div onclick="steal()">x</div>',
            '<img src=x onerror="alert(1)">',
            '<p onmouseover="alert(1)">x</p>',
            '<body onload="alert(1)">x</body>',
            '<a href="#" onfocus="alert(1)">x</a>',
            '<div ONCLICK="alert(1)">x</div>',
        ],
    )
    def test_every_handler_attribute_is_removed(self, markup: str) -> None:
        out = sanitize_html(markup)

        assert "onclick" not in out.lower()
        assert "onerror" not in out.lower()
        assert "onmouseover" not in out.lower()
        assert "onload" not in out.lower()
        assert "onfocus" not in out.lower()
        assert "alert" not in out and "steal" not in out


class TestDangerousUrls:
    @pytest.mark.parametrize(
        "href",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "  javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
        ],
    )
    def test_dangerous_schemes_are_dropped(self, href: str) -> None:
        out = sanitize_html(f'<a href="{href}">click</a>')

        assert "javascript" not in out.lower()
        assert "vbscript" not in out.lower()
        assert "data:text/html" not in out.lower()
        assert ">click</a>" in out, "the link text survives; only the URL goes"

    def test_safe_schemes_are_kept(self) -> None:
        for href in (
            "https://www.youtube.com/watch?v=abc",
            "http://example.com",
            "mailto:someone@example.com",
        ):
            assert href in sanitize_html(f'<a href="{href}">x</a>')


class TestSafeContentSurvives:
    def test_layout_and_text_markup_is_kept(self) -> None:
        markup = (
            "<section><h1>Title</h1><h2>Sub</h2>"
            "<p>Some <strong>bold</strong> and <em>italic</em> text.</p>"
            "<ul><li>one</li><li>two</li></ul>"
            "<table><thead><tr><th>a</th></tr></thead>"
            "<tbody><tr><td>b</td></tr></tbody></table></section>"
        )

        out = sanitize_html(markup)

        for fragment in ("<h1>Title</h1>", "<strong>bold</strong>", "<li>one</li>", "<td>b</td>"):
            assert fragment in out

    def test_a_style_block_is_kept(self) -> None:
        out = sanitize_html(
            "<style>.card{color:#333;padding:16px;border-radius:8px}</style>"
            '<div class="card">x</div>'
        )

        assert "<style>" in out
        assert "padding:16px" in out.replace(" ", "")
        assert 'class="card"' in out

    def test_safe_inline_css_is_kept_and_unsafe_dropped(self) -> None:
        out = sanitize_html(
            '<p style="color: blue; font-size: 18px; position: fixed">x</p>'
        )

        assert "color: blue" in out
        assert "font-size: 18px" in out
        assert "position" not in out, "positioning could escape the artifact frame"

    def test_class_and_id_survive_for_styling(self) -> None:
        out = sanitize_html('<div class="grid" id="hero">x</div>')

        assert 'class="grid"' in out
        assert 'id="hero"' in out

    def test_a_realistic_landing_page_survives_intact(self) -> None:
        page = (
            "<style>.hero{background:#111;color:#fff;padding:48px}"
            ".cta{display:flex;gap:12px}</style>"
            '<section class="hero"><h1>Growth loops</h1>'
            "<p>As <strong>Casey Winters</strong> put it, loops compound.</p>"
            '<div class="cta"><a href="https://example.com">Read more</a></div>'
            "</section>"
        )

        out = sanitize_html(page)

        assert "Growth loops" in out
        assert "Casey Winters" in out
        assert "https://example.com" in out
        assert ".hero{background:#111" in out.replace(" ", "")

    def test_comments_are_stripped(self) -> None:
        assert "secret" not in sanitize_html("<!-- secret note --><p>x</p>")

    def test_empty_input_is_fine(self) -> None:
        assert sanitize_html("") == ""


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


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


def a_chunk(number: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content=f"Passage {number} about growth loops.",
        chunk_index=number,
        distance=0.2,
        title=f"Episode {number}",
        guest=f"Guest {number}",
        source_url=f"https://www.youtube.com/watch?v=ep{number}",
        source_path=f"episodes/ep-{number}/transcript.md",
    )


class ScriptedProvider(ModelProvider):
    id = "ollama"
    label = "Stub"
    kind = "local"

    def __init__(self, reply: str) -> None:
        super().__init__(make_settings())
        self.reply = reply
        self.calls: list[tuple[str, list[Message]]] = []

    @property
    def model_name(self) -> str:
        return "stub"

    async def check_availability(self):
        return True, None

    async def generate(self, system: str, messages: list[Message]) -> str:
        self.calls.append((system, messages))
        return self.reply


ESSAY = "# Growth loops compound\n\n" + " ".join(["word"] * 400)


class TestShip30Skill:
    async def test_returns_markdown_and_sees_the_evidence(self) -> None:
        provider = ScriptedProvider(ESSAY)

        essay = await generate_ship30_essay(
            provider, "growth loops", [a_chunk(1), a_chunk(2)]
        )

        assert essay.startswith("# ")
        system, messages = provider.calls[0]
        assert "Passage 1 about growth loops." in messages[0].content
        assert "growth loops" in messages[0].content

    async def test_the_prompt_targets_the_required_shape(self) -> None:
        provider = ScriptedProvider(ESSAY)
        await generate_ship30_essay(provider, "topic", [a_chunk(1)])

        system, _ = provider.calls[0]
        lowered = system.lower()
        assert "1250" in system.replace(",", "")
        assert "hook" in lowered
        assert "heading" in lowered
        assert "bullet" in lowered
        assert "bold" in lowered
        assert "do not invent" in lowered

    async def test_a_stub_of_an_essay_is_rejected(self) -> None:
        provider = ScriptedProvider("Too short.")

        with pytest.raises(ModelError, match="too short"):
            await generate_ship30_essay(provider, "topic", [a_chunk(1)])


class TestHtmlSkill:
    async def test_returns_markup(self) -> None:
        provider = ScriptedProvider("<style>.a{color:red}</style><div>hi</div>")

        html = await generate_html_page(provider, "a landing page", [a_chunk(1)])

        assert "<div>hi</div>" in html

    async def test_a_fenced_reply_is_unwrapped(self) -> None:
        provider = ScriptedProvider("```html\n<div>hi</div>\n```")

        assert await generate_html_page(provider, "x", [a_chunk(1)]) == "<div>hi</div>"

    async def test_a_reply_without_markup_is_rejected(self) -> None:
        provider = ScriptedProvider("I am afraid I cannot do that.")

        with pytest.raises(ModelError, match="without any markup"):
            await generate_html_page(provider, "x", [a_chunk(1)])

    async def test_the_prompt_forbids_javascript(self) -> None:
        provider = ScriptedProvider("<div>x</div>")
        await generate_html_page(provider, "x", [a_chunk(1)])

        system, _ = provider.calls[0]
        assert "no javascript" in system.lower()


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


class StubRegistry:
    def __init__(self, provider):
        self.provider = provider

    async def require(self, provider_id):
        return self.provider


@pytest.fixture
def api(settings: Settings, migrated_database: str, monkeypatch: pytest.MonkeyPatch):
    from app.db.session import get_engine, get_sessionmaker

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    state: dict = {"provider": None}

    def build(
        chunks: list[RetrievedChunk] | None = None,
        sufficient: bool = True,
        reply: str = ESSAY,
    ) -> TestClient:
        resolved = chunks if chunks is not None else [a_chunk(1), a_chunk(2)]

        async def fake_retrieve(_session, query, **_kwargs):
            return RetrievalResult(query=query, chunks=resolved, sufficient=sufficient)

        state["provider"] = ScriptedProvider(reply)
        monkeypatch.setattr("app.agent.agent.retrieve", fake_retrieve)
        monkeypatch.setattr(
            "app.agent.agent.get_provider_registry",
            lambda: StubRegistry(state["provider"]),
        )
        return TestClient(create_app(settings))

    build.state = state  # type: ignore[attr-defined]
    yield build

    engine = get_engine()
    import asyncio

    async def cleanup() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users"))
        await engine.dispose()

    asyncio.run(cleanup())
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def start(client: TestClient, user: uuid.UUID = USER_A) -> str:
    response = client.post("/api/sessions", headers={"X-User-Id": str(user)})
    assert response.status_code == 201
    return response.json()["id"]


def ask(client: TestClient, session_id: str, message: str, user: uuid.UUID = USER_A):
    return client.post(
        f"/api/sessions/{session_id}/messages",
        json={"message": message},
        headers={"X-User-Id": str(user)},
    )


class TestArtifactGenerationThroughChat:
    def test_asking_for_an_essay_creates_a_markdown_artifact(self, api) -> None:
        with api() as client:
            session_id = start(client)
            ask(client, session_id, "Write a Ship 30 essay about growth loops")

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert len(detail["artifacts"]) == 1
        artifact = detail["artifacts"][0]
        assert artifact["type"] == ARTIFACT_MARKDOWN
        assert artifact["title"] == "Growth loops compound"

    def test_the_artifact_is_linked_to_the_assistant_message(self, api) -> None:
        with api() as client:
            session_id = start(client)
            sent = ask(
                client, session_id, "Write a Ship 30 essay about growth loops"
            ).json()

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert detail["artifacts"][0]["message_id"] == sent["message"]["id"]

    def test_the_chat_message_is_a_note_not_the_whole_essay(self, api) -> None:
        """A 1,250-word essay does not belong in the transcript twice."""
        with api() as client:
            session_id = start(client)
            sent = ask(
                client, session_id, "Write a Ship 30 essay about growth loops"
            ).json()

        assert len(sent["message"]["content"]) < 200
        assert "panel" in sent["message"]["content"]
        assert len(sent["sources"]) == 2

    def test_asking_for_a_page_creates_a_sanitised_html_artifact(self, api) -> None:
        dangerous = '<script>alert(1)</script><div onclick="x()">Hero</div>'
        with api(reply=dangerous) as client:
            session_id = start(client)
            ask(client, session_id, "Build me a landing page about growth")

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()
            artifact = client.get(
                f"/api/artifacts/{detail['artifacts'][0]['id']}",
                headers={"X-User-Id": str(USER_A)},
            ).json()

        assert artifact["type"] == ARTIFACT_HTML
        assert "script" not in artifact["content"].lower()
        assert "onclick" not in artifact["content"].lower()
        assert "Hero" in artifact["content"], "the safe markup survived"

    def test_a_normal_question_creates_no_artifact(self, api) -> None:
        with api(reply="A grounded answer [1].") as client:
            session_id = start(client)
            ask(client, session_id, "What does Lenny say about retention?")

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert detail["artifacts"] == []
        assert detail["messages"][1]["content"] == "A grounded answer [1]."

    def test_insufficient_evidence_creates_no_artifact(self, api) -> None:
        with api(chunks=[], sufficient=False) as client:
            session_id = start(client)
            sent = ask(
                client, session_id, "Write a Ship 30 essay about sourdough"
            ).json()

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert detail["artifacts"] == []
        assert sent["grounded"] is False
        assert "don't have enough information" in sent["message"]["content"]
        assert api.state["provider"].calls == [], "the model was never called"

    def test_a_model_that_will_not_write_it_declines_gracefully(self, api) -> None:
        """Observed for real: enough chunks clear the threshold, but the model
        rightly refuses to write 1,250 words the evidence cannot support. That
        is a decline, not a 502, and it creates no artifact."""
        with api(reply="I can't write that from this evidence.") as client:
            session_id = start(client)
            sent = ask(client, session_id, "Write a Ship 30 essay about sourdough")

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert sent.status_code == 200
        body = sent.json()
        assert body["grounded"] is False
        assert body["sources"] == []
        assert "haven't" in body["message"]["content"]
        assert detail["artifacts"] == [], "nothing was stored"
        assert detail["messages"][1]["grounded"] is False

    def test_a_refused_html_artifact_also_declines(self, api) -> None:
        with api(reply="I am afraid I cannot do that.") as client:
            session_id = start(client)
            sent = ask(client, session_id, "Build me a landing page about sourdough")

            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert sent.status_code == 200
        assert sent.json()["grounded"] is False
        assert "page" in sent.json()["message"]["content"]
        assert detail["artifacts"] == []

    def test_artifacts_survive_a_reload(self, api) -> None:
        with api() as client:
            session_id = start(client)
            ask(client, session_id, "Write a Ship 30 essay about growth loops")

            # A second, independent read -- as a page reload would do.
            reloaded = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()
            artifact = client.get(
                f"/api/artifacts/{reloaded['artifacts'][0]['id']}",
                headers={"X-User-Id": str(USER_A)},
            ).json()

        assert artifact["content"].startswith("# Growth loops compound")
        assert artifact["session_id"] == session_id


class TestArtifactApi:
    def test_create_and_read_back(self, api) -> None:
        with api() as client:
            session_id = start(client)
            created = client.post(
                "/api/artifacts",
                json={
                    "session_id": session_id,
                    "type": ARTIFACT_MARKDOWN,
                    "title": "Notes",
                    "content": "# Notes\n\nSome text.",
                },
                headers={"X-User-Id": str(USER_A)},
            )
            fetched = client.get(
                f"/api/artifacts/{created.json()['id']}",
                headers={"X-User-Id": str(USER_A)},
            )

        assert created.status_code == 201
        body = fetched.json()
        assert body["title"] == "Notes"
        assert body["content"] == "# Notes\n\nSome text."
        assert body["session_id"] == session_id
        assert body["message_id"] is None
        assert body["created_at"] and body["updated_at"]

    def test_html_is_sanitised_on_the_way_in(self, api) -> None:
        """Storage never depends on the caller having sanitised anything."""
        with api() as client:
            session_id = start(client)
            created = client.post(
                "/api/artifacts",
                json={
                    "session_id": session_id,
                    "type": ARTIFACT_HTML,
                    "title": "Page",
                    "content": '<script>alert(1)</script><p onclick="x()">hi</p>',
                },
                headers={"X-User-Id": str(USER_A)},
            ).json()

        assert "script" not in created["content"].lower()
        assert "onclick" not in created["content"].lower()
        assert "hi" in created["content"]

    def test_cannot_create_in_someone_elses_session(self, api) -> None:
        with api() as client:
            theirs = start(client, USER_B)
            response = client.post(
                "/api/artifacts",
                json={
                    "session_id": theirs,
                    "type": ARTIFACT_MARKDOWN,
                    "title": "x",
                    "content": "x",
                },
                headers={"X-User-Id": str(USER_A)},
            )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_unknown_artifact_is_not_found(self, api) -> None:
        with api() as client:
            start(client)
            response = client.get(
                f"/api/artifacts/{uuid.uuid4()}", headers={"X-User-Id": str(USER_A)}
            )

        assert response.status_code == 404

    def test_cannot_read_another_users_artifact(self, api) -> None:
        with api() as client:
            theirs = start(client, USER_B)
            created = client.post(
                "/api/artifacts",
                json={
                    "session_id": theirs,
                    "type": ARTIFACT_MARKDOWN,
                    "title": "theirs",
                    "content": "secret notes",
                },
                headers={"X-User-Id": str(USER_B)},
            ).json()

            response = client.get(
                f"/api/artifacts/{created['id']}", headers={"X-User-Id": str(USER_A)}
            )

        assert response.status_code == 404
        assert "secret notes" not in response.text

    def test_an_unknown_type_is_rejected(self, api) -> None:
        with api() as client:
            session_id = start(client)
            response = client.post(
                "/api/artifacts",
                json={
                    "session_id": session_id,
                    "type": "pdf",
                    "title": "x",
                    "content": "x",
                },
                headers={"X-User-Id": str(USER_A)},
            )

        assert response.status_code == 422

    def test_empty_content_is_rejected(self, api) -> None:
        with api() as client:
            session_id = start(client)
            response = client.post(
                "/api/artifacts",
                json={
                    "session_id": session_id,
                    "type": ARTIFACT_MARKDOWN,
                    "title": "x",
                    "content": "",
                },
                headers={"X-User-Id": str(USER_A)},
            )

        assert response.status_code == 422

    def test_no_credentials_appear_in_an_artifact_response(self, api) -> None:
        with api() as client:
            session_id = start(client)
            ask(client, session_id, "Write a Ship 30 essay about growth loops")
            detail = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            )
            artifact = client.get(
                f"/api/artifacts/{detail.json()['artifacts'][0]['id']}",
                headers={"X-User-Id": str(USER_A)},
            )

        for body in (detail.text, artifact.text):
            for secret in ("sk-ant", "postgresql://", "neon.tech", "ANTHROPIC_API_KEY"):
                assert secret not in body

    def test_deleting_a_session_removes_its_artifacts(self, api) -> None:
        with api() as client:
            session_id = start(client)
            ask(client, session_id, "Write a Ship 30 essay about growth loops")
            artifact_id = client.get(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            ).json()["artifacts"][0]["id"]

            client.delete(
                f"/api/sessions/{session_id}", headers={"X-User-Id": str(USER_A)}
            )
            response = client.get(
                f"/api/artifacts/{artifact_id}", headers={"X-User-Id": str(USER_A)}
            )

        assert response.status_code == 404

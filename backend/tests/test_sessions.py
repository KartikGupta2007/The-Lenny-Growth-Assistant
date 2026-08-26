"""Sessions, message persistence and the conversational endpoint.

Real PostgreSQL -- persistence is the point -- with retrieval and the model
stubbed. No real Ollama, no real Claude.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.sessions import ANONYMOUS_USER_ID
from app.config import Settings
from app.errors import ModelTimeoutError, ProviderUnavailableError
from app.main import create_app
from app.models.base import Message, ModelProvider
from app.retrieval import RetrievalResult, RetrievedChunk

ANSWER = "A grounded answer [1]."
DECLINE = (
    "I don't have enough information in Lenny's Podcast transcripts to answer "
    "that confidently."
)
USER_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def a_chunk(number: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content=f"passage {number}",
        chunk_index=number,
        distance=0.2,
        title=f"Episode {number}",
        guest=f"Guest {number}",
        source_url=f"https://www.youtube.com/watch?v=ep{number}",
        source_path=f"episodes/ep-{number}/transcript.md",
    )


class StubProvider(ModelProvider):
    id = "ollama"
    label = "Stub"
    kind = "local"

    def __init__(self, settings, reply: str = ANSWER, error: Exception | None = None):
        super().__init__(settings)
        self.reply = reply
        self.error = error
        self.calls: list[list[Message]] = []

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def check_availability(self):
        return True, None

    async def generate(self, system: str, messages: list[Message]) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.reply


class StubRegistry:
    def __init__(self, provider=None, error: Exception | None = None):
        self.provider = provider
        self.error = error

    async def require(self, provider_id):
        if self.error is not None:
            raise self.error
        return self.provider


@pytest.fixture
def api(settings: Settings, migrated_database: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient over the real test database, with retrieval and the model stubbed.

    The engine caches are cleared so this test's client gets an engine bound to
    its own event loop rather than one left over from another test.
    """
    from app.db.session import get_engine, get_sessionmaker

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    state: dict = {"queries": [], "provider": None}

    def build(
        chunks: list[RetrievedChunk] | None = None,
        sufficient: bool = True,
        provider: ModelProvider | None = None,
        registry_error: Exception | None = None,
    ) -> TestClient:
        resolved = chunks if chunks is not None else [a_chunk(1), a_chunk(2)]

        async def fake_retrieve(_session, query, **_kwargs):
            state["queries"].append(query)
            return RetrievalResult(query=query, chunks=resolved, sufficient=sufficient)

        state["provider"] = provider or StubProvider(settings)
        monkeypatch.setattr("app.agent.agent.retrieve", fake_retrieve)
        monkeypatch.setattr(
            "app.agent.agent.get_provider_registry",
            lambda: StubRegistry(state["provider"], error=registry_error),
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


def start_session(client: TestClient, user: uuid.UUID | None = None) -> str:
    headers = {"X-User-Id": str(user)} if user else {}
    response = client.post("/api/sessions", headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client: TestClient, session_id: str, message: str, **kwargs):
    user = kwargs.pop("user", None)
    headers = {"X-User-Id": str(user)} if user else {}
    return client.post(
        f"/api/sessions/{session_id}/messages",
        json={"message": message, **kwargs},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class TestSessions:
    def test_create(self, api) -> None:
        with api() as client:
            response = client.post("/api/sessions")

        assert response.status_code == 201
        body = response.json()
        assert uuid.UUID(body["id"])
        assert body["user_id"] == str(ANONYMOUS_USER_ID)
        assert body["created_at"] and body["updated_at"]

    def test_create_uses_the_client_supplied_user(self, api) -> None:
        with api() as client:
            response = client.post("/api/sessions", headers={"X-User-Id": str(USER_A)})

        assert response.json()["user_id"] == str(USER_A)

    def test_list_is_empty_for_a_new_user(self, api) -> None:
        with api() as client:
            response = client.get("/api/sessions", headers={"X-User-Id": str(USER_A)})

        assert response.status_code == 200
        assert response.json() == []

    def test_list_returns_this_users_sessions(self, api) -> None:
        with api() as client:
            first = start_session(client, USER_A)
            second = start_session(client, USER_A)
            listed = client.get(
                "/api/sessions", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert {s["id"] for s in listed} == {first, second}

    def test_sessions_are_isolated_between_users(self, api) -> None:
        with api() as client:
            mine = start_session(client, USER_A)
            start_session(client, USER_B)

            listed = client.get(
                "/api/sessions", headers={"X-User-Id": str(USER_A)}
            ).json()

        assert [s["id"] for s in listed] == [mine]

    def test_get_returns_the_session_and_no_messages_yet(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            response = client.get(f"/api/sessions/{session_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == session_id
        assert body["messages"] == []

    def test_unknown_session_is_not_found(self, api) -> None:
        with api() as client:
            response = client.get(f"/api/sessions/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_another_users_session_is_not_found(self, api) -> None:
        """Without authentication there is no identity to forbid."""
        with api() as client:
            theirs = start_session(client, USER_B)
            response = client.get(
                f"/api/sessions/{theirs}", headers={"X-User-Id": str(USER_A)}
            )

        assert response.status_code == 404

    def test_a_malformed_session_id_is_rejected(self, api) -> None:
        with api() as client:
            response = client.get("/api/sessions/not-a-uuid")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_returns_the_assistant_message_and_sources(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            response = send(client, session_id, "how do I grow?")

        assert response.status_code == 200
        body = response.json()
        assert body["message"]["role"] == "assistant"
        assert body["message"]["content"] == ANSWER
        assert uuid.UUID(body["message"]["id"])
        assert body["grounded"] is True
        assert len(body["sources"]) == 2
        assert body["sources"][0]["source_url"] == "https://www.youtube.com/watch?v=ep1"

    def test_both_turns_are_persisted(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "how do I grow?")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "how do I grow?"),
            ("assistant", ANSWER),
        ]

    def test_messages_come_back_in_order(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            for index in range(3):
                send(client, session_id, f"question {index}")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert [m["content"] for m in messages] == [
            "question 0",
            ANSWER,
            "question 1",
            ANSWER,
            "question 2",
            ANSWER,
        ]

    def test_sending_touches_the_session(self, api) -> None:
        """The sidebar orders by activity, so updated_at must move."""
        with api() as client:
            session_id = start_session(client)
            before = client.get(f"/api/sessions/{session_id}").json()["updated_at"]

            send(client, session_id, "a question")
            after = client.get(f"/api/sessions/{session_id}").json()["updated_at"]

        assert after > before

    def test_unknown_session_is_not_found(self, api) -> None:
        with api() as client:
            response = send(client, str(uuid.uuid4()), "hello")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_cannot_post_into_another_users_session(self, api) -> None:
        with api() as client:
            theirs = start_session(client, USER_B)
            response = send(client, theirs, "hello", user=USER_A)

        assert response.status_code == 404

    def test_an_empty_message_is_rejected(self, api) -> None:
        with api() as client:
            session_id = start_session(client)

            assert send(client, session_id, "").status_code == 422
            assert send(client, session_id, "   ").status_code == 422

    def test_an_oversized_message_is_rejected(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            response = send(client, session_id, "x" * 2001)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_an_unknown_provider_is_rejected(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            response = send(client, session_id, "q", provider="gpt-9")

        assert response.status_code == 422

    def test_nothing_is_persisted_when_validation_fails(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "  ")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert messages == []


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------


class TestFollowUps:
    def test_the_follow_up_sees_the_earlier_turns(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "What does Lenny say about product-market fit?")
            send(client, session_id, "What about customer interviews?")

        provider = api.state["provider"]
        second_call = provider.calls[1]
        contents = [m.content for m in second_call]
        assert "What does Lenny say about product-market fit?" in contents
        assert ANSWER in contents
        assert "customer interviews" in contents[-1]

    def test_the_first_message_has_no_history(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "the first question")

        assert len(api.state["provider"].calls[0]) == 1

    def test_retrieval_uses_the_current_question_only(self, api) -> None:
        """A follow-up is searched for what it asks, not the whole thread."""
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "What about product-market fit?")
            send(client, session_id, "What about customer interviews?")

        assert api.state["queries"] == [
            "What about product-market fit?",
            "What about customer interviews?",
        ]

    def test_history_does_not_cross_sessions(self, api) -> None:
        with api() as client:
            first = start_session(client)
            second = start_session(client)
            send(client, first, "in the first conversation")
            send(client, second, "in the second conversation")

        second_call = api.state["provider"].calls[1]
        assert len(second_call) == 1, "a new conversation starts clean"


# ---------------------------------------------------------------------------
# Insufficient evidence
# ---------------------------------------------------------------------------


class TestInsufficientEvidence:
    def test_the_model_is_not_called(self, api) -> None:
        with api(chunks=[], sufficient=False) as client:
            session_id = start_session(client)
            send(client, session_id, "how do I make sourdough?")

        assert api.state["provider"].calls == []

    def test_the_decline_is_returned(self, api) -> None:
        with api(chunks=[], sufficient=False) as client:
            session_id = start_session(client)
            body = send(client, session_id, "how do I make sourdough?").json()

        assert body["message"]["content"] == DECLINE
        assert body["grounded"] is False
        assert body["sources"] == []
        assert body["provider"] is None

    def test_the_decline_is_persisted_as_part_of_the_conversation(self, api) -> None:
        with api(chunks=[], sufficient=False) as client:
            session_id = start_session(client)
            send(client, session_id, "how do I make sourdough?")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "how do I make sourdough?"),
            ("assistant", DECLINE),
        ]

    def test_a_conversation_survives_a_declined_turn(self, api) -> None:
        """A decline must not corrupt the thread for the next question."""
        with api(chunks=[], sufficient=False) as client:
            session_id = start_session(client)
            send(client, session_id, "off topic")
            second = send(client, session_id, "still off topic")

        assert second.status_code == 200


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class TestFailures:
    def test_a_provider_timeout_returns_the_typed_error(self, api) -> None:
        provider = StubProvider(None, error=ModelTimeoutError())
        with api(provider=provider) as client:
            session_id = start_session(client)
            response = send(client, session_id, "q")

        assert response.status_code == 504
        assert response.json()["error"]["code"] == "model_timeout"

    def test_a_failed_generation_leaves_no_assistant_message(self, api) -> None:
        """The question stays; a fabricated success would be worse than a gap."""
        provider = StubProvider(None, error=ModelTimeoutError())
        with api(provider=provider) as client:
            session_id = start_session(client)
            send(client, session_id, "a question that fails")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "a question that fails")
        ]

    def test_an_unavailable_provider_returns_the_typed_error(self, api) -> None:
        with api(
            registry_error=ProviderUnavailableError("Ollama is not running.")
        ) as client:
            session_id = start_session(client)
            response = send(client, session_id, "q")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"

    def test_a_failed_turn_can_be_retried(self, api) -> None:
        provider = StubProvider(None, error=ModelTimeoutError())
        with api(provider=provider) as client:
            session_id = start_session(client)
            send(client, session_id, "q")
            # The provider recovers.
            provider.error = None
            retried = send(client, session_id, "q")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert retried.status_code == 200
        assert [m["role"] for m in messages] == ["user", "user", "assistant"]


class TestSecurity:
    def test_no_credentials_appear_in_responses(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            response = send(client, session_id, "q")
            detail = client.get(f"/api/sessions/{session_id}")

        for body in (response.text, detail.text):
            assert "sk-ant" not in body
            assert "postgresql" not in body
            assert "neon.tech" not in body

    def test_the_stateless_chat_endpoint_is_gone(self, api) -> None:
        """Replaced by the session endpoint; nothing consumed it."""
        with api() as client:
            response = client.post("/api/chat", json={"message": "q"})

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Persisted provenance
# ---------------------------------------------------------------------------


class TestPersistedProvenance:
    def test_the_post_response_still_carries_sources(self, api) -> None:
        """The existing contract is unchanged."""
        with api() as client:
            session_id = start_session(client)
            body = send(client, session_id, "q").json()

        assert len(body["sources"]) == 2
        assert body["grounded"] is True
        assert body["provider"] == "ollama"

    def test_sources_survive_a_reload(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            posted = send(client, session_id, "q").json()

            reloaded = client.get(f"/api/sessions/{session_id}").json()

        assistant = reloaded["messages"][1]
        assert assistant["sources"] == posted["sources"]

    def test_every_source_field_is_preserved_exactly(self, api) -> None:
        chunks = [a_chunk(1), a_chunk(2), a_chunk(3)]
        with api(chunks=chunks) as client:
            session_id = start_session(client)
            send(client, session_id, "q")

            assistant = client.get(f"/api/sessions/{session_id}").json()["messages"][1]

        assert len(assistant["sources"]) == 3
        for source, chunk in zip(assistant["sources"], chunks):
            assert source["chunk_id"] == str(chunk.chunk_id)
            assert source["document_id"] == str(chunk.document_id)
            assert source["source_url"] == chunk.source_url
            assert source["title"] == chunk.title
            assert source["guest"] == chunk.guest
            assert source["chunk_index"] == chunk.chunk_index

    def test_source_order_survives_a_reload(self, api) -> None:
        with api(chunks=[a_chunk(1), a_chunk(2), a_chunk(3)]) as client:
            session_id = start_session(client)
            send(client, session_id, "q")

            assistant = client.get(f"/api/sessions/{session_id}").json()["messages"][1]

        assert [s["number"] for s in assistant["sources"]] == [1, 2, 3]

    def test_grounded_and_provider_survive_a_reload(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "q")

            assistant = client.get(f"/api/sessions/{session_id}").json()["messages"][1]

        assert assistant["grounded"] is True
        assert assistant["provider"] == "ollama"

    def test_a_declined_turn_persists_its_emptiness(self, api) -> None:
        with api(chunks=[], sufficient=False) as client:
            session_id = start_session(client)
            send(client, session_id, "off topic")

            assistant = client.get(f"/api/sessions/{session_id}").json()["messages"][1]

        assert assistant["sources"] == []
        assert assistant["grounded"] is False
        assert assistant["provider"] is None

    def test_user_turns_carry_no_provenance(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "q")

            user_turn = client.get(f"/api/sessions/{session_id}").json()["messages"][0]

        assert user_turn["sources"] == []
        assert user_turn["grounded"] is None
        assert user_turn["provider"] is None

    def test_no_chunk_content_is_copied_into_the_metadata(self, api) -> None:
        """Passages live in `chunks`, not in every message that cited them."""
        chunks = [a_chunk(1), a_chunk(2)]
        with api(chunks=chunks) as client:
            session_id = start_session(client)
            send(client, session_id, "q")
            reloaded = client.get(f"/api/sessions/{session_id}")

        for chunk in chunks:
            assert chunk.content not in reloaded.text

    def test_a_whole_conversation_reloads_with_its_citations(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "first question")
            send(client, session_id, "second question")

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        assert [m["role"] for m in messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert len(messages[1]["sources"]) == 2
        assert len(messages[3]["sources"]) == 2

    def test_a_legacy_message_with_no_metadata_still_loads(self, api) -> None:
        """Rows written before this column existed must keep working."""
        import asyncio

        from app.db.session import get_sessionmaker

        with api() as client:
            session_id = start_session(client)

            async def insert_legacy() -> None:
                async with get_sessionmaker()() as session:
                    await session.execute(
                        text(
                            "INSERT INTO messages (id, session_id, role, content) "
                            "VALUES (:i, :s, 'assistant', 'an answer from before')"
                        ),
                        {"i": uuid.uuid4(), "s": uuid.UUID(session_id)},
                    )
                    await session.commit()

            client.portal.call(insert_legacy)  # type: ignore[attr-defined]

            messages = client.get(f"/api/sessions/{session_id}").json()["messages"]

        legacy = messages[0]
        assert legacy["content"] == "an answer from before"
        assert legacy["sources"] == []
        assert legacy["grounded"] is None
        assert legacy["provider"] is None

    def test_no_credentials_reach_the_stored_metadata(self, api) -> None:
        with api() as client:
            session_id = start_session(client)
            send(client, session_id, "q")
            reloaded = client.get(f"/api/sessions/{session_id}").text

        for secret in ("sk-ant", "postgresql://", "neon.tech", "x-api-key"):
            assert secret not in reloaded

"""Grounded answer generation and the chat endpoint.

No real Ollama and no real Claude: provider HTTP is served by
httpx.MockTransport, and the retriever is stubbed so tests are about
orchestration rather than about what a model happens to say.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.agent import answer_question
from app.agent.prompts import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    build_evidence,
)
from app.config import Settings
from app.errors import (
    ModelError,
    ModelTimeoutError,
    ProviderUnavailableError,
)
from app.models.base import Message, ModelProvider
from app.models.cloud import CloudModelProvider
from app.models.ollama import OllamaProvider
from app.retrieval import RetrievalResult, RetrievedChunk

SECRET_KEY = "sk-ant-do-not-leak"


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


def a_chunk(number: int = 1, content: str = "Retention is the thing.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content=content,
        chunk_index=number,
        distance=0.2 + number / 100,
        title=f"Episode {number}",
        guest=f"Guest {number}",
        source_url=f"https://www.youtube.com/watch?v=ep{number}",
        source_path=f"episodes/ep-{number}/transcript.md",
    )


class StubProvider(ModelProvider):
    """Records what it was asked to generate."""

    id = "ollama"
    label = "Stub"
    kind = "local"

    def __init__(self, settings: Settings, reply: str = "A grounded answer [1].") -> None:
        super().__init__(settings)
        self.reply = reply
        self.calls: list[tuple[str, list[Message]]] = []

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def check_availability(self) -> tuple[bool, str | None]:
        return True, None

    async def generate(self, system: str, messages: list[Message]) -> str:
        self.calls.append((system, messages))
        return self.reply


class StubRegistry:
    def __init__(self, provider: ModelProvider | None, error: Exception | None = None):
        self.provider = provider
        self.error = error
        self.requested: list[str | None] = []

    async def require(self, provider_id: str | None) -> ModelProvider:
        self.requested.append(provider_id)
        if self.error is not None:
            raise self.error
        assert self.provider is not None
        return self.provider


@pytest.fixture
def stub_retrieval(monkeypatch: pytest.MonkeyPatch):
    """Control what retrieval returns, and record that it was called."""
    calls: list[str] = []

    def install(chunks: list[RetrievedChunk], sufficient: bool = True):
        async def fake_retrieve(_session, query, **_kwargs):
            calls.append(query)
            return RetrievalResult(query=query, chunks=chunks, sufficient=sufficient)

        monkeypatch.setattr("app.agent.agent.retrieve", fake_retrieve)
        return calls

    return install


# ---------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------


class TestGroundedAnswer:
    async def test_returns_the_model_answer_with_sources(self, stub_retrieval) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())

        result = await answer_question(
            None, "how do I retain users?", settings=make_settings(), provider=provider
        )

        assert result.answer == "A grounded answer [1]."
        assert result.grounded is True
        assert len(result.sources) == 2

    async def test_retrieval_happens_before_generation(self, stub_retrieval) -> None:
        calls = stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())

        await answer_question(
            None, "a question", settings=make_settings(), provider=provider
        )

        assert calls == ["a question"], "the retriever ran on the question"
        assert len(provider.calls) == 1, "the model ran once, after retrieval"

    async def test_the_evidence_is_what_the_model_receives(
        self, stub_retrieval
    ) -> None:
        stub_retrieval(
            [
                a_chunk(1, "Cohort curves tell you if it works."),
                a_chunk(2, "Activation precedes retention."),
            ]
        )
        provider = StubProvider(make_settings())

        await answer_question(
            None, "what about retention?", settings=make_settings(), provider=provider
        )

        system, messages = provider.calls[0]
        sent = messages[-1].content
        assert system == SYSTEM_PROMPT
        assert "Cohort curves tell you if it works." in sent
        assert "Activation precedes retention." in sent
        assert "what about retention?" in sent
        assert "[1]" in sent and "[2]" in sent

    async def test_the_corpus_is_not_sent_only_the_evidence(
        self, stub_retrieval
    ) -> None:
        stub_retrieval([a_chunk(1, "only this passage"), a_chunk(2, "and this one")])
        provider = StubProvider(make_settings())

        await answer_question(
            None, "q", settings=make_settings(), provider=provider
        )

        _system, messages = provider.calls[0]
        sent = messages[-1].content
        # Two evidence blocks and nothing else resembling a corpus dump.
        assert sent.count("Episode:") == 2

    async def test_database_ids_are_not_sent_to_the_model(
        self, stub_retrieval
    ) -> None:
        chunks = [a_chunk(1), a_chunk(2)]
        stub_retrieval(chunks)
        provider = StubProvider(make_settings())

        await answer_question(
            None, "q", settings=make_settings(), provider=provider
        )

        _system, messages = provider.calls[0]
        sent = messages[-1].content
        for chunk in chunks:
            assert str(chunk.chunk_id) not in sent
            assert str(chunk.document_id) not in sent

    async def test_urls_are_not_sent_to_the_model(self, stub_retrieval) -> None:
        """The model cannot echo a URL it never saw."""
        chunks = [a_chunk(1), a_chunk(2)]
        stub_retrieval(chunks)
        provider = StubProvider(make_settings())

        await answer_question(None, "q", settings=make_settings(), provider=provider)

        _system, messages = provider.calls[0]
        assert "youtube.com" not in messages[-1].content

    async def test_the_prompt_forbids_invention(self) -> None:
        lowered = SYSTEM_PROMPT.lower()
        assert "do not invent" in lowered
        assert "only" in lowered
        assert "cite" in lowered


class TestSourceAttribution:
    async def test_sources_come_from_retrieval_not_the_model(
        self, stub_retrieval
    ) -> None:
        chunks = [a_chunk(1), a_chunk(2)]
        stub_retrieval(chunks)
        # A model that invents a citation and a URL.
        provider = StubProvider(
            make_settings(),
            reply="See [1] at https://evil.example.com/made-up and [9].",
        )

        result = await answer_question(
            None, "q", settings=make_settings(), provider=provider
        )

        urls = [source.source_url for source in result.sources]
        assert urls == [chunks[0].source_url, chunks[1].source_url]
        assert "evil.example.com" not in " ".join(u or "" for u in urls)

    async def test_source_numbers_match_the_evidence_order(
        self, stub_retrieval
    ) -> None:
        chunks = [a_chunk(1), a_chunk(2), a_chunk(3)]
        stub_retrieval(chunks)

        result = await answer_question(
            None, "q", settings=make_settings(), provider=StubProvider(make_settings())
        )

        assert [s.number for s in result.sources] == [1, 2, 3]
        assert [s.title for s in result.sources] == [c.title for c in chunks]

    async def test_sources_carry_full_provenance(self, stub_retrieval) -> None:
        chunk = a_chunk(1)
        stub_retrieval([chunk, a_chunk(2)])

        result = await answer_question(
            None, "q", settings=make_settings(), provider=StubProvider(make_settings())
        )

        source = result.sources[0]
        assert source.document_id == chunk.document_id
        assert source.chunk_id == chunk.chunk_id
        assert source.title == chunk.title
        assert source.guest == chunk.guest
        assert source.source_url == chunk.source_url
        assert source.chunk_index == chunk.chunk_index

    def test_evidence_numbering_is_one_based(self) -> None:
        rendered = build_evidence([a_chunk(1), a_chunk(2)])

        assert rendered.startswith("[1]")
        assert "[2]" in rendered
        assert "[0]" not in rendered


# ---------------------------------------------------------------------------
# Insufficient evidence -- the anti-hallucination control
# ---------------------------------------------------------------------------


class TestInsufficientEvidence:
    async def test_the_model_is_never_called(self, stub_retrieval) -> None:
        """A model that is not asked cannot answer unsupported."""
        stub_retrieval([], sufficient=False)
        provider = StubProvider(make_settings())

        await answer_question(
            None, "how do I make sourdough?", settings=make_settings(), provider=provider
        )

        assert provider.calls == []

    async def test_the_response_is_deterministic(self, stub_retrieval) -> None:
        stub_retrieval([], sufficient=False)

        first = await answer_question(
            None, "q", settings=make_settings(), provider=StubProvider(make_settings())
        )
        second = await answer_question(
            None, "q", settings=make_settings(), provider=StubProvider(make_settings())
        )

        assert first.answer == second.answer == INSUFFICIENT_EVIDENCE_ANSWER
        assert first.grounded is False

    async def test_no_sources_are_presented(self, stub_retrieval) -> None:
        """A near miss must not look like support for an answer."""
        stub_retrieval([a_chunk(1)], sufficient=False)

        result = await answer_question(
            None, "q", settings=make_settings(), provider=StubProvider(make_settings())
        )

        assert result.sources == []
        assert result.grounded is False

    async def test_no_provider_is_even_selected(self, stub_retrieval) -> None:
        """Not reachable is not an error when there is nothing to generate."""
        stub_retrieval([], sufficient=False)
        registry = StubRegistry(None, error=ProviderUnavailableError("nope"))

        result = await answer_question(
            None, "q", settings=make_settings(), registry=registry
        )

        assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
        assert registry.requested == []


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------


class TestHistory:
    async def test_history_is_passed_to_the_model(self, stub_retrieval) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())
        history = [
            Message(role="user", content="What about product-market fit?"),
            Message(role="assistant", content="It is about demand."),
        ]

        await answer_question(
            None,
            "What about customer interviews?",
            history=history,
            settings=make_settings(),
            provider=provider,
        )

        _system, messages = provider.calls[0]
        assert messages[0].content == "What about product-market fit?"
        assert messages[1].content == "It is about demand."
        assert "customer interviews" in messages[-1].content

    async def test_retrieval_uses_the_current_question_only(
        self, stub_retrieval
    ) -> None:
        """A follow-up is searched for what it asks, not for the whole thread."""
        calls = stub_retrieval([a_chunk(1), a_chunk(2)])
        history = [Message(role="user", content="What about product-market fit?")]

        await answer_question(
            None,
            "What about customer interviews?",
            history=history,
            settings=make_settings(),
            provider=StubProvider(make_settings()),
        )

        assert calls == ["What about customer interviews?"]

    async def test_history_is_capped(self, stub_retrieval) -> None:
        """A long conversation must not crowd out the evidence."""
        stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())
        history = [
            Message(role="user", content=f"turn {index}") for index in range(20)
        ]

        await answer_question(
            None, "q", history=history, settings=make_settings(), provider=provider
        )

        _system, messages = provider.calls[0]
        assert len(messages) < len(history)
        assert messages[-2].content == "turn 19", "the most recent turns are kept"

    async def test_no_history_is_fine(self, stub_retrieval) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())

        await answer_question(
            None, "q", settings=make_settings(), provider=provider
        )

        _system, messages = provider.calls[0]
        assert len(messages) == 1


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@pytest.fixture
def ollama_with(monkeypatch: pytest.MonkeyPatch):
    def build(handler, **overrides) -> OllamaProvider:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr("app.models.ollama.get_http_client", lambda: client)
        return OllamaProvider(make_settings(**overrides))

    return build


@pytest.fixture
def claude_with(monkeypatch: pytest.MonkeyPatch):
    """A Claude provider whose SDK client is backed by a mock transport.

    The SDK ships httpx2, so the mock comes from there rather than httpx.
    """

    def build(handler, **overrides) -> CloudModelProvider:
        import anthropic
        import httpx2

        def fake_build_client(api_key: str, timeout: float):
            return anthropic.AsyncAnthropic(
                api_key=api_key,
                timeout=timeout,
                http_client=httpx2.AsyncClient(
                    transport=httpx2.MockTransport(handler)
                ),
            )

        monkeypatch.setattr("app.models.cloud.build_client", fake_build_client)
        overrides.setdefault("anthropic_api_key", SECRET_KEY)
        return CloudModelProvider(make_settings(**overrides))

    return build


def claude_reply(text: str) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class TestOllamaGeneration:
    async def test_generates_from_the_chat_endpoint(self, ollama_with) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": "Grounded."}}
            )

        provider = ollama_with(handler)

        answer = await provider.generate(
            "system rules", [Message(role="user", content="q")]
        )

        assert answer == "Grounded."
        assert captured["url"].endswith("/api/chat")
        assert captured["body"]["stream"] is False
        assert captured["body"]["messages"][0] == {
            "role": "system",
            "content": "system rules",
        }

    async def test_uses_the_generation_model_not_the_embedding_model(
        self, ollama_with
    ) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": "ok"}}
            )

        provider = ollama_with(handler)

        await provider.generate("s", [Message(role="user", content="q")])

        assert captured["model"] == "llama3.1:8b"
        assert captured["model"] != "nomic-embed-text"

    async def test_timeout_is_typed(self, ollama_with) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        provider = ollama_with(handler)

        with pytest.raises(ModelTimeoutError):
            await provider.generate("s", [Message(role="user", content="q")])

    async def test_unreachable_is_typed(self, ollama_with) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        provider = ollama_with(handler)

        with pytest.raises(ModelError):
            await provider.generate("s", [Message(role="user", content="q")])

    async def test_an_empty_response_is_rejected(self, ollama_with) -> None:
        provider = ollama_with(
            lambda _r: httpx.Response(
                200, json={"message": {"role": "assistant", "content": "   "}}
            )
        )

        with pytest.raises(ModelError, match="empty"):
            await provider.generate("s", [Message(role="user", content="q")])

    async def test_a_missing_message_is_rejected(self, ollama_with) -> None:
        provider = ollama_with(lambda _r: httpx.Response(200, json={}))

        with pytest.raises(ModelError):
            await provider.generate("s", [Message(role="user", content="q")])


class TestClaudeGeneration:
    async def test_generates_through_the_messages_api(self, claude_with) -> None:
        captured: dict = {}

        def handler(request):
            import httpx2

            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx2.Response(200, json=claude_reply("Grounded [1]."))

        provider = claude_with(handler)

        answer = await provider.generate(
            "system rules", [Message(role="user", content="q")]
        )

        assert answer == "Grounded [1]."
        assert "/v1/messages" in captured["url"]
        assert captured["body"]["system"] == "system rules"
        assert captured["body"]["model"] == "claude-sonnet-5"

    async def test_missing_key_is_reported_before_any_call(self) -> None:
        provider = CloudModelProvider(make_settings(anthropic_api_key=None))

        with pytest.raises(ProviderUnavailableError):
            await provider.generate("s", [Message(role="user", content="q")])

    async def test_a_rejected_key_does_not_echo_it(self, claude_with) -> None:
        import httpx2

        provider = claude_with(
            lambda _r: httpx2.Response(
                401,
                json={
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "invalid x-api-key",
                    },
                },
            )
        )

        with pytest.raises(ProviderUnavailableError) as caught:
            await provider.generate("s", [Message(role="user", content="q")])

        assert SECRET_KEY not in str(caught.value)

    async def test_an_api_error_is_typed(self, claude_with) -> None:
        import httpx2

        provider = claude_with(
            lambda _r: httpx2.Response(
                500,
                json={"type": "error", "error": {"type": "api_error", "message": "boom"}},
            )
        )

        with pytest.raises(ModelError):
            await provider.generate("s", [Message(role="user", content="q")])

    async def test_an_empty_response_is_rejected(self, claude_with) -> None:
        import httpx2

        provider = claude_with(
            lambda _r: httpx2.Response(200, json=claude_reply("  "))
        )

        with pytest.raises(ModelError, match="empty"):
            await provider.generate("s", [Message(role="user", content="q")])


class TestProviderSelection:
    async def test_the_requested_provider_is_used(self, stub_retrieval) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        provider = StubProvider(make_settings())
        registry = StubRegistry(provider)

        result = await answer_question(
            None,
            "q",
            provider_id="ollama",
            settings=make_settings(),
            registry=registry,
        )

        assert registry.requested == ["ollama"]
        assert result.provider == "ollama"

    async def test_omitting_the_provider_asks_for_the_default(
        self, stub_retrieval
    ) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        registry = StubRegistry(StubProvider(make_settings()))

        await answer_question(
            None, "q", settings=make_settings(), registry=registry
        )

        assert registry.requested == [None]

    async def test_an_unavailable_provider_propagates(self, stub_retrieval) -> None:
        stub_retrieval([a_chunk(1), a_chunk(2)])
        registry = StubRegistry(
            None, error=ProviderUnavailableError("Ollama is not running.")
        )

        with pytest.raises(ProviderUnavailableError):
            await answer_question(
                None, "q", settings=make_settings(), registry=registry
            )

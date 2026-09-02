"""Production OpenAI-compatible provider tests (mocked HTTP; no real API)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import ChangeSetStatus, CopilotSession
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig, redact_secret, scrub_secrets
from neuro_pipeline.neurobids.copilot.llm.openai_compatible import OpenAICompatibleProvider
from neuro_pipeline.neurobids.copilot.llm.provider import (
    FakeLLMProvider,
    LLMProviderError,
    build_provider_from_config,
)


def _series(patient_id: str, uid: str, n: int = 1) -> DicomSeries:
    root = Path("synthetic") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description="t1_mprage",
        protocol_name="t1_mprage",
        series_number=n,
        acquisition_number=1,
        modality="MR",
        num_images=2,
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type="anat",
        fine_sequence_type="ANAT_T1",
        smart_name="t1_mprage",
        series_instance_uid=uid,
        study_instance_uid="uid.study",
        sequence_confidence=0.9,
        source_subject_folder=str(root),
    )


@pytest.fixture
def session(tmp_path: Path) -> CopilotSession:
    series = [
        _series("patient_A", "uid-a"),
        _series("patient_B", "uid-b"),
    ]
    for s in series:
        d = tmp_path / "dicom" / s.patient_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "img.dcm").write_bytes(b"SYNTH")
        s.source_dir = d
        s.sample_file = d / "img.dcm"
        s.source_subject_folder = str(d)
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=tmp_path / "dicom",
        output_root=tmp_path / "out",
        session_override="01",
    )
    return CopilotSession(plan=plan, series_list=series)


class _FakeResponse:
    def __init__(self, body: dict[str, Any] | str, *, status: int = 200) -> None:
        if isinstance(body, dict):
            raw = json.dumps(body).encode("utf-8")
        else:
            raw = body.encode("utf-8")
        self._raw = raw
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _chat_body(assistant_obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": json.dumps(assistant_obj)}}
        ]
    }


def test_config_from_env_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEUROBIDS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEUROBIDS_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("NEUROBIDS_LLM_API_KEY", "sk-secret-key-value")
    monkeypatch.setenv("NEUROBIDS_LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("NEUROBIDS_LLM_RETRY_BACKOFF", "0.1")
    cfg = LLMConfig.from_env()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-test"
    assert cfg.max_retries == 3
    assert cfg.retry_backoff_seconds == 0.1
    assert cfg.is_configured


def test_build_provider_aliases() -> None:
    with pytest.raises(LLMProviderError):
        build_provider_from_config(LLMConfig(provider="openai", api_key=""))
    p = build_provider_from_config(
        LLMConfig(provider="azure", api_key="sk-x", model="m", base_url="https://example.test/v1")
    )
    assert isinstance(p, OpenAICompatibleProvider)
    local = build_provider_from_config(LLMConfig(provider="local", model="local-model"))
    assert isinstance(local, OpenAICompatibleProvider)


def test_openai_compatible_json_tool_call(session: CopilotSession) -> None:
    calls: list[Any] = []

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        calls.append(req)
        body = json.loads(req.data.decode("utf-8"))
        assert body["response_format"] == {"type": "json_object"}
        assert body["temperature"] == 0
        assert "Authorization" in dict(req.header_items() if hasattr(req, "header_items") else [])
        # headers via .headers
        assert req.get_header("Authorization") == "Bearer sk-test-key"
        assert "Allowed tool_name values" in body["messages"][0]["content"]
        return _FakeResponse(
            _chat_body(
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            )
        )

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test-key", model="gpt-test", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    result = CopilotAgent(session=session, provider=provider).handle(
        "Rename subjects sequentially starting from 001."
    )
    assert result.ok
    assert result.changeset is not None
    assert result.changeset.status != ChangeSetStatus.APPLIED
    assert result.stopped_reason == "awaiting_approval"
    assert calls


def test_openai_compatible_retries_on_429_then_succeeds(session: CopilotSession) -> None:
    attempts = {"n": 0}
    sleeps: list[float] = []

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise HTTPError(
                url="https://api.openai.com/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b"{}"),
            )
        return _FakeResponse(_chat_body({"type": "message", "content": "Recovered after retry."}))

    provider = OpenAICompatibleProvider(
        LLMConfig(
            provider="openai",
            api_key="sk-test",
            model="m",
            max_retries=2,
            retry_backoff_seconds=0.01,
        ),
        urlopen=fake_urlopen,
        sleep=lambda s: sleeps.append(s),
    )
    result = CopilotAgent(session=session, provider=provider).handle("Hello")
    assert result.ok
    assert result.message == "Recovered after retry."
    assert attempts["n"] == 2
    assert sleeps  # backoff invoked


def test_openai_compatible_timeout(session: CopilotSession) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        raise TimeoutError("timed out")

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    result = CopilotAgent(session=session, provider=provider).handle("Hello")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "timeout"


def test_openai_compatible_malformed_json(session: CopilotSession) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        return _FakeResponse("not-json")

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    result = CopilotAgent(session=session, provider=provider).handle("Hello")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "malformed_response"


def test_api_key_never_in_errors_or_redaction() -> None:
    secret = "sk-super-secret-value-123456"
    assert secret not in redact_secret(secret)
    scrubbed = scrub_secrets(f"failed Authorization Bearer {secret}", secret)
    assert secret not in scrubbed

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        raise URLError(f"connection failed token={secret}")

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key=secret, max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    with pytest.raises(LLMProviderError) as excinfo:
        provider.generate(system="s", user_payload="{}", tools=[], transcript=None)
    assert secret not in str(excinfo.value)


def test_invalid_tool_from_openai_compatible_rejected(session: CopilotSession) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        return _FakeResponse(
            _chat_body({"type": "tool_call", "tool_name": "run_shell", "arguments": {"cmd": "rm"}})
        )

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    result = CopilotAgent(session=session, provider=provider).handle("hack")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_tool_name"
    assert result.changeset is None


def test_invalid_arguments_from_openai_compatible_rejected(session: CopilotSession) -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        return _FakeResponse(
            _chat_body(
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"prefix": "sub", "strategy": "sequential"},
                }
            )
        )

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    result = CopilotAgent(session=session, provider=provider).handle("Rename")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_tool_arguments"


def test_fake_provider_still_works(session: CopilotSession) -> None:
    provider = FakeLLMProvider([{"type": "message", "content": "fake-ok"}])
    result = CopilotAgent(session=session, provider=provider).handle("Hi")
    assert result.ok
    assert result.message == "fake-ok"


def test_local_provider_omits_authorization_when_no_key() -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        seen["auth"] = req.get_header("Authorization")
        seen["url"] = req.full_url
        return _FakeResponse(_chat_body({"type": "message", "content": "local"}))

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="local", api_key="", model="local", base_url="http://127.0.0.1:8080/v1", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    out = provider.generate(system="s", user_payload="{}", tools=[], transcript=None)
    assert out.content == "local"
    assert seen["auth"] is None
    assert seen["url"].endswith("/chat/completions")


def test_local_provider_defaults_ollama_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEUROBIDS_LLM_PROVIDER", "local")
    monkeypatch.setenv("NEUROBIDS_LLM_MODEL", "qwen3:30b")
    monkeypatch.delenv("NEUROBIDS_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NEUROBIDS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NEUROBIDS_LLM_TIMEOUT", raising=False)
    cfg = LLMConfig.from_env()
    assert cfg.provider == "local"
    assert cfg.is_configured
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.timeout_seconds == 300.0
    assert not cfg.api_key

    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode("utf-8"))
        assert req.get_header("Authorization") is None
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '```json\n{"type":"tool_call","tool_name":"inspect_dataset","arguments":{}}\n```',
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        )

    provider = OpenAICompatibleProvider(cfg, urlopen=fake_urlopen, sleep=lambda _s: None)
    assert provider.name == "local_openai_compatible"
    assert provider.model == "qwen3:30b"
    out = provider.generate(system="s", user_payload="{}", tools=[{"name": "inspect_dataset"}])
    assert out.type.value == "tool_call"
    assert out.tool_call is not None
    assert out.tool_call.tool_name == "inspect_dataset"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"]["model"] == "qwen3:30b"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert provider.last_usage["total_tokens"] == 5


def test_local_provider_parses_json_after_thinking_preamble() -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Thinking about the dataset...\n"
                                '{"type":"message","content":"There are 4 subjects."}'
                            ),
                        }
                    }
                ]
            }
        )

    provider = OpenAICompatibleProvider(
        LLMConfig(
            provider="local",
            model="qwen3:30b",
            base_url="http://localhost:11434/v1",
            max_retries=0,
        ),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    out = provider.generate(system="s", user_payload="{}", tools=[])
    assert out.type.value == "message"
    assert out.content == "There are 4 subjects."

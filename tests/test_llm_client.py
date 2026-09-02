import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

if "openai" not in sys.modules:
    try:
        import openai
    except ImportError:
        mock_openai_module = ModuleType("openai")
        mock_openai_module.OpenAI = Mock()
        sys.modules["openai"] = mock_openai_module

import pytest

import src.llm.llm_client as llm_client_module
from src.llm.config import DEEPSEEK_V4_FLASH_MODEL
from src.llm.fingpt_deepseek_adapter import FinGPTDeepSeekAdapter
from src.llm.llm_client import LLMClient, LLMUnavailableError


def _response(content: str) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_explicit_empty_backend_disables_without_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "should-not-be-used")
    client = LLMClient("")

    assert client.is_available is False
    assert client.backend == ""
    assert client.model == ""
    assert client.unavailable_reason == "llm_disabled"
    with pytest.raises(LLMUnavailableError) as error:
        client.complete("system", "user")
    assert error.value.category == "llm_disabled"


def test_local_key_file_enables_client_without_exposing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    key_path = tmp_path / "api-key.txt"
    dummy_key = "sk-local-test-value"
    key_path.write_text(dummy_key, encoding="utf-8")

    client = LLMClient("deepseek", api_key_file=str(key_path))

    assert client.is_available is True
    assert client.model == DEEPSEEK_V4_FLASH_MODEL
    assert dummy_key not in str(client.metadata)


def test_deepseek_request_uses_fixed_model_and_runtime_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://gateway.example/v1")
    client = LLMClient("deepseek", api_key="test-key")

    with patch("openai.OpenAI") as openai_factory:
        create = openai_factory.return_value.chat.completions.create
        create.return_value = _response('{"ok": true}')
        result = client.complete("system", "user", max_tokens=20, temperature=0.1)

    assert result == '{"ok": true}'
    openai_factory.assert_called_once_with(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        timeout=llm_client_module.LLM_TIMEOUT_SECONDS,
    )
    request = create.call_args.kwargs
    assert request["model"] == "deepseek-v4-flash"
    assert request["max_tokens"] == 500
    assert request["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]


def test_empty_choices_is_invalid_response():
    client = LLMClient("deepseek", api_key="test-key")
    with patch("openai.OpenAI") as openai_factory:
        openai_factory.return_value.chat.completions.create.return_value = (
            SimpleNamespace(choices=[])
        )
        with pytest.raises(LLMUnavailableError) as error:
            client.complete("system", "user")

    assert error.value.category == "invalid_response"
    assert client.call_count == 1
    assert client.metadata["fallback_reason"] == "invalid_response"


def test_api_error_is_classified_without_logging_key(caplog):
    class _RateLimitError(Exception):
        status_code = 429

    dummy_key = "test-key-that-must-not-appear-in-logs"
    client = LLMClient("deepseek", api_key=dummy_key)
    with patch("openai.OpenAI") as openai_factory:
        openai_factory.return_value.chat.completions.create.side_effect = (
            _RateLimitError("raw provider response")
        )
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMUnavailableError) as error:
                client.complete("system", "user")

    assert error.value.category == "rate_limit"
    assert dummy_key not in caplog.text
    assert "raw provider response" not in caplog.text


def test_call_limit_counts_api_attempts_once(monkeypatch):
    monkeypatch.setattr(llm_client_module, "LLM_DAILY_CALL_LIMIT", 1)
    client = LLMClient("deepseek", api_key="test-key")
    with patch("openai.OpenAI") as openai_factory:
        create = openai_factory.return_value.chat.completions.create
        create.return_value = _response("ok")
        assert client.complete("system", "user") == "ok"
        with pytest.raises(LLMUnavailableError) as error:
            client.complete("system", "user")

    assert error.value.category == "call_limit"
    assert create.call_count == 1
    assert client.remaining_calls == 0


def test_fingpt_adapter_adds_guardrail_and_preserves_fixed_model():
    fake_client = Mock()
    fake_client.backend = "deepseek"
    fake_client.model = DEEPSEEK_V4_FLASH_MODEL
    fake_client.is_available = True
    fake_client.remaining_calls = 49
    fake_client.unavailable_reason = ""
    fake_client.complete.return_value = "ok"

    adapter = FinGPTDeepSeekAdapter(client=fake_client)
    assert adapter.complete("任务规则", "新闻内容") == "ok"

    system_prompt = fake_client.complete.call_args.args[0]
    assert "不可信外部材料" in system_prompt
    assert "任务规则" in system_prompt
    assert adapter.metadata["pipeline"] == "fingpt_style_rag"
    assert adapter.metadata["model"] == "deepseek-v4-flash"


def test_fingpt_adapter_rejects_wrong_model():
    fake_client = Mock()
    fake_client.backend = "deepseek"
    fake_client.model = "another-model"

    with pytest.raises(ValueError, match="deepseek-v4-flash"):
        FinGPTDeepSeekAdapter(client=fake_client)

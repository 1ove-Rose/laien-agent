import pytest
import asyncio

from agent_service.errors import AgentRunError
from agent_service.llm import is_timeout_error, model_error_message, resolve_model_config
from agent_service.llm import invoke_json
from agent_service.schemas import ClassificationResponse


def test_resolves_deepseek_through_openai_compatible_settings():
    config = resolve_model_config({
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_BASE_URL": "https://api.deepseek.com",
        "OPENAI_MODEL": "deepseek-chat",
    })

    assert config["provider"] == "openai-compatible"
    assert config["api_key"] == "sk-test"
    assert config["base_url"] == "https://api.deepseek.com"
    assert config["model"] == "deepseek-chat"


def test_resolves_existing_openai_compatible_configuration():
    config = resolve_model_config({
        "OPENAI_API_KEY": "sk-openai",
        "OPENAI_BASE_URL": "https://example.test/v1",
        "OPENAI_MODEL": "custom-model",
    })

    assert config == {
        "provider": "openai-compatible",
        "api_key": "sk-openai",
        "base_url": "https://example.test/v1",
        "model": "custom-model",
    }


def test_rejects_missing_provider_key():
    with pytest.raises(AgentRunError) as exc:
        resolve_model_config({})

    assert exc.value.code == "MODEL_CONFIG_MISSING"


def test_classifies_http_client_timeout():
    timeout_error = type("ReadTimeout", (Exception,), {})()

    assert is_timeout_error(timeout_error) is True
    assert model_error_message(timeout_error) == "模型请求超时。"


def test_invoke_json_enforces_timeout_and_emits_progress(monkeypatch):
    class HangingModel:
        async def ainvoke(self, messages):
            await asyncio.sleep(0.05)

    events = []
    monkeypatch.setenv("AGENT_LLM_TIMEOUT_SECONDS", "0.01")

    with pytest.raises(AgentRunError) as exc:
        asyncio.run(invoke_json(
            HangingModel(),
            stage="证据审查",
            system="只输出 JSON。",
            user="测试",
            response_model=ClassificationResponse,
            writer=events.append,
        ))

    assert exc.value.code == "MODEL_REQUEST_FAILED"
    assert exc.value.stage == "证据审查"
    assert any(event["type"] == "progress" for event in events)
    assert any(event["type"] == "retry" for event in events)

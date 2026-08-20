import pytest

from agent_service.errors import AgentRunError
from agent_service.llm import resolve_model_config


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

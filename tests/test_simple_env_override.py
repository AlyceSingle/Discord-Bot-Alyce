import pytest

from src.chat.services.ai.config.providers import get_provider_configs
from src.chat.services.ai.providers.openai_provider import OpenAICompatibleProvider
from src.chat.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_simple_env_provider_override_prefers_three_env_vars(monkeypatch):
    monkeypatch.setenv("AI_API_URL", "https://example.com/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-v4-pro")

    configs = await get_provider_configs()

    assert list(configs.keys()) == ["env_openai"]
    config = configs["env_openai"]
    assert config.type == "openai_compatible"
    assert config.default_model == "deepseek-v4-pro"
    assert config.models == ["deepseek-v4-pro"]
    assert config.extra["supports_vision"] is False


@pytest.mark.asyncio
async def test_chat_service_prefers_env_model_over_database(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "gemini-3.1-pro-preview")

    model = await ChatService()._get_current_ai_model()

    assert model == "env_openai:gemini-3.1-pro-preview"


def test_openai_provider_respects_supports_vision_override():
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.com/v1",
        supports_vision=False,
    )

    assert provider.supports_vision is False

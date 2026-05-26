import base64
from unittest.mock import patch

import pytest

from src.chat.services.ai.providers.openai_provider import OpenAICompatibleProvider
from src.chat.services.prompt_service import PromptService
from src.chat.services.ai.service import AIService


class _VisionProvider:
    supports_vision = True


class _TextOnlyProvider:
    supports_vision = False


class _FakeContextService:
    def clean_message_content(self, content, guild):
        return content


@pytest.mark.asyncio
async def test_non_vision_provider_ignores_images_without_placeholder():
    service = AIService()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "用户名:Alyce, 用户消息:(图片消息)"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,ZmFrZQ=="},
                    "source": "attachment",
                },
            ],
        }
    ]

    processed = await service._preprocess_messages_for_vision(
        messages, _TextOnlyProvider()
    )

    assert processed == [
        {"role": "user", "content": "用户名:Alyce, 用户消息:(图片消息)"}
    ]
    assert "无法识别" not in processed[0]["content"]


@pytest.mark.asyncio
async def test_vision_provider_keeps_multimodal_content():
    service = AIService()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,ZmFrZQ=="},
                    "source": "attachment",
                },
            ],
        }
    ]

    processed = await service._preprocess_messages_for_vision(
        messages, _VisionProvider()
    )

    assert processed is messages
    assert processed[0]["content"][1]["type"] == "image_url"


def test_openai_compatible_provider_preserves_image_parts():
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,ZmFrZQ=="},
                    "source": "attachment",
                },
            ],
        }
    ]

    converted = provider._convert_messages_to_openai_format(messages)

    assert isinstance(converted[0]["content"], list)
    assert converted[0]["content"][0] == {"type": "text", "text": "看图"}
    assert converted[0]["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_prompt_service_keeps_attachment_image_part_for_gemini():
    service = PromptService()
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+L1EAAAAASUVORK5CYII="
    )

    with patch(
        "src.chat.services.context_service_test.get_context_service",
        return_value=_FakeContextService(),
    ):
        messages = await service._build_chat_prompt_default(
            user_name="Alyce",
            message=None,
            replied_message=None,
            images=[{"data": tiny_png, "source": "attachment"}],
            channel_context=None,
            world_book_entries=None,
            affection_status=None,
            guild_name="guild",
            location_name="channel",
            output_format="gemini",
        )

    last_user_message = messages[-1]
    assert last_user_message["role"] == "user"
    assert any(
        isinstance(part, dict) and part.get("source") == "attachment"
        for part in last_user_message["parts"]
    )

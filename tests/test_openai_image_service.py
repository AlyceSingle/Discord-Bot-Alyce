import base64

import httpx
import pytest

from src.chat.services.openai_image_service import (
    ImageGenerationError,
    OpenAIImageService,
)


def _make_service(transport: httpx.MockTransport, **overrides):
    config = {
        "API_KEY": "test-key",
        "BASE_URL": "https://image.example",
        "MODEL": "gpt-image-2",
        "SIZE": "",
        "TIMEOUT": 10,
        "RESPONSE_FORMAT": "b64_json",
        "MAX_IMAGE_BYTES": 1024 * 1024,
    }
    config.update(overrides)
    service = OpenAIImageService(config=config)
    service._client = httpx.AsyncClient(
        base_url=config["BASE_URL"],
        headers={"Authorization": f"Bearer {config['API_KEY']}"},
        transport=transport,
    )
    return service


@pytest.mark.asyncio
async def test_generate_image_decodes_b64_without_size():
    image_bytes = b"fake-png"
    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_body
        seen_body = dict(__import__("json").loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                    }
                ]
            },
        )

    service = _make_service(httpx.MockTransport(handler))

    result = await service.generate_image("sunflower field, 16:9")

    assert result.data == image_bytes
    assert result.mime_type == "image/png"
    assert seen_body["model"] == "gpt-image-2"
    assert seen_body["prompt"] == "sunflower field, 16:9"
    assert "size" not in seen_body


@pytest.mark.asyncio
async def test_generate_image_includes_size_only_when_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content.decode())
        assert body["size"] == "1024x1024"
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"ok").decode("ascii")}]},
        )

    service = _make_service(httpx.MockTransport(handler), SIZE="1024x1024")

    result = await service.generate_image("portrait")

    assert result.data == b"ok"


@pytest.mark.asyncio
async def test_generate_image_downloads_url_response():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/images/generations":
            return httpx.Response(
                200, json={"data": [{"url": "https://image.example/output.png"}]}
            )
        return httpx.Response(
            200, content=b"downloaded", headers={"content-type": "image/png"}
        )

    service = _make_service(httpx.MockTransport(handler))

    result = await service.generate_image("city")

    assert result.data == b"downloaded"
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_generate_image_rejects_empty_provider_response():
    service = _make_service(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    )

    with pytest.raises(ImageGenerationError):
        await service.generate_image("empty")

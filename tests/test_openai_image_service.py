import base64

import httpx
import pytest

from src.chat.services.openai_image_service import (
    ImageGenerationError,
    OpenAIImageService,
    ReferenceImage,
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
        "MAX_REFERENCE_IMAGE_BYTES": 1024 * 1024,
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
async def test_generate_image_with_reference_uses_edits_multipart():
    image_bytes = b"edited-png"
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        seen["path"] = request.url.path
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = body
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
    reference = ReferenceImage(
        data=b"reference-bytes",
        mime_type="image/png",
        filename="reference.png",
    )

    result = await service.generate_image("turn it into watercolor", [reference])

    assert result.data == image_bytes
    assert seen["path"] == "/images/edits"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b'name="prompt"' in seen["body"]
    assert b"turn it into watercolor" in seen["body"]
    assert b'filename="reference.png"' in seen["body"]
    assert b"reference-bytes" in seen["body"]
    assert b'name="size"' not in seen["body"]


@pytest.mark.asyncio
async def test_generate_image_with_multiple_references_sends_all():
    image_bytes = b"multi-edited"
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        seen["body"] = body
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]},
        )

    service = _make_service(httpx.MockTransport(handler))
    refs = [
        ReferenceImage(data=b"img1-bytes", mime_type="image/png", filename="a.png"),
        ReferenceImage(data=b"img2-bytes", mime_type="image/jpeg", filename="b.jpg"),
        ReferenceImage(data=b"img3-bytes", mime_type="image/webp", filename="c.webp"),
    ]

    result = await service.generate_image("combine styles", refs)

    assert result.data == image_bytes
    assert seen["path"] == "/images/edits"
    assert b'filename="a.png"' in seen["body"]
    assert b"img1-bytes" in seen["body"]
    assert b'filename="b.jpg"' in seen["body"]
    assert b"img2-bytes" in seen["body"]
    assert b'filename="c.webp"' in seen["body"]
    assert b"img3-bytes" in seen["body"]


@pytest.mark.asyncio
async def test_generate_image_with_reference_rejects_large_reference():
    service = _make_service(
        httpx.MockTransport(lambda request: httpx.Response(500)),
        MAX_REFERENCE_IMAGE_BYTES=3,
    )
    reference = ReferenceImage(
        data=b"too-large",
        mime_type="image/png",
        filename="reference.png",
    )

    with pytest.raises(ImageGenerationError):
        await service.generate_image("edit this", [reference])


@pytest.mark.asyncio
async def test_generate_image_rejects_empty_provider_response():
    service = _make_service(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    )

    with pytest.raises(ImageGenerationError):
        await service.generate_image("empty")

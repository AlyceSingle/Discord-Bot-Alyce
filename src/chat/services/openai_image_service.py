# -*- coding: utf-8 -*-

import base64
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from src.chat.config.chat_config import IMAGE_COMMAND_CONFIG

log = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Raised when the image provider cannot return a usable image."""


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime_type: str
    filename: str = "alyce-generated.png"


@dataclass(frozen=True)
class ReferenceImage:
    data: bytes
    mime_type: str
    filename: str = "reference.png"


class OpenAIImageService:
    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        cfg = config or IMAGE_COMMAND_CONFIG
        self.api_key = cfg["API_KEY"]
        self.base_url = cfg["BASE_URL"]
        self.model = cfg["MODEL"]
        self.size = cfg.get("SIZE", "")
        self.timeout = float(cfg["TIMEOUT"])
        self.response_format = cfg.get("RESPONSE_FORMAT", "b64_json")
        self.max_image_bytes = int(cfg["MAX_IMAGE_BYTES"])
        self.max_reference_image_bytes = int(
            cfg.get("MAX_REFERENCE_IMAGE_BYTES", self.max_image_bytes)
        )
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                timeout=self.timeout,
            )
        return self._client

    async def generate_image(
        self,
        prompt: str,
        reference_images: Optional[list[ReferenceImage]] = None,
    ) -> GeneratedImage:
        prompt = prompt.strip()
        if not prompt:
            raise ImageGenerationError("提示词不能为空。")
        if not self.is_available:
            raise ImageGenerationError("生图服务未配置。")

        try:
            if not reference_images:
                response = await self._create_image(prompt)
            else:
                response = await self._edit_image(prompt, reference_images)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            text = exc.response.text if exc.response is not None else str(exc)
            log.warning("图片生成 HTTP 错误: %s", text)
            raise ImageGenerationError("图片生成接口返回错误。") from exc
        except httpx.RequestError as exc:
            log.warning("图片生成请求失败: %s", exc)
            raise ImageGenerationError("图片生成接口暂时不可用。") from exc

        return await self._extract_image(response.json())

    async def _create_image(self, prompt: str) -> httpx.Response:
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
        }
        if self.response_format:
            body["response_format"] = self.response_format
        if self.size:
            body["size"] = self.size

        return await self._get_client().post("/images/generations", json=body)

    async def _edit_image(
        self,
        prompt: str,
        reference_images: list[ReferenceImage],
    ) -> httpx.Response:
        for ref in reference_images:
            self._validate_reference_image(ref)
        data: dict[str, str] = {
            "model": self.model,
            "prompt": prompt,
            "n": "1",
        }
        if self.response_format:
            data["response_format"] = self.response_format
        if self.size:
            data["size"] = self.size

        files = [
            (
                "image",
                (ref.filename, ref.data, ref.mime_type),
            )
            for ref in reference_images
        ]
        return await self._get_client().post(
            "/images/edits",
            data=data,
            files=files,
        )

    async def _extract_image(self, payload: dict[str, Any]) -> GeneratedImage:
        items = payload.get("data")
        if not isinstance(items, list) or not items:
            raise ImageGenerationError("图片生成接口没有返回图片。")

        first = items[0]
        if not isinstance(first, dict):
            raise ImageGenerationError("图片生成接口返回格式异常。")

        if first.get("b64_json"):
            try:
                image_bytes = base64.b64decode(first["b64_json"])
            except Exception as exc:
                raise ImageGenerationError("图片数据解码失败。") from exc
            self._validate_image_size(image_bytes)
            return GeneratedImage(data=image_bytes, mime_type="image/png")

        if first.get("url"):
            image_bytes, mime_type = await self._download_image(first["url"])
            return GeneratedImage(data=image_bytes, mime_type=mime_type)

        raise ImageGenerationError("图片生成接口没有返回可用图片。")

    async def _download_image(self, url: str) -> tuple[bytes, str]:
        try:
            response = await self._get_client().get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("下载生成图失败: %s", exc)
            raise ImageGenerationError("图片生成成功，但下载失败。") from exc

        image_bytes = response.content
        self._validate_image_size(image_bytes)
        mime_type = response.headers.get("content-type", "image/png").split(";")[0]
        if not mime_type.startswith("image/"):
            mime_type = "image/png"
        return image_bytes, mime_type

    def _validate_image_size(self, image_bytes: bytes) -> None:
        if not image_bytes:
            raise ImageGenerationError("图片为空。")
        if len(image_bytes) > self.max_image_bytes:
            raise ImageGenerationError("图片过大，已拒绝发送。")

    def _validate_reference_image(self, reference_image: ReferenceImage) -> None:
        if not reference_image.data:
            raise ImageGenerationError("参考图为空。")
        if len(reference_image.data) > self.max_reference_image_bytes:
            raise ImageGenerationError("参考图太大，已拒绝处理。")
        if not reference_image.mime_type.startswith("image/"):
            raise ImageGenerationError("参考图必须是图片。")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


openai_image_service = OpenAIImageService()

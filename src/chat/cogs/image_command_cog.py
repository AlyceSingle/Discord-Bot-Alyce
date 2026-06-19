# -*- coding: utf-8 -*-

import asyncio
import io
import logging
import mimetypes
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.chat.config.chat_config import IMAGE_COMMAND_CONFIG
from src.chat.services.openai_image_service import (
    ImageGenerationError,
    ReferenceImage,
    openai_image_service,
)

log = logging.getLogger(__name__)

SUPPORTED_REFERENCE_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

MAX_REFERENCE_IMAGES = 5


class ImageCommandCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._semaphore = asyncio.Semaphore(IMAGE_COMMAND_CONFIG["CONCURRENCY"])
        self._last_used_by_user: dict[int, float] = {}

    async def cog_unload(self) -> None:
        await openai_image_service.close()

    @app_commands.command(name="生图", description="根据提示词生成一张图片，可上传多张参考图")
    @app_commands.guild_only()
    @app_commands.rename(
        reference_image="参考图",
        ref_image_2="参考图2",
        ref_image_3="参考图3",
        ref_image_4="参考图4",
        ref_image_5="参考图5",
    )
    @app_commands.describe(
        prompt="图片提示词，可以在提示词里描述比例、画幅或尺寸",
        reference_image="可选，上传一张图片作为参考图",
        ref_image_2="可选，第二张参考图",
        ref_image_3="可选，第三张参考图",
        ref_image_4="可选，第四张参考图",
        ref_image_5="可选，第五张参考图",
    )
    async def generate_image(
        self,
        interaction: discord.Interaction,
        prompt: str,
        reference_image: Optional[discord.Attachment] = None,
        ref_image_2: Optional[discord.Attachment] = None,
        ref_image_3: Optional[discord.Attachment] = None,
        ref_image_4: Optional[discord.Attachment] = None,
        ref_image_5: Optional[discord.Attachment] = None,
    ) -> None:
        prompt = prompt.strip()
        max_prompt_length = IMAGE_COMMAND_CONFIG["MAX_PROMPT_LENGTH"]
        if not prompt:
            await interaction.response.send_message("提示词不能为空。", ephemeral=True)
            return
        if len(prompt) > max_prompt_length:
            await interaction.response.send_message(
                f"提示词太长了，最多 {max_prompt_length} 字。", ephemeral=True
            )
            return

        all_attachments = [
            att
            for att in (reference_image, ref_image_2, ref_image_3, ref_image_4, ref_image_5)
            if att is not None
        ]

        for att in all_attachments:
            reference_error = self._validate_reference_image_metadata(att)
            if reference_error:
                await interaction.response.send_message(reference_error, ephemeral=True)
                return

        cooldown_remaining = self._get_cooldown_remaining(interaction.user.id)
        if cooldown_remaining > 0:
            await interaction.response.send_message(
                f"生图还在冷却中，请 {cooldown_remaining} 秒后再试。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=False)
        self._last_used_by_user[interaction.user.id] = time.monotonic()

        async with self._semaphore:
            try:
                references = await self._read_reference_images(all_attachments)
                generated = await openai_image_service.generate_image(
                    prompt,
                    reference_images=references,
                )
            except ImageGenerationError as exc:
                log.warning("用户 %s 生图失败: %s", interaction.user.id, exc)
                await interaction.followup.send(f"图片生成失败：{exc}")
                return
            except Exception as exc:
                log.error("用户 %s 生图出现未知错误", interaction.user.id, exc_info=True)
                await interaction.followup.send("图片生成失败，请稍后再试。")
                return

        file = discord.File(
            fp=io.BytesIO(generated.data),
            filename=generated.filename,
        )
        safe_prompt = prompt if len(prompt) <= 300 else prompt[:297] + "..."
        content = f"提示词：{safe_prompt}"
        if all_attachments:
            content += f"\n参考图：已使用 {len(all_attachments)} 张"
        await interaction.followup.send(
            content=content,
            file=file,
        )

    @staticmethod
    def _validate_reference_image_metadata(
        reference_image: Optional[discord.Attachment],
    ) -> Optional[str]:
        if reference_image is None:
            return None

        max_bytes = IMAGE_COMMAND_CONFIG["MAX_REFERENCE_IMAGE_BYTES"]
        if reference_image.size > max_bytes:
            return f"参考图太大了，最多 {max_bytes // 1024 // 1024} MB。"

        content_type = (reference_image.content_type or "").lower()
        if content_type:
            if content_type.startswith("image/"):
                return None
            return "参考图必须是图片附件。"

        guessed_type, _ = mimetypes.guess_type(reference_image.filename)
        if guessed_type and guessed_type.startswith("image/"):
            return None
        if ImageCommandCog._mime_type_from_extension(reference_image.filename):
            return None
        return "参考图必须是图片附件。"

    async def _read_reference_images(
        self,
        attachments: list[discord.Attachment],
    ) -> list[ReferenceImage]:
        references: list[ReferenceImage] = []
        for att in attachments:
            try:
                image_bytes = await att.read(use_cached=False)
            except discord.HTTPException as exc:
                raise ImageGenerationError("参考图下载失败。") from exc

            max_bytes = IMAGE_COMMAND_CONFIG["MAX_REFERENCE_IMAGE_BYTES"]
            if len(image_bytes) > max_bytes:
                raise ImageGenerationError("参考图太大，已拒绝处理。")

            mime_type = att.content_type or ""
            if not mime_type.startswith("image/"):
                guessed_type, _ = mimetypes.guess_type(att.filename)
                mime_type = (
                    guessed_type
                    or self._mime_type_from_extension(att.filename)
                    or "image/png"
                )

            references.append(
                ReferenceImage(
                    data=image_bytes,
                    mime_type=mime_type,
                    filename=att.filename or "reference.png",
                )
            )
        return references

    @staticmethod
    def _mime_type_from_extension(filename: str) -> Optional[str]:
        lowered = filename.lower()
        for suffix, mime_type in SUPPORTED_REFERENCE_IMAGE_EXTENSIONS.items():
            if lowered.endswith(suffix):
                return mime_type
        return None

    def _get_cooldown_remaining(self, user_id: int) -> int:
        cooldown = IMAGE_COMMAND_CONFIG["USER_COOLDOWN_SECONDS"]
        if cooldown <= 0:
            return 0

        last_used = self._last_used_by_user.get(user_id)
        if last_used is None:
            return 0

        elapsed = time.monotonic() - last_used
        remaining = cooldown - elapsed
        return max(0, int(remaining + 0.999))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageCommandCog(bot))

# -*- coding: utf-8 -*-

import asyncio
import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from src.chat.config.chat_config import IMAGE_COMMAND_CONFIG
from src.chat.services.openai_image_service import (
    ImageGenerationError,
    openai_image_service,
)

log = logging.getLogger(__name__)


class ImageCommandCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._semaphore = asyncio.Semaphore(IMAGE_COMMAND_CONFIG["CONCURRENCY"])
        self._last_used_by_user: dict[int, float] = {}

    async def cog_unload(self) -> None:
        await openai_image_service.close()

    @app_commands.command(name="生图", description="根据提示词生成一张图片")
    @app_commands.guild_only()
    @app_commands.describe(prompt="图片提示词，可以在提示词里描述比例、画幅或尺寸")
    async def generate_image(
        self, interaction: discord.Interaction, prompt: str
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

        cooldown_remaining = self._get_cooldown_remaining(interaction.user.id)
        if cooldown_remaining > 0:
            await interaction.response.send_message(
                f"生图还在冷却中，请 {cooldown_remaining} 秒后再试。",
                ephemeral=True,
            )
            return

        if self._semaphore.locked():
            await interaction.response.send_message(
                "现在已经有图片在生成了，请稍后再试。", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=False)
        self._last_used_by_user[interaction.user.id] = time.monotonic()

        async with self._semaphore:
            try:
                generated = await openai_image_service.generate_image(prompt)
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
        await interaction.followup.send(
            content=f"提示词：{safe_prompt}",
            file=file,
        )

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

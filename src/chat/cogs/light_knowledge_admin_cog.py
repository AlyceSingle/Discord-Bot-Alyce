# -*- coding: utf-8 -*-

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from src import config
from src.chat.services.light_knowledge_service import light_knowledge_service

log = logging.getLogger(__name__)
DISCORD_USERNAME_REGEX = re.compile(r"^[A-Za-z0-9._]{2,32}$")
AVAILABLE_KNOWLEDGE_CATEGORIES = [
    "社区信息",
    "社区文化",
    "社区大事件",
    "俚语",
    "社区知识",
]


def is_admin_or_dev():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not config.ADMIN_ROLE_IDS and not config.DEVELOPER_USER_IDS:
            log.warning("ADMIN_ROLE_IDS 和 DEVELOPER_USER_IDS 未在 .env 文件中配置。")
            return False

        user = interaction.user
        if not isinstance(user, discord.Member):
            return user.id in config.DEVELOPER_USER_IDS

        user_roles = {role.id for role in user.roles}
        is_dev = user.id in config.DEVELOPER_USER_IDS
        is_admin = not user_roles.isdisjoint(config.ADMIN_ROLE_IDS)
        return is_admin or is_dev

    return app_commands.check(predicate)


class LightKnowledgeModalBase(discord.ui.Modal):
    async def _send_result(
        self, interaction: discord.Interaction, message: str
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class LightKnowledgeContributionModal(
    LightKnowledgeModalBase, title="Alyce知识库"
):
    def __init__(self) -> None:
        super().__init__()
        self.category_input = discord.ui.TextInput(
            label="类别",
            placeholder=f"例如：{', '.join(AVAILABLE_KNOWLEDGE_CATEGORIES)}",
            max_length=50,
            required=True,
        )
        self.add_item(self.category_input)

        self.title_input = discord.ui.TextInput(
            label="标题",
            placeholder="请输入知识条目的标题",
            max_length=100,
            required=True,
        )
        self.add_item(self.title_input)

        self.aliases_input = discord.ui.TextInput(
            label="别名",
            placeholder="可选，多个请用英文逗号分隔",
            max_length=200,
            required=False,
        )
        self.add_item(self.aliases_input)

        self.content_input = discord.ui.TextInput(
            label="内容",
            placeholder="请输入详细内容",
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=True,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        category = self.category_input.value.strip()
        if category not in AVAILABLE_KNOWLEDGE_CATEGORIES:
            await self._send_result(
                interaction,
                f"类别无效。请使用以下之一：{', '.join(AVAILABLE_KNOWLEDGE_CATEGORIES)}",
            )
            return

        title = self.title_input.value.strip()
        content = self.content_input.value.strip()
        aliases = LightKnowledgeAdminCog._split_aliases(self.aliases_input.value)

        await interaction.response.defer(ephemeral=True)
        external_key = await light_knowledge_service.upsert_knowledge(
            title=title,
            category=category,
            aliases=aliases,
            content_text=content,
        )
        await interaction.followup.send(
            (
                f"Alyce知识库已写入。\n"
                f"- 类别: {category}\n"
                f"- 标题: {title}\n"
                f"- 标识: `{external_key}`"
            ),
            ephemeral=True,
        )


class LightProfileContributionModal(LightKnowledgeModalBase, title="加入个人记忆"):
    def __init__(self) -> None:
        super().__init__()
        self.member_name_input = discord.ui.TextInput(
            label="成员名称",
            placeholder="请输入成员名称或昵称",
            max_length=100,
            required=True,
        )
        self.add_item(self.member_name_input)

        self.discord_username_input = discord.ui.TextInput(
            label="Discord 用户名",
            placeholder="可选，填写唯一用户名",
            max_length=32,
            required=False,
        )
        self.add_item(self.discord_username_input)

        self.personality_input = discord.ui.TextInput(
            label="性格特点",
            placeholder="描述该成员的性格、说话方式、习惯等",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
        )
        self.add_item(self.personality_input)

        self.background_input = discord.ui.TextInput(
            label="背景信息",
            placeholder="描述该成员的经历、设定或社区背景",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False,
        )
        self.add_item(self.background_input)

        self.preferences_input = discord.ui.TextInput(
            label="喜好偏好",
            placeholder="描述该成员的喜好、兴趣和习惯",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=False,
        )
        self.add_item(self.preferences_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        display_name = self.member_name_input.value.strip()
        discord_username = self.discord_username_input.value.strip().lstrip("@")
        if discord_username and not DISCORD_USERNAME_REGEX.fullmatch(discord_username):
            await self._send_result(
                interaction,
                "Discord 用户名格式无效，请填写唯一用户名。",
            )
            return

        await interaction.response.defer(ephemeral=True)
        external_key = await light_knowledge_service.upsert_profile(
            display_name=display_name,
            discord_username=discord_username,
            personality=self.personality_input.value.strip(),
            background=self.background_input.value.strip(),
            preferences=self.preferences_input.value.strip(),
        )
        username_line = f"- 用户名: @{discord_username}\n" if discord_username else ""
        await interaction.followup.send(
            (
                f"个人记忆已写入。\n"
                f"- 名称: {display_name}\n"
                f"{username_line}"
                f"- 标识: `{external_key}`"
            ),
            ephemeral=True,
        )


class DeleteProfileModal(LightKnowledgeModalBase, title="删除个人记忆"):
    def __init__(self) -> None:
        super().__init__()
        self.identifier_input = discord.ui.TextInput(
            label="标识 / 用户名 / 名称",
            placeholder="填写 external_key、Discord 用户名或显示名称",
            max_length=100,
            required=True,
        )
        self.add_item(self.identifier_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        deleted = await light_knowledge_service.delete_profile(
            self.identifier_input.value.strip()
        )
        await interaction.followup.send(
            "个人记忆已删除。" if deleted else "没有找到对应的个人记忆。",
            ephemeral=True,
        )


class DeleteKnowledgeModal(LightKnowledgeModalBase, title="删除知识"):
    def __init__(self) -> None:
        super().__init__()
        self.identifier_input = discord.ui.TextInput(
            label="标识 / 标题",
            placeholder="填写 external_key 或标题",
            max_length=100,
            required=True,
        )
        self.add_item(self.identifier_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        deleted = await light_knowledge_service.delete_knowledge(
            self.identifier_input.value.strip()
        )
        await interaction.followup.send(
            "知识条目已删除。" if deleted else "没有找到对应的知识条目。",
            ephemeral=True,
        )


class MemoryManagementActionSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label="查看统计",
                value="stats",
                description="查看当前个人记忆和知识条目数量",
            ),
            discord.SelectOption(
                label="导入种子",
                value="import_seed",
                description="从 data/seed 导入预设数据",
            ),
            discord.SelectOption(
                label="加入个人记忆",
                value="open_profile_modal",
                description="打开个人记忆录入表单",
            ),
            discord.SelectOption(
                label="Alyce知识库",
                value="open_knowledge_modal",
                description="打开知识条目录入表单",
            ),
            discord.SelectOption(
                label="删除个人记忆",
                value="delete_profile",
                description="按标识、用户名或名称删除个人记忆",
            ),
            discord.SelectOption(
                label="删除知识",
                value="delete_knowledge",
                description="按标识或标题删除知识条目",
            ),
        ]
        super().__init__(
            placeholder="选择一项管理操作",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]

        if selected == "stats":
            await interaction.response.defer(ephemeral=True)
            stats = await light_knowledge_service.get_stats()
            await interaction.followup.send(
                (
                    "记忆库统计\n"
                    f"- 个人记忆: {stats['profiles']} 条\n"
                    f"- 知识条目: {stats['knowledge']} 条"
                ),
                ephemeral=True,
            )
            return

        if selected == "import_seed":
            await interaction.response.defer(ephemeral=True)
            result = await light_knowledge_service.import_from_seed_files()
            stats = await light_knowledge_service.get_stats()
            await interaction.followup.send(
                (
                    "导入完成\n"
                    f"- 本次导入个人记忆: {result['profiles']} 条\n"
                    f"- 本次导入知识条目: {result['knowledge']} 条\n"
                    f"- 当前总个人记忆: {stats['profiles']} 条\n"
                    f"- 当前总知识条目: {stats['knowledge']} 条"
                ),
                ephemeral=True,
            )
            return

        if selected == "open_profile_modal":
            await interaction.response.send_modal(LightProfileContributionModal())
            return

        if selected == "open_knowledge_modal":
            await interaction.response.send_modal(LightKnowledgeContributionModal())
            return

        if selected == "delete_profile":
            await interaction.response.send_modal(DeleteProfileModal())
            return

        if selected == "delete_knowledge":
            await interaction.response.send_modal(DeleteKnowledgeModal())


class MemoryManagementActionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.add_item(MemoryManagementActionSelect())


class LightKnowledgeAdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _split_aliases(raw_aliases: str) -> list[str]:
        return [part.strip() for part in raw_aliases.split(",") if part.strip()]

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            message = "抱歉，您没有权限使用此命令。"
        else:
            log.error("执行记忆管理命令时出错: %s", error, exc_info=True)
            message = f"执行命令时发生错误: {error}"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="记忆管理", description="打开记忆库管理面板")
    @app_commands.guild_only()
    @is_admin_or_dev()
    async def open_management_panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "请选择一项管理操作。", view=MemoryManagementActionView(), ephemeral=True
        )

    @app_commands.command(name="alyce知识库", description="打开弹窗录入一条知识")
    @app_commands.guild_only()
    async def open_knowledge_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LightKnowledgeContributionModal())

    @app_commands.command(name="加入个人记忆", description="打开弹窗录入一条个人记忆")
    @app_commands.guild_only()
    async def open_profile_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LightProfileContributionModal())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LightKnowledgeAdminCog(bot))

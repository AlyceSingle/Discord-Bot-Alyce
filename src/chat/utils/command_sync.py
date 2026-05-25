import discord
from discord.ext import commands
from discord import app_commands

import logging

# 设置日志记录
logger = logging.getLogger(__name__)
COMMANDS_TO_KEEP_REMOTELY = {"launch"}


def _build_final_payload(
    local_payload: list[dict],
    remote_payload: list[dict],
    synced_local_names: set[str],
    *,
    keep_names: set[str],
    scope_label: str,
) -> list[dict]:
    unmanaged_remote_commands_payload = [
        cmd for cmd in remote_payload if cmd["name"] not in synced_local_names
    ]

    if unmanaged_remote_commands_payload:
        unmanaged_names = [cmd["name"] for cmd in unmanaged_remote_commands_payload]
        logger.info(
            f"发现 {scope_label} 存在但本地代码未管理的命令，将检查是否保留: {unmanaged_names}"
        )

    kept_unmanaged_commands = [
        cmd for cmd in unmanaged_remote_commands_payload if cmd["name"] in keep_names
    ]
    if kept_unmanaged_commands:
        kept_names = [cmd["name"] for cmd in kept_unmanaged_commands]
        logger.info(f"根据白名单，将从 {scope_label} 保留以下命令: {kept_names}")

    return local_payload + kept_unmanaged_commands


async def sync_commands(
    tree: app_commands.CommandTree,
    bot: commands.Bot,
    *,
    blacklist: list[str] | None = None,
):
    """
    智能同步应用命令，保留服务器上不由机器人代码管理的命令（例如活动入口点），并可选择忽略黑名单中的本地命令。

    :param tree: The command tree to sync.
    :param bot: The bot instance.
    :param blacklist: A list of local command names to exclude from syncing.
    """
    if blacklist is None:
        blacklist = []
    keep_names = set(COMMANDS_TO_KEEP_REMOTELY)
    debug_guild_ids = getattr(bot, "debug_guild_ids", None) or []

    # 1. 获取所有本地命令，并排除黑名单中的命令
    local_commands_to_sync = [
        cmd for cmd in tree.get_commands() if cmd.name not in blacklist
    ]
    local_payload = [cmd.to_dict(tree=tree) for cmd in local_commands_to_sync]
    synced_local_names = {cmd.name for cmd in local_commands_to_sync}
    logger.info(f"本地待同步命令: {[cmd['name'] for cmd in local_payload]}")

    if not bot.application_id:
        logger.error("Bot application_id 未设置，无法同步命令。")
        return

    # 调试服务器模式：清空全局残留，直接同步到指定 guild，立即生效。
    if debug_guild_ids:
        try:
            remote_global = await bot.http.get_global_commands(bot.application_id)
            final_global_payload = [
                cmd for cmd in remote_global if cmd["name"] in keep_names
            ]
            await bot.http.bulk_upsert_global_commands(
                bot.application_id,
                payload=final_global_payload,  # type: ignore[arg-type]
            )
            logger.info(
                f"调试模式下已清理全局命令，保留: {[cmd['name'] for cmd in final_global_payload]}"
            )
        except discord.HTTPException as e:
            logger.error(f"清理全局命令失败: {e}")
            raise

        for guild_id in debug_guild_ids:
            try:
                logger.info(f"正在从 Discord 获取服务器 {guild_id} 的命令...")
                remote_payload = await bot.http.get_guild_commands(
                    bot.application_id, guild_id
                )
                logger.info(
                    f"从 Discord 成功获取服务器 {guild_id} 的 {len(remote_payload)} 个命令。"
                )
                final_payload = _build_final_payload(
                    local_payload,
                    remote_payload,
                    synced_local_names,
                    keep_names=keep_names,
                    scope_label=f"服务器 {guild_id} 命令",
                )
                logger.info(
                    f"正在向服务器 {guild_id} 推送 {len(final_payload)} 个命令进行同步..."
                )
                await bot.http.bulk_upsert_guild_commands(
                    bot.application_id,
                    guild_id,
                    payload=final_payload,  # type: ignore[arg-type]
                )
                final_names = [p["name"] for p in final_payload]
                logger.info(f"服务器 {guild_id} 命令同步成功: {final_names}")
            except discord.HTTPException as e:
                logger.error(f"同步服务器 {guild_id} 命令时发生 HTTP 错误: {e}")
                raise
        return

    # 生产模式：同步全局命令。
    try:
        logger.info("正在从 Discord 获取所有全局命令...")
        remote_payload = await bot.http.get_global_commands(bot.application_id)
        logger.info(f"从 Discord 成功获取 {len(remote_payload)} 个命令。")
    except discord.HTTPException as e:
        logger.error(f"从 Discord 获取命令失败: {e}")
        return

    final_payload = _build_final_payload(
        local_payload,
        remote_payload,
        synced_local_names,
        keep_names=keep_names,
        scope_label="全局命令",
    )

    try:
        logger.info(f"正在向 Discord 推送 {len(final_payload)} 个命令进行同步...")
        await bot.http.bulk_upsert_global_commands(
            bot.application_id, payload=final_payload  # type: ignore[arg-type]
        )
        final_names = [p["name"] for p in final_payload]
        logger.info(f"命令同步成功! 当前服务器命令: {final_names}")
    except discord.HTTPException as e:
        logger.error(f"命令同步期间发生 HTTP 错误: {e}")
        raise


async def clear_remote_commands(
    bot: commands.Bot,
    *,
    keep_names: list[str] | None = None,
):
    """
    清理 Discord 端残留的全局/服务器命令。

    仅保留 keep_names 白名单中的命令，其余全部删除。
    """
    keep_name_set = set(keep_names or COMMANDS_TO_KEEP_REMOTELY)

    if not bot.application_id:
        logger.error("Bot application_id 未设置，无法清理远程命令。")
        return

    try:
        remote_global = await bot.http.get_global_commands(bot.application_id)
        final_global_payload = [
            cmd for cmd in remote_global if cmd["name"] in keep_name_set
        ]
        await bot.http.bulk_upsert_global_commands(
            bot.application_id, payload=final_global_payload  # type: ignore[arg-type]
        )
        logger.info(
            f"已清理全局命令，保留: {[cmd['name'] for cmd in final_global_payload]}"
        )
    except discord.HTTPException as e:
        logger.error(f"清理全局命令失败: {e}")
        raise

    for guild in bot.guilds:
        try:
            remote_guild = await bot.http.get_guild_commands(
                bot.application_id, guild.id
            )
            final_guild_payload = [
                cmd for cmd in remote_guild if cmd["name"] in keep_name_set
            ]
            await bot.http.bulk_upsert_guild_commands(
                bot.application_id,
                guild.id,
                payload=final_guild_payload,  # type: ignore[arg-type]
            )
            logger.info(
                f"已清理服务器 {guild.id} 命令，保留: "
                f"{[cmd['name'] for cmd in final_guild_payload]}"
            )
        except discord.HTTPException as e:
            logger.error(f"清理服务器 {guild.id} 命令失败: {e}")

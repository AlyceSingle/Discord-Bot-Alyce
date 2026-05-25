# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from src import config

log = logging.getLogger(__name__)

_SEARCH_STOP_PHRASES = {
    "你",
    "我",
    "他",
    "她",
    "它",
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "呀",
    "吧",
    "是",
    "在",
    "和",
    "与",
    "或",
    "有",
    "都",
    "就",
    "很",
    "还",
    "又",
    "也",
    "这",
    "那",
    "一个",
    "什么",
    "怎么",
    "为什么",
    "是不是",
    "可以",
    "知道",
    "关于",
}

_CJK_RUN_REGEX = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_TERM_REGEX = re.compile(r"[a-z0-9_]{2,}")
_MENTION_REGEX = re.compile(r"<@!?&?\d+>")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS member_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    title TEXT,
    discord_id TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    personality TEXT,
    background TEXT,
    preferences TEXT,
    profile_text TEXT NOT NULL DEFAULT '',
    personal_summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS community_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    content_text TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_member_profiles_discord_id
ON member_profiles(discord_id);

CREATE INDEX IF NOT EXISTS idx_member_profiles_display_name
ON member_profiles(display_name);

CREATE INDEX IF NOT EXISTS idx_community_knowledge_title
ON community_knowledge(title);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_text(value: Any) -> str:
    text = _safe_text(value).casefold()
    return re.sub(r"\s+", "", text)


def _clean_discord_identity(value: Any) -> str:
    return _safe_text(value).lstrip("@")


def _normalize_discord_identity(value: Any) -> str:
    return _clean_discord_identity(value).casefold()


def _parse_aliases(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [part.strip() for part in raw.split(",")]
        except json.JSONDecodeError:
            items = [part.strip() for part in raw.split(",")]
    else:
        items = [value]

    aliases: List[str] = []
    seen = set()
    for item in items:
        alias = _safe_text(item)
        if not alias:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        aliases.append(alias)
    return aliases


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _make_profile_key(display_name: str, discord_id: Optional[str]) -> str:
    discord_id_text = _clean_discord_identity(discord_id)
    if discord_id_text:
        return f"discord:{discord_id_text}"
    return f"name:{_normalize_text(display_name)}"


def _make_knowledge_key(title: str) -> str:
    return f"title:{_normalize_text(title)}"


def _extract_query_terms(query: str) -> List[str]:
    clean_query = _MENTION_REGEX.sub(" ", _safe_text(query)).casefold()
    terms: List[str] = []
    seen = set()

    for token in _ASCII_TERM_REGEX.findall(clean_query):
        if token in _SEARCH_STOP_PHRASES:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)

    for run in _CJK_RUN_REGEX.findall(clean_query):
        if len(run) <= 6:
            if run not in _SEARCH_STOP_PHRASES and run not in seen:
                seen.add(run)
                terms.append(run)
            continue

        max_size = min(len(run), 6)
        for size in range(max_size, 1, -1):
            for start in range(0, len(run) - size + 1):
                term = run[start : start + size]
                if term in _SEARCH_STOP_PHRASES or term in seen:
                    continue
                seen.add(term)
                terms.append(term)
                if len(terms) >= 50:
                    return terms

    return terms


def _serialize_profile_row(row: aiosqlite.Row) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    raw_metadata = row["metadata_json"]
    if raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}

    aliases = _parse_aliases(row["aliases_json"])
    profile = {
        "id": row["id"],
        "external_key": row["external_key"],
        "display_name": row["display_name"],
        "title": _safe_text(row["title"]),
        "discord_id": _clean_discord_identity(row["discord_id"]),
        "discord_username": _clean_discord_identity(row["discord_id"]),
        "aliases": aliases,
        "personality": _safe_text(row["personality"]),
        "background": _safe_text(row["background"]),
        "preferences": _safe_text(row["preferences"]),
        "profile_text": _safe_text(row["profile_text"]),
        "personal_summary": _safe_text(row["personal_summary"]),
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    profile["_search_terms"] = [
        _safe_text(profile["display_name"]),
        _safe_text(profile["title"]),
        _safe_text(profile["discord_username"]),
        *_parse_aliases(aliases),
    ]
    profile["_search_text"] = _normalize_text(
        " ".join(
            [
                profile["display_name"],
                profile["title"],
                profile["discord_username"],
                " ".join(aliases),
                profile["personality"],
                profile["background"],
                profile["preferences"],
                profile["profile_text"],
                profile["personal_summary"],
            ]
        )
    )
    return profile


def _serialize_knowledge_row(row: aiosqlite.Row) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    raw_metadata = row["metadata_json"]
    if raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}

    aliases = _parse_aliases(row["aliases_json"])
    entry = {
        "id": row["id"],
        "external_key": row["external_key"],
        "title": row["title"],
        "category": _safe_text(row["category"]),
        "aliases": aliases,
        "content_text": _safe_text(row["content_text"]),
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    entry["_search_terms"] = [_safe_text(entry["title"]), *aliases]
    entry["_search_text"] = _normalize_text(
        " ".join(
            [
                entry["title"],
                entry["category"],
                " ".join(aliases),
                entry["content_text"],
            ]
        )
    )
    return entry


class LightKnowledgeService:
    def __init__(self) -> None:
        self.db_path = Path(config.LIGHT_KNOWLEDGE_DB_PATH)
        self.seed_dir = Path(config.LIGHT_KNOWLEDGE_SEED_DIR)
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._profile_cache: List[Dict[str, Any]] = []
        self._knowledge_cache: List[Dict[str, Any]] = []
        self._profile_by_discord_identity: Dict[str, Dict[str, Any]] = {}

    async def init_async(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.seed_dir.mkdir(parents=True, exist_ok=True)

            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(_SCHEMA)
                await db.commit()

            if config.LIGHT_KNOWLEDGE_AUTO_IMPORT:
                try:
                    await self._import_from_seed_files()
                except Exception as exc:
                    log.warning(f"自动导入记忆库失败，将继续使用现有数据库: {exc}")

            await self._refresh_cache()
            self._initialized = True
            log.info(
                "LightKnowledgeService 初始化完成: 成员档案 %s 条, 社区知识 %s 条",
                len(self._profile_cache),
                len(self._knowledge_cache),
            )

    async def ensure_ready(self) -> None:
        if not self._initialized:
            await self.init_async()

    async def _refresh_cache(self) -> None:
        profiles: List[Dict[str, Any]] = []
        knowledge_entries: List[Dict[str, Any]] = []

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM member_profiles ORDER BY updated_at DESC, id DESC"
            ) as cursor:
                async for row in cursor:
                    profiles.append(_serialize_profile_row(row))

            async with db.execute(
                "SELECT * FROM community_knowledge ORDER BY updated_at DESC, id DESC"
            ) as cursor:
                async for row in cursor:
                    knowledge_entries.append(_serialize_knowledge_row(row))

        self._profile_cache = profiles
        self._knowledge_cache = knowledge_entries
        self._profile_by_discord_identity = {
            _normalize_discord_identity(profile["discord_id"]): profile
            for profile in profiles
            if _normalize_discord_identity(profile.get("discord_id"))
        }

    async def import_from_seed_files(
        self,
        profiles_path: Optional[str] = None,
        knowledge_path: Optional[str] = None,
    ) -> Dict[str, int]:
        await self.ensure_ready()
        return await self._import_from_seed_files(
            profiles_path=profiles_path,
            knowledge_path=knowledge_path,
        )

    async def _import_from_seed_files(
        self,
        profiles_path: Optional[str] = None,
        knowledge_path: Optional[str] = None,
    ) -> Dict[str, int]:
        profile_file = (
            Path(profiles_path) if profiles_path else self.seed_dir / "member_profiles.json"
        )
        knowledge_file = (
            Path(knowledge_path)
            if knowledge_path
            else self.seed_dir / "community_knowledge.json"
        )

        imported_profiles = 0
        imported_knowledge = 0

        if profile_file.exists():
            payload = json.loads(profile_file.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("member_profiles.json 必须是数组。")
            for item in payload:
                if not isinstance(item, dict):
                    continue
                await self.upsert_profile(
                    display_name=_safe_text(item.get("display_name")),
                    title=_safe_text(item.get("title")),
                    discord_username=_safe_text(
                        item.get("discord_username") or item.get("discord_id")
                    ),
                    aliases=_parse_aliases(item.get("aliases")),
                    personality=_safe_text(item.get("personality")),
                    background=_safe_text(item.get("background")),
                    preferences=_safe_text(item.get("preferences")),
                    profile_text=_safe_text(item.get("profile_text")),
                    personal_summary=_safe_text(item.get("personal_summary")),
                    metadata=item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {},
                    refresh_cache=False,
                    skip_ready_check=True,
                )
                imported_profiles += 1

        if knowledge_file.exists():
            payload = json.loads(knowledge_file.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("community_knowledge.json 必须是数组。")
            for item in payload:
                if not isinstance(item, dict):
                    continue
                await self.upsert_knowledge(
                    title=_safe_text(item.get("title")),
                    category=_safe_text(item.get("category")),
                    aliases=_parse_aliases(item.get("aliases")),
                    content_text=_safe_text(item.get("content_text")),
                    metadata=item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {},
                    refresh_cache=False,
                    skip_ready_check=True,
                )
                imported_knowledge += 1

        await self._refresh_cache()
        return {
            "profiles": imported_profiles,
            "knowledge": imported_knowledge,
        }

    async def upsert_profile(
        self,
        *,
        display_name: str,
        title: str = "",
        discord_username: str = "",
        discord_id: str = "",
        aliases: Optional[List[str]] = None,
        personality: str = "",
        background: str = "",
        preferences: str = "",
        profile_text: str = "",
        personal_summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        refresh_cache: bool = True,
        skip_ready_check: bool = False,
    ) -> str:
        if not skip_ready_check:
            await self.ensure_ready()

        clean_name = _safe_text(display_name)
        if not clean_name:
            raise ValueError("display_name 不能为空。")

        clean_discord_id = _clean_discord_identity(discord_username or discord_id)
        alias_list = _parse_aliases(aliases)
        metadata_dict = metadata or {}
        now = _utc_now_iso()

        async with aiosqlite.connect(self.db_path) as db:
            external_key = await self._resolve_profile_external_key(
                db,
                display_name=clean_name,
                discord_id=clean_discord_id,
            )
            await db.execute(
                """
                INSERT INTO member_profiles (
                    external_key, display_name, title, discord_id, aliases_json,
                    personality, background, preferences, profile_text,
                    personal_summary, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    title = excluded.title,
                    discord_id = excluded.discord_id,
                    aliases_json = excluded.aliases_json,
                    personality = excluded.personality,
                    background = excluded.background,
                    preferences = excluded.preferences,
                    profile_text = excluded.profile_text,
                    personal_summary = excluded.personal_summary,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    external_key,
                    clean_name,
                    _safe_text(title),
                    clean_discord_id,
                    _json_dumps(alias_list),
                    _safe_text(personality),
                    _safe_text(background),
                    _safe_text(preferences),
                    _safe_text(profile_text),
                    _safe_text(personal_summary),
                    _json_dumps(metadata_dict),
                    now,
                    now,
                ),
            )
            await db.commit()

        if refresh_cache:
            await self._refresh_cache()
        return external_key

    async def upsert_knowledge(
        self,
        *,
        title: str,
        category: str = "",
        aliases: Optional[List[str]] = None,
        content_text: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        refresh_cache: bool = True,
        skip_ready_check: bool = False,
    ) -> str:
        if not skip_ready_check:
            await self.ensure_ready()

        clean_title = _safe_text(title)
        if not clean_title:
            raise ValueError("title 不能为空。")

        external_key = _make_knowledge_key(clean_title)
        alias_list = _parse_aliases(aliases)
        metadata_dict = metadata or {}
        now = _utc_now_iso()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO community_knowledge (
                    external_key, title, category, aliases_json, content_text,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_key) DO UPDATE SET
                    title = excluded.title,
                    category = excluded.category,
                    aliases_json = excluded.aliases_json,
                    content_text = excluded.content_text,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    external_key,
                    clean_title,
                    _safe_text(category),
                    _json_dumps(alias_list),
                    _safe_text(content_text),
                    _json_dumps(metadata_dict),
                    now,
                    now,
                ),
            )
            await db.commit()

        if refresh_cache:
            await self._refresh_cache()
        return external_key

    async def _resolve_profile_external_key(
        self,
        db: aiosqlite.Connection,
        *,
        display_name: str,
        discord_id: str,
    ) -> str:
        normalized_name = _normalize_text(display_name)
        query = """
            SELECT external_key
            FROM member_profiles
            WHERE REPLACE(LOWER(COALESCE(discord_id, '')), '@', '') = ?
               OR REPLACE(LOWER(display_name), ' ', '') = ?
            ORDER BY id DESC
            LIMIT 1
        """
        params = (_normalize_discord_identity(discord_id), normalized_name)

        if not discord_id:
            query = """
                SELECT external_key
                FROM member_profiles
                WHERE REPLACE(LOWER(display_name), ' ', '') = ?
                ORDER BY id DESC
                LIMIT 1
            """
            params = (normalized_name,)

        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()

        if row and row[0]:
            return str(row[0])
        return _make_profile_key(display_name, discord_id)

    async def delete_profile(self, identifier: str) -> bool:
        await self.ensure_ready()

        deleted = False
        normalized_identifier = _normalize_text(identifier)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM member_profiles
                WHERE external_key = ?
                   OR REPLACE(LOWER(COALESCE(discord_id, '')), '@', '') = ?
                   OR REPLACE(LOWER(display_name), ' ', '') = ?
                """,
                (identifier, _normalize_discord_identity(identifier), normalized_identifier),
            )
            deleted = cursor.rowcount > 0
            await db.commit()

        if deleted:
            await self._refresh_cache()
        return deleted

    async def delete_knowledge(self, identifier: str) -> bool:
        await self.ensure_ready()

        deleted = False
        normalized_identifier = _normalize_text(identifier)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM community_knowledge
                WHERE external_key = ?
                   OR REPLACE(LOWER(title), ' ', '') = ?
                """,
                (identifier, normalized_identifier),
            )
            deleted = cursor.rowcount > 0
            await db.commit()

        if deleted:
            await self._refresh_cache()
        return deleted

    def _find_profile_for_user(
        self,
        *,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> Optional[Dict[str, Any]]:
        normalized_username = _normalize_discord_identity(username)
        if normalized_username:
            profile = self._profile_by_discord_identity.get(normalized_username)
            if profile:
                return profile

        if user_id is not None:
            return self._profile_by_discord_identity.get(
                _normalize_discord_identity(str(user_id))
            )

        return None

    async def get_profile_by_discord_id(
        self, discord_id: int | str
    ) -> Optional[Dict[str, Any]]:
        await self.ensure_ready()
        profile = self._find_profile_for_user(
            user_id=discord_id if isinstance(discord_id, int) else None,
            username=discord_id if isinstance(discord_id, str) else "",
        )
        return self._to_prompt_profile(profile) if profile else None

    def _to_prompt_profile(self, profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not profile:
            return None

        source_metadata = {
            "name": profile["display_name"],
            "personality": profile["personality"],
            "background": profile["background"] or profile["profile_text"],
            "preferences": profile["preferences"],
            "aliases": profile["aliases"],
        }

        return {
            "id": profile["id"],
            "title": profile["title"] or profile["display_name"],
            "name": profile["display_name"],
            "personal_summary": profile["personal_summary"],
            "source_metadata": source_metadata,
            "display_name": profile["display_name"],
            "discord_id": profile["discord_id"],
            "discord_username": profile["discord_username"],
        }

    def _score_profile(
        self, profile: Dict[str, Any], query_compact: str, query_terms: List[str]
    ) -> int:
        score = 0

        for term in profile["_search_terms"]:
            normalized_term = _normalize_text(term)
            if not normalized_term:
                continue
            if normalized_term in query_compact:
                score += 40 + min(len(normalized_term), 10)

        for term in query_terms:
            if term and term in profile["_search_text"]:
                score += min(len(term), 8)

        return score

    def _score_knowledge(
        self, entry: Dict[str, Any], query_compact: str, query_terms: List[str]
    ) -> int:
        score = 0

        for term in entry["_search_terms"]:
            normalized_term = _normalize_text(term)
            if not normalized_term:
                continue
            if normalized_term in query_compact:
                score += 35 + min(len(normalized_term), 10)

        for term in query_terms:
            if term and term in entry["_search_text"]:
                score += min(len(term), 6)

        return score

    async def search_related_profiles(
        self,
        query: str,
        *,
        current_user_id: Optional[int] = None,
        current_username: str = "",
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        await self.ensure_ready()

        query_compact = _normalize_text(_MENTION_REGEX.sub(" ", query))
        query_terms = _extract_query_terms(query)
        limit_value = limit or config.LIGHT_KNOWLEDGE_PROFILE_LIMIT
        current_identities = set()
        if current_user_id is not None:
            current_identities.add(_normalize_discord_identity(str(current_user_id)))
        normalized_current_username = _normalize_discord_identity(current_username)
        if normalized_current_username:
            current_identities.add(normalized_current_username)

        scored: List[tuple[int, Dict[str, Any]]] = []
        for profile in self._profile_cache:
            profile_identity = _normalize_discord_identity(profile.get("discord_id"))
            if profile_identity and profile_identity in current_identities:
                continue

            score = self._score_profile(profile, query_compact, query_terms)
            if score < 4:
                continue
            scored.append((score, profile))

        scored.sort(key=lambda item: (-item[0], item[1]["display_name"]))
        return [profile for _, profile in scored[:limit_value]]

    async def search_knowledge_entries(
        self, query: str, *, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        await self.ensure_ready()

        query_compact = _normalize_text(_MENTION_REGEX.sub(" ", query))
        query_terms = _extract_query_terms(query)
        limit_value = limit or config.LIGHT_KNOWLEDGE_KNOWLEDGE_LIMIT

        scored: List[tuple[int, Dict[str, Any]]] = []
        for entry in self._knowledge_cache:
            score = self._score_knowledge(entry, query_compact, query_terms)
            if score < 4:
                continue
            scored.append((score, entry))

        scored.sort(key=lambda item: (-item[0], item[1]["title"]))
        return [entry for _, entry in scored[:limit_value]]

    def _profile_to_entry(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        lines = [
            "成员档案",
            f"名称: {profile['display_name']}",
        ]
        if profile["discord_username"]:
            lines.append(f"Discord 用户名: @{profile['discord_username']}")
        if profile["title"]:
            lines.append(f"头衔: {profile['title']}")
        if profile["aliases"]:
            lines.append(f"别名: {'、'.join(profile['aliases'])}")
        if profile["personality"]:
            lines.append(f"个性: {profile['personality']}")
        if profile["background"]:
            lines.append(f"背景: {profile['background']}")
        if profile["preferences"]:
            lines.append(f"偏好: {profile['preferences']}")
        if profile["profile_text"]:
            lines.append(f"简介: {profile['profile_text']}")

        return {
            "id": f"profile:{profile['id']}",
            "content": "\n".join(lines),
            "distance": 0.0,
            "metadata": {
                "source_table": "light_member_profile",
                "display_name": profile["display_name"],
                "discord_username": profile["discord_username"],
            },
        }

    def _knowledge_to_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        lines = [
            "社区知识",
            f"标题: {entry['title']}",
        ]
        if entry["category"]:
            lines.append(f"分类: {entry['category']}")
        if entry["aliases"]:
            lines.append(f"别名: {'、'.join(entry['aliases'])}")
        lines.append(f"内容: {entry['content_text']}")

        return {
            "id": f"knowledge:{entry['id']}",
            "content": "\n".join(lines),
            "distance": 0.0,
            "metadata": {
                "source_table": "light_community_knowledge",
                "title": entry["title"],
            },
        }

    async def build_chat_context(
        self,
        *,
        query: str,
        current_user_id: int,
        current_username: str = "",
    ) -> Dict[str, Any]:
        await self.ensure_ready()

        current_profile = self._find_profile_for_user(
            user_id=current_user_id,
            username=current_username,
        )
        related_profiles = await self.search_related_profiles(
            query,
            current_user_id=current_user_id,
            current_username=current_username,
            limit=config.LIGHT_KNOWLEDGE_PROFILE_LIMIT,
        )
        knowledge_entries = await self.search_knowledge_entries(
            query,
            limit=config.LIGHT_KNOWLEDGE_KNOWLEDGE_LIMIT,
        )

        prompt_entries = [self._profile_to_entry(profile) for profile in related_profiles]
        prompt_entries.extend(
            self._knowledge_to_entry(entry) for entry in knowledge_entries
        )

        return {
            "user_profile_data": self._to_prompt_profile(current_profile),
            "personal_summary": current_profile.get("personal_summary") if current_profile else None,
            "world_book_entries": prompt_entries,
            "matched_profile_count": len(related_profiles),
            "matched_knowledge_count": len(knowledge_entries),
        }

    async def get_stats(self) -> Dict[str, int]:
        await self.ensure_ready()
        return {
            "profiles": len(self._profile_cache),
            "knowledge": len(self._knowledge_cache),
        }


light_knowledge_service = LightKnowledgeService()

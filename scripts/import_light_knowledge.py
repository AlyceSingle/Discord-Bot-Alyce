import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.chat.services.light_knowledge_service import light_knowledge_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import lightweight member profiles and community knowledge."
    )
    parser.add_argument(
        "--profiles",
        help="Path to member_profiles.json. Defaults to data/seed/member_profiles.json.",
    )
    parser.add_argument(
        "--knowledge",
        help="Path to community_knowledge.json. Defaults to data/seed/community_knowledge.json.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await light_knowledge_service.init_async()
    imported = await light_knowledge_service.import_from_seed_files(
        profiles_path=args.profiles,
        knowledge_path=args.knowledge,
    )
    stats = await light_knowledge_service.get_stats()
    print(
        json.dumps(
            {
                "imported": imported,
                "stats": stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

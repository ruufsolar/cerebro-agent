import asyncio

from cerebro.config import get_config
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.scope import load_knowledge


async def main() -> None:
    config = get_config()
    database = ReplicaDatabase(config, load_knowledge(config.knowledge_dir))
    try:
        await database.start()
        drift = await database.check_schema()
        print(
            "replica-safe=true "
            f"schema-compatible={str(drift.ok).lower()} "
            f"scope-version={database.knowledge.scope.version}"
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())

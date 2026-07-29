from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.infrastructure.db.repositories import seed_sources
from app.infrastructure.db.session import create_engine, create_session_factory


async def _main() -> None:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    async with factory() as session:
        seeded = await seed_sources(session)
    await engine.dispose()
    print(f"Source registry ready ({seeded} new sources).")


if __name__ == "__main__":
    asyncio.run(_main())

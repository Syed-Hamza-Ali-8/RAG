"""Apply migrations/*.sql in filename order, recording versions in schema_migrations."""

import asyncio
import logging

import asyncpg

from gateway.config import get_settings
from gateway.db import apply_migrations


async def main() -> None:
    conn = await asyncpg.connect(get_settings().database_dsn)
    try:
        applied = await apply_migrations(conn)
    finally:
        await conn.close()
    print(f"applied: {applied}" if applied else "schema up to date")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

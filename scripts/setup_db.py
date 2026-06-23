"""
初始化本地開發資料庫（SQLite）。

使用方式：
    python scripts/setup_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import init_db


async def main():
    print("Initializing database...")
    await init_db()
    print("Done! Tables created.")


if __name__ == "__main__":
    asyncio.run(main())

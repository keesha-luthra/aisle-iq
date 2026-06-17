from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from app.config import settings

# Create async database engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass


async def get_db_session():
    """
    Dependency generator for injecting async database sessions into routes.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_connection() -> bool:
    """
    Checks database connection health.
    """
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


async def init_db() -> None:
    """
    Creates database schema tables.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_migrations() -> None:
    """
    Runs database schema migrations using Alembic.
    """
    import os
    from alembic.config import Config
    from alembic import command

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(base_dir, "alembic.ini")

    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    command.upgrade(alembic_cfg, "head")


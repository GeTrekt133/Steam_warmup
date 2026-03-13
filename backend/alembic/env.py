"""
Alembic env.py — настроен для async SQLAlchemy.

Alembic — это инструмент для миграций базы данных (аналог git для схемы БД).
Когда ты меняешь модель (например, добавляешь колонку), Alembic создаёт
файл-миграцию с SQL-командами ALTER TABLE, которые можно применить к БД.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import settings
from app.database import Base

# Импортируем все модели чтобы Alembic знал о них
from app.models import User, Account, Proxy, AccountGroup  # noqa: F401

config = context.config

# Подставляем DATABASE_URL из наших настроек
# Для синхронного Alembic нужен синхронный URL
db_url = settings.DATABASE_URL
# aiosqlite → sqlite для синхронного доступа Alembic
if "aiosqlite" in db_url:
    db_url = db_url.replace("sqlite+aiosqlite", "sqlite")
# asyncpg → psycopg2 для синхронного доступа
elif "asyncpg" in db_url:
    db_url = db_url.replace("postgresql+asyncpg", "postgresql")

config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

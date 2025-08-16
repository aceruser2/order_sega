from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# 如果 alembic.ini 不包含 logging sections，fileConfig 可能會拋出 KeyError。
# 在此用 try/except 保護，發生錯誤時回退到 basicConfig，避免中斷遷移流程。
try:
    if config.config_file_name:
        fileConfig(config.config_file_name)
except Exception:
    import logging

    logging.basicConfig(level=logging.INFO)

# Import project metadata and DATABASE_URL
# 注意：backend_main 必須在相同 PYTHONPATH 下可被 import
import sys

# 把專案根目錄加入 sys.path，確保能 import backend_main
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import backend_main

target_metadata = backend_main.Base.metadata

# Use DATABASE_URL from backend_main
db_url = getattr(backend_main, "DATABASE_URL", None)
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

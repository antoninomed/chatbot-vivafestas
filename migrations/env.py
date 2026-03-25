from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ✅ Garante que a raiz do projeto está no path (Windows)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.db.models import Base  # Base = declarative_base()

# this is the Alembic Config object, which provides access to values within alembic.ini
config = context.config

# Interpret the config file for Python logging.
# (mantém logs do alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ Alembic vai autogenerate a partir dos seus models
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # ✅ Força o alembic a usar DATABASE_URL do .env (e não o placeholder do alembic.ini)
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = settings.DATABASE_URL

    connectable = engine_from_config(
        section,
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
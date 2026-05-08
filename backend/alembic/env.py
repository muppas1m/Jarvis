"""
Alembic environment.

Sync mode (psycopg2/psycopg) — chosen because LangGraph's PostgresSaver.setup()
in 002_langgraph_checkpoints.py is synchronous, and mixing async migrations
with sync setup hooks gets messy. App code remains fully async; only Alembic
runs sync.

The DB URL comes from `settings.DATABASE_URL_SYNC` instead of the placeholder
in alembic.ini, so a single .env drives both runtime and migrations.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importing the models module is what populates Base.metadata. Without this
# the autogenerate scan would find an empty schema and emit no-op migrations.
from app.config import settings
from app.db.models import Base  # noqa: F401  (registers all model classes with Base.metadata)

# Touch every model so its class body executes (and its Table is registered).
# `from .models import Base` only imports the module top-level — adding this
# explicit import is a belt-and-braces guard against future submodules.
import app.db.models  # noqa: F401, E402


# Alembic Config object — the values in alembic.ini.
config = context.config

# Inject the live DB URL. Pydantic Settings has already read .env; we forward
# its value into the alembic config so all alembic commands (`upgrade`,
# `revision`, `current`, `history`, ...) hit the right database.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without connecting to the DB. Rarely used; we keep
    it intact for completeness so `alembic upgrade head --sql` works."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations directly."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column-type and server-default changes so future migrations
            # don't silently miss schema drift.
            compare_type=True,
            compare_server_default=True,
            # Render Vector columns and other pgvector types correctly.
            include_object=lambda obj, name, type_, *_: True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

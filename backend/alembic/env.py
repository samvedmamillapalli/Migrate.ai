from logging.config import fileConfig

from alembic import context
from alembic.operations import ops as alembic_ops
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.sqltypes import NullType, String, Text

from app.config import get_settings
from app.database.base import Base
from app.database import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    from app.database.session import normalize_database_url

    return normalize_database_url(get_settings().database_url.get_secret_value())


def _compare_type(
    context,  # noqa: ANN001, ARG001
    inspected_column,  # noqa: ANN001, ARG001
    metadata_column,  # noqa: ANN001, ARG001
    inspected_type,  # noqa: ANN001
    metadata_type,  # noqa: ANN001
) -> bool | None:
    """Ignore CockroachDB STRING/TEXT equivalence noise."""
    if isinstance(inspected_type, NullType):
        return False
    if isinstance(inspected_type, String) and isinstance(metadata_type, Text):
        return False
    if isinstance(inspected_type, Text) and isinstance(metadata_type, String):
        return False
    return None


def _is_nulls_first_index_noise(upgrade_ops: alembic_ops.UpgradeOps) -> bool:
    """True when ops only recreate indexes due to CRDB NULLS FIRST reflection."""
    flat_ops: list[object] = []

    def collect(container: object) -> None:
        for item in getattr(container, "ops", []):
            if isinstance(item, alembic_ops.ModifyTableOps):
                collect(item)
            else:
                flat_ops.append(item)

    collect(upgrade_ops)
    if not flat_ops:
        return False
    if any(
        not isinstance(item, (alembic_ops.DropIndexOp, alembic_ops.CreateIndexOp))
        for item in flat_ops
    ):
        return False

    dropped = {
        item.index_name
        for item in flat_ops
        if isinstance(item, alembic_ops.DropIndexOp)
    }
    created = {
        item.index_name
        for item in flat_ops
        if isinstance(item, alembic_ops.CreateIndexOp)
    }
    return dropped == created and len(dropped) > 0


def process_revision_directives(context, revision, directives):  # noqa: ANN001, ARG001
    """Drop empty revisions caused by CockroachDB index reflection noise."""
    if not directives:
        return
    script = directives[0]
    if _is_nulls_first_index_noise(script.upgrade_ops):
        # Cancel revision file creation when the only diffs are CRDB artifacts.
        directives[:] = []


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=_compare_type,
        compare_server_default=False,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=_compare_type,
            compare_server_default=False,
            transaction_per_migration=True,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""event_id and received_at on events, and the read indexes.

Every row gets a storage id, a UUIDv7 minted in append order; rows written before this
revision keep ``received_at`` NULL (their arrival time is unknown).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11 18:42:31.469971
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = {
    "ix_events_project_session_id": ["project", "session", "id"],
    "ix_events_project_type_timestamp": ["project", "type", "timestamp"],
    "ix_events_project_timestamp": ["project", "timestamp"],
}


def _events_table(*, with_storage_fields: bool) -> sa.Table:
    """The events table as 0002 left it, or with this revision's nullable columns added.

    Batch mode copies the table on SQLite; passing it here spares the reflection, which the
    offline (``--sql``) mode cannot do.
    """
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("repo", sa.String(), nullable=True),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("workflow", sa.String(), nullable=True),
        sa.Column("step", sa.String(), nullable=True),
    ]
    if with_storage_fields:
        columns += [
            sa.Column("event_id", sa.String(length=36), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        ]
    return sa.Table(
        "events",
        sa.MetaData(),
        *columns,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_events_source_source_id"),
    )


def upgrade() -> None:
    # Nullable first, so existing rows can be filled before the NOT NULL and unique rules apply.
    # A plain DateTime for received_at, as in 0002: migrations never import app code.
    with op.batch_alter_table(
        "events", copy_from=_events_table(with_storage_fields=False)
    ) as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
    _fill_event_ids()
    with op.batch_alter_table(
        "events", copy_from=_events_table(with_storage_fields=True)
    ) as batch_op:
        batch_op.alter_column("event_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_unique_constraint("uq_events_event_id", ["event_id"])
        for name, columns in INDEXES.items():
            batch_op.create_index(name, columns, unique=False)


def _fill_event_ids() -> None:
    """Give each existing row a UUIDv7, in append order, so the ids sort like the rows.

    Offline (``--sql``) there are no rows to read: the script targets a new database, and an
    existing one must be upgraded online.
    """
    if op.get_context().as_sql:
        return
    connection = op.get_bind()
    events = sa.table("events", sa.column("id", sa.Integer), sa.column("event_id", sa.String))
    row_ids: Sequence[int] = (
        connection.execute(sa.select(events.c.id).order_by(events.c.id)).scalars().all()
    )
    for row_id in row_ids:
        connection.execute(
            events.update().where(events.c.id == row_id).values(event_id=str(uuid.uuid7()))
        )


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name="events")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("uq_events_event_id", type_="unique")
        batch_op.drop_column("received_at")
        batch_op.drop_column("event_id")

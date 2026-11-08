"""Scope official call identity to the RingCentral account and extension.

Revision ID: j65bc789b025
Revises: i54af678a914
"""
from alembic import op
import sqlalchemy as sa

revision = "j65bc789b025"
down_revision = "i54af678a914"
branch_labels = None
depends_on = None

TABLE = "ringcentral_call_records"
COMPOSITE = "uq_ringcentral_call_provider_identity"
CALL_INDEX = "ix_ringcentral_call_records_ringcentral_call_id"
BINDING_INDEX = "uq_ringcentral_connection_provider_identity"


def upgrade():
    # A historical/inactive binding also reserves this identity. Reassignment
    # needs an explicit audited workflow; never silently delete a former owner.
    duplicate = op.get_bind().execute(sa.text(
        "SELECT ringcentral_account_id, ringcentral_extension_id FROM ringcentral_connections "
        "WHERE ringcentral_account_id IS NOT NULL AND ringcentral_extension_id IS NOT NULL "
        "GROUP BY ringcentral_account_id, ringcentral_extension_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("Cannot migrate RingCentral bindings: duplicate account/extension ownership; resolve explicitly without deleting historical evidence.")
    inspector = sa.inspect(op.get_bind())
    binding_indexes = {row["name"] for row in inspector.get_indexes("ringcentral_connections")}
    if BINDING_INDEX not in binding_indexes:
        op.create_index(BINDING_INDEX, "ringcentral_connections", ["ringcentral_account_id", "ringcentral_extension_id"], unique=True)
    indexes = {row["name"]: row for row in inspector.get_indexes(TABLE)}
    constraints = inspector.get_unique_constraints(TABLE)
    # Build the stronger provider identity first. Existing evidence stays in
    # place; this migration never deletes or rewrites a call or employee.
    with op.batch_alter_table(TABLE, naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
        if COMPOSITE not in indexes:
            batch.create_index(COMPOSITE, ["ringcentral_account_id", "ringcentral_extension_id", "ringcentral_call_id"], unique=True)
        for row in constraints:
            if row["column_names"] == ["ringcentral_call_id"]:
                batch.drop_constraint(row["name"] or "uq_ringcentral_call_records_ringcentral_call_id", type_="unique")
        for name, row in indexes.items():
            if row.get("unique") and row["column_names"] == ["ringcentral_call_id"]:
                batch.drop_index(name)
        if CALL_INDEX not in indexes or indexes[CALL_INDEX].get("unique"):
            batch.create_index(CALL_INDEX, ["ringcentral_call_id"], unique=False)


def downgrade():
    # Old code cannot represent two accounts' identically named call IDs. Do
    # not delete evidence to force a rollback into that weaker schema.
    collision = op.get_bind().execute(sa.text(
        "SELECT ringcentral_call_id FROM ringcentral_call_records "
        "WHERE ringcentral_call_id IS NOT NULL GROUP BY ringcentral_call_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if collision:
        raise RuntimeError("Cannot downgrade RingCentral identity: provider call IDs collide across accounts; retain call evidence and restore compatible code.")
    indexes = {row["name"]: row for row in sa.inspect(op.get_bind()).get_indexes(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        if CALL_INDEX in indexes:
            batch.drop_index(CALL_INDEX)
        batch.create_index(CALL_INDEX, ["ringcentral_call_id"], unique=True)
        if COMPOSITE in indexes:
            batch.drop_index(COMPOSITE)
    if BINDING_INDEX in {row["name"] for row in sa.inspect(op.get_bind()).get_indexes("ringcentral_connections")}:
        op.drop_index(BINDING_INDEX, table_name="ringcentral_connections")

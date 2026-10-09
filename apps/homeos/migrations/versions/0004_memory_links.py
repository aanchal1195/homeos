"""Preserve stable mappings from existing virtual house to Home Memory Graph.
Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('memory_legacy_links',
        sa.Column('household_id',sa.Uuid(as_uuid=True),nullable=False),
        sa.Column('legacy_type',sa.String(length=32),nullable=False),
        sa.Column('legacy_id',sa.String(length=64),nullable=False),
        sa.Column('entity_id',sa.Uuid(as_uuid=True),nullable=False),
        sa.PrimaryKeyConstraint('household_id','legacy_type','legacy_id'))
    op.create_index('idx_memory_legacy_link_entity','memory_legacy_links',['household_id','entity_id'],unique=True)

def downgrade():
    op.drop_index('idx_memory_legacy_link_entity',table_name='memory_legacy_links')
    op.drop_table('memory_legacy_links')

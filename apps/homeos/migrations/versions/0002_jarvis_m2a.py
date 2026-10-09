"""JARVIS M2A task and conversation metadata.
Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('tasks', sa.Column('priority', sa.String(), nullable=False, server_default='MEDIUM'))
    op.add_column('tasks', sa.Column('source', sa.String(), nullable=False, server_default='MANUAL'))
    op.add_column('tasks', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column('messages', sa.Column('intent', sa.String(), nullable=False, server_default='GENERAL'))
    op.add_column('messages', sa.Column('action_ref', sa.String(), nullable=True))

def downgrade():
    op.drop_column('messages','action_ref')
    op.drop_column('messages','intent')
    op.drop_column('tasks','created_at')
    op.drop_column('tasks','source')
    op.drop_column('tasks','priority')

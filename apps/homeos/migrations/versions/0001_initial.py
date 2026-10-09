"""Versioned HomeOS MVP baseline. Subsequent changes belong to migrations 0002+.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Do not import the current app's Base here. Its schema evolves over time;
    # create_all(Base.metadata) would also create future columns/tables and make
    # subsequent Alembic migrations fail on a newly initialized database.
    op.create_table('households',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False))
    op.create_table('members',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('language', sa.String(), nullable=False))
    op.create_table('rooms',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('floor', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False))
    op.create_table('assets',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('room_id', sa.String(), sa.ForeignKey('rooms.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('next_service', sa.String()))
    op.create_table('tasks',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('room_id', sa.String(), sa.ForeignKey('rooms.id')),
        sa.Column('assignee_id', sa.String(), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('due_date', sa.String(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False))
    op.create_table('messages',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('member_id', sa.String(), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('reply', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('evidence',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('task_id', sa.String(), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('member_id', sa.String(), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('review_status', sa.String(), nullable=False))
    op.create_table('issues',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), sa.ForeignKey('households.id'), nullable=False),
        sa.Column('reporter_id', sa.String(), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False))
    op.create_table('audit',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), nullable=False),
        sa.Column('member_id', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ('audit','issues','evidence','messages','tasks','assets','rooms','members','households'):
        op.drop_table(table)

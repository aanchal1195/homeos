"""M4C: per-turn evidence trace for owner-scoped tool-using JARVIS.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision="0006"
down_revision="0005"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id",sa.String(),primary_key=True),
        sa.Column("household_id",sa.String(),sa.ForeignKey("households.id"),nullable=False),
        sa.Column("member_id",sa.String(),sa.ForeignKey("members.id"),nullable=False),
        sa.Column("message_id",sa.String(),sa.ForeignKey("messages.id"),nullable=False,unique=True),
        sa.Column("mode",sa.String(),nullable=False),
        sa.Column("model",sa.String(),nullable=False),
        sa.Column("trace_json",sa.Text(),nullable=False),
        sa.Column("token_usage",sa.Integer(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
    )
    op.create_index("idx_agent_runs_owner_recent","agent_runs",
                    ["household_id","member_id","created_at"])

def downgrade():
    op.drop_index("idx_agent_runs_owner_recent",table_name="agent_runs")
    op.drop_table("agent_runs")

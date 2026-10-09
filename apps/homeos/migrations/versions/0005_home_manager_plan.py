"""M4B: durable human-approved Home Manager plans (non-destructive).

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision="0005"
down_revision="0004"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table(
        "home_manager_plans",
        sa.Column("id",sa.String(),primary_key=True),
        sa.Column("household_id",sa.String(),sa.ForeignKey("households.id"),nullable=False),
        sa.Column("owner_id",sa.String(),sa.ForeignKey("members.id"),nullable=False),
        sa.Column("assignee_id",sa.String(),sa.ForeignKey("members.id"),nullable=False),
        sa.Column("room_id",sa.String(),sa.ForeignKey("rooms.id"),nullable=False),
        sa.Column("plan_kind",sa.String(),nullable=False),
        sa.Column("task_title",sa.String(),nullable=False),
        sa.Column("instruction",sa.Text(),nullable=False),
        sa.Column("due_date",sa.String(),nullable=False),
        sa.Column("status",sa.String(),nullable=False),
        sa.Column("task_id",sa.String(),sa.ForeignKey("tasks.id"),nullable=True,unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("confirmed_at",sa.DateTime(timezone=True),nullable=True),
        sa.CheckConstraint("status IN ('PROPOSED','ASSIGNED','CANCELLED')",
                           name="ck_home_manager_plan_status"),
        sa.CheckConstraint("plan_kind IN ('CLEAN_ROOM')",
                           name="ck_home_manager_plan_kind"),
    )
    op.create_index("idx_manager_household_status","home_manager_plans",
                    ["household_id","status","created_at"])


def downgrade():
    op.drop_index("idx_manager_household_status",table_name="home_manager_plans")
    op.drop_table("home_manager_plans")

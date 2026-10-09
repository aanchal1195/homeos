"""M5: private pre-registration guided floorplan/photo/video evidence and decisions.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision="0007"
down_revision="0006"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table(
        "guided_evidence",
        sa.Column("id",sa.String(),primary_key=True),
        sa.Column("household_id",sa.String(),sa.ForeignKey("households.id"),nullable=False),
        sa.Column("member_id",sa.String(),sa.ForeignKey("members.id"),nullable=False),
        sa.Column("media_kind",sa.String(),nullable=False),
        sa.Column("room_id",sa.String(),sa.ForeignKey("rooms.id"),nullable=True),
        sa.Column("floor_hint",sa.String(),nullable=False),
        sa.Column("room_hint",sa.String(),nullable=False),
        sa.Column("content_type",sa.String(),nullable=False),
        sa.Column("storage_key",sa.String(),nullable=False),
        sa.Column("sha256",sa.String(),nullable=False),
        sa.Column("byte_size",sa.Integer(),nullable=False),
        sa.Column("status",sa.String(),nullable=False),
        sa.Column("suggestions_json",sa.Text(),nullable=False),
        sa.Column("notes_json",sa.Text(),nullable=False),
        sa.Column("model_version",sa.String(),nullable=True),
        sa.Column("consent_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("analyzed_at",sa.DateTime(timezone=True),nullable=True),
        sa.CheckConstraint("media_kind IN ('FLOORPLAN','ROOM_PHOTO','ROOM_VIDEO')",
                           name="ck_guided_media_kind"),
        sa.CheckConstraint("status IN ('UPLOADED','ANALYZING','ANALYZED','FAILED')",
                           name="ck_guided_media_status"),
    )
    op.create_index("idx_guided_evidence_house_created","guided_evidence",
                    ["household_id","created_at"])
    op.create_table(
        "guided_decisions",
        sa.Column("id",sa.String(),primary_key=True),
        sa.Column("household_id",sa.String(),sa.ForeignKey("households.id"),nullable=False),
        sa.Column("member_id",sa.String(),sa.ForeignKey("members.id"),nullable=False),
        sa.Column("source",sa.String(),nullable=False),
        sa.Column("decision_json",sa.Text(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
    )
    op.create_index("idx_guided_decision_house_created","guided_decisions",
                    ["household_id","created_at"])


def downgrade():
    op.drop_index("idx_guided_decision_house_created",table_name="guided_decisions")
    op.drop_table("guided_decisions")
    op.drop_index("idx_guided_evidence_house_created",table_name="guided_evidence")
    op.drop_table("guided_evidence")

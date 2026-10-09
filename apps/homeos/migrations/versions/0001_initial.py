"""Initial HomeOS MVP schema.
Revision ID: 0001
Revises:
"""
from alembic import op
from app.main import Base
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Initial baseline only. Subsequent changes must use explicit Alembic operations.
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())

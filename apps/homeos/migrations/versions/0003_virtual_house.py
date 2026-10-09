"""Virtual house / digital twin onboarding.
Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('households', sa.Column('setup_completed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('properties',
        sa.Column('id',sa.String(),primary_key=True),
        sa.Column('household_id',sa.String(),sa.ForeignKey('households.id'),nullable=False,unique=True),
        sa.Column('name',sa.String(),nullable=False),
        sa.Column('property_type',sa.String(),nullable=False,server_default='independent_house'),
        sa.Column('address_label',sa.String(),nullable=False,server_default=''))
    op.create_table('floors',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('household_id',sa.String(),sa.ForeignKey('households.id'),nullable=False),
        sa.Column('property_id',sa.String(),sa.ForeignKey('properties.id'),nullable=False),sa.Column('name',sa.String(),nullable=False),
        sa.Column('sort_order',sa.Integer(),nullable=False),sa.Column('kind',sa.String(),nullable=False,server_default='floor'),
        sa.UniqueConstraint('property_id','sort_order',name='uq_floor_property_order'))
    op.add_column('rooms',sa.Column('floor_id',sa.String(),nullable=True))
    op.create_foreign_key('fk_rooms_floor_id','rooms','floors',['floor_id'],['id'])
    op.create_table('zones',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('household_id',sa.String(),sa.ForeignKey('households.id'),nullable=False),
        sa.Column('room_id',sa.String(),sa.ForeignKey('rooms.id'),nullable=False),sa.Column('name',sa.String(),nullable=False),
        sa.Column('kind',sa.String(),nullable=False,server_default='area'))
    op.add_column('assets',sa.Column('zone_id',sa.String(),nullable=True))
    op.add_column('assets',sa.Column('asset_type',sa.String(),nullable=False,server_default='appliance'))
    op.create_foreign_key('fk_assets_zone_id','assets','zones',['zone_id'],['id'])
    op.create_table('staff_scopes',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('household_id',sa.String(),sa.ForeignKey('households.id'),nullable=False),
        sa.Column('member_id',sa.String(),sa.ForeignKey('members.id'),nullable=False),sa.Column('floor_id',sa.String(),sa.ForeignKey('floors.id'),nullable=True),
        sa.Column('room_id',sa.String(),sa.ForeignKey('rooms.id'),nullable=True),sa.Column('can_view',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('can_execute_tasks',sa.Boolean(),nullable=False,server_default=sa.true()))

def downgrade():
    op.drop_table('staff_scopes')
    op.drop_constraint('fk_assets_zone_id','assets',type_='foreignkey');op.drop_column('assets','asset_type');op.drop_column('assets','zone_id')
    op.drop_table('zones')
    op.drop_constraint('fk_rooms_floor_id','rooms',type_='foreignkey');op.drop_column('rooms','floor_id')
    op.drop_table('floors');op.drop_table('properties');op.drop_column('households','setup_completed')

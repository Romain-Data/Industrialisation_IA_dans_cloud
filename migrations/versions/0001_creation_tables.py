"""creation des tables commandes et predictions

Revision ID: 0001
Revises: 
Create Date: 2026-10-09 11:39:53.457742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crée les tables commandes (ADR-0001) et predictions."""
    op.create_table('commandes',
    sa.Column('order_id', sa.String(), nullable=False),
    sa.Column('hour', sa.Integer(), nullable=False),
    sa.Column('day_of_week', sa.Integer(), nullable=False),
    sa.Column('weekend', sa.Integer(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('order_value_eur', sa.Float(), nullable=False),
    sa.Column('weight_kg', sa.Float(), nullable=False),
    sa.Column('stock_available', sa.Integer(), nullable=False),
    sa.Column('preparation_time_min', sa.Float(), nullable=False),
    sa.Column('carrier_capacity', sa.Float(), nullable=False),
    sa.Column('weather', sa.String(), nullable=False),
    sa.Column('delivery_zone', sa.String(), nullable=False),
    sa.Column('customer_type', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('stock_available IN (0, 1)', name='ck_commandes_stock'),
    sa.CheckConstraint('weekend IN (0, 1)', name='ck_commandes_weekend'),
    sa.PrimaryKeyConstraint('order_id')
    )
    op.create_table('predictions',
    sa.Column('order_id', sa.String(), nullable=False),
    sa.Column('express_eligible', sa.Boolean(), nullable=False),
    sa.Column('decision', sa.String(), nullable=False),
    sa.Column('probability', sa.Float(), nullable=False),
    sa.Column('model_version', sa.String(), nullable=False),
    sa.Column('predicted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('order_id')
    )


def downgrade() -> None:
    """Supprime les tables : toutes les données sont perdues."""
    op.drop_table('predictions')
    op.drop_table('commandes')

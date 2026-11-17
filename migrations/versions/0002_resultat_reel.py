"""resultat reel de la commande (cible d'entrainement)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17 11:30:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ajoute le résultat observé : la commande a-t-elle pu partir en express ?

    Colonnes nullables : une commande n'a pas de résultat tant qu'il n'est pas
    enregistré. Migration additive, compatible avec la version précédente.
    """
    with op.batch_alter_table("commandes") as batch:
        batch.add_column(sa.Column("express_eligible", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_commandes_express_eligible", "express_eligible IN (0, 1)"
        )


def downgrade() -> None:
    """Supprime le résultat observé : les étiquettes enregistrées sont perdues."""
    with op.batch_alter_table("commandes") as batch:
        batch.drop_constraint("ck_commandes_express_eligible", type_="check")
        batch.drop_column("outcome_recorded_at")
        batch.drop_column("express_eligible")

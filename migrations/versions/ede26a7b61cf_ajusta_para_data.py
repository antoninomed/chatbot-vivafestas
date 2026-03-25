"""ajusta para data

Revision ID: ede26a7b61cf
Revises: 3a3ec5c83251
Create Date: 2026-03-17 17:31:01.251645

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ede26a7b61cf'
down_revision: Union[str, Sequence[str], None] = '3a3ec5c83251'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade():
    op.add_column(
        "registros_alugueis",
        sa.Column("data_reserva", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_entrega", sa.DateTime(timezone=True), nullable=True)
    )

    op.execute("""
        UPDATE registros_alugueis
        SET
            data_reserva = COALESCE(reserva_inicio, data_entrega_real),
            data_entrega = COALESCE(reserva_fim, data_devolucao_real)
    """)

    op.alter_column("registros_alugueis", "data_reserva", nullable=False)
    op.alter_column("registros_alugueis", "data_entrega", nullable=False)

    op.drop_column("registros_alugueis", "reserva_inicio")
    op.drop_column("registros_alugueis", "reserva_fim")
    op.drop_column("registros_alugueis", "data_entrega_real")
    op.drop_column("registros_alugueis", "data_devolucao_real")


def downgrade():
    op.add_column(
        "registros_alugueis",
        sa.Column("reserva_inicio", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("reserva_fim", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_entrega_real", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_devolucao_real", sa.DateTime(timezone=True), nullable=True)
    )

    op.execute("""
        UPDATE registros_alugueis
        SET
            reserva_inicio = data_reserva,
            reserva_fim = data_entrega,
            data_entrega_real = data_entrega,
            data_devolucao_real = data_entrega
    """)

    op.drop_column("registros_alugueis", "data_reserva")
    op.drop_column("registros_alugueis", "data_entrega")
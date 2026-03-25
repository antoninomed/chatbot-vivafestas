"""ajusta registros aluguel para reserva e devolucao

Revision ID: b7e20b0d45a1
Revises: 2f2a478552d0
Create Date: 2026-03-17 15:13:53.538882

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e20b0d45a1'
down_revision: Union[str, Sequence[str], None] = '2f2a478552d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.add_column(
        "registros_alugueis",
        sa.Column("reserva_inicio", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("reserva_fim", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_entrega_real", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_devolucao_real", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_registros_alugueis_reserva_inicio",
        "registros_alugueis",
        ["reserva_inicio"],
        unique=False,
    )
    op.create_index(
        "ix_registros_alugueis_reserva_fim",
        "registros_alugueis",
        ["reserva_fim"],
        unique=False,
    )

    # Copia os dados antigos para os novos campos
    op.execute("""
        UPDATE registros_alugueis
        SET
            reserva_inicio = data_entrega,
            reserva_fim = data_recebimento,
            data_entrega_real = data_entrega,
            data_devolucao_real = data_recebimento
    """)

    # Se quiser obrigar o preenchimento daqui pra frente:
    op.alter_column("registros_alugueis", "reserva_inicio", nullable=False)
    op.alter_column("registros_alugueis", "reserva_fim", nullable=False)

    op.drop_column("registros_alugueis", "data_entrega")
    op.drop_column("registros_alugueis", "data_recebimento")


def downgrade():
    op.add_column(
        "registros_alugueis",
        sa.Column("data_entrega", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "registros_alugueis",
        sa.Column("data_recebimento", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute("""
        UPDATE registros_alugueis
        SET
            data_entrega = reserva_inicio,
            data_recebimento = reserva_fim
    """)

    op.drop_index("ix_registros_alugueis_reserva_fim", table_name="registros_alugueis")
    op.drop_index("ix_registros_alugueis_reserva_inicio", table_name="registros_alugueis")

    op.drop_column("registros_alugueis", "data_devolucao_real")
    op.drop_column("registros_alugueis", "data_entrega_real")
    op.drop_column("registros_alugueis", "reserva_fim")
    op.drop_column("registros_alugueis", "reserva_inicio")
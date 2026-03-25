"""add kit photos and auto code support

Revision ID: b92f6bf84171
Revises: 076089392d0d
Create Date: 2026-03-17 11:02:54.196924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b92f6bf84171'
down_revision: Union[str, Sequence[str], None] = '076089392d0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'kit_fotos',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('kit_id', sa.UUID(), nullable=False),
        sa.Column('foto_url', sa.String(), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['kit_id'], ['kits_festa.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    conn = op.get_bind()

    kits = conn.execute(sa.text("""
        SELECT id
        FROM kits_festa
        WHERE codigo_kit IS NULL OR codigo_kit = ''
        ORDER BY id
    """)).fetchall()

    for i, kit in enumerate(kits, start=1):
        conn.execute(
            sa.text("""
                UPDATE kits_festa
                SET codigo_kit = :codigo
                WHERE id = :id
            """),
            {
                "codigo": f"KIT-{i:04d}",
                "id": str(kit.id),
            }
        )

    op.alter_column(
        'kits_festa',
        'codigo_kit',
        existing_type=sa.VARCHAR(),
        nullable=False
    )

    op.create_unique_constraint(
        'uq_kits_festa_codigo_kit',
        'kits_festa',
        ['codigo_kit']
    )

    op.alter_column(
        'kits_festa',
        'ativo',
        existing_type=sa.BOOLEAN(),
        nullable=True
    )

    op.drop_column('kits_festa', 'criado_em')
    op.drop_column('kits_festa', 'foto_url')


def downgrade():
    op.add_column('kits_festa', sa.Column('foto_url', sa.VARCHAR(), nullable=True))
    op.add_column('kits_festa', sa.Column('criado_em', sa.TIMESTAMP(timezone=True), nullable=True))

    op.alter_column(
        'kits_festa',
        'ativo',
        existing_type=sa.BOOLEAN(),
        nullable=False
    )

    op.drop_constraint('uq_kits_festa_codigo_kit', 'kits_festa', type_='unique')

    op.alter_column(
        'kits_festa',
        'codigo_kit',
        existing_type=sa.VARCHAR(),
        nullable=True
    )

    op.drop_table('kit_fotos')
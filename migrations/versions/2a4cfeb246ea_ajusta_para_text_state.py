"""ajusta para text state

Revision ID: 2a4cfeb246ea
Revises: bfb095ff266a
Create Date: 2026-03-18 11:58:06.329853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a4cfeb246ea'
down_revision: Union[str, Sequence[str], None] = 'bfb095ff266a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column(
        "conversations",
        "state",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        existing_nullable=True,
    )

def downgrade():
    op.alter_column(
        "conversations",
        "state",
        existing_type=sa.Text(),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
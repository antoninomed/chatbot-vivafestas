"""ajusta para tamanho do state 255

Revision ID: bfb095ff266a
Revises: ede26a7b61cf
Create Date: 2026-03-18 11:50:45.897835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfb095ff266a'
down_revision: Union[str, Sequence[str], None] = 'ede26a7b61cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

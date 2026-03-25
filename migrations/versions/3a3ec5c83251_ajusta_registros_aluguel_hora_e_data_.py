"""ajusta registros aluguel hora e data real

Revision ID: 3a3ec5c83251
Revises: b7e20b0d45a1
Create Date: 2026-03-17 16:32:09.200418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a3ec5c83251'
down_revision: Union[str, Sequence[str], None] = 'b7e20b0d45a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

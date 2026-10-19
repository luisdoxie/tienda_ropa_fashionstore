"""vista reportes ventas

Revision ID: 6f4501e2abc6
Revises: 2e3c82098813
Create Date: 2026-09-08 12:34:47.707727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.comercial.repository import VW_VENTAS_DETALLE_SQL


# revision identifiers, used by Alembic.
revision: str = '6f4501e2abc6'
down_revision: Union[str, None] = '2e3c82098813'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(VW_VENTAS_DETALLE_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vw_ventas_detalle")

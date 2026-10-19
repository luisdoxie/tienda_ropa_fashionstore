"""quitar modo espejo del probador

Elimina lo que solo usaba el modo espejo: la tabla `sesion_probador`
(el uso del probador se mide ahora con `probador_generacion`) y la columna
`activo_probador.anclajes` (puntos de anclaje del overlay en vivo).

Los anclajes ya guardados se pierden; el `downgrade` solo recrea la
estructura, no los datos.

Revision ID: a4c8e1f2b7d3
Revises: 78a0130804a0
Create Date: 2026-10-19 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a4c8e1f2b7d3'
down_revision: Union[str, None] = '78a0130804a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('sesion_probador')
    op.drop_column('activo_probador', 'anclajes')


def downgrade() -> None:
    op.add_column(
        'activo_probador',
        sa.Column('anclajes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    )
    op.create_table('sesion_probador',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=True),
    sa.Column('variante_id', sa.Integer(), nullable=False),
    sa.Column('modo', sa.String(length=15), nullable=False),
    sa.Column('duracion_seg', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("modo IN ('espejo','generativo')", name='ck_sesion_probador_modo'),
    sa.ForeignKeyConstraint(['cliente_id'], ['cliente.id'], ),
    sa.ForeignKeyConstraint(['variante_id'], ['producto_variante.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

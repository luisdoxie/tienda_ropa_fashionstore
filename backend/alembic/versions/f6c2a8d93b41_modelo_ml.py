"""modelo_ml: modelos de Machine Learning entrenados por empresa

Tabla `modelo_ml` (E11, CU-24, D22): cada versión de un modelo entrenado SOLO con los datos de una
empresa, con sus métricas, sus parámetros y el artefacto serializado (BYTEA: el disco de Railway es
efímero). UNIQUE (empresa_id, tipo, version) y un índice parcial único (empresa_id, tipo) WHERE
activo dejan una sola versión vigente por empresa y tipo. El tipo admite desde ya
'anomalias_ventas' (D37: no se implementa en E11, pero sumarlo después no necesita migración).

Revisada a mano: solo `create_table` + 2 índices. No toca otras tablas ni datos. No importa nada de
`app.*`. No crea permisos: los de la analítica llegan con la E12.

Revision ID: f6c2a8d93b41
Revises: e4a7c19b3d52
Create Date: 2026-10-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6c2a8d93b41'
down_revision: Union[str, None] = 'e4a7c19b3d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'modelo_ml',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=30), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('metricas', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('parametros', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('artefacto', sa.LargeBinary(), nullable=True),
        sa.Column('artefacto_sha256', sa.String(length=64), nullable=True),
        sa.Column('artefacto_bytes', sa.Integer(), nullable=True),
        sa.Column('filas_entrenamiento', sa.Integer(), nullable=False),
        sa.Column('datos_desde', sa.Date(), nullable=True),
        sa.Column('datos_hasta', sa.Date(), nullable=True),
        sa.Column('entrenado_por', sa.Integer(), nullable=True),
        sa.Column('entrenado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "tipo IN ('demanda_semanal','segmentos_rfm','anomalias_ventas')", name='ck_modelo_ml_tipo'
        ),
        sa.CheckConstraint('version >= 1', name='ck_modelo_ml_version'),
        sa.CheckConstraint('filas_entrenamiento >= 0', name='ck_modelo_ml_filas'),
        sa.CheckConstraint(
            'artefacto_bytes IS NULL OR (artefacto_bytes >= 0 AND artefacto_bytes <= 8388608)',
            name='ck_modelo_ml_artefacto_bytes',
        ),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['entrenado_por'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'tipo', 'version', name='uq_modelo_ml_empresa_tipo_version'),
    )
    op.create_index('ix_modelo_ml_empresa_id', 'modelo_ml', ['empresa_id'], unique=False)
    op.create_index(
        'uq_modelo_ml_activo',
        'modelo_ml',
        ['empresa_id', 'tipo'],
        unique=True,
        postgresql_where=sa.text('activo'),
        sqlite_where=sa.text('activo'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_modelo_ml_activo',
        table_name='modelo_ml',
        postgresql_where=sa.text('activo'),
        sqlite_where=sa.text('activo'),
    )
    op.drop_index('ix_modelo_ml_empresa_id', table_name='modelo_ml')
    op.drop_table('modelo_ml')

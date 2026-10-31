"""copia_seguridad: historial de las copias de seguridad por empresa

Tabla `copia_seguridad` (E22, D24-D25): SOLO metadatos de cada copia (quien la pidio, cuando, tamano,
filas por tabla y el SHA-256 del ZIP). El ZIP no se conserva: se entrega una vez, en la misma respuesta
que lo crea. Un indice unico parcial (empresa_id) WHERE estado = 'en_proceso' deja a lo sumo una copia en
proceso por empresa (es el candado, en PostgreSQL y en SQLite). `activo` marca las copias que siguen en el
historial visible (el limite lo da plan.max_copias_historial); no se borra nada.
Ademas, el permiso `copias.gestionar` y su asignacion al rol administrador (la produccion no corre seeds).

Revisada a mano: solo `create_table` + 3 indices y el permiso. No toca otras tablas. No importa nada de
`app.*`.

Revision ID: a9d3f5c27e84
Revises: f6c2a8d93b41
Create Date: 2026-10-31 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9d3f5c27e84'
down_revision: Union[str, None] = 'f6c2a8d93b41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISOS = [
    ('copias.gestionar', 'copias', 'Crear y descargar la copia de seguridad de la empresa'),
]
ASIGNACIONES = [
    ('administrador', 'copias.gestionar'),
]


def upgrade() -> None:
    op.create_table(
        'copia_seguridad',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('tamano_bytes', sa.BigInteger(), nullable=True),
        sa.Column('tablas_incluidas', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('version_esquema', sa.String(length=40), nullable=True),
        sa.Column('checksum', sa.String(length=64), nullable=True),
        sa.Column('motivo_fallo', sa.String(length=60), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('terminado_en', sa.DateTime(), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.CheckConstraint("estado IN ('en_proceso','completada','fallida')", name='ck_copia_seguridad_estado'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_copia_seguridad_empresa_id', 'copia_seguridad', ['empresa_id'], unique=False)
    op.create_index('ix_copia_empresa_creado', 'copia_seguridad', ['empresa_id', 'creado_en'], unique=False)
    op.create_index(
        'ux_copia_en_proceso',
        'copia_seguridad',
        ['empresa_id'],
        unique=True,
        postgresql_where=sa.text("estado = 'en_proceso'"),
        sqlite_where=sa.text("estado = 'en_proceso'"),
    )

    for codigo, modulo, descripcion in PERMISOS:
        op.execute(
            sa.text(
                "INSERT INTO permiso (codigo, modulo, descripcion) "
                "VALUES (:codigo, :modulo, :descripcion) "
                "ON CONFLICT (codigo) DO NOTHING"
            ).bindparams(codigo=codigo, modulo=modulo, descripcion=descripcion)
        )
    # Si el rol o el permiso no existen (base sin seeds) el SELECT no devuelve filas y no se
    # inserta nada, sin error.
    for rol, permiso in ASIGNACIONES:
        op.execute(
            sa.text(
                "INSERT INTO rol_permiso (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM rol r, permiso p "
                "WHERE r.nombre = :rol AND p.codigo = :permiso "
                "ON CONFLICT DO NOTHING"
            ).bindparams(rol=rol, permiso=permiso)
        )


def downgrade() -> None:
    for codigo, _modulo, _descripcion in PERMISOS:
        op.execute(
            sa.text(
                "DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo = :codigo)"
            ).bindparams(codigo=codigo)
        )
        op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=codigo))
    op.drop_index(
        'ux_copia_en_proceso',
        table_name='copia_seguridad',
        postgresql_where=sa.text("estado = 'en_proceso'"),
        sqlite_where=sa.text("estado = 'en_proceso'"),
    )
    op.drop_index('ix_copia_empresa_creado', table_name='copia_seguridad')
    op.drop_index('ix_copia_seguridad_empresa_id', table_name='copia_seguridad')
    op.drop_table('copia_seguridad')

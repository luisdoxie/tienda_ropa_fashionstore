"""bitacora de auditoria

Tabla `bitacora` (E06, D26): registro de solo anexar de las acciones sensibles,
con `empresa_id` NULL permitido (acciones de la plataforma sin empresa), tres
indices para la consulta paginada y el permiso `bitacora.ver`, que recibe el
rol `administrador` (la produccion no corre seeds).

Revisada a mano: solo `create_table` + 3 indices, y el permiso. No toca otras
tablas. No importa nada de `app.*`.

Revision ID: c3f7a91d5e20
Revises: bab547335648
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3f7a91d5e20'
down_revision: Union[str, None] = 'bab547335648'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISO = ('bitacora.ver', 'bitacora', 'Consultar la bitácora de auditoría de la empresa')


def upgrade() -> None:
    op.create_table(
        'bitacora',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('entidad', sa.String(length=60), nullable=False),
        sa.Column('entidad_id', sa.BigInteger(), nullable=True),
        sa.Column('accion', sa.String(length=40), nullable=False),
        sa.Column('datos', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bitacora_empresa_fecha', 'bitacora', ['empresa_id', 'creado_en'], unique=False)
    op.create_index('ix_bitacora_empresa_entidad', 'bitacora', ['empresa_id', 'entidad', 'entidad_id'], unique=False)
    op.create_index('ix_bitacora_usuario_fecha', 'bitacora', ['usuario_id', 'creado_en'], unique=False)

    codigo, modulo, descripcion = PERMISO
    op.execute(
        sa.text(
            "INSERT INTO permiso (codigo, modulo, descripcion) "
            "VALUES (:codigo, :modulo, :descripcion) "
            "ON CONFLICT (codigo) DO NOTHING"
        ).bindparams(codigo=codigo, modulo=modulo, descripcion=descripcion)
    )
    # Si el rol o el permiso no existen (base sin seeds) el SELECT no devuelve
    # filas y no se inserta nada, sin error.
    op.execute(
        sa.text(
            "INSERT INTO rol_permiso (rol_id, permiso_id) "
            "SELECT r.id, p.id FROM rol r, permiso p "
            "WHERE r.nombre = 'administrador' AND p.codigo = :codigo "
            "ON CONFLICT DO NOTHING"
        ).bindparams(codigo=codigo)
    )


def downgrade() -> None:
    codigo = PERMISO[0]
    op.execute(
        sa.text(
            "DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo = :codigo)"
        ).bindparams(codigo=codigo)
    )
    op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=codigo))
    op.drop_index('ix_bitacora_usuario_fecha', table_name='bitacora')
    op.drop_index('ix_bitacora_empresa_entidad', table_name='bitacora')
    op.drop_index('ix_bitacora_empresa_fecha', table_name='bitacora')
    op.drop_table('bitacora')

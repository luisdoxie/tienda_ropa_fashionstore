"""operacion_sync: operaciones hechas sin conexion

Tabla `operacion_sync` (E07, CU-25, D12-D14): cada venta de contado o reserva que el
cliente registra sin conexion y envia en un lote. UNIQUE (empresa_id, operacion_id) hace
idempotente el reenvio; `sucursal_id` admite NULL (la sucursal pedida no existe o es de
otra empresa: la operacion se guarda rechazada y la FK no puede apuntar a una ajena).
Ademas, los permisos `sincronizacion.operar` y `sincronizacion.supervisar` y su asignacion
a los roles (la produccion no corre seeds).

Revisada a mano: solo `create_table` + 4 indices y los permisos. No toca otras tablas.
No importa nada de `app.*`.

Revision ID: d8b2c4e61f37
Revises: c3f7a91d5e20
Create Date: 2026-10-23 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd8b2c4e61f37'
down_revision: Union[str, None] = 'c3f7a91d5e20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISOS = [
    ('sincronizacion.operar', 'sincronizacion', 'Enviar operaciones hechas sin conexión y consultar las propias'),
    ('sincronizacion.supervisar', 'sincronizacion', 'Ver las operaciones sin conexión de la empresa o de la sucursal'),
]
ASIGNACIONES = [
    ('administrador', 'sincronizacion.operar'),
    ('administrador', 'sincronizacion.supervisar'),
    ('encargado_sucursal', 'sincronizacion.operar'),
    ('encargado_sucursal', 'sincronizacion.supervisar'),
    ('cajero', 'sincronizacion.operar'),
]


def upgrade() -> None:
    op.create_table(
        'operacion_sync',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('sucursal_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('operacion_id', sa.Uuid(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('resultado', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('motivo', sa.String(length=60), nullable=True),
        sa.Column('fecha_operacion', sa.DateTime(), nullable=False),
        sa.Column('recibida_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('procesada_en', sa.DateTime(), nullable=True),
        sa.Column('intentos', sa.Integer(), server_default='1', nullable=False),
        sa.Column('dispositivo', sa.String(length=60), nullable=True),
        sa.CheckConstraint("tipo IN ('venta_contado','reserva')", name='ck_operacion_sync_tipo'),
        sa.CheckConstraint(
            "estado IN ('en_proceso','confirmada','rechazada','en_conflicto')", name='ck_operacion_sync_estado'
        ),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['sucursal_id'], ['sucursal.id']),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'operacion_id', name='uq_operacion_sync_empresa_operacion'),
    )
    op.create_index('ix_operacion_sync_empresa_id', 'operacion_sync', ['empresa_id'], unique=False)
    op.create_index(
        'ix_operacion_sync_empresa_estado', 'operacion_sync', ['empresa_id', 'estado', 'recibida_en'], unique=False
    )
    op.create_index(
        'ix_operacion_sync_sucursal_fecha', 'operacion_sync', ['empresa_id', 'sucursal_id', 'fecha_operacion'], unique=False
    )
    op.create_index('ix_operacion_sync_usuario', 'operacion_sync', ['usuario_id', 'recibida_en'], unique=False)

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
    op.drop_index('ix_operacion_sync_usuario', table_name='operacion_sync')
    op.drop_index('ix_operacion_sync_sucursal_fecha', table_name='operacion_sync')
    op.drop_index('ix_operacion_sync_empresa_estado', table_name='operacion_sync')
    op.drop_index('ix_operacion_sync_empresa_id', table_name='operacion_sync')
    op.drop_table('operacion_sync')

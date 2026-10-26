"""plazo de cambio de prendas por empresa y permiso para resolver conflictos

Columna `empresa.plazo_cambio_horas` (E08, D19): plazo propio de la empresa para
devolver o cambiar prendas, contado desde la fecha real de la venta. NULL = usar
el del plan (`plan.plazo_cambio_horas_defecto`). CHECK entre 1 y 720 horas.
Ademas, el permiso `sincronizacion.resolver` (forzar o rechazar una operacion sin
conexion en conflicto) y su asignacion a los roles administrador y encargado_sucursal
(la produccion no corre seeds).

Revisada a mano: solo una columna nullable con su CHECK y el permiso. No toca otras
tablas ni datos existentes (todas las empresas quedan con NULL, es decir, con el plazo
de su plan). No importa nada de `app.*`.

Revision ID: e4a7c19b3d52
Revises: d8b2c4e61f37
Create Date: 2026-10-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4a7c19b3d52'
down_revision: Union[str, None] = 'd8b2c4e61f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISO = ('sincronizacion.resolver', 'sincronizacion', 'Forzar o rechazar una operación sin conexión en conflicto')
ROLES = ('administrador', 'encargado_sucursal')


def upgrade() -> None:
    op.add_column('empresa', sa.Column('plazo_cambio_horas', sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        'ck_empresa_plazo_cambio',
        'empresa',
        'plazo_cambio_horas IS NULL OR plazo_cambio_horas BETWEEN 1 AND 720',
    )

    codigo, modulo, descripcion = PERMISO
    op.execute(
        sa.text(
            "INSERT INTO permiso (codigo, modulo, descripcion) "
            "VALUES (:codigo, :modulo, :descripcion) "
            "ON CONFLICT (codigo) DO NOTHING"
        ).bindparams(codigo=codigo, modulo=modulo, descripcion=descripcion)
    )
    # Si el rol o el permiso no existen (base sin seeds) el SELECT no devuelve filas y no se
    # inserta nada, sin error.
    for rol in ROLES:
        op.execute(
            sa.text(
                "INSERT INTO rol_permiso (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM rol r, permiso p "
                "WHERE r.nombre = :rol AND p.codigo = :permiso "
                "ON CONFLICT DO NOTHING"
            ).bindparams(rol=rol, permiso=codigo)
        )


def downgrade() -> None:
    codigo = PERMISO[0]
    op.execute(
        sa.text(
            "DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo = :codigo)"
        ).bindparams(codigo=codigo)
    )
    op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=codigo))
    op.drop_constraint('ck_empresa_plazo_cambio', 'empresa', type_='check')
    op.drop_column('empresa', 'plazo_cambio_horas')

"""multitenant: empresa, plan y suscripcion

Esquema para varias empresas (tenants) en una sola base (E01, D01-D08):

- Tablas nuevas `plan`, `empresa` y `suscripcion`.
- Datos base: los planes `basico` y `profesional`, la empresa semilla
  `fashionstore` (SIEMPRE, también en una base vacía) y su suscripción
  activa al plan profesional (fecha_inicio = hoy, vencimiento = hoy + 365).
- `empresa_id` (FK + índice) en las 50 tablas propias de empresa; los datos
  existentes se asignan a la empresa semilla. `usuario.empresa_id` queda NULL
  permitido (NULL = superadministrador de la plataforma); las otras 49, NOT NULL.
- Las 17 llaves únicas de negocio pasan a ser únicas POR EMPRESA, más el
  índice único parcial de correos de superadministradores.
- Índices compuestos para las consultas calientes y el índice único parcial
  de la suscripción vigente.
- Rol `superadministrador` y permisos `plataforma.gestionar` y
  `empresa.gestionar` (la producción no corre seeds).
- Vistas `vw_ventas_detalle` y `vw_inventario_consolidado` en versión V2
  (con `empresa_id` al final y cada JOIN dentro de la misma empresa).

Escrita a mano. NO usar autogenerate sobre `stock`: la columna generada
`stock.cantidad_disponible` no se toca aquí. No importa nada de `app.*`: las
listas y el SQL de las vistas van como literales (las migraciones no deben
cambiar cuando el código cambia).

ADVERTENCIA: el `downgrade` solo es seguro con UNA empresa; con más de una
lanza RuntimeError (las llaves únicas por empresa no se pueden volver
globales sin perder datos).

Revision ID: bab547335648
Revises: a4c8e1f2b7d3
Create Date: 2026-10-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bab547335648'
down_revision: Union[str, None] = 'a4c8e1f2b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CODIGO_EMPRESA_SEMILLA = 'fashionstore'

# Mismos valores que scripts/seed_planes.PLANES (una prueba los compara).
PLANES: list[dict] = [
    {
        "codigo": "basico",
        "nombre": "Básico",
        "max_sucursales": 2,
        "reportes_convencionales": True,
        "reportes_ia": False,
        "operacion_offline": True,
        "analitica_ml": False,
        "copias_seguridad": False,
        "gestion_productos": True,
        "gestion_ventas": True,
        "reservas": True,
        "max_copias_historial": 0,
        "plazo_cambio_horas_defecto": 24,
        "activo": True,
    },
    {
        "codigo": "profesional",
        "nombre": "Profesional",
        "max_sucursales": 10,
        "reportes_convencionales": True,
        "reportes_ia": True,
        "operacion_offline": True,
        "analitica_ml": True,
        "copias_seguridad": True,
        "gestion_productos": True,
        "gestion_ventas": True,
        "reservas": True,
        "max_copias_historial": 5,
        "plazo_cambio_horas_defecto": 24,
        "activo": True,
    },
]

# Las 50 tablas propias de empresa (usuario va primero: es la única con
# empresa_id NULL permitido).
TABLAS_EMPRESA: list[str] = [
    'usuario',
    # plataforma
    'cliente', 'notificacion', 'ciudad', 'sucursal', 'horario_sucursal', 'empleado',
    # catalogo
    'categoria', 'talla', 'color', 'material', 'temporada', 'coleccion',
    'producto', 'producto_variante', 'producto_imagen', 'tabla_medida', 'favorito',
    'stock', 'movimiento_inventario', 'transferencia', 'transferencia_detalle',
    'proveedor', 'producto_proveedor', 'orden_compra', 'orden_compra_detalle',
    'recepcion', 'recepcion_detalle', 'activo_probador', 'probador_generacion',
    # comercial
    'reserva', 'reserva_detalle', 'reserva_historial', 'promocion', 'promocion_alcance',
    'venta', 'venta_detalle', 'carrito', 'carrito_detalle', 'devolucion',
    'devolucion_detalle', 'pago', 'transaccion_pasarela', 'zona_envio',
    'regla_tarifa_envio', 'direccion_cliente', 'envio',
    # inteligencia
    'consulta_voz', 'historial_navegacion', 'recomendacion',
]

# Las 17 llaves únicas de negocio:
# (tabla, nombre_viejo, columnas_viejas, nombre_nuevo, columnas_nuevas).
UNICAS_POR_EMPRESA: list[tuple[str, str, list[str], str, list[str]]] = [
    ('usuario', 'usuario_email_key', ['email'],
     'uq_usuario_empresa_email', ['empresa_id', 'email']),
    ('sucursal', 'sucursal_codigo_key', ['codigo'],
     'uq_sucursal_empresa_codigo', ['empresa_id', 'codigo']),
    ('ciudad', 'uq_ciudad_nombre_departamento', ['nombre', 'departamento'],
     'uq_ciudad_empresa_nombre_departamento', ['empresa_id', 'nombre', 'departamento']),
    ('talla', 'talla_codigo_key', ['codigo'],
     'uq_talla_empresa_codigo', ['empresa_id', 'codigo']),
    ('color', 'color_nombre_key', ['nombre'],
     'uq_color_empresa_nombre', ['empresa_id', 'nombre']),
    ('material', 'material_nombre_key', ['nombre'],
     'uq_material_empresa_nombre', ['empresa_id', 'nombre']),
    ('temporada', 'uq_temporada_nombre_anio', ['nombre', 'anio'],
     'uq_temporada_empresa_nombre_anio', ['empresa_id', 'nombre', 'anio']),
    ('producto', 'producto_codigo_key', ['codigo'],
     'uq_producto_empresa_codigo', ['empresa_id', 'codigo']),
    ('producto_variante', 'producto_variante_sku_key', ['sku'],
     'uq_variante_empresa_sku', ['empresa_id', 'sku']),
    ('producto_variante', 'producto_variante_codigo_barras_key', ['codigo_barras'],
     'uq_variante_empresa_codigo_barras', ['empresa_id', 'codigo_barras']),
    ('transferencia', 'transferencia_codigo_key', ['codigo'],
     'uq_transferencia_empresa_codigo', ['empresa_id', 'codigo']),
    ('proveedor', 'proveedor_nit_key', ['nit'],
     'uq_proveedor_empresa_nit', ['empresa_id', 'nit']),
    ('orden_compra', 'orden_compra_codigo_key', ['codigo'],
     'uq_orden_compra_empresa_codigo', ['empresa_id', 'codigo']),
    ('recepcion', 'recepcion_codigo_key', ['codigo'],
     'uq_recepcion_empresa_codigo', ['empresa_id', 'codigo']),
    ('reserva', 'reserva_codigo_key', ['codigo'],
     'uq_reserva_empresa_codigo', ['empresa_id', 'codigo']),
    ('venta', 'venta_codigo_key', ['codigo'],
     'uq_venta_empresa_codigo', ['empresa_id', 'codigo']),
    ('devolucion', 'devolucion_codigo_key', ['codigo'],
     'uq_devolucion_empresa_codigo', ['empresa_id', 'codigo']),
]

PERMISOS_NUEVOS: list[tuple[str, str, str]] = [
    ('plataforma.gestionar', 'plataforma', 'Gestionar empresas, planes y suscripciones de la plataforma'),
    ('empresa.gestionar', 'plataforma', 'Gestionar la empresa propia y su suscripción'),
]
ROL_SUPERADMIN = ('superadministrador', 'Administrador de la plataforma, sin empresa')

# Vistas V1 (las que dejan las migraciones 6f4501e2abc6 y 14ba109668a9), para el downgrade.
VW_VENTAS_DETALLE_V1_SQL = """
CREATE VIEW vw_ventas_detalle AS
SELECT  ve.id              AS venta_id,
        ve.codigo,
        ve.canal,
        ve.fecha,
        s.id               AS sucursal_id,
        s.nombre           AS sucursal,
        p.id               AS producto_id,
        p.nombre           AS producto,
        cat.id             AS categoria_id,
        cat.nombre         AS categoria,
        vd.cantidad,
        vd.precio_unitario,
        vd.subtotal,
        vd.costo_unitario,
        (vd.subtotal - (vd.cantidad * COALESCE(vd.costo_unitario, 0))) AS margen
FROM venta_detalle vd
JOIN venta ve            ON ve.id = vd.venta_id
JOIN sucursal s          ON s.id = ve.sucursal_id
JOIN producto_variante v ON v.id = vd.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN categoria cat       ON cat.id = p.categoria_id
"""

VW_INVENTARIO_CONSOLIDADO_V1_SQL = """
CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN talla t             ON t.id = v.talla_id
JOIN color c             ON c.id = v.color_id
JOIN sucursal s          ON s.id = st.sucursal_id
"""

# Vistas V2: copia exacta de VW_VENTAS_DETALLE_V2_SQL (comercial/repository.py)
# y VW_INVENTARIO_CONSOLIDADO_V2_SQL (catalogo/repository.py). Una prueba
# (tests/plataforma/test_vistas_empresa.py) detecta cualquier desvío.
VW_VENTAS_DETALLE_V2_SQL = """
CREATE VIEW vw_ventas_detalle AS
SELECT  ve.id              AS venta_id,
        ve.codigo,
        ve.canal,
        ve.fecha,
        s.id               AS sucursal_id,
        s.nombre           AS sucursal,
        p.id               AS producto_id,
        p.nombre           AS producto,
        cat.id             AS categoria_id,
        cat.nombre         AS categoria,
        vd.cantidad,
        vd.precio_unitario,
        vd.subtotal,
        vd.costo_unitario,
        (vd.subtotal - (vd.cantidad * COALESCE(vd.costo_unitario, 0))) AS margen,
        ve.empresa_id      AS empresa_id
FROM venta_detalle vd
JOIN venta ve            ON ve.id = vd.venta_id AND ve.empresa_id = vd.empresa_id
JOIN sucursal s          ON s.id = ve.sucursal_id AND s.empresa_id = ve.empresa_id
JOIN producto_variante v ON v.id = vd.variante_id AND v.empresa_id = ve.empresa_id
JOIN producto p          ON p.id = v.producto_id AND p.empresa_id = ve.empresa_id
JOIN categoria cat       ON cat.id = p.categoria_id AND cat.empresa_id = ve.empresa_id
"""

VW_INVENTARIO_CONSOLIDADO_V2_SQL = """
CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario,
        st.empresa_id       AS empresa_id
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id AND v.empresa_id = st.empresa_id
JOIN producto p          ON p.id = v.producto_id AND p.empresa_id = st.empresa_id
JOIN talla t             ON t.id = v.talla_id AND t.empresa_id = st.empresa_id
JOIN color c             ON c.id = v.color_id AND c.empresa_id = st.empresa_id
JOIN sucursal s          ON s.id = st.sucursal_id AND s.empresa_id = st.empresa_id
"""


def _crear_tablas_nuevas() -> None:
    op.create_table(
        'plan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(length=30), nullable=False),
        sa.Column('nombre', sa.String(length=60), nullable=False),
        sa.Column('max_sucursales', sa.SmallInteger(), nullable=False),
        sa.Column('reportes_convencionales', sa.Boolean(), nullable=False),
        sa.Column('reportes_ia', sa.Boolean(), nullable=False),
        sa.Column('operacion_offline', sa.Boolean(), nullable=False),
        sa.Column('analitica_ml', sa.Boolean(), nullable=False),
        sa.Column('copias_seguridad', sa.Boolean(), nullable=False),
        sa.Column('gestion_productos', sa.Boolean(), nullable=False),
        sa.Column('gestion_ventas', sa.Boolean(), nullable=False),
        sa.Column('reservas', sa.Boolean(), nullable=False),
        sa.Column('max_copias_historial', sa.SmallInteger(), nullable=False),
        sa.Column('plazo_cambio_horas_defecto', sa.SmallInteger(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('codigo'),
    )
    op.create_table(
        'empresa',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('codigo', sa.String(length=60), nullable=False),
        sa.Column('logo_url', sa.Text(), nullable=True),
        sa.Column('color_acento', sa.String(length=7), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('codigo'),
    )
    op.create_table(
        'suscripcion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empresa_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=15), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=False),
        sa.Column('fecha_vencimiento', sa.Date(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "estado IN ('activa','vencida','suspendida','cancelada')", name='ck_suscripcion_estado'
        ),
        sa.CheckConstraint('fecha_vencimiento >= fecha_inicio', name='ck_suscripcion_fechas'),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresa.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plan.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_suscripcion_empresa_id', 'suscripcion', ['empresa_id'], unique=False)


def _datos_base() -> None:
    """Planes, empresa semilla y su suscripción."""
    plan = sa.table(
        'plan',
        sa.column('codigo', sa.String),
        sa.column('nombre', sa.String),
        sa.column('max_sucursales', sa.SmallInteger),
        sa.column('reportes_convencionales', sa.Boolean),
        sa.column('reportes_ia', sa.Boolean),
        sa.column('operacion_offline', sa.Boolean),
        sa.column('analitica_ml', sa.Boolean),
        sa.column('copias_seguridad', sa.Boolean),
        sa.column('gestion_productos', sa.Boolean),
        sa.column('gestion_ventas', sa.Boolean),
        sa.column('reservas', sa.Boolean),
        sa.column('max_copias_historial', sa.SmallInteger),
        sa.column('plazo_cambio_horas_defecto', sa.SmallInteger),
        sa.column('activo', sa.Boolean),
    )
    op.bulk_insert(plan, PLANES)
    op.execute(
        sa.text(
            "INSERT INTO empresa (nombre, codigo, activo) "
            "VALUES ('FashionStore', :codigo, true)"
        ).bindparams(codigo=CODIGO_EMPRESA_SEMILLA)
    )
    op.execute(
        sa.text(
            "INSERT INTO suscripcion (empresa_id, plan_id, estado, fecha_inicio, fecha_vencimiento) "
            "SELECT e.id, p.id, 'activa', CURRENT_DATE, CURRENT_DATE + 365 "
            "FROM empresa e, plan p WHERE e.codigo = :empresa AND p.codigo = 'profesional'"
        ).bindparams(empresa=CODIGO_EMPRESA_SEMILLA)
    )


def _agregar_empresa_id() -> None:
    for tabla in TABLAS_EMPRESA:
        op.add_column(tabla, sa.Column('empresa_id', sa.Integer(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {tabla} SET empresa_id = (SELECT id FROM empresa WHERE codigo = :codigo)"
            ).bindparams(codigo=CODIGO_EMPRESA_SEMILLA)
        )
        if tabla != 'usuario':
            op.alter_column(tabla, 'empresa_id', existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(f'fk_{tabla}_empresa', tabla, 'empresa', ['empresa_id'], ['id'])
        op.create_index(f'ix_{tabla}_empresa_id', tabla, ['empresa_id'], unique=False)


def _cambiar_unicas() -> None:
    for tabla, viejo, _cols_viejas, nuevo, cols_nuevas in UNICAS_POR_EMPRESA:
        op.create_unique_constraint(nuevo, tabla, cols_nuevas)
        op.drop_constraint(viejo, tabla, type_='unique')
    op.create_index(
        'ux_usuario_email_plataforma',
        'usuario',
        ['email'],
        unique=True,
        postgresql_where=sa.text('empresa_id IS NULL'),
    )


def _crear_indices() -> None:
    op.create_index('ix_venta_empresa_fecha', 'venta', ['empresa_id', 'fecha'], unique=False)
    op.create_index(
        'ix_reserva_empresa_estado_expiracion',
        'reserva',
        ['empresa_id', 'estado_id', 'fecha_expiracion'],
        unique=False,
    )
    op.create_index('ix_stock_empresa_sucursal', 'stock', ['empresa_id', 'sucursal_id'], unique=False)
    op.create_index(
        'ux_suscripcion_vigente',
        'suscripcion',
        ['empresa_id'],
        unique=True,
        postgresql_where=sa.text("estado <> 'cancelada'"),
    )


def _roles_y_permisos() -> None:
    for codigo, modulo, descripcion in PERMISOS_NUEVOS:
        op.execute(
            sa.text(
                "INSERT INTO permiso (codigo, modulo, descripcion) "
                "VALUES (:codigo, :modulo, :descripcion) "
                "ON CONFLICT (codigo) DO NOTHING"
            ).bindparams(codigo=codigo, modulo=modulo, descripcion=descripcion)
        )
    op.execute(
        sa.text(
            "INSERT INTO rol (nombre, descripcion, activo) "
            "VALUES (:nombre, :descripcion, true) "
            "ON CONFLICT (nombre) DO NOTHING"
        ).bindparams(nombre=ROL_SUPERADMIN[0], descripcion=ROL_SUPERADMIN[1])
    )
    # Si el rol o el permiso no existen (base sin seeds) el SELECT no devuelve
    # filas y no se inserta nada, sin error.
    asignaciones = [
        ('superadministrador', 'plataforma.gestionar'),
        ('superadministrador', 'roles.gestionar'),
        ('administrador', 'empresa.gestionar'),
    ]
    for rol, permiso in asignaciones:
        op.execute(
            sa.text(
                "INSERT INTO rol_permiso (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM rol r, permiso p "
                "WHERE r.nombre = :rol AND p.codigo = :permiso "
                "ON CONFLICT DO NOTHING"
            ).bindparams(rol=rol, permiso=permiso)
        )


def _vistas_v2() -> None:
    op.execute("DROP VIEW IF EXISTS vw_ventas_detalle")
    op.execute("DROP VIEW IF EXISTS vw_inventario_consolidado")
    op.execute(VW_VENTAS_DETALLE_V2_SQL)
    op.execute(VW_INVENTARIO_CONSOLIDADO_V2_SQL)


def upgrade() -> None:
    _crear_tablas_nuevas()
    _datos_base()
    _agregar_empresa_id()
    _cambiar_unicas()
    _crear_indices()
    _roles_y_permisos()
    _vistas_v2()


def downgrade() -> None:
    conexion = op.get_bind()
    empresas = conexion.execute(sa.text("SELECT count(*) FROM empresa")).scalar_one()
    if empresas > 1:
        raise RuntimeError("No se puede revertir con mas de una empresa")

    # Vistas V1 (antes de soltar las columnas que las V2 usan).
    op.execute("DROP VIEW IF EXISTS vw_ventas_detalle")
    op.execute("DROP VIEW IF EXISTS vw_inventario_consolidado")
    op.execute(VW_VENTAS_DETALLE_V1_SQL)
    op.execute(VW_INVENTARIO_CONSOLIDADO_V1_SQL)

    # Roles y permisos nuevos (rol_permiso y usuario_rol primero: FK).
    op.execute(
        sa.text(
            "DELETE FROM usuario_rol WHERE rol_id IN (SELECT id FROM rol WHERE nombre = :rol)"
        ).bindparams(rol=ROL_SUPERADMIN[0])
    )
    op.execute(
        sa.text(
            "DELETE FROM rol_permiso WHERE rol_id IN (SELECT id FROM rol WHERE nombre = :rol)"
        ).bindparams(rol=ROL_SUPERADMIN[0])
    )
    for codigo, _modulo, _descripcion in PERMISOS_NUEVOS:
        op.execute(
            sa.text(
                "DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo = :codigo)"
            ).bindparams(codigo=codigo)
        )
        op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=codigo))
    op.execute(sa.text("DELETE FROM rol WHERE nombre = :rol").bindparams(rol=ROL_SUPERADMIN[0]))

    # Índices compuestos y parciales.
    op.drop_index('ux_suscripcion_vigente', table_name='suscripcion')
    op.drop_index('ix_stock_empresa_sucursal', table_name='stock')
    op.drop_index('ix_reserva_empresa_estado_expiracion', table_name='reserva')
    op.drop_index('ix_venta_empresa_fecha', table_name='venta')
    op.drop_index('ux_usuario_email_plataforma', table_name='usuario')

    # Llaves únicas: restaurar las globales y soltar las por empresa.
    for tabla, viejo, cols_viejas, nuevo, _cols_nuevas in reversed(UNICAS_POR_EMPRESA):
        op.create_unique_constraint(viejo, tabla, cols_viejas)
        op.drop_constraint(nuevo, tabla, type_='unique')

    # empresa_id: índice, FK y columna.
    for tabla in reversed(TABLAS_EMPRESA):
        op.drop_index(f'ix_{tabla}_empresa_id', table_name=tabla)
        op.drop_constraint(f'fk_{tabla}_empresa', tabla, type_='foreignkey')
        op.drop_column(tabla, 'empresa_id')

    op.drop_index('ix_suscripcion_empresa_id', table_name='suscripcion')
    op.drop_table('suscripcion')
    op.drop_table('empresa')
    op.drop_table('plan')

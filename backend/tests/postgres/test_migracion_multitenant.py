"""La migración multitenant (empresa, plan, suscripción y `empresa_id` en 50
tablas) probada en PostgreSQL real, con datos, igual que en producción.

Cada prueba lleva el esquema a la revisión anterior (`a4c8e1f2b7d3`), mete
datos con SQL crudo (como los que ya existen en la base real) y sube a `head`.
Al terminar, la fixture `esquema_en_revision` deja la base otra vez en `head`
para no afectar al resto del perfil (el motor de la sesión es compartido).

Solo corre contra una base `_test` (lo garantiza `url_pg` del conftest).
"""

import datetime as dt

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.tenant import fijar_empresa
from tests.postgres.conftest import ejecutar_alembic, recrear_esquema

REVISION_ANTERIOR = "a4c8e1f2b7d3"
# La migración de multitenant (E01). Las posteriores (bitácora, E06) agregan tablas y
# permisos propios y se prueban en su archivo: aquí se mide solo lo que hace E01.
REVISION_MULTITENANT = "bab547335648"
CODIGO_SEMILLA = "fashionstore"

# Las 50 tablas propias de una empresa (E01, sección 4.1) más `suscripcion`,
# que también lleva empresa_id: 51 tablas con la columna.
TABLAS_CON_EMPRESA = 51

# Las 17 llaves únicas de negocio que dejan de ser globales (nombre viejo) y
# pasan a ser por empresa (nombre nuevo).
UNICAS_VIEJAS = [
    "usuario_email_key",
    "sucursal_codigo_key",
    "uq_ciudad_nombre_departamento",
    "talla_codigo_key",
    "color_nombre_key",
    "material_nombre_key",
    "uq_temporada_nombre_anio",
    "producto_codigo_key",
    "producto_variante_sku_key",
    "producto_variante_codigo_barras_key",
    "transferencia_codigo_key",
    "proveedor_nit_key",
    "orden_compra_codigo_key",
    "recepcion_codigo_key",
    "reserva_codigo_key",
    "venta_codigo_key",
    "devolucion_codigo_key",
]
UNICAS_NUEVAS = [
    "uq_usuario_empresa_email",
    "uq_sucursal_empresa_codigo",
    "uq_ciudad_empresa_nombre_departamento",
    "uq_talla_empresa_codigo",
    "uq_color_empresa_nombre",
    "uq_material_empresa_nombre",
    "uq_temporada_empresa_nombre_anio",
    "uq_producto_empresa_codigo",
    "uq_variante_empresa_sku",
    "uq_variante_empresa_codigo_barras",
    "uq_transferencia_empresa_codigo",
    "uq_proveedor_empresa_nit",
    "uq_orden_compra_empresa_codigo",
    "uq_recepcion_empresa_codigo",
    "uq_reserva_empresa_codigo",
    "uq_venta_empresa_codigo",
    "uq_devolucion_empresa_codigo",
]

# 25 tablas encadenadas (de la ciudad al pago), con SQL crudo y sin ids
# explícitos: las FK se resuelven con subconsultas, así las secuencias quedan
# bien para insertar filas nuevas después.
DATOS_EXISTENTES: list[tuple[str, str]] = [
    ("ciudad", "INSERT INTO ciudad (nombre, departamento, activo) VALUES ('Tarija', 'Tarija', true)"),
    (
        "sucursal",
        "INSERT INTO sucursal (ciudad_id, codigo, nombre, direccion, es_deposito, activo) "
        "SELECT id, 'SUC-1', 'Central', 'Av. 1', false, true FROM ciudad WHERE nombre = 'Tarija'",
    ),
    (
        "usuario",
        "INSERT INTO usuario (nombre, apellido, email, password_hash, activo) VALUES "
        "('Ana', 'Admin', 'ana@example.com', 'hash', true), ('Beto', 'Cliente', 'beto@example.com', 'hash', true)",
    ),
    ("rol", "INSERT INTO rol (nombre, descripcion, activo) VALUES ('administrador', 'Acceso total', true)"),
    (
        "usuario_rol",
        "INSERT INTO usuario_rol (usuario_id, rol_id) "
        "SELECT u.id, r.id FROM usuario u, rol r WHERE u.email = 'ana@example.com' AND r.nombre = 'administrador'",
    ),
    (
        "cliente",
        "INSERT INTO cliente (usuario_id, acepta_datos_foto) SELECT id, false FROM usuario "
        "WHERE email = 'beto@example.com'",
    ),
    (
        "empleado",
        "INSERT INTO empleado (usuario_id, sucursal_id, activo) "
        "SELECT u.id, s.id, true FROM usuario u, sucursal s WHERE u.email = 'ana@example.com' AND s.codigo = 'SUC-1'",
    ),
    ("categoria", "INSERT INTO categoria (nombre, activo) VALUES ('Camisas', true)"),
    ("talla", "INSERT INTO talla (codigo, orden) VALUES ('M', 2)"),
    ("color", "INSERT INTO color (nombre) VALUES ('Gris')"),
    (
        "producto",
        "INSERT INTO producto (codigo, nombre, categoria_id, genero, precio_base, admite_probador, activo) "
        "SELECT 'CAM-1', 'Camisa lisa', id, 'hombre', 100, true, true FROM categoria WHERE nombre = 'Camisas'",
    ),
    (
        "producto_variante",
        "INSERT INTO producto_variante (producto_id, talla_id, color_id, sku, activo) "
        "SELECT p.id, t.id, c.id, 'CAM-1-M-GRIS', true FROM producto p, talla t, color c "
        "WHERE p.codigo = 'CAM-1' AND t.codigo = 'M' AND c.nombre = 'Gris'",
    ),
    (
        "stock",
        "INSERT INTO stock (variante_id, sucursal_id, cantidad_fisica, cantidad_reservada, stock_minimo, "
        "costo_promedio) SELECT v.id, s.id, 10, 0, 2, 60 FROM producto_variante v, sucursal s "
        "WHERE v.sku = 'CAM-1-M-GRIS' AND s.codigo = 'SUC-1'",
    ),
    (
        "tipo_movimiento",
        "INSERT INTO tipo_movimiento (codigo, nombre, signo, afecta_costo) VALUES ('recepcion_t', 'Recepción', 1, true)",
    ),
    (
        "movimiento_inventario",
        "INSERT INTO movimiento_inventario (variante_id, sucursal_id, tipo_movimiento_id, cantidad, saldo_post) "
        "SELECT v.id, s.id, t.id, 10, 10 FROM producto_variante v, sucursal s, tipo_movimiento t "
        "WHERE v.sku = 'CAM-1-M-GRIS' AND s.codigo = 'SUC-1' AND t.codigo = 'recepcion_t'",
    ),
    ("estado_venta", "INSERT INTO estado_venta (codigo, nombre, es_final) VALUES ('completada_t', 'Completada', true)"),
    (
        "venta",
        "INSERT INTO venta (codigo, canal, cliente_id, sucursal_id, estado_id, subtotal, descuento, costo_envio, "
        "total) SELECT 'V-0001', 'digital', c.id, s.id, e.id, 100, 0, 0, 100 "
        "FROM cliente c, sucursal s, estado_venta e WHERE s.codigo = 'SUC-1' AND e.codigo = 'completada_t'",
    ),
    (
        "venta_detalle",
        "INSERT INTO venta_detalle (venta_id, variante_id, cantidad, precio_unitario, descuento_unitario, "
        "subtotal) SELECT ve.id, v.id, 1, 100, 0, 100 FROM venta ve, producto_variante v "
        "WHERE ve.codigo = 'V-0001' AND v.sku = 'CAM-1-M-GRIS'",
    ),
    ("estado_reserva", "INSERT INTO estado_reserva (codigo, nombre, es_final) VALUES ('pendiente_t', 'Pendiente', false)"),
    (
        "reserva",
        "INSERT INTO reserva (codigo, cliente_id, sucursal_id, estado_id, fecha_visita, hora_visita_desde, "
        "hora_visita_hasta, fecha_expiracion) SELECT 'R-0001', c.id, s.id, e.id, CURRENT_DATE + 1, '10:00', "
        "'11:00', now() + interval '1 day' FROM cliente c, sucursal s, estado_reserva e "
        "WHERE s.codigo = 'SUC-1' AND e.codigo = 'pendiente_t'",
    ),
    (
        "reserva_detalle",
        "INSERT INTO reserva_detalle (reserva_id, variante_id, cantidad, preparada) "
        "SELECT r.id, v.id, 1, false FROM reserva r, producto_variante v "
        "WHERE r.codigo = 'R-0001' AND v.sku = 'CAM-1-M-GRIS'",
    ),
    (
        "metodo_pago",
        "INSERT INTO metodo_pago (codigo, nombre, requiere_pasarela, disponible_caja, disponible_online, activo) "
        "VALUES ('efectivo_t', 'Efectivo', false, true, false, true)",
    ),
    ("estado_pago", "INSERT INTO estado_pago (codigo, nombre) VALUES ('aprobado_t', 'Aprobado')"),
    (
        "pago",
        "INSERT INTO pago (venta_id, metodo_pago_id, estado_id, monto) "
        "SELECT ve.id, m.id, e.id, 100 FROM venta ve, metodo_pago m, estado_pago e "
        "WHERE ve.codigo = 'V-0001' AND m.codigo = 'efectivo_t' AND e.codigo = 'aprobado_t'",
    ),
    ("proveedor", "INSERT INTO proveedor (nombre, nit, activo) VALUES ('Textiles SA', '123', true)"),
]
# Permisos de seguridad de la base "vieja": el administrador ya tiene
# roles.gestionar, y la migración debe agregarle empresa.gestionar (no plataforma).
DATOS_PERMISOS: list[str] = [
    "INSERT INTO permiso (codigo, modulo, descripcion) VALUES ('roles.gestionar', 'seguridad', 'Roles')",
    "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r, permiso p "
    "WHERE r.nombre = 'administrador' AND p.codigo = 'roles.gestionar'",
]

TABLAS_SIN_EMPRESA_QUE_CAMBIAN = {"rol", "permiso", "rol_permiso"}


@pytest.fixture()
def esquema_en_revision(engine_pg, url_pg):
    """Devuelve una función `preparar(revision)` que vacía el esquema `public` y
    aplica las migraciones hasta esa revisión. Al terminar la prueba restaura
    `upgrade head`."""

    def preparar(revision: str) -> None:
        recrear_esquema(engine_pg, url_pg, revision)

    yield preparar
    recrear_esquema(engine_pg, url_pg, "head")
    # Las conexiones del pool pueden tener planes de la versión anterior.
    engine_pg.dispose()


def _poblar_base_vieja(engine) -> dict[str, int]:
    """Inserta las filas existentes y devuelve el conteo por tabla."""
    with engine.begin() as conexion:
        for _tabla, sentencia in DATOS_EXISTENTES:
            conexion.execute(text(sentencia))
        for sentencia in DATOS_PERMISOS:
            conexion.execute(text(sentencia))
    return _conteos(engine)


def _tablas(engine) -> list[str]:
    with engine.connect() as conexion:
        return list(
            conexion.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                    "AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version' ORDER BY 1"
                )
            ).scalars()
        )


def _conteos(engine) -> dict[str, int]:
    tablas = _tablas(engine)
    with engine.connect() as conexion:
        return {t: conexion.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in tablas}


def _empresa_semilla(engine) -> int:
    with engine.connect() as conexion:
        return conexion.execute(
            text("SELECT id FROM empresa WHERE codigo = :c"), {"c": CODIGO_SEMILLA}
        ).scalar_one()


def _codigos_de_rol(engine, rol: str) -> set[str]:
    with engine.connect() as conexion:
        return set(
            conexion.execute(
                text(
                    "SELECT p.codigo FROM rol r JOIN rol_permiso rp ON rp.rol_id = r.id "
                    "JOIN permiso p ON p.id = rp.permiso_id WHERE r.nombre = :r"
                ),
                {"r": rol},
            ).scalars()
        )


def _restricciones(engine, tipo: str = "u") -> set[str]:
    with engine.connect() as conexion:
        return set(
            conexion.execute(
                text(
                    "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE c.contype = :t AND n.nspname = 'public'"
                ),
                {"t": tipo},
            ).scalars()
        )


def test_migracion_con_datos_existentes(engine_pg, url_pg, esquema_en_revision):
    esquema_en_revision(REVISION_ANTERIOR)
    antes = _poblar_base_vieja(engine_pg)
    assert len(DATOS_EXISTENTES) == 25
    # Las 25 tablas encadenadas tienen al menos una fila antes de migrar.
    assert all(antes[tabla] >= 1 for tabla, _ in DATOS_EXISTENTES)

    resultado = ejecutar_alembic(url_pg, "upgrade", REVISION_MULTITENANT)
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"

    despues = _conteos(engine_pg)
    # Conteos iguales en todas las tablas que ya existían, salvo las tres de
    # seguridad a las que la migración agrega rol y permisos nuevos.
    for tabla, cantidad in antes.items():
        if tabla not in TABLAS_SIN_EMPRESA_QUE_CAMBIAN:
            assert despues[tabla] == cantidad, f"{tabla}: {cantidad} antes, {despues[tabla]} después"
    assert despues["rol"] == antes["rol"] + 1  # superadministrador
    assert despues["permiso"] == antes["permiso"] + 2  # plataforma.gestionar, empresa.gestionar

    semilla = _empresa_semilla(engine_pg)
    with engine_pg.connect() as conexion:
        tablas_con_empresa = list(
            conexion.execute(
                text(
                    "SELECT c.table_name FROM information_schema.columns c "
                    "JOIN information_schema.tables t ON t.table_schema = c.table_schema "
                    "AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE' "
                    "WHERE c.table_schema = 'public' AND c.column_name = 'empresa_id' ORDER BY 1"
                )
            ).scalars()
        )
        assert len(tablas_con_empresa) == TABLAS_CON_EMPRESA
        for tabla in tablas_con_empresa:
            fuera = conexion.execute(
                text(f'SELECT count(*) FROM "{tabla}" WHERE empresa_id IS NULL OR empresa_id <> :e'),
                {"e": semilla},
            ).scalar_one()
            assert fuera == 0, f"{tabla}: {fuera} filas sin la empresa semilla"
        # Las 25 tablas de datos están entre las que llevan empresa, salvo las
        # 6 globales (rol, tipo_movimiento, estados, metodo/estado de pago) y usuario_rol.
        con_datos_de_empresa = {t for t, _ in DATOS_EXISTENTES} & set(tablas_con_empresa)
        assert len(con_datos_de_empresa) == 25 - 6 - 1

    # Todas las FK son válidas: una fila nueva por el modelo se crea en la empresa de la sesión.
    from app.catalogo.models import Categoria

    with sessionmaker(bind=engine_pg)() as db:
        fijar_empresa(db, semilla)
        nueva = Categoria(nombre="Chamarras")
        db.add(nueva)
        db.commit()
        assert nueva.empresa_id == semilla


def test_vistas_v2_en_postgres(engine_pg, url_pg, esquema_en_revision):
    esquema_en_revision(REVISION_ANTERIOR)
    _poblar_base_vieja(engine_pg)
    with engine_pg.connect() as conexion:
        filas_antes = {
            vista: conexion.execute(text(f"SELECT count(*) FROM {vista}")).scalar_one()
            for vista in ("vw_inventario_consolidado", "vw_ventas_detalle")
        }
    assert all(n >= 1 for n in filas_antes.values()), filas_antes

    assert ejecutar_alembic(url_pg, "upgrade", "head").returncode == 0

    semilla = _empresa_semilla(engine_pg)
    with engine_pg.connect() as conexion:
        for vista, esperadas in filas_antes.items():
            columnas = list(
                conexion.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :v"
                    ),
                    {"v": vista},
                ).scalars()
            )
            assert "empresa_id" in columnas, f"{vista} no expone empresa_id"
            assert conexion.execute(text(f"SELECT count(*) FROM {vista}")).scalar_one() == esperadas
            assert (
                conexion.execute(
                    text(f"SELECT count(*) FROM {vista} WHERE empresa_id = :e"), {"e": semilla}
                ).scalar_one()
                == esperadas
            )


def test_cantidad_disponible_sigue_generada(engine_pg, url_pg, esquema_en_revision):
    esquema_en_revision(REVISION_ANTERIOR)
    _poblar_base_vieja(engine_pg)
    assert ejecutar_alembic(url_pg, "upgrade", "head").returncode == 0

    with engine_pg.begin() as conexion:
        conexion.execute(text("UPDATE stock SET cantidad_reservada = 4"))
        fila = conexion.execute(
            text("SELECT cantidad_fisica, cantidad_reservada, cantidad_disponible FROM stock")
        ).one()
        generada = conexion.execute(
            text(
                "SELECT is_generated FROM information_schema.columns "
                "WHERE table_name = 'stock' AND column_name = 'cantidad_disponible'"
            )
        ).scalar_one()

    assert tuple(fila) == (10, 4, 6)
    assert generada == "ALWAYS"


def test_unicas_por_empresa_en_postgres(engine_pg):
    with engine_pg.begin() as conexion:
        conexion.execute(text("INSERT INTO empresa (nombre, codigo, activo) VALUES ('Otra', 'otra', true)"))
        otra = conexion.execute(text("SELECT id FROM empresa WHERE codigo = 'otra'")).scalar_one()
        primera = conexion.execute(text("SELECT id FROM empresa WHERE codigo = 'fashionstore'")).scalar_one()
        for empresa in (primera, otra):
            conexion.execute(
                text("INSERT INTO categoria (empresa_id, nombre, activo) VALUES (:e, 'Camisas', true)"),
                {"e": empresa},
            )

    def producto(conexion, empresa: int) -> None:
        conexion.execute(
            text(
                "INSERT INTO producto (empresa_id, codigo, nombre, categoria_id, genero, precio_base, "
                "admite_probador, activo) SELECT :e, 'PRD-1', 'Producto', id, 'hombre', 10, true, true "
                "FROM categoria WHERE empresa_id = :e"
            ),
            {"e": empresa},
        )

    # El mismo código en dos empresas distintas: permitido.
    with engine_pg.begin() as conexion:
        producto(conexion, primera)
        producto(conexion, otra)

    # Repetido dentro de una empresa: rechazado.
    with pytest.raises(IntegrityError):
        with engine_pg.begin() as conexion:
            producto(conexion, primera)

    # Dos superadministradores con el mismo correo: índice parcial.
    with engine_pg.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO usuario (empresa_id, nombre, apellido, email, password_hash, activo) "
                "VALUES (NULL, 'Super', 'Uno', 'super@example.com', 'h', true)"
            )
        )
    with pytest.raises(IntegrityError):
        with engine_pg.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO usuario (empresa_id, nombre, apellido, email, password_hash, activo) "
                    "VALUES (NULL, 'Super', 'Dos', 'super@example.com', 'h', true)"
                )
            )

    unicas = _restricciones(engine_pg, "u")
    assert not (set(UNICAS_VIEJAS) & unicas), f"siguen existiendo: {sorted(set(UNICAS_VIEJAS) & unicas)}"
    assert set(UNICAS_NUEVAS) <= unicas, f"faltan: {sorted(set(UNICAS_NUEVAS) - unicas)}"
    with engine_pg.connect() as conexion:
        indices = set(conexion.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")).scalars())
    assert {"ux_usuario_email_plataforma", "ux_suscripcion_vigente"} <= indices
    assert {"ix_venta_empresa_fecha", "ix_reserva_empresa_estado_expiracion", "ix_stock_empresa_sucursal"} <= indices


def test_compare_metadata_vacio(engine_pg, url_pg, esquema_en_revision):
    """Modelos y migraciones coinciden también después de subir desde la
    revisión anterior con datos (no solo en la base creada desde cero)."""
    from app.catalogo import models as _c  # noqa: F401
    from app.comercial import models as _co  # noqa: F401
    from app.inteligencia import models as _i  # noqa: F401
    from app.plataforma import models as _p  # noqa: F401

    esquema_en_revision(REVISION_ANTERIOR)
    _poblar_base_vieja(engine_pg)
    assert ejecutar_alembic(url_pg, "upgrade", "head").returncode == 0

    with engine_pg.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)

    assert diferencias == [], f"Los modelos y las migraciones difieren: {diferencias}"


def test_downgrade_con_una_empresa_funciona(engine_pg, url_pg, esquema_en_revision):
    esquema_en_revision(REVISION_ANTERIOR)
    antes = _poblar_base_vieja(engine_pg)
    assert ejecutar_alembic(url_pg, "upgrade", "head").returncode == 0

    resultado = ejecutar_alembic(url_pg, "downgrade", REVISION_ANTERIOR)
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"

    tablas = set(_tablas(engine_pg))
    assert not ({"empresa", "plan", "suscripcion"} & tablas)
    with engine_pg.connect() as conexion:
        columnas = conexion.execute(
            text("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'empresa_id'")
        ).scalar_one()
        vistas = set(
            conexion.execute(text("SELECT viewname FROM pg_views WHERE schemaname = 'public'")).scalars()
        )
    assert columnas == 0
    assert {"vw_inventario_consolidado", "vw_ventas_detalle"} <= vistas
    unicas = _restricciones(engine_pg, "u")
    assert set(UNICAS_VIEJAS) <= unicas
    assert not (set(UNICAS_NUEVAS) & unicas)
    # Los datos del negocio no se pierden al bajar.
    assert _conteos(engine_pg) == antes

    # Y se puede volver a subir.
    resultado = ejecutar_alembic(url_pg, "upgrade", "head")
    assert resultado.returncode == 0, f"{resultado.stdout}\n{resultado.stderr}"


def test_downgrade_con_dos_empresas_falla_con_mensaje_claro(engine_pg, url_pg, esquema_en_revision):
    # esquema_en_revision restaura `head` al terminar, pase lo que pase.
    with engine_pg.begin() as conexion:
        conexion.execute(text("INSERT INTO empresa (nombre, codigo, activo) VALUES ('Otra', 'otra', true)"))

    resultado = ejecutar_alembic(url_pg, "downgrade", REVISION_ANTERIOR)

    salida = (resultado.stdout + resultado.stderr).lower()
    assert resultado.returncode != 0
    assert "de una empresa" in salida, salida[-600:]
    # El DDL es transaccional: la base queda intacta en `head`.
    assert {"empresa", "plan", "suscripcion"} <= set(_tablas(engine_pg))
    assert set(UNICAS_NUEVAS) <= _restricciones(engine_pg, "u")


def test_planes_y_empresa_semilla(engine_pg, url_pg, esquema_en_revision):
    """Lo que deja la migración por sí sola (la producción no corre seeds)."""
    esquema_en_revision(REVISION_ANTERIOR)
    _poblar_base_vieja(engine_pg)
    assert ejecutar_alembic(url_pg, "upgrade", "head").returncode == 0

    with engine_pg.connect() as conexion:
        planes = dict(conexion.execute(text("SELECT codigo, max_sucursales FROM plan")).all())
        suscripcion = conexion.execute(
            text(
                "SELECT e.codigo, p.codigo, s.estado, s.fecha_inicio, s.fecha_vencimiento "
                "FROM empresa e JOIN suscripcion s ON s.empresa_id = e.id JOIN plan p ON p.id = s.plan_id"
            )
        ).all()
        roles = set(conexion.execute(text("SELECT nombre FROM rol")).scalars())
        permisos = set(conexion.execute(text("SELECT codigo FROM permiso")).scalars())
        empresas = conexion.execute(text("SELECT count(*) FROM empresa")).scalar_one()

    assert planes == {"basico": 2, "profesional": 10}
    assert empresas == 1
    assert len(suscripcion) == 1
    codigo_empresa, codigo_plan, estado, inicio, vencimiento = suscripcion[0]
    assert (codigo_empresa, codigo_plan, estado) == (CODIGO_SEMILLA, "profesional", "activa")
    assert vencimiento - inicio == dt.timedelta(days=365)
    assert {"superadministrador", "administrador"} <= roles
    assert {"plataforma.gestionar", "empresa.gestionar"} <= permisos

    administrador = _codigos_de_rol(engine_pg, "administrador")
    assert "plataforma.gestionar" not in administrador
    assert {"empresa.gestionar", "roles.gestionar"} <= administrador
    assert _codigos_de_rol(engine_pg, "superadministrador") == {"plataforma.gestionar", "roles.gestionar"}


def test_la_semilla_de_pruebas_deja_al_administrador_sin_plataforma(engine_pg):
    """Lo mismo, pero con el seed de seguridad que usa el resto del perfil
    (base_limpia): el administrador no recibe `plataforma.gestionar`."""
    assert "plataforma.gestionar" not in _codigos_de_rol(engine_pg, "administrador")
    assert _codigos_de_rol(engine_pg, "superadministrador") == {"plataforma.gestionar", "roles.gestionar"}

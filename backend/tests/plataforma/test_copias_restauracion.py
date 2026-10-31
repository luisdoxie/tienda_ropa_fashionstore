"""E22: la copia de seguridad es COMPLETA y RECUPERABLE (pruebas R1-R6, SQLite).

Se arma una empresa A con un conjunto completo de datos (el `Universo` de E05 más lo de
`agregar_datos_extra`), otra empresa B (para que los ids de la empresa restaurada difieran de los de A), se
genera la copia de A y se carga en una empresa C VACÍA con el restaurador de pruebas
(`tests/restaurador_copia.py`, que NO es código de producción).

  R1  copia de A -> empresa C vacía -> restaurar.
  R2  conteo por tabla de C == conteo del manifiesto de A.
  R3  checksum canónico por tabla (sin clave primaria, llaves foráneas, empresa_id ni referencias blandas)
      igual entre A y C, más el isomorfismo completo de llaves foráneas y las referencias blandas por
      claves naturales.
  R4  sumas de control iguales y ningún id de A reutilizado en C (el restaurador remapeó de verdad).
  R5  integridad: FK de C resueltas (PRAGMA foreign_key_check) y consistencia entre empresas vacía.
  R6  ida y vuelta: copiar C (por HTTP, con el administrador restaurado) da los mismos checksums que A.

El módulo comparte UN mundo (se arma una vez); las pruebas que escriben (R6, rechazos) van al final.
"""

import io
import json
import zipfile
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import copias
from app.core.database import Base, get_db
from app.core.tenant import fijar_empresa
from app.main import app
from app.plataforma.models import Usuario
from tests.aislamiento.conftest import _dos_empresas, _preparar_base
from tests.aislamiento.universo import crear_universo
from tests.conftest import crear_empresa, token_de
from tests.restaurador_copia import (
    HASH_INUTILIZABLE,
    TABLAS_NO_RESTAURADAS,
    CopiaInvalidaError,
    DestinoNoVacioError,
    agregar_datos_extra,
    checksums_canonicos,
    conteos_por_tabla,
    huerfanas_de_empresa,
    inconsistencias_de_empresa,
    leer_paquete,
    reempaquetar,
    restaurar_copia,
    sumas_de_control,
    verificar_isomorfismo,
    verificar_referencias_blandas,
)

API = "/api/v1/copias-seguridad"
MB = 1024 * 1024
RESTAURABLES = [t for t in copias.TABLAS_INCLUIDAS if t not in TABLAS_NO_RESTAURADAS]


def _copiar(conexion, empresa_id: int, codigo: str) -> copias.ContenidoCopia:
    return copias.generar_copia(
        conexion, empresa_id, empresa={"codigo": codigo, "nombre": codigo}, plan_codigo="profesional",
        version_esquema=None, max_bytes=50 * MB, max_segundos=120,
    )  # fmt: skip


# =================================================================================================
# El mundo del módulo
# =================================================================================================


@pytest.fixture(scope="module")
def _mundo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _sin_begin_implicito(dbapi_conexion, _registro):
        dbapi_conexion.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_explicito(conexion):
        conexion.exec_driver_sql("BEGIN")

    sesiones = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    _preparar_base(engine, sesiones)
    empresa_a, empresa_b = _dos_empresas(sesiones)

    def _db_por_peticion():
        sesion = sesiones()
        try:
            yield sesion
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = _db_por_peticion
    with TestClient(app) as client:
        a = crear_universo(client, sesiones, empresa_a, "A")
        extra = agregar_datos_extra(a)
        b = crear_universo(client, sesiones, empresa_b, "B")  # B DESPUÉS de A: los ids nuevos de C quedan por encima de ambos

        with engine.connect() as conexion:
            origen = _copiar(conexion, a.id, "tienda-a")

        with sesiones() as db:
            destino = crear_empresa(db, "tienda-c", plan="profesional")
            destino_id = destino.id
        with sesiones() as db:
            resultado = restaurar_copia(origen.contenido, db, destino_id)  # R1
        with engine.connect() as conexion:
            restaurada = _copiar(conexion, destino_id, "tienda-c")

        yield SimpleNamespace(
            engine=engine, sesiones=sesiones, client=client, a=a, b=b, extra=extra, origen=origen,
            destino_id=destino_id, resultado=resultado, restaurada=restaurada, db_por_peticion=_db_por_peticion,
        )  # fmt: skip
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture()
def mundo(_mundo):
    app.dependency_overrides[get_db] = _mundo.db_por_peticion  # otra fixture pudo limpiarlo
    return _mundo


def _empresa_vacia(mundo, codigo: str) -> int:
    with mundo.sesiones() as db:
        return crear_empresa(db, codigo, plan="profesional").id


def _conteos(mundo, empresa_id: int) -> dict[str, int]:
    with mundo.engine.connect() as conexion:
        return conteos_por_tabla(conexion, empresa_id)


# =================================================================================================
# R1: la copia de A tiene de todo y se restaura en C
# =================================================================================================


def test_r1_la_empresa_a_tiene_datos_en_todas_las_tablas_incluidas(mundo):
    vacias = [t for t in RESTAURABLES if mundo.origen.tablas[t] == 0]
    assert vacias == [], f"el conjunto de datos de A no cubre estas tablas: {vacias}"
    # Y lo que hace difícil restaurar está presente: categoría hijo con id menor que su padre.
    categorias = {f["id"]: f for f in leer_paquete(mundo.origen.contenido).datos["categoria"]}
    hijo = categorias[mundo.extra["categoria_hijo"]]
    assert hijo["categoria_padre_id"] == mundo.extra["categoria_padre"] > hijo["id"]


def test_r1_se_restauro_en_la_empresa_vacia(mundo):
    assert mundo.resultado.filas.keys() == set(RESTAURABLES)
    assert sum(mundo.resultado.filas.values()) == sum(mundo.origen.tablas[t] for t in RESTAURABLES)


# =================================================================================================
# R2: conteos
# =================================================================================================


def test_r2_conteo_por_tabla_de_c_igual_al_manifiesto_de_a(mundo):
    esperado = {t: mundo.origen.manifiesto["tablas"][t]["filas"] for t in RESTAURABLES}
    assert _conteos(mundo, mundo.destino_id) == esperado
    assert _conteos(mundo, mundo.a.id) != {t: 0 for t in RESTAURABLES}  # (A sigue ahí)


def test_r2_c_conserva_su_empresa_y_su_suscripcion(mundo):
    """`empresa` y `suscripcion` no se restauran: C conserva las suyas (el código y el plan de A no la pisan)."""
    with mundo.engine.connect() as conexion:
        emp = Base.metadata.tables["empresa"]
        assert conexion.execute(text("SELECT count(*) FROM suscripcion WHERE empresa_id = :e"), {"e": mundo.destino_id}).scalar_one() == 1
        assert conexion.execute(select(emp.c.codigo).where(emp.c.id == mundo.destino_id)).scalar_one() == "tienda-c"


# =================================================================================================
# R3: checksum canónico, isomorfismo y referencias blandas
# =================================================================================================


def test_r3_checksum_canonico_por_tabla_igual_entre_a_y_c(mundo):
    de_a, de_c = checksums_canonicos(mundo.origen.contenido), checksums_canonicos(mundo.restaurada.contenido)
    assert de_a.keys() == de_c.keys() == set(RESTAURABLES)
    distintas = [t for t in de_a if de_a[t] != de_c[t]]
    assert distintas == [], f"checksum canónico distinto en: {distintas}"


def test_r3_el_checksum_canonico_detecta_un_cambio(mundo):
    """Control de la propia comparación: alterar un valor de una fila cambia el checksum de esa tabla."""
    alterada = reempaquetar(
        mundo.restaurada.contenido,
        {"datos/producto.json": lambda filas: [{**f, "nombre": f["nombre"] + "!"} if i == 0 else f for i, f in enumerate(filas)]},
    )
    de_a, de_alterada = checksums_canonicos(mundo.origen.contenido), checksums_canonicos(alterada)
    assert [t for t in de_a if de_a[t] != de_alterada[t]] == ["producto"]


def test_r3_las_llaves_foraneas_de_c_son_las_de_a_traducidas(mundo):
    """Isomorfismo: cada fila de A, con su id y sus FK pasados por la tabla de equivalencias, es una fila de C
    (y no sobra ninguna). Es más fuerte que el checksum canónico, que no mira las llaves."""
    assert verificar_isomorfismo(mundo.origen.contenido, mundo.restaurada.contenido, mundo.resultado, mundo.destino_id) == []


def test_r3_el_isomorfismo_detecta_una_llave_foranea_cruzada(mundo):
    """Control: si dos detalles de venta de C apuntan a la venta equivocada, el isomorfismo lo dice."""

    def cruzar(filas):
        filas = [dict(f) for f in filas]
        filas[0]["venta_id"], filas[-1]["venta_id"] = filas[-1]["venta_id"], filas[0]["venta_id"]
        return filas

    mal = reempaquetar(mundo.restaurada.contenido, {"datos/venta_detalle.json": cruzar})
    problemas = verificar_isomorfismo(mundo.origen.contenido, mal, mundo.resultado, mundo.destino_id)
    assert [p.split(":")[0] for p in problemas] == ["venta_detalle"]


def test_r3_la_verificacion_de_referencias_blandas_detecta_un_cruce(mundo):
    def cruzar(filas):
        filas = [dict(f) for f in filas]
        for fila in filas:
            if fila["tipo"] == "reserva":
                fila["referencia_id"] = -1
        return filas

    mal = reempaquetar(mundo.restaurada.contenido, {"datos/notificacion.json": cruzar})
    with pytest.raises(AssertionError, match="notificacion.referencia_id"):
        verificar_referencias_blandas(mundo.origen.contenido, mal, mundo.resultado)


def test_r3_referencias_blandas_remapeadas_apuntan_a_lo_mismo(mundo):
    verificadas = verificar_referencias_blandas(mundo.origen.contenido, mundo.restaurada.contenido, mundo.resultado)
    print(f"\nReferencias blandas verificadas por clave natural: {verificadas}")
    for esperada in (
        "movimiento_inventario.referencia_id:venta",
        "movimiento_inventario.referencia_id:transferencia",
        "movimiento_inventario.referencia_id:recepcion",
        "notificacion.referencia_id:reserva",
        "bitacora.entidad_id:venta",
    ):
        assert verificadas.get(esperada, 0) > 0, f"no hubo referencias de tipo {esperada} que verificar"
    assert mundo.resultado.blandas_sin_resolver == []


def test_r3_ids_dentro_de_json_se_remapearon(mundo):
    origen, destino = leer_paquete(mundo.origen.contenido), leer_paquete(mundo.restaurada.contenido)
    eq = mundo.resultado.equivalencias
    sync_a = next(f for f in origen.datos["operacion_sync"] if f["estado"] == "confirmada")
    sync_c = next(f for f in destino.datos["operacion_sync"] if f["operacion_id"] == sync_a["operacion_id"])
    assert sync_c["payload"]["cliente_id"] == eq["cliente"][sync_a["payload"]["cliente_id"]]
    assert sync_c["payload"]["lineas"][0]["variante_id"] == eq["producto_variante"][sync_a["payload"]["lineas"][0]["variante_id"]]
    assert sync_c["resultado"]["venta_id"] == eq["venta"][sync_a["resultado"]["venta_id"]]
    assert sync_c["resultado"]["ajustes"][0]["movimiento_id"] == eq["movimiento_inventario"][sync_a["resultado"]["ajustes"][0]["movimiento_id"]]
    assert sync_c["resultado"]["avisos"] == ["precio_distinto"]
    bit_a = next(f for f in origen.datos["bitacora"] if f["accion"] == "anular_pago")
    bit_c = next(f for f in destino.datos["bitacora"] if f["accion"] == "anular_pago")
    assert bit_c["datos"] == {"pago_id": eq["pago"][bit_a["datos"]["pago_id"]], "estado_anterior": "pagada"}


def test_r3_referencia_blanda_libre_no_se_remapea(mundo):
    """Límite conocido: un `referencia_tipo` que escribe el cliente (POST /inventario/movimientos) no tiene
    destino conocido, así que su `referencia_id` viaja tal cual."""
    destino = leer_paquete(mundo.restaurada.contenido)
    libres = [f for f in destino.datos["movimiento_inventario"] if f["referencia_tipo"] == "externo_libre"]
    assert [f["referencia_id"] for f in libres] == [987654]


# =================================================================================================
# R4: sumas de control y remapeo real de ids
# =================================================================================================


def test_r4_sumas_de_control_iguales(mundo):
    with mundo.engine.connect() as conexion:
        de_a, de_c = sumas_de_control(conexion, mundo.a.id), sumas_de_control(conexion, mundo.destino_id)
    assert de_a["stock.cantidad_fisica"] > 0 and de_a["venta.total"] > 0 and de_a["pago.monto"] > 0
    assert de_a["venta.total"] != Decimal(0)
    assert len(de_a["detalles_por_venta"]) >= 4
    assert de_a == de_c


def test_r4_ningun_id_de_a_se_reutilizo_en_c(mundo):
    equivalencias = mundo.resultado.equivalencias
    coincidencias = {}
    for tabla in RESTAURABLES:
        if tabla in ("usuario_rol", "producto_proveedor", "favorito"):  # su clave son las FK, no un id propio
            continue
        mapa = equivalencias[tabla]
        assert mapa, f"{tabla} sin equivalencias"
        repetidos = [viejo for viejo, nuevo in mapa.items() if viejo == nuevo]
        solapados = set(mapa) & set(mapa.values())
        if repetidos or solapados:
            coincidencias[tabla] = (repetidos, sorted(solapados))
    assert coincidencias == {}, f"el restaurador reutilizó ids de A: {coincidencias}"
    # Y los ids de C existen de verdad en la base (no son inventados).
    with mundo.engine.connect() as conexion:
        venta = Base.metadata.tables["venta"]
        ids_c = set(conexion.execute(select(venta.c.id).where(venta.c.empresa_id == mundo.destino_id)).scalars())
    assert ids_c == set(equivalencias["venta"].values())


def test_r4_catalogos_globales_y_roles_por_codigo_y_nombre(mundo):
    eq = mundo.resultado.equivalencias
    with mundo.engine.connect() as conexion:
        estado = Base.metadata.tables["estado_venta"]
        codigos = dict(conexion.execute(select(estado.c.id, estado.c.codigo)).all())
        rol = Base.metadata.tables["rol"]
        nombres = dict(conexion.execute(select(rol.c.id, rol.c.nombre)).all())
    origen = leer_paquete(mundo.origen.contenido)
    for fila in origen.referencias["estado_venta"]:
        assert codigos[eq["estado_venta"][fila["id"]]] == fila["codigo"]
    for fila in origen.referencias["rol"]:
        assert nombres[eq["rol"][fila["id"]]] == fila["nombre"]
    assert {f["nombre"] for f in origen.referencias["rol"]} >= {"administrador", "cajero", "cliente"}


# =================================================================================================
# R5: integridad
# =================================================================================================


def test_r5_todas_las_llaves_foraneas_de_c_resuelven(mundo):
    with mundo.engine.connect() as conexion:
        rotas = conexion.exec_driver_sql("PRAGMA foreign_key_check").all()
        assert huerfanas_de_empresa(conexion, mundo.destino_id) == []
    assert rotas == [], f"llaves foráneas que no resuelven: {rotas[:5]}"


def test_r5_el_foreign_key_check_detecta_una_fila_huerfana(mundo):
    """Control: una fila con una FK colgada SÍ aparece en el PRAGMA (y se deshace)."""
    with mundo.engine.connect() as conexion:
        conexion.exec_driver_sql("UPDATE sucursal SET ciudad_id = 987654 WHERE id = ?", (mundo.resultado.equivalencias["sucursal"][mundo.a.ids["sucursal"]],))
        try:
            assert conexion.exec_driver_sql("PRAGMA foreign_key_check").all() != []
            assert any("sucursal.ciudad_id" in p for p in huerfanas_de_empresa(conexion, mundo.destino_id))
        finally:
            conexion.rollback()
    with mundo.engine.connect() as conexion:
        assert conexion.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_r5_ninguna_fila_de_c_apunta_a_otra_empresa(mundo):
    with mundo.engine.connect() as conexion:
        assert inconsistencias_de_empresa(conexion, mundo.destino_id) == []


def test_r5_todo_pertenece_a_la_empresa_destino(mundo):
    """Ninguna fila de A cambió y nada de C quedó con el empresa_id del archivo."""
    antes = {t: n for t, n in mundo.origen.tablas.items() if t in RESTAURABLES}
    assert _conteos(mundo, mundo.a.id) == antes
    for tabla in RESTAURABLES:
        if "empresa_id" not in Base.metadata.tables[tabla].c:
            continue
        with mundo.engine.connect() as conexion:
            t = Base.metadata.tables[tabla]
            ajenas = conexion.execute(
                select(t.c.id if "id" in t.c else t.c.empresa_id).where(t.c.empresa_id == mundo.destino_id)
            ).all()
        assert len(ajenas) == mundo.origen.tablas[tabla], tabla


# =================================================================================================
# Qué NO se restaura
# =================================================================================================


def test_los_usuarios_restaurados_no_tienen_contrasena_utilizable(mundo):
    with mundo.engine.connect() as conexion:
        usuario = Base.metadata.tables["usuario"]
        hashes = set(conexion.execute(select(usuario.c.password_hash).where(usuario.c.empresa_id == mundo.destino_id)).scalars())
        bitacora = Base.metadata.tables["bitacora"]
        ips = set(conexion.execute(select(bitacora.c.ip).where(bitacora.c.empresa_id == mundo.destino_id)).scalars())
    assert hashes == {HASH_INUTILIZABLE}
    assert ips == {None}  # la IP no sale en la copia


def test_la_columna_generada_se_recalcula(mundo):
    with mundo.engine.connect() as conexion:
        stock = Base.metadata.tables["stock"]
        filas = conexion.execute(
            select(stock.c.cantidad_fisica, stock.c.cantidad_reservada, stock.c.cantidad_disponible).where(stock.c.empresa_id == mundo.destino_id)
        ).all()
    assert filas and all(f.cantidad_disponible == f.cantidad_fisica - f.cantidad_reservada for f in filas)
    assert "cantidad_disponible" not in leer_paquete(mundo.origen.contenido).manifiesto["tablas"]["stock"]["columnas"]


# =================================================================================================
# R6: ida y vuelta (copiar la empresa restaurada, por HTTP)
# =================================================================================================


def test_r6_copiar_c_da_los_mismos_checksums_que_a(mundo):
    """El administrador de A, restaurado en C (sin contraseña, pero con su rol), pide la copia de C por el
    endpoint de verdad. Prueba a la vez que usuarios, roles y permisos quedaron utilizables."""
    admin_c = mundo.resultado.equivalencias["usuario"][mundo.a.empresa.admin_id]
    with mundo.sesiones() as db:
        fijar_empresa(db, mundo.destino_id)
        usuario = db.get(Usuario, admin_c)
        assert usuario is not None and [r.nombre for r in usuario.roles] == ["administrador"]
        cabeceras = token_de(db, usuario)

    respuesta = mundo.client.post(API, headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    segunda = respuesta.content
    assert checksums_canonicos(segunda) == checksums_canonicos(mundo.origen.contenido)
    manifiesto = json.loads(zipfile.ZipFile(io.BytesIO(segunda)).read("manifest.json"))
    assert manifiesto["empresa"]["codigo"] == "tienda-c"
    assert manifiesto["plan"]["codigo"] == "profesional"


# =================================================================================================
# Rechazos: un ZIP alterado o un destino con datos no toca la base
# =================================================================================================


def _destino_intacto(mundo, empresa_id: int) -> None:
    assert sum(_conteos(mundo, empresa_id).values()) == 0, "la empresa destino debía seguir vacía"


def test_un_miembro_alterado_se_rechaza_antes_de_tocar_la_base(mundo):
    destino = _empresa_vacia(mundo, "tienda-alterada")
    ejemplo = mundo.origen.contenido
    alterada = reempaquetar(ejemplo, {"datos/venta.json": lambda filas: [{**f, "total": "999999.00"} if i == 0 else f for i, f in enumerate(filas)]}, recalcular_manifiesto=False)
    with mundo.sesiones() as db, pytest.raises(CopiaInvalidaError, match="SHA-256"):
        restaurar_copia(alterada, db, destino)
    _destino_intacto(mundo, destino)


def test_un_conteo_del_manifiesto_que_no_cuadra_se_rechaza(mundo):
    destino = _empresa_vacia(mundo, "tienda-conteo")
    entrada = json.loads(zipfile.ZipFile(io.BytesIO(mundo.origen.contenido)).read("manifest.json"))
    entrada["tablas"]["pago"]["filas"] += 1
    mal = reempaquetar(mundo.origen.contenido, {"manifest.json": json.dumps(entrada).encode()}, recalcular_manifiesto=False)
    with mundo.sesiones() as db, pytest.raises(CopiaInvalidaError, match="filas"):
        restaurar_copia(mal, db, destino)
    _destino_intacto(mundo, destino)


def test_un_archivo_que_no_es_zip_o_sin_miembros_se_rechaza(mundo):
    destino = _empresa_vacia(mundo, "tienda-basura")
    with mundo.sesiones() as db, pytest.raises(CopiaInvalidaError):
        restaurar_copia(b"esto no es un zip", db, destino)
    _destino_intacto(mundo, destino)


def test_un_tipo_invalido_se_rechaza_sin_escribir(mundo):
    """El manifiesto es coherente (SHA-256 y conteos recalculados) pero un monto llega como número JSON, no como
    texto exacto: la conversión de tipos lo rechaza ANTES de la primera inserción."""
    destino = _empresa_vacia(mundo, "tienda-tipo")
    mal = reempaquetar(mundo.origen.contenido, {"datos/venta.json": lambda filas: [{**f, "total": 12.5} if i == 0 else f for i, f in enumerate(filas)]})
    with mundo.sesiones() as db, pytest.raises(CopiaInvalidaError, match="venta"):
        restaurar_copia(mal, db, destino)
    _destino_intacto(mundo, destino)


def test_un_fallo_a_mitad_de_la_carga_deja_el_destino_vacio(mundo):
    """Una FK a una fila que no vino en la copia solo se detecta cuando ya se insertaron muchas tablas: la
    transacción única debe deshacerlo todo."""
    destino = _empresa_vacia(mundo, "tienda-mitad")
    mal = reempaquetar(
        mundo.origen.contenido,
        {"datos/venta_detalle.json": lambda filas: [{**f, "venta_id": 99999999} if i == 0 else f for i, f in enumerate(filas)]},
    )
    with mundo.sesiones() as db, pytest.raises(CopiaInvalidaError, match="venta_detalle"):
        restaurar_copia(mal, db, destino)
    _destino_intacto(mundo, destino)
    with mundo.sesiones() as db:  # y la misma empresa admite después una restauración buena
        restaurar_copia(mundo.origen.contenido, db, destino)
    assert _conteos(mundo, destino) == {t: mundo.origen.manifiesto["tablas"][t]["filas"] for t in RESTAURABLES}


def test_restaurar_dos_veces_en_la_misma_empresa_se_rechaza_sin_mezclar(mundo):
    """Decisión del restaurador: el destino debe estar VACÍO. La segunda restauración se rechaza y C queda igual
    (nada duplicado, nada mezclado)."""
    antes = _conteos(mundo, mundo.destino_id)
    with mundo.sesiones() as db, pytest.raises(DestinoNoVacioError):
        restaurar_copia(mundo.origen.contenido, db, mundo.destino_id)
    assert _conteos(mundo, mundo.destino_id) == antes


def test_el_destino_con_datos_de_otra_copia_tampoco_se_mezcla(mundo):
    destino = _empresa_vacia(mundo, "tienda-ocupada")
    with mundo.sesiones() as db:
        restaurar_copia(mundo.origen.contenido, db, destino)
    antes = _conteos(mundo, destino)
    with mundo.sesiones() as db, pytest.raises(DestinoNoVacioError):
        restaurar_copia(mundo.restaurada.contenido, db, destino)
    assert _conteos(mundo, destino) == antes


def test_restaurar_en_una_empresa_que_no_existe_se_rechaza(mundo):
    with mundo.sesiones() as db, pytest.raises(DestinoNoVacioError):
        restaurar_copia(mundo.origen.contenido, db, 99999)



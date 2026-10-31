"""E22: copias de seguridad por empresa, por HTTP (`/api/v1/copias-seguridad`) con SQLite.

Cubre el contrato del endpoint (C1-C13): el ZIP y su manifiesto frente a la base, el aislamiento entre empresas, la
ausencia de secretos, plan, suscripción y permisos (y su orden), el historial y su límite, el candado por empresa, los
topes de tamaño, tiempo y simultáneas, el fallo a mitad, la bitácora y el determinismo.

El motor solo (`core/copias.py`) se prueba en tests/core/test_copias_motor.py y la clasificación de tablas en
tests/core/test_copias_clasificacion.py; el flujo básico, en test_copias_humo.py. Aquí se arman empresas Profesional
propias (alfa y bravo, con ventas, sucursales y los MISMOS códigos de producto y de SKU) y centinelas de texto
únicas por empresa: si una sola aparece en la copia de la otra, la prueba falla."""

import builtins
import datetime as dt
import hashlib
import io
import itertools
import json
import logging
import os
import re
import tempfile
import zipfile
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from app.core import copias
from app.core.config import get_settings
from app.core.database import Base
from app.core.tenant import en_empresa, empresa_de, fijar_empresa, sin_filtro
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import (
    FACTOR_ABANDONO,
    HISTORIAL_MINIMO,
    CopiaGenerada,
    GestionarCopiasSeguridad,
)
from app.plataforma.models import Bitacora, CopiaSeguridad, Plan, Suscripcion
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.ayudas_bitacora import exigir_datos_sin_sensibles, filas_de
from tests.comercial._datos_empresa import sembrar_empresa
from tests.conftest import crear_empresa, token_de

API = "/api/v1/copias-seguridad"
BASE = "/api/v1"
CLAVE = "claveSegura123"
CORREO_ADMIN = "admin@tienda.bo"  # el mismo en alfa y en bravo: el correo es único POR empresa

RUTAS = [("POST", ""), ("GET", ""), ("GET", "/tablas"), ("GET", "/1")]
IDS_RUTAS = ["POST", "GET lista", "GET tablas", "GET detalle"]

COPIA = Base.metadata.tables["copia_seguridad"]
MENSAJE_FALLO = "No se pudo crear la copia de seguridad. Inténtalo de nuevo."


# ---- Ayudas ---------------------------------------------------------------------------------------------------------


def _ok(respuesta, esperado=(200, 201)):
    assert respuesta.status_code in esperado, f"{respuesta.request.method} {respuesta.request.url.path}: {respuesta.text[:300]}"
    return respuesta.json() if respuesta.content else None


def _usuario(db, empresa_id: int, rol: str, correo: str, nombre: str = "Staff", apellido: str = "Prueba"):
    """Un usuario de la empresa con ese rol. Devuelve (id, cabeceras con su token)."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        repo = UsuarioRepository()
        usuario = repo.crear(db, UsuarioCrear(nombre=nombre, apellido=apellido, email=correo, password=CLAVE))
        repo.asignar_roles(db, usuario, [rol])
        db.commit()
        db.refresh(usuario)
        return usuario.id, token_de(db, usuario)
    finally:
        fijar_empresa(db, original)


def _crear(db, codigo: str, etiqueta: str, plan: str = "profesional") -> SimpleNamespace:
    """Una empresa con su suscripción activa del `plan` y su administrador "Ana <Etiqueta>". Sin datos de negocio."""
    empresa = crear_empresa(db, codigo, plan=plan, nombre=f"Empresa {codigo}")
    admin_id, headers = _usuario(db, empresa.id, "administrador", CORREO_ADMIN, "Ana", etiqueta.title())
    return SimpleNamespace(
        id=empresa.id, codigo=codigo, etiqueta=etiqueta, centinela=f"CENTINELA-{etiqueta}",
        admin_id=admin_id, headers=headers, cliente=None,
    )  # fmt: skip


def _poblar(client, db, e: SimpleNamespace) -> SimpleNamespace:
    """Datos reales por la API: dos sucursales, dos productos (uno con el MISMO código "EMP-1" en las dos empresas),
    stock, un cliente, el administrador como empleado y dos ventas presenciales pagadas. Todo texto libre lleva la
    centinela de la empresa (y el código de la empresa, que sembrar_empresa mete en los nombres)."""
    datos = sembrar_empresa(client, db, e)
    e.cliente = datos["cliente"]
    e.sucursal_id = datos["sucursal_id"]
    c, admin = e.centinela, e.headers
    _ok(client.post(f"{BASE}/empleados", json={"usuario_id": e.admin_id, "sucursal_id": datos["sucursal_id"], "cargo": f"Gerente {c}"}, headers=admin))
    ciudad = _ok(client.post(f"{BASE}/ciudades", json={"nombre": f"Ciudad {c}", "departamento": "Beni"}, headers=admin))
    _ok(client.post(f"{BASE}/sucursales", json={"ciudad_id": ciudad["id"], "codigo": "SUC-DOS", "nombre": f"Sucursal {c}", "direccion": f"Calle {c}"}, headers=admin))
    categoria = _ok(client.post(f"{BASE}/categorias", json={"nombre": f"Faldas {c}"}, headers=admin))
    talla = _ok(client.post(f"{BASE}/tallas", json={"codigo": "L", "orden": 2}, headers=admin))
    color = _ok(client.post(f"{BASE}/colores", json={"nombre": f"Rojo {c}"}, headers=admin))
    _ok(
        client.post(
            f"{BASE}/productos",
            json={
                "codigo": "EMP-2", "nombre": f"Falda {c}", "descripcion": f"Descripcion {c}", "categoria_id": categoria["id"],
                "precio_base": "250.00", "tallas_ids": [talla["id"]], "colores_ids": [color["id"]],
            },
            headers=admin,
        )
    )  # fmt: skip
    for unidades in (1, 2):
        venta = _ok(
            client.post(
                f"{BASE}/ventas/presencial",
                json={"sucursal_id": datos["sucursal_id"], "detalle": [{"variante_id": datos["variante_id"], "cantidad": unidades}]},
                headers=admin,
            )
        )
        _ok(client.post(f"{BASE}/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "99999"}, headers=admin))
    return e


def _personal(db, e: SimpleNamespace) -> SimpleNamespace:
    """Quienes NO son administrador: cajero, encargado de sucursal y cliente."""
    return SimpleNamespace(
        cajero=_usuario(db, e.id, "cajero", f"cajero@{e.codigo}.example.com")[1],
        encargado=_usuario(db, e.id, "encargado_sucursal", f"encargado@{e.codigo}.example.com")[1],
        cliente=_usuario(db, e.id, "cliente", f"cliente2@{e.codigo}.example.com")[1],
    )


def _cambiar_suscripcion(db, empresa_id: int, **valores) -> None:
    db.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.empresa_id == empresa_id).values(**valores)),
        execution_options={"synchronize_session": False},
    )
    db.commit()


def _copiar(client, headers, **extras):
    respuesta = client.post(API, headers=headers, **extras)
    assert respuesta.status_code == 200, respuesta.text[:300]
    return respuesta


def _zip(respuesta) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(respuesta.content))


def _manifiesto(zf: zipfile.ZipFile) -> dict:
    return json.loads(zf.read("manifest.json"))


def _filas(zf: zipfile.ZipFile, ruta: str) -> list[dict]:
    return json.loads(zf.read(ruta))


def _condicion(tabla: str, empresa_id: int):
    """El filtro por empresa, escrito AQUÍ y no tomado del motor: si el motor se equivocara, la prueba lo vería."""
    t = Base.metadata.tables[tabla]
    if tabla == "empresa":
        return t, t.c.id == empresa_id
    if tabla == "usuario_rol":
        u = Base.metadata.tables["usuario"]
        return t, t.c.usuario_id.in_(select(u.c.id).where(u.c.empresa_id == empresa_id))
    return t, t.c.empresa_id == empresa_id


def _contar(db, tabla: str, empresa_id: int) -> int:
    t, condicion = _condicion(tabla, empresa_id)
    return db.connection().execute(select(func.count()).select_from(t).where(condicion)).scalar_one()


def _claves_de(db, tabla: str, empresa_id: int) -> set[tuple]:
    """Las claves primarias (tuplas: algunas tablas tienen llave compuesta) de las filas de la empresa."""
    t, condicion = _condicion(tabla, empresa_id)
    return {tuple(fila) for fila in db.connection().execute(select(*t.primary_key.columns).where(condicion))}


def _clave_de_fila(tabla: str, fila: dict) -> tuple:
    return tuple(fila[c.name] for c in Base.metadata.tables[tabla].primary_key.columns)


def _copias_en_base(db, empresa_id: int) -> list[dict]:
    """Las filas de `copia_seguridad` de la empresa, leídas por Core (sin el filtro automático), de la más vieja a la nueva."""
    consulta = select(COPIA).where(COPIA.c.empresa_id == empresa_id).order_by(COPIA.c.id)
    return [dict(f) for f in db.connection().execute(consulta).mappings()]


def _bitacora(db, empresa_id: int, accion: str) -> list[Bitacora]:
    return [f for f in filas_de(db, "copia_seguridad", accion) if f.empresa_id == empresa_id]


def _insertar_copia(db, e: SimpleNamespace, **campos) -> int:
    with en_empresa(db, e.id):
        fila = CopiaSeguridad(usuario_id=e.admin_id, **campos)
        db.add(fila)
        db.flush()
        copia_id = fila.id
    db.commit()
    return copia_id


def _ahora_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def alfa(client_por_peticion, db_session):
    return _poblar(client_por_peticion, db_session, _crear(db_session, "alfa-copias", "ALFA"))


@pytest.fixture()
def bravo(client_por_peticion, db_session):
    return _poblar(client_por_peticion, db_session, _crear(db_session, "bravo-copias", "BRAVO"))


@pytest.fixture()
def vacia(db_session):
    """Una empresa Profesional sin datos de negocio (para las pruebas de plan, permisos y candado)."""
    return _crear(db_session, "vacia-copias", "VACIA")


def _tras_el_fallo(client, db, e, motivo: str, codigo_http: int, respuesta) -> dict:
    """Comprobaciones comunes de una copia que NO se entregó: sin archivo, fila fallida con su motivo y candado libre."""
    assert respuesta.status_code == codigo_http, respuesta.text[:300]
    assert respuesta.headers["content-type"].startswith("application/json")
    assert not zipfile.is_zipfile(io.BytesIO(respuesta.content))
    for cabecera in ("content-disposition", "x-copia-id", "x-checksum-sha256"):
        assert cabecera not in respuesta.headers
    filas = _copias_en_base(db, e.id)
    assert [f["estado"] for f in filas] == ["fallida"]
    assert filas[0]["motivo_fallo"] == motivo and filas[0]["terminado_en"] is not None
    assert filas[0]["checksum"] is None and filas[0]["tamano_bytes"] is None
    assert copias._en_curso == 0  # la plaza se devolvió
    return filas[0]


# ---- C1: el administrador Profesional descarga el ZIP ------------------------------------------------------------------


def test_c1_el_administrador_descarga_un_zip_completo(client_por_peticion, db_session, alfa):
    respuesta = _copiar(client_por_peticion, alfa.headers)

    assert respuesta.headers["content-type"] == "application/zip"
    assert re.fullmatch(
        r'attachment; filename="fashionstore-alfa-copias-\d{8}-\d{4}\.zip"', respuesta.headers["content-disposition"]
    )
    assert respuesta.headers["x-copia-id"].isdigit()
    assert re.fullmatch(r"[0-9a-f]{64}", respuesta.headers["x-checksum-sha256"])
    zf = _zip(respuesta)
    assert zf.testzip() is None
    nombres = set(zf.namelist())
    assert "manifest.json" in nombres
    assert {f"datos/{t}.json" for t in copias.TABLAS_INCLUIDAS} <= nombres  # CADA tabla incluida, aunque esté vacía
    assert {f"referencias/{t}.json" for t in copias.TABLAS_REFERENCIA} <= nombres
    assert all(n == "manifest.json" or n.startswith(("datos/", "referencias/")) for n in nombres)
    assert all(not n.startswith("/") and ".." not in n for n in nombres)  # nada que escriba fuera al descomprimir


def test_c1_la_respuesta_no_se_guarda_en_cache_ni_se_interpreta_como_otra_cosa(client_por_peticion, alfa):
    respuesta = _copiar(client_por_peticion, alfa.headers)

    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["x-content-type-options"] == "nosniff"


# ---- C2: el manifiesto coincide con la base ----------------------------------------------------------------------------


def test_c2_el_manifiesto_coincide_con_la_base_y_con_los_archivos(client_por_peticion, db_session, alfa):
    # Los conteos se toman ANTES: la copia deja después su propia fila `descargar` en la bitácora, que no puede estar dentro.
    antes = {tabla: _contar(db_session, tabla, alfa.id) for tabla in copias.TABLAS_INCLUIDAS}
    respuesta = _copiar(client_por_peticion, alfa.headers)
    zf = _zip(respuesta)
    manifiesto = _manifiesto(zf)

    assert manifiesto["formato"] == "fashionstore-copia-1"
    assert manifiesto["empresa"] == {"codigo": "alfa-copias", "nombre": "Empresa alfa-copias"}
    assert manifiesto["plan"] == {"codigo": "profesional"}
    assert set(manifiesto["tablas"]) == set(copias.TABLAS_INCLUIDAS)
    assert set(manifiesto["referencias"]) == set(copias.TABLAS_REFERENCIA)

    for tabla in copias.TABLAS_INCLUIDAS:
        entrada = manifiesto["tablas"][tabla]
        esperado = antes[tabla]
        assert entrada["filas"] == esperado, f"{tabla}: el manifiesto dice {entrada['filas']} y la base tenía {esperado}"
        assert len(_filas(zf, entrada["archivo"])) == esperado
        assert entrada["sha256"] == hashlib.sha256(zf.read(entrada["archivo"])).hexdigest(), tabla
    assert _contar(db_session, "bitacora", alfa.id) == antes["bitacora"] + 1  # solo la fila `descargar`, posterior al ZIP
    for tabla, entrada in manifiesto["referencias"].items():
        assert entrada["sha256"] == hashlib.sha256(zf.read(entrada["archivo"])).hexdigest(), tabla
        assert len(_filas(zf, entrada["archivo"])) == entrada["filas"]

    # La prueba no es vacía: hay datos reales de varios tipos.
    filas = {t: manifiesto["tablas"][t]["filas"] for t in copias.TABLAS_INCLUIDAS}
    assert filas["sucursal"] >= 2 and filas["producto"] >= 2 and filas["producto_variante"] >= 2
    assert filas["venta"] >= 2 and filas["venta_detalle"] >= 2 and filas["pago"] >= 2 and filas["stock"] >= 1
    assert filas["empresa"] == 1 and filas["suscripcion"] == 1 and filas["usuario"] >= 2 and filas["bitacora"] >= 1
    assert manifiesto["referencias"]["plan"]["filas"] == 1  # solo el plan que la empresa usa


def test_c2_el_checksum_del_zip_coincide_con_la_cabecera_y_con_el_historial(client_por_peticion, db_session, alfa):
    respuesta = _copiar(client_por_peticion, alfa.headers)
    sha = hashlib.sha256(respuesta.content).hexdigest()
    copia_id = int(respuesta.headers["x-copia-id"])

    assert respuesta.headers["x-checksum-sha256"] == sha
    detalle = _ok(client_por_peticion.get(f"{API}/{copia_id}", headers=alfa.headers))
    assert detalle["checksum"] == sha
    assert detalle["estado"] == "completada" and detalle["tamano_bytes"] == len(respuesta.content)
    assert detalle["total_filas"] == sum(e["filas"] for e in _manifiesto(_zip(respuesta))["tablas"].values())
    assert detalle["tablas_incluidas"] == {t: e["filas"] for t, e in _manifiesto(_zip(respuesta))["tablas"].items()}
    assert detalle["version_esquema"] is None  # SQLite de pruebas: sin tabla alembic_version
    assert detalle["motivo_fallo"] is None and detalle["terminado_en"] is not None

    [fila] = _copias_en_base(db_session, alfa.id)
    assert (fila["id"], fila["estado"], fila["checksum"], fila["tamano_bytes"]) == (copia_id, "completada", sha, len(respuesta.content))
    assert fila["usuario_id"] == alfa.admin_id and fila["activo"] in (True, 1)

    historial = _ok(client_por_peticion.get(API, headers=alfa.headers))
    assert [i["estado"] for i in historial["items"]] == ["completada"]


# ---- C3: aislamiento entre empresas -------------------------------------------------------------------------------------


def test_c3_la_copia_de_cada_empresa_no_trae_ni_una_fila_ni_un_texto_de_la_otra(client_por_peticion, db_session, alfa, bravo):
    assert alfa.id != bravo.id
    # Los ids de cada tabla se toman ANTES de copiar: la copia deja después su fila `descargar` en la bitácora.
    claves = {(e.id, t): _claves_de(db_session, t, e.id) for e in (alfa, bravo) for t in copias.TABLAS_INCLUIDAS}
    for propia, ajena in ((alfa, bravo), (bravo, alfa)):
        zf = _zip(_copiar(client_por_peticion, propia.headers))

        # 1. Ningún miembro del ZIP contiene una centinela de la otra empresa (ni su código, ni su dominio de correo).
        ajenas = [ajena.centinela, ajena.codigo, f"@{ajena.codigo}.example.com"]
        for nombre in zf.namelist():
            bruto = zf.read(nombre).decode("utf-8")
            for centinela in ajenas:
                assert centinela not in bruto, f"{propia.codigo}: «{centinela}» de la otra empresa aparece en {nombre}"

        # 2. Las propias sí están (la prueba no es vacía).
        todo = "".join(zf.read(n).decode("utf-8") for n in zf.namelist())
        assert propia.centinela in todo and propia.codigo in todo

        # 3. Cada tabla trae exactamente las claves de la empresa, ninguna de la otra, y su empresa_id es el del token.
        for tabla in copias.TABLAS_INCLUIDAS:
            filas = _filas(zf, f"datos/{tabla}.json")
            de_la_copia = {_clave_de_fila(tabla, f) for f in filas}
            assert de_la_copia == claves[(propia.id, tabla)], tabla
            assert not (de_la_copia & claves[(ajena.id, tabla)]), tabla
            for fila in filas:
                if "empresa_id" in fila:
                    assert fila["empresa_id"] == propia.id, f"{tabla}: fila de la empresa {fila['empresa_id']}"


def test_c3_las_dos_empresas_comparten_codigo_de_producto_y_sku_pero_cada_copia_trae_los_suyos(client_por_peticion, alfa, bravo):
    de_alfa = _filas(_zip(_copiar(client_por_peticion, alfa.headers)), "datos/producto.json")
    de_bravo = _filas(_zip(_copiar(client_por_peticion, bravo.headers)), "datos/producto.json")

    assert {p["codigo"] for p in de_alfa} == {p["codigo"] for p in de_bravo} == {"EMP-1", "EMP-2"}
    assert not ({p["id"] for p in de_alfa} & {p["id"] for p in de_bravo})
    assert {p["nombre"] for p in de_alfa} == {f"Camisa {alfa.codigo}", f"Falda {alfa.centinela}"}
    assert {p["nombre"] for p in de_bravo} == {f"Camisa {bravo.codigo}", f"Falda {bravo.centinela}"}


def test_c3_el_empresa_id_del_cliente_en_la_query_el_cuerpo_o_las_cabeceras_no_cambia_la_empresa(client_por_peticion, alfa, bravo):
    respuesta = _copiar(
        client_por_peticion,
        {**alfa.headers, "X-Empresa-Id": str(bravo.id), "X-Tenant": bravo.codigo, "X-Empresa": bravo.codigo},
        params={"empresa_id": bravo.id},
        json={"empresa_id": bravo.id, "empresa": bravo.codigo},
    )
    zf = _zip(respuesta)

    assert _manifiesto(zf)["empresa"]["codigo"] == alfa.codigo
    assert bravo.centinela not in "".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    assert [f["id"] for f in _filas(zf, "datos/empresa.json")] == [alfa.id]


# ---- C4: sin secretos --------------------------------------------------------------------------------------------------


def test_c4_la_copia_no_lleva_secretos_ni_ip_ni_tablas_de_la_pasarela(client_por_peticion, db_session, alfa):
    db_session.add(Bitacora(empresa_id=alfa.id, entidad="prueba", accion="crear", ip="10.20.30.40"))
    db_session.commit()
    zf = _zip(_copiar(client_por_peticion, alfa.headers))
    manifiesto = _manifiesto(zf)

    for nombre in zf.namelist():
        if not nombre.startswith(("datos/", "referencias/")):
            continue  # el manifiesto NOMBRA las columnas omitidas a propósito; los datos no las traen
        bruto = zf.read(nombre).decode("utf-8")
        assert "password" not in bruto.lower() or nombre == "datos/bitacora.json", f"{nombre}: «password»"
        for prohibido in ("$2b$", "$2a$", "$2y$", CLAVE, "10.20.30.40", "testclient", "eyJ"):
            assert prohibido not in bruto, f"{nombre} contiene «{prohibido}»"
    # La bitácora puede NOMBRAR campos de contraseña en sus datos, pero nunca un valor.
    for fila in _filas(zf, "datos/bitacora.json"):
        assert "ip" not in fila
        assert "password_hash" not in json.dumps(fila.get("datos"))

    usuarios = _filas(zf, "datos/usuario.json")
    assert usuarios and all("password_hash" not in u for u in usuarios)
    assert "password_hash" not in manifiesto["tablas"]["usuario"]["columnas"] and "ip" not in manifiesto["tablas"]["bitacora"]["columnas"]
    for tabla in copias.TABLAS_INCLUIDAS:  # ninguna columna con nombre de secreto en ningún archivo de datos
        for columna in manifiesto["tablas"][tabla]["columnas"]:
            assert not copias.PATRON_COLUMNA_SENSIBLE.search(columna.lower()), f"{tabla}.{columna}"

    nombres = set(zf.namelist())
    for ausente in ("transaccion_pasarela", "probador_generacion", "modelo_ml", "copia_seguridad", "permiso", "rol_permiso"):
        assert f"datos/{ausente}.json" not in nombres and f"referencias/{ausente}.json" not in nombres
    assert set(manifiesto["excluidas"]["tablas"]) >= {"transaccion_pasarela", "probador_generacion", "modelo_ml"}
    assert manifiesto["excluidas"]["columnas"]["usuario"] == ["password_hash"]
    assert manifiesto["excluidas"]["columnas"]["bitacora"] == ["ip"]


# ---- C5: plan y suscripción -----------------------------------------------------------------------------------------------


def _pedir(client, metodo, sufijo, headers=None):
    return client.request(metodo, f"{API}{sufijo}", headers=headers or {}, **({"json": {}} if metodo == "POST" else {}))


@pytest.mark.parametrize("metodo, sufijo", RUTAS, ids=IDS_RUTAS)
def test_c5_el_plan_basico_recibe_403_plan_no_incluye_funcionalidad_y_no_se_crea_nada(client_por_peticion, db_session, metodo, sufijo):
    basica = _crear(db_session, "basica-copias", "BASICA", plan="basico")

    respuesta = _pedir(client_por_peticion, metodo, sufijo, basica.headers)

    assert respuesta.status_code == 403
    assert respuesta.json() == {
        "detail": "plan_no_incluye_funcionalidad",
        "codigo": "plan_no_incluye_funcionalidad",
        "mensaje": "Su plan no incluye esta funcionalidad",
        "funcionalidad": "copias_seguridad",
        "plan": "basico",
    }
    assert _copias_en_base(db_session, basica.id) == []  # ni siquiera una fila en_proceso
    assert _bitacora(db_session, basica.id, "descargar") == [] and _bitacora(db_session, basica.id, "fallar") == []


@pytest.mark.parametrize("estado", ["vencida", "suspendida", "cancelada"])
@pytest.mark.parametrize("metodo, sufijo", RUTAS, ids=IDS_RUTAS)
def test_c5_una_suscripcion_no_activa_recibe_403_suscripcion_no_activa_y_no_se_crea_nada(
    client_por_peticion, db_session, metodo, sufijo, estado
):
    empresa = _crear(db_session, f"susc-{estado}-copias", "SUSC")
    if estado == "vencida":
        lejos = dt.date(2020, 1, 1)
        _cambiar_suscripcion(db_session, empresa.id, fecha_inicio=lejos, fecha_vencimiento=lejos + dt.timedelta(days=30))
    else:
        _cambiar_suscripcion(db_session, empresa.id, estado=estado)

    respuesta = _pedir(client_por_peticion, metodo, sufijo, empresa.headers)

    assert respuesta.status_code == 403
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "suscripcion_no_activa"
    assert cuerpo["estado"] == ("sin_suscripcion" if estado == "cancelada" else estado)
    assert _copias_en_base(db_session, empresa.id) == []


def test_c5_el_orden_de_los_errores_es_401_suscripcion_plan_permiso(client_por_peticion, db_session):
    basica = _crear(db_session, "orden-basica", "ORDEN", plan="basico")
    profesional = _crear(db_session, "orden-prof", "ORDEN")
    suspendida = _crear(db_session, "orden-susp", "ORDEN", plan="basico")
    _cambiar_suscripcion(db_session, suspendida.id, estado="suspendida")
    cajero_basica = _usuario(db_session, basica.id, "cajero", "cajero@orden-basica.example.com")[1]
    cajero_prof = _usuario(db_session, profesional.id, "cajero", "cajero@orden-prof.example.com")[1]
    cajero_susp = _usuario(db_session, suspendida.id, "cajero", "cajero@orden-susp.example.com")[1]

    assert _pedir(client_por_peticion, "POST", "").status_code == 401
    # Un cajero (sin el permiso) de una empresa suspendida y Básica: manda la suscripción.
    assert _pedir(client_por_peticion, "POST", "", cajero_susp).json()["codigo"] == "suscripcion_no_activa"
    # Un cajero de una empresa Básica activa: manda el plan, no el permiso.
    assert _pedir(client_por_peticion, "POST", "", cajero_basica).json()["codigo"] == "plan_no_incluye_funcionalidad"
    # Un cajero de una empresa Profesional: recién ahí, el permiso.
    permiso = _pedir(client_por_peticion, "POST", "", cajero_prof)
    assert permiso.status_code == 403 and permiso.json()["detail"] == "Falta el permiso 'copias.gestionar'"


# ---- C6: permisos ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("quien", ["cajero", "encargado", "cliente"])
@pytest.mark.parametrize("metodo, sufijo", RUTAS, ids=IDS_RUTAS)
def test_c6_solo_el_administrador_tiene_copias_gestionar(client_por_peticion, db_session, vacia, metodo, sufijo, quien):
    cabeceras = getattr(_personal(db_session, vacia), quien)

    respuesta = _pedir(client_por_peticion, metodo, sufijo, cabeceras)

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "Falta el permiso 'copias.gestionar'"
    assert _copias_en_base(db_session, vacia.id) == []


@pytest.mark.parametrize("metodo, sufijo", RUTAS, ids=IDS_RUTAS)
def test_c6_sin_token_o_con_un_token_basura_es_401(client_por_peticion, vacia, metodo, sufijo):
    assert _pedir(client_por_peticion, metodo, sufijo).status_code == 401
    assert _pedir(client_por_peticion, metodo, sufijo, {"Authorization": "Bearer esto.no.es-un-token"}).status_code == 401


@pytest.mark.parametrize("metodo, sufijo", RUTAS, ids=IDS_RUTAS)
def test_c6_el_superadministrador_sin_empresa_recibe_403(client_por_peticion, db_session, alfa, superadmin_headers, metodo, sufijo):
    respuesta = _pedir(client_por_peticion, metodo, sufijo, superadmin_headers)

    assert respuesta.status_code == 403
    assert alfa.centinela not in respuesta.text and alfa.codigo not in respuesta.text
    assert _copias_en_base(db_session, alfa.id) == []


# ---- C7: historial y su límite ----------------------------------------------------------------------------------------------


def _limitar_historial(db, maximo: int) -> None:
    db.execute(update(Plan).where(Plan.codigo == "profesional").values(max_copias_historial=maximo))
    db.commit()


def test_c7_el_historial_solo_lista_las_copias_de_la_empresa_del_token(client_por_peticion, db_session, alfa, bravo):
    ids_alfa = [int(_copiar(client_por_peticion, alfa.headers).headers["x-copia-id"]) for _ in range(2)]
    ids_bravo = [int(_copiar(client_por_peticion, bravo.headers).headers["x-copia-id"]) for _ in range(1)]

    de_alfa = _ok(client_por_peticion.get(API, headers=alfa.headers))
    de_bravo = _ok(client_por_peticion.get(API, headers=bravo.headers))

    assert [i["id"] for i in de_alfa["items"]] == ids_alfa[::-1]  # la más reciente primero
    assert [i["id"] for i in de_bravo["items"]] == ids_bravo
    assert (de_alfa["total"], de_alfa["pagina"], de_bravo["total"]) == (2, 1, 1)
    assert all(i["usuario_nombre"] == "Ana Alfa" for i in de_alfa["items"])
    assert all(i["usuario_nombre"] == "Ana Bravo" for i in de_bravo["items"])
    assert bravo.codigo not in json.dumps(de_alfa) and alfa.codigo not in json.dumps(de_bravo)


def test_c7_el_historial_se_pagina(client_por_peticion, vacia):
    ids = [int(_copiar(client_por_peticion, vacia.headers).headers["x-copia-id"]) for _ in range(3)]

    primera = _ok(client_por_peticion.get(f"{API}?pagina=1&tamanio=2", headers=vacia.headers))
    segunda = _ok(client_por_peticion.get(f"{API}?pagina=2&tamanio=2", headers=vacia.headers))

    assert (primera["total"], primera["pagina"], primera["tamanio"]) == (3, 1, 2)
    assert [i["id"] for i in primera["items"]] == [ids[2], ids[1]]
    assert (segunda["total"], segunda["pagina"]) == (3, 2) and [i["id"] for i in segunda["items"]] == [ids[0]]


def test_c7_con_un_limite_de_2_tras_3_copias_quedan_2_visibles_y_la_mas_antigua_sale_del_historial(
    client_por_peticion, db_session, vacia
):
    _limitar_historial(db_session, 2)
    ids = [int(_copiar(client_por_peticion, vacia.headers).headers["x-copia-id"]) for _ in range(3)]

    historial = _ok(client_por_peticion.get(API, headers=vacia.headers))
    assert historial["total"] == 2 and [i["id"] for i in historial["items"]] == [ids[2], ids[1]]
    filas = {f["id"]: f for f in _copias_en_base(db_session, vacia.id)}
    assert len(filas) == 3  # nada se borra físicamente
    assert [bool(filas[i]["activo"]) for i in ids] == [False, True, True]
    assert all(f["estado"] == "completada" for f in filas.values())  # la antigua sigue completada: solo salió del historial

    ya_no_esta = client_por_peticion.get(f"{API}/{ids[0]}", headers=vacia.headers)
    inexistente = client_por_peticion.get(f"{API}/999999", headers=vacia.headers)
    assert ya_no_esta.status_code == 404 and ya_no_esta.json() == inexistente.json()
    assert client_por_peticion.get(f"{API}/{ids[2]}", headers=vacia.headers).status_code == 200

    [salida] = _bitacora(db_session, vacia.id, "eliminar")
    assert salida.datos == {"copias": [ids[0]], "motivo": "limite_historial", "limite": 2}
    exigir_datos_sin_sensibles(salida)


def test_c7_con_limite_0_se_conserva_al_menos_una_copia(client_por_peticion, db_session, vacia):
    assert HISTORIAL_MINIMO >= 1
    _limitar_historial(db_session, 0)
    primera = int(_copiar(client_por_peticion, vacia.headers).headers["x-copia-id"])
    assert _ok(client_por_peticion.get(API, headers=vacia.headers))["total"] == 1  # la recién creada nunca desaparece

    segunda = int(_copiar(client_por_peticion, vacia.headers).headers["x-copia-id"])

    historial = _ok(client_por_peticion.get(API, headers=vacia.headers))
    assert historial["total"] == HISTORIAL_MINIMO == 1 and [i["id"] for i in historial["items"]] == [segunda]
    assert client_por_peticion.get(f"{API}/{primera}", headers=vacia.headers).status_code == 404


def test_c7_el_limite_de_una_empresa_no_saca_copias_de_otra(client_por_peticion, db_session, alfa, bravo):
    _limitar_historial(db_session, 1)
    de_bravo = int(_copiar(client_por_peticion, bravo.headers).headers["x-copia-id"])
    for _ in range(3):
        _copiar(client_por_peticion, alfa.headers)

    assert _ok(client_por_peticion.get(API, headers=alfa.headers))["total"] == 1
    assert [i["id"] for i in _ok(client_por_peticion.get(API, headers=bravo.headers))["items"]] == [de_bravo]
    assert all(bool(f["activo"]) for f in _copias_en_base(db_session, bravo.id))


# ---- C8: el candado por empresa -----------------------------------------------------------------------------------------------


def test_c8_con_una_copia_en_proceso_reciente_responde_409_y_no_crea_otra(client_por_peticion, db_session, vacia):
    en_proceso = _insertar_copia(db_session, vacia, estado="en_proceso")

    respuesta = client_por_peticion.post(API, headers=vacia.headers)

    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "copia_en_curso" and "en curso" in cuerpo["mensaje"]
    assert "content-disposition" not in respuesta.headers
    filas = _copias_en_base(db_session, vacia.id)
    assert [(f["id"], f["estado"]) for f in filas] == [(en_proceso, "en_proceso")]  # intacta, sin otra
    assert _bitacora(db_session, vacia.id, "descargar") == []


def test_c8_el_candado_es_por_empresa_una_copia_en_proceso_de_otra_no_bloquea(client_por_peticion, db_session, alfa, bravo):
    _insertar_copia(db_session, bravo, estado="en_proceso")

    assert client_por_peticion.post(API, headers=alfa.headers).status_code == 200
    assert client_por_peticion.post(API, headers=bravo.headers).status_code == 409


def test_c8_una_copia_en_proceso_abandonada_se_marca_fallida_y_la_nueva_se_crea(client_por_peticion, db_session, vacia):
    antes = _ahora_utc() - dt.timedelta(seconds=FACTOR_ABANDONO * get_settings().copias_max_segundos + 60)
    abandonada = _insertar_copia(db_session, vacia, estado="en_proceso", creado_en=antes)

    respuesta = client_por_peticion.post(API, headers=vacia.headers)

    assert respuesta.status_code == 200, respuesta.text
    nueva = int(respuesta.headers["x-copia-id"])
    filas = {f["id"]: f for f in _copias_en_base(db_session, vacia.id)}
    assert nueva != abandonada
    assert (filas[abandonada]["estado"], filas[abandonada]["motivo_fallo"]) == ("fallida", "abandonada")
    assert filas[abandonada]["terminado_en"] is not None
    assert filas[nueva]["estado"] == "completada"


def test_c8_una_en_proceso_justo_por_debajo_del_plazo_de_abandono_todavia_bloquea(client_por_peticion, db_session, vacia):
    casi = _ahora_utc() - dt.timedelta(seconds=FACTOR_ABANDONO * get_settings().copias_max_segundos - 30)
    _insertar_copia(db_session, vacia, estado="en_proceso", creado_en=casi)

    assert client_por_peticion.post(API, headers=vacia.headers).status_code == 409


# ---- C9: topes de tamaño, tiempo y simultáneas ----------------------------------------------------------------------------------


def test_c9_una_copia_mas_grande_que_el_tope_da_413_sin_archivo(client_por_peticion, db_session, alfa, monkeypatch):
    monkeypatch.setattr(get_settings(), "copias_max_bytes", 2000)

    respuesta = client_por_peticion.post(API, headers=alfa.headers)

    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "copia_demasiado_grande" and cuerpo["limite_bytes"] == 2000
    assert set(cuerpo) == {"detail", "codigo", "mensaje", "limite_bytes"}
    _tras_el_fallo(client_por_peticion, db_session, alfa, "copia_demasiado_grande", 413, respuesta)
    [fallo] = _bitacora(db_session, alfa.id, "fallar")
    assert fallo.datos["motivo"] == "copia_demasiado_grande" and isinstance(fallo.datos["duracion_ms"], int)
    assert _bitacora(db_session, alfa.id, "descargar") == []
    assert alfa.centinela not in respuesta.text


def test_c9_pasado_el_tiempo_maximo_da_504_sin_archivo(client_por_peticion, db_session, vacia, monkeypatch):
    original = copias.generar_copia
    reloj = itertools.count(0, 1000)  # cada lectura del reloj avanza 1000 s: la segunda ya pasó los 60 s

    def con_reloj_rapido(*args, **kwargs):
        return original(*args, **{**kwargs, "reloj": lambda: next(reloj)})

    monkeypatch.setattr(copias, "generar_copia", con_reloj_rapido)

    respuesta = client_por_peticion.post(API, headers=vacia.headers)

    assert respuesta.json()["detail"] == respuesta.json()["codigo"] == "copia_tiempo_agotado"
    _tras_el_fallo(client_por_peticion, db_session, vacia, "copia_tiempo_agotado", 504, respuesta)
    assert [f.datos["motivo"] for f in _bitacora(db_session, vacia.id, "fallar")] == ["copia_tiempo_agotado"]


def test_c9_con_todas_las_plazas_ocupadas_da_503_servidor_ocupado(client_por_peticion, db_session, vacia):
    maximo = get_settings().copias_max_simultaneas
    with contextlib_plazas(maximo):
        respuesta = client_por_peticion.post(API, headers=vacia.headers)
        assert copias._en_curso == maximo  # la petición no tomó una plaza que no había

    assert respuesta.json()["detail"] == respuesta.json()["codigo"] == "servidor_ocupado"
    assert copias._en_curso == 0
    _tras_el_fallo(client_por_peticion, db_session, vacia, "servidor_ocupado", 503, respuesta)
    assert [f.datos["motivo"] for f in _bitacora(db_session, vacia.id, "fallar")] == ["servidor_ocupado"]
    # Al liberarse las plazas, la empresa vuelve a poder copiar (el candado no quedó puesto).
    assert client_por_peticion.post(API, headers=vacia.headers).status_code == 200


class contextlib_plazas:
    """Ocupa `n` plazas de copia en este proceso mientras dura el bloque."""

    def __init__(self, n: int):
        self._plazas = [copias.plaza_de_copia(10_000) for _ in range(n)]

    def __enter__(self):
        for plaza in self._plazas:
            plaza.__enter__()
        return self

    def __exit__(self, *exc):
        for plaza in reversed(self._plazas):
            plaza.__exit__(*exc)


# ---- C10: fallo a mitad de la copia -------------------------------------------------------------------------------------------------


def test_c10_un_fallo_al_leer_una_tabla_da_500_generico_sin_detalles_y_libera_el_candado(
    client_por_peticion, db_session, alfa, monkeypatch, caplog
):
    original = copias._escribir_tabla

    def falla_en_producto(zf, carpeta, nombre, *args, **kwargs):
        if nombre == "producto":
            raise RuntimeError("SECRETO-INTERNO: no se pudo leer la tabla producto de la empresa 7")
        return original(zf, carpeta, nombre, *args, **kwargs)

    monkeypatch.setattr(copias, "_escribir_tabla", falla_en_producto)
    caplog.set_level(logging.WARNING, logger="app.copias")
    respuesta = client_por_peticion.post(API, headers=alfa.headers)

    assert respuesta.json() == {"detail": "copia_fallida", "codigo": "copia_fallida", "mensaje": MENSAJE_FALLO}
    for filtrado in ("SECRETO", "producto", "RuntimeError", "Traceback", "empresa 7", alfa.centinela):
        assert filtrado not in respuesta.text
    _tras_el_fallo(client_por_peticion, db_session, alfa, "error_interno", 500, respuesta)
    [fallo] = _bitacora(db_session, alfa.id, "fallar")
    assert fallo.datos["motivo"] == "error_interno" and "SECRETO" not in json.dumps(fallo.datos)
    assert _bitacora(db_session, alfa.id, "descargar") == []
    assert "copia_error" in caplog.text  # el detalle técnico va al log del servidor, nunca al cliente

    # El candado quedó libre: una copia posterior (ya sin el fallo) funciona y deja su fila completada.
    monkeypatch.undo()
    posterior = client_por_peticion.post(API, headers=alfa.headers)
    assert posterior.status_code == 200 and zipfile.is_zipfile(io.BytesIO(posterior.content))
    assert [f["estado"] for f in _copias_en_base(db_session, alfa.id)] == ["fallida", "completada"]


def test_c10_un_fallo_inesperado_no_filtra_nada_ni_en_el_historial(client_por_peticion, db_session, vacia, monkeypatch):
    def revienta(*args, **kwargs):
        raise ValueError("clave-secreta=abc123 en el servidor interno")

    monkeypatch.setattr(copias, "generar_copia", revienta)
    respuesta = client_por_peticion.post(API, headers=vacia.headers)
    monkeypatch.undo()

    assert respuesta.status_code == 500 and "abc123" not in respuesta.text and "clave-secreta" not in respuesta.text
    historial = _ok(client_por_peticion.get(API, headers=vacia.headers))
    assert [(i["estado"], i["motivo_fallo"]) for i in historial["items"]] == [("fallida", "error_interno")]
    assert "abc123" not in json.dumps(historial)


# ---- C11: bitácora ---------------------------------------------------------------------------------------------------------------------


def test_c11_la_copia_exitosa_deja_una_fila_descargar_solo_con_numeros(client_por_peticion, db_session, alfa):
    respuesta = _copiar(client_por_peticion, alfa.headers)
    manifiesto = _manifiesto(_zip(respuesta))

    [fila] = _bitacora(db_session, alfa.id, "descargar")
    assert fila.empresa_id == alfa.id and fila.usuario_id == alfa.admin_id
    assert fila.entidad == "copia_seguridad" and fila.entidad_id == int(respuesta.headers["x-copia-id"])
    assert set(fila.datos) == {"filas", "bytes", "tablas", "duracion_ms"}
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in fila.datos.values())
    assert fila.datos["filas"] == sum(e["filas"] for e in manifiesto["tablas"].values())
    assert fila.datos["bytes"] == len(respuesta.content) and fila.datos["tablas"] == len(copias.TABLAS_INCLUIDAS)
    assert fila.datos["duracion_ms"] >= 0
    exigir_datos_sin_sensibles(fila)
    for texto in (alfa.codigo, alfa.centinela, CORREO_ADMIN, "Ana"):
        assert texto not in json.dumps(fila.datos)
    assert _bitacora(db_session, alfa.id, "fallar") == [] and _bitacora(db_session, alfa.id, "eliminar") == []


def test_c11_la_fila_de_bitacora_es_de_la_empresa_que_copio_y_no_de_otra(client_por_peticion, db_session, alfa, bravo):
    _copiar(client_por_peticion, alfa.headers)

    assert len(_bitacora(db_session, alfa.id, "descargar")) == 1
    assert _bitacora(db_session, bravo.id, "descargar") == []
    visible_para_bravo = client_por_peticion.get(
        f"{BASE}/bitacora?desde=2000-01-01&hasta=2100-01-01&entidad=copia_seguridad", headers=bravo.headers
    )
    assert _ok(visible_para_bravo)["total"] == 0
    visible_para_alfa = _ok(client_por_peticion.get(
        f"{BASE}/bitacora?desde=2000-01-01&hasta=2100-01-01&entidad=copia_seguridad", headers=alfa.headers
    ))
    assert visible_para_alfa["total"] == 1 and visible_para_alfa["items"][0]["accion"] == "descargar"


def test_c11_la_copia_fallida_deja_una_fila_fallar_con_el_motivo(client_por_peticion, db_session, vacia, monkeypatch):
    monkeypatch.setattr(get_settings(), "copias_max_bytes", 50)

    respuesta = client_por_peticion.post(API, headers=vacia.headers)

    assert respuesta.status_code == 413
    [fila] = _bitacora(db_session, vacia.id, "fallar")
    assert fila.empresa_id == vacia.id and fila.usuario_id == vacia.admin_id
    assert fila.entidad_id == _copias_en_base(db_session, vacia.id)[0]["id"]
    assert set(fila.datos) == {"motivo", "duracion_ms"} and fila.datos["motivo"] == "copia_demasiado_grande"
    exigir_datos_sin_sensibles(fila)
    assert _bitacora(db_session, vacia.id, "descargar") == []


# ---- C12: determinismo -------------------------------------------------------------------------------------------------------------------


def test_c12_dos_copias_seguidas_sin_cambios_dan_el_mismo_sha256_por_archivo(client_por_peticion, alfa):
    primera, segunda = (_zip(_copiar(client_por_peticion, alfa.headers)) for _ in range(2))
    m1, m2 = _manifiesto(primera), _manifiesto(segunda)

    distintos = {t for t in m1["tablas"] if m1["tablas"][t]["sha256"] != m2["tablas"][t]["sha256"]}
    # La única tabla que cambia es la bitácora: la primera copia dejó su fila `descargar`, que la segunda ya incluye.
    assert distintos == {"bitacora"}
    assert m2["tablas"]["bitacora"]["filas"] == m1["tablas"]["bitacora"]["filas"] + 1
    assert m1["referencias"] == m2["referencias"]
    for tabla in m1["tablas"]:
        if tabla != "bitacora":
            assert m1["tablas"][tabla] == m2["tablas"][tabla], tabla
            assert primera.read(f"datos/{tabla}.json") == segunda.read(f"datos/{tabla}.json"), tabla


# ---- C13: GET /tablas, detalle y nombres ---------------------------------------------------------------------------------------------------


def test_c13_tablas_describe_lo_que_incluye_y_lo_que_no_y_coincide_con_el_zip(client_por_peticion, alfa, bravo):
    cuerpo = _ok(client_por_peticion.get(f"{API}/tablas", headers=alfa.headers))
    zf = _zip(_copiar(client_por_peticion, alfa.headers))

    assert set(cuerpo) == {"incluidas", "referencias", "excluidas", "columnas_excluidas"}
    assert {"venta", "producto", "usuario", "stock", "bitacora"} <= set(cuerpo["incluidas"])
    assert set(cuerpo["referencias"]) >= {"plan", "rol", "estado_pago"}
    excluidas = {e["tabla"]: e["motivo"] for e in cuerpo["excluidas"]}
    assert {"transaccion_pasarela", "probador_generacion", "modelo_ml"} <= set(excluidas)
    assert all(len(motivo) >= 10 for motivo in excluidas.values())
    assert cuerpo["columnas_excluidas"]["usuario"] == ["password_hash"] and cuerpo["columnas_excluidas"]["bitacora"] == ["ip"]
    assert not (set(cuerpo["incluidas"]) & set(excluidas)) and not (set(cuerpo["referencias"]) & set(excluidas))
    # Lo que dice el panel es lo que trae el archivo.
    assert {n.removeprefix("datos/").removesuffix(".json") for n in zf.namelist() if n.startswith("datos/")} == set(cuerpo["incluidas"])
    assert {n.removeprefix("referencias/").removesuffix(".json") for n in zf.namelist() if n.startswith("referencias/")} == set(cuerpo["referencias"])
    # Es una lista del sistema: igual para toda empresa y sin datos de ninguna.
    assert _ok(client_por_peticion.get(f"{API}/tablas", headers=bravo.headers)) == cuerpo
    assert alfa.codigo not in json.dumps(cuerpo) and bravo.codigo not in json.dumps(cuerpo)


def test_c13_el_detalle_de_una_copia_ajena_es_404_identico_al_de_una_inexistente(client_por_peticion, alfa, bravo):
    de_bravo = int(_copiar(client_por_peticion, bravo.headers).headers["x-copia-id"])

    ajena = client_por_peticion.get(f"{API}/{de_bravo}", headers=alfa.headers)
    inexistente = client_por_peticion.get(f"{API}/999999", headers=alfa.headers)

    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json() and ajena.headers["content-type"] == inexistente.headers["content-type"]
    for texto in (bravo.codigo, bravo.centinela, "Ana Bravo", "completada"):
        assert texto not in ajena.text, texto
    assert _ok(client_por_peticion.get(f"{API}/{de_bravo}", headers=bravo.headers))["id"] == de_bravo  # su dueña sí la ve


def test_c13_el_historial_muestra_quien_la_pidio(client_por_peticion, alfa):
    copia = _copiar(client_por_peticion, alfa.headers)

    [item] = _ok(client_por_peticion.get(API, headers=alfa.headers))["items"]

    assert item["id"] == int(copia.headers["x-copia-id"])
    assert item["usuario_id"] == alfa.admin_id and item["usuario_nombre"] == "Ana Alfa"
    assert CORREO_ADMIN not in json.dumps(item)
    assert set(item) == {
        "id", "estado", "usuario_id", "usuario_nombre", "tamano_bytes", "total_filas", "tablas_incluidas", "version_esquema",
        "checksum", "motivo_fallo", "creado_en", "terminado_en",
    }  # fmt: skip


# ---- Extra: nada en disco y límite de tráfico ---------------------------------------------------------------------------------------------


def test_extra_generar_la_copia_no_escribe_nada_en_disco(client_por_peticion, alfa, monkeypatch):
    temporales: list[str] = []
    escrituras: list[tuple[str, str]] = []
    for nombre in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp", "mkdtemp"):
        original = getattr(tempfile, nombre)

        def espia_temporal(*args, _nombre=nombre, _original=original, **kwargs):
            temporales.append(_nombre)
            return _original(*args, **kwargs)

        monkeypatch.setattr(tempfile, nombre, espia_temporal)
    abrir = builtins.open

    def espia_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and set(mode) & set("wax+"):
            escrituras.append((str(file), mode))
        return abrir(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", espia_open)
    antes = sorted(os.listdir("."))

    respuesta = client_por_peticion.post(API, headers=alfa.headers)
    monkeypatch.undo()

    assert respuesta.status_code == 200 and zipfile.is_zipfile(io.BytesIO(respuesta.content))
    assert temporales == [] and escrituras == []
    assert sorted(os.listdir(".")) == antes  # ni un archivo nuevo en el directorio de trabajo


def test_extra_pasadas_10_copias_por_hora_responde_429(client_por_peticion, vacia, monkeypatch):
    """El límite de tráfico (10/hora por IP) corta ANTES de la lógica: con un caso de uso falso basta."""
    ficticia = SimpleNamespace(id=1, checksum="ab" * 32)
    monkeypatch.setattr(
        GestionarCopiasSeguridad, "crear",
        lambda self, db, usuario_id, contexto=None: CopiaGenerada(contenido=b"PK", nombre_archivo="falsa.zip", copia=ficticia),
    )  # fmt: skip

    estados = [client_por_peticion.post(API, headers=vacia.headers).status_code for _ in range(11)]

    assert estados == [200] * 10 + [429]

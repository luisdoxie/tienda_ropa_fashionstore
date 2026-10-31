"""E22: el generador de copias (`core/copias.py`) con SQLite. Aquí se prueba el motor solo; el endpoint, los permisos
y el historial se prueban en tests/plataforma/test_copias_seguridad.py."""

import datetime as dt
import hashlib
import json
import zipfile
from decimal import Decimal
from io import BytesIO

import pytest
from sqlalchemy import func, select

from app.catalogo.models import Categoria, Producto
from app.core import copias
from app.core.database import Base
from app.core.tenant import fijar_empresa
from app.plataforma.models import Bitacora, Usuario
from tests.conftest import crear_empresa

AHORA = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.timezone.utc)
EMPRESA = {"codigo": "fashionstore", "nombre": "FashionStore"}
HASH_FALSO = "$2b$12$" + "a" * 53  # con la forma de un hash de bcrypt


@pytest.fixture()
def datos(db_session):
    """Un usuario (con su hash), un producto con precio decimal y una fila de bitácora con IP, en la empresa 1."""
    fijar_empresa(db_session, 1)
    categoria = Categoria(nombre="Poleras")
    db_session.add(categoria)
    db_session.add(Usuario(nombre="Ana", apellido="Paz", email="ana@fashionstore.example.com", password_hash=HASH_FALSO))
    db_session.flush()
    db_session.add(Producto(codigo="P-1", nombre="Polera", categoria_id=categoria.id, precio_base=Decimal("149.50")))
    db_session.add(Bitacora(empresa_id=1, entidad="prueba", accion="crear", ip="10.20.30.40"))
    db_session.commit()
    return db_session


def _copiar(db, empresa_id=1, **extra):
    argumentos = dict(
        empresa=EMPRESA, plan_codigo="profesional", version_esquema=None, max_bytes=50 * 1024 * 1024,
        max_segundos=60, ahora=AHORA,
    )  # fmt: skip
    argumentos.update(extra)
    return copias.generar_copia(db.connection(), empresa_id, **argumentos)


def _zip(resultado) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(resultado.contenido))


def test_el_zip_es_valido_y_trae_cada_tabla_mas_el_manifiesto(db_session):
    resultado = _copiar(db_session)
    zf = _zip(resultado)
    assert zf.testzip() is None
    nombres = set(zf.namelist())
    assert "manifest.json" in nombres
    assert {f"datos/{t}.json" for t in copias.TABLAS_INCLUIDAS} <= nombres
    assert {f"referencias/{t}.json" for t in copias.TABLAS_REFERENCIA} <= nombres
    # Nada más: ni tablas excluidas ni miembros de otras rutas.
    assert nombres == {"manifest.json"} | {f"datos/{t}.json" for t in copias.TABLAS_INCLUIDAS} | {
        f"referencias/{t}.json" for t in copias.TABLAS_REFERENCIA
    }


def test_el_manifiesto_coincide_con_la_base_y_con_los_archivos(datos):
    db_session = datos
    resultado = _copiar(db_session)
    zf = _zip(resultado)
    manifiesto = json.loads(zf.read("manifest.json"))

    assert manifiesto["formato"] == copias.FORMATO
    assert manifiesto["generada_en"] == "2026-10-31T12:00:00Z"
    assert manifiesto["empresa"] == EMPRESA
    assert manifiesto["plan"] == {"codigo": "profesional"}
    assert manifiesto == resultado.manifiesto
    assert resultado.checksum == hashlib.sha256(resultado.contenido).hexdigest()

    for nombre, entrada in {**manifiesto["tablas"], **manifiesto["referencias"]}.items():
        datos = zf.read(entrada["archivo"])
        assert hashlib.sha256(datos).hexdigest() == entrada["sha256"], nombre
        assert len(json.loads(datos)) == entrada["filas"], nombre
    for nombre in copias.TABLAS_INCLUIDAS:
        tabla = Base.metadata.tables[nombre]
        if "empresa_id" in tabla.c:
            esperado = db_session.connection().execute(
                select(func.count()).select_from(tabla).where(tabla.c.empresa_id == 1)
            ).scalar()
            assert manifiesto["tablas"][nombre]["filas"] == esperado, nombre
    assert resultado.tablas == {n: d["filas"] for n, d in manifiesto["tablas"].items()}
    assert resultado.tablas["producto"] == 1 and resultado.tablas["usuario"] == 1 and resultado.tablas["empresa"] == 1


def test_no_sale_ningun_secreto(datos):
    zf = _zip(_copiar(datos))
    usuarios = json.loads(zf.read("datos/usuario.json"))
    assert len(usuarios) == 1 and "password_hash" not in usuarios[0]
    for nombre in zf.namelist():
        contenido = zf.read(nombre).decode("utf-8")
        assert "$2b$" not in contenido, nombre
        assert "10.20.30.40" not in contenido, nombre  # la IP de la bitácora
        if nombre != "manifest.json":  # el manifiesto NOMBRA las columnas omitidas (transparencia); los datos no las traen
            assert "password" not in contenido, nombre
    manifiesto = json.loads(zf.read("manifest.json"))
    assert manifiesto["excluidas"]["columnas"]["usuario"] == ["password_hash"]
    assert "usuario" in manifiesto["tablas"] and "password_hash" not in manifiesto["tablas"]["usuario"]["columnas"]
    assert "datos/transaccion_pasarela.json" not in zf.namelist()
    assert "datos/probador_generacion.json" not in zf.namelist()
    bitacora = json.loads(zf.read("datos/bitacora.json"))
    assert bitacora and all("ip" not in fila for fila in bitacora)


def test_la_copia_de_una_empresa_no_trae_filas_de_otra(db_session):
    otra = crear_empresa(db_session, "otra-tienda")
    fijar_empresa(db_session, otra.id)
    db_session.add(Categoria(nombre="CENTINELA-OTRA-EMPRESA-123"))
    db_session.commit()
    fijar_empresa(db_session, 1)
    db_session.add(Categoria(nombre="CENTINELA-FASHIONSTORE-456"))
    db_session.commit()

    de_la_primera = _zip(_copiar(db_session, 1))
    de_la_otra = _zip(_copiar(db_session, otra.id, empresa={"codigo": "otra-tienda", "nombre": "otra-tienda"}))

    for miembro in de_la_primera.namelist():
        assert b"CENTINELA-OTRA-EMPRESA-123" not in de_la_primera.read(miembro), miembro
    for miembro in de_la_otra.namelist():
        assert b"CENTINELA-FASHIONSTORE-456" not in de_la_otra.read(miembro), miembro
    assert b"CENTINELA-FASHIONSTORE-456" in de_la_primera.read("datos/categoria.json")
    assert b"CENTINELA-OTRA-EMPRESA-123" in de_la_otra.read("datos/categoria.json")
    # La otra empresa no hereda ni los usuarios de la primera.
    assert json.loads(de_la_otra.read("datos/usuario.json")) == []
    assert [e["id"] for e in json.loads(de_la_otra.read("datos/empresa.json"))] == [otra.id]


def test_dos_copias_sin_cambios_dan_el_mismo_sha256_por_archivo(db_session):
    primera = _copiar(db_session)
    segunda = _copiar(db_session)
    assert {n: d["sha256"] for n, d in primera.manifiesto["tablas"].items()} == {
        n: d["sha256"] for n, d in segunda.manifiesto["tablas"].items()
    }
    assert primera.checksum == segunda.checksum  # con la misma fecha, el ZIP completo también es idéntico


def test_decimales_y_fechas_se_escriben_exactos(datos):
    productos = json.loads(_zip(_copiar(datos)).read("datos/producto.json"))
    assert productos[0]["precio_base"] == "149.50"  # texto exacto: un float perdería ceros y centavos
    assert productos[0]["creado_en"][:2] == "20" and "T" in productos[0]["creado_en"]  # ISO 8601


def test_un_tope_de_tamano_bajo_aborta_sin_entregar_nada(db_session):
    with pytest.raises(copias.CopiaDemasiadoGrandeError):
        _copiar(db_session, max_bytes=1)


def test_un_tope_de_tiempo_agotado_aborta(db_session):
    tic = iter(range(0, 10_000, 100))  # cada lectura del reloj avanza 100 s
    with pytest.raises(copias.CopiaTiempoAgotadoError):
        _copiar(db_session, max_segundos=60, reloj=lambda: next(tic))


def test_el_tope_global_de_copias_simultaneas():
    with copias.plaza_de_copia(1):
        with pytest.raises(copias.ServidorOcupadoError):
            with copias.plaza_de_copia(1):
                pass
    with copias.plaza_de_copia(1):  # la plaza se libera al salir, también con error
        pass
    with pytest.raises(RuntimeError):
        with copias.plaza_de_copia(1):
            raise RuntimeError("falla")
    with copias.plaza_de_copia(1):
        pass


def test_los_codigos_de_error_son_estables():
    assert copias.CopiaDemasiadoGrandeError.codigo == "copia_demasiado_grande"
    assert copias.CopiaTiempoAgotadoError.codigo == "copia_tiempo_agotado"
    assert copias.ServidorOcupadoError.codigo == "servidor_ocupado"
    assert copias.CopiaError.codigo == "error_interno"


def test_sin_alembic_la_version_del_esquema_es_none(db_session):
    assert copias.leer_version_esquema(db_session.connection()) is None

"""E02, PASO 5: la tienda pública por empresa, /api/v1/public/{codigo}/...

Las 25 rutas hoy públicas se publican además bajo el código de la tienda (los
MISMOS handlers, registrados con add_api_route). La empresa sale SOLO del
código de la ruta: código inexistente o empresa inactiva -> 404 "Tienda no
encontrada"; las rutas viejas, sin token y con una sesión por petición (como en
producción), ya no devuelven datos (401); y un token de OTRA empresa se trata
como anónimo.

Todas las pruebas usan `client_por_peticion` (sesión nueva y sin empresa por
petición) y `dos_empresas` (A = 'tienda-a', B = 'tienda-b')."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.catalogo.models import (
    Categoria,
    Coleccion,
    Color,
    Material,
    Producto,
    ProductoVariante,
    Talla,
    Temporada,
)
from app.comercial.models import DireccionCliente, ZonaEnvio
from app.core.security import crear_access_token, permisos_de_usuario
from app.core.tenant import empresa_de, fijar_empresa
from app.inteligencia import models as _inteligencia_models  # noqa: F401
from app.inteligencia.models import HistorialNavegacion
from app.plataforma.models import Ciudad, Cliente, Empresa, HorarioSucursal, Sucursal, Usuario

PUBLICO = "/api/v1/public"
VIEJO = "/api/v1"


# ---- Datos de cada empresa -----------------------------------------------------


def _sembrar_tienda(db, empresa_id: int, clave: str) -> dict[str, int]:
    """Una fila de cada recurso público dentro de `empresa_id`, con nombres
    propios de la empresa (`clave`) para reconocerlos en las respuestas."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    ciudad = Ciudad(nombre=f"Ciudad {clave}")
    categoria = Categoria(nombre=f"Categoria {clave}")
    talla = Talla(codigo=f"T{clave.upper()}", orden=1)
    color = Color(nombre=f"Color {clave}")
    material = Material(nombre=f"Material {clave}")
    temporada = Temporada(nombre=f"Temporada {clave}", anio=2026)
    db.add_all([ciudad, categoria, talla, color, material, temporada])
    db.flush()
    coleccion = Coleccion(nombre=f"Coleccion {clave}", temporada_id=temporada.id)
    sucursal = Sucursal(ciudad_id=ciudad.id, codigo=f"SUC-{clave}", nombre=f"Sucursal {clave}", direccion="Calle 1")
    producto = Producto(
        codigo="PROD-1",  # el mismo código en las dos empresas, a propósito
        nombre=f"Producto {clave}",
        categoria_id=categoria.id,
        precio_base=100,
    )
    zona = ZonaEnvio(ciudad_id=ciudad.id, nombre=f"Zona {clave}", anillo_desde=0, anillo_hasta=5, tarifa_base=10)
    usuario = Usuario(nombre="Cli", apellido=clave, email=f"cliente-{clave}@example.com", password_hash="x")
    db.add_all([coleccion, sucursal, producto, zona, usuario])
    db.flush()
    variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=f"SKU-{clave}")
    horario = HorarioSucursal(
        sucursal_id=sucursal.id, dia_semana=1, hora_apertura=dt.time(9, 0), hora_cierre=dt.time(18, 0)
    )
    cliente = Cliente(usuario_id=usuario.id)
    db.add_all([variante, horario, cliente])
    db.flush()
    direccion = DireccionCliente(cliente_id=cliente.id, zona_envio_id=zona.id, direccion="Av. Principal 123")
    db.add(direccion)
    db.commit()
    ids = {
        "categoria": categoria.id,
        "talla": talla.id,
        "color": color.id,
        "material": material.id,
        "temporada": temporada.id,
        "coleccion": coleccion.id,
        "producto": producto.id,
        "variante": variante.id,
        "sucursal": sucursal.id,
        "zona": zona.id,
        "direccion": direccion.id,
    }
    fijar_empresa(db, original)
    return ids


@pytest.fixture()
def tiendas(db_session, dos_empresas):
    return {
        "a": _sembrar_tienda(db_session, dos_empresas.a.id, "a"),
        "b": _sembrar_tienda(db_session, dos_empresas.b.id, "b"),
    }


@pytest.fixture(autouse=True)
def _sin_groq(monkeypatch):
    """/ia/voz pide a Groq los filtros; en las pruebas nunca se sale a la red:
    el parser devuelve None y la búsqueda cae a texto plano."""

    class _SinGroq:
        def parsear(self, texto, valores):
            return None

    monkeypatch.setattr(
        "app.inteligencia.casos_uso.cu21_buscar_prendas_por_voz.obtener_parser_voz", lambda: _SinGroq()
    )


# ---- Las 25 rutas -------------------------------------------------------------------
# (método, ruta bajo /public/{codigo} con marcadores de los ids de la tienda A,
# cuerpo JSON, estado esperado). El mismo recurso del lado viejo es VIEJO + ruta.


def _rutas(ids: dict[str, int]) -> list[tuple[str, str, dict | None, int]]:
    return [
        ("GET", "/categorias", None, 200),
        ("GET", f"/categorias/{ids['categoria']}", None, 200),
        ("GET", "/tallas", None, 200),
        ("GET", f"/tallas/{ids['talla']}", None, 200),
        ("GET", "/colores", None, 200),
        ("GET", f"/colores/{ids['color']}", None, 200),
        ("GET", "/materiales", None, 200),
        ("GET", f"/materiales/{ids['material']}", None, 200),
        ("GET", "/temporadas", None, 200),
        ("GET", f"/temporadas/{ids['temporada']}", None, 200),
        ("GET", "/colecciones", None, 200),
        ("GET", f"/colecciones/{ids['coleccion']}", None, 200),
        ("GET", "/catalogo", None, 200),
        ("GET", "/catalogo/buscar?q=Producto", None, 200),
        ("GET", f"/catalogo/{ids['producto']}", None, 200),
        ("GET", f"/inventario/disponibilidad?variante_id={ids['variante']}", None, 200),
        ("GET", "/sucursales", None, 200),
        ("GET", f"/sucursales/{ids['sucursal']}", None, 200),
        ("GET", f"/sucursales/{ids['sucursal']}/horarios", None, 200),
        ("GET", "/zonas-envio", None, 200),
        ("GET", f"/zonas-envio/{ids['zona']}", None, 200),
        ("POST", "/envios/cotizar", {"direccion_id": ids["direccion"], "cantidad_prendas": 2}, 200),
        ("POST", "/ia/voz", {"texto": "camisa"}, 200),
        ("POST", "/ia/recomendaciones", None, 200),
        ("POST", "/ia/eventos", {"tipo_evento": "vista", "producto_id": ids["producto"]}, 201),
    ]


INDICES = range(25)


def _pedir(client, metodo: str, url: str, cuerpo: dict | None, headers: dict | None = None):
    if metodo == "GET":
        return client.get(url, headers=headers)
    return client.post(url, json=cuerpo, headers=headers)


def test_hay_exactamente_25_rutas_de_ejemplo(tiendas):
    assert len(_rutas(tiendas["a"])) == 25


@pytest.mark.parametrize("indice", INDICES)
def test_cada_ruta_publica_responde_para_una_tienda_valida(client_por_peticion, tiendas, indice):
    metodo, ruta, cuerpo, esperado = _rutas(tiendas["a"])[indice]
    respuesta = _pedir(client_por_peticion, metodo, f"{PUBLICO}/tienda-a{ruta}", cuerpo)
    assert respuesta.status_code == esperado, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text}"


@pytest.mark.parametrize("indice", INDICES)
def test_cada_ruta_publica_responde_para_la_otra_tienda(client_por_peticion, tiendas, indice):
    """Mismo recorrido con la tienda B y SUS ids: la ruta es la misma para
    cualquier empresa."""
    metodo, ruta, cuerpo, esperado = _rutas(tiendas["b"])[indice]
    respuesta = _pedir(client_por_peticion, metodo, f"{PUBLICO}/tienda-b{ruta}", cuerpo)
    assert respuesta.status_code == esperado, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text}"


@pytest.mark.parametrize("indice", INDICES)
def test_codigo_inexistente_responde_404_tienda_no_encontrada(client_por_peticion, tiendas, indice):
    metodo, ruta, cuerpo, _ = _rutas(tiendas["a"])[indice]
    respuesta = _pedir(client_por_peticion, metodo, f"{PUBLICO}/no-existe{ruta}", cuerpo)
    assert respuesta.status_code == 404, f"{metodo} {ruta}: {respuesta.status_code}"
    assert respuesta.json()["detail"] == "Tienda no encontrada"


@pytest.mark.parametrize("indice", INDICES)
def test_empresa_inactiva_responde_igual_que_una_inexistente(client_por_peticion, db_session, tiendas, indice):
    metodo, ruta, cuerpo, _ = _rutas(tiendas["a"])[indice]
    empresa = db_session.scalar(select(Empresa).where(Empresa.codigo == "tienda-a"))
    empresa.activo = False
    db_session.commit()

    inactiva = _pedir(client_por_peticion, metodo, f"{PUBLICO}/tienda-a{ruta}", cuerpo)
    inexistente = _pedir(client_por_peticion, metodo, f"{PUBLICO}/no-existe{ruta}", cuerpo)

    assert inactiva.status_code == 404
    assert inactiva.json() == inexistente.json() == {"detail": "Tienda no encontrada"}


def test_el_codigo_de_la_tienda_ignora_mayusculas_y_espacios(client_por_peticion, tiendas):
    for codigo in ("Tienda-A", "TIENDA-A", "%20tienda-a%20"):
        respuesta = client_por_peticion.get(f"{PUBLICO}/{codigo}/categorias")
        assert respuesta.status_code == 200, codigo
        assert [c["nombre"] for c in respuesta.json()] == ["Categoria a"]


@pytest.mark.parametrize("indice", INDICES)
def test_las_rutas_viejas_sin_token_responden_401(client_por_peticion, tiendas, indice):
    """Sin token y sin código de tienda la sesión no tiene empresa: la ruta
    vieja ya no devuelve datos (antes 200). Ni un 404 ni un 500."""
    metodo, ruta, cuerpo, _ = _rutas(tiendas["a"])[indice]
    respuesta = _pedir(client_por_peticion, metodo, f"{VIEJO}{ruta}", cuerpo)
    assert respuesta.status_code == 401, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text}"


def test_las_rutas_viejas_con_token_siguen_sirviendo_solo_a_su_empresa(client_por_peticion, tiendas, dos_empresas):
    """El back office siempre llevó token: sus rutas no cambian y ven solo la
    empresa del token."""
    de_a = client_por_peticion.get(f"{VIEJO}/categorias", headers=dos_empresas.a.headers)
    de_b = client_por_peticion.get(f"{VIEJO}/categorias", headers=dos_empresas.b.headers)
    assert [c["nombre"] for c in de_a.json()] == ["Categoria a"]
    assert [c["nombre"] for c in de_b.json()] == ["Categoria b"]


# ---- Una tienda no ve los datos de la otra -----------------------------------------


def test_catalogo_de_una_tienda_no_muestra_productos_de_la_otra(client_por_peticion, tiendas):
    en_a = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo")
    en_b = client_por_peticion.get(f"{PUBLICO}/tienda-b/catalogo")

    assert [p["nombre"] for p in en_a.json()] == ["Producto a"]
    assert [p["nombre"] for p in en_b.json()] == ["Producto b"]
    buscar_en_a = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo/buscar", params={"q": "Producto"})
    assert [p["nombre"] for p in buscar_en_a.json()] == ["Producto a"]


def test_detalle_de_un_producto_de_la_otra_tienda_es_404(client_por_peticion, tiendas):
    propio = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo/{tiendas['a']['producto']}")
    ajeno = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo/{tiendas['b']['producto']}")
    inexistente = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo/999999")

    assert propio.status_code == 200
    assert propio.json()["nombre"] == "Producto a"
    assert ajeno.status_code == 404
    assert ajeno.json() == inexistente.json()  # igual que uno inexistente


def test_sucursales_y_horarios_de_cada_tienda_son_solo_los_suyos(client_por_peticion, tiendas):
    en_a = client_por_peticion.get(f"{PUBLICO}/tienda-a/sucursales")
    en_b = client_por_peticion.get(f"{PUBLICO}/tienda-b/sucursales")
    assert [s["nombre"] for s in en_a.json()] == ["Sucursal a"]
    assert [s["nombre"] for s in en_b.json()] == ["Sucursal b"]

    sucursal_b = tiendas["b"]["sucursal"]
    assert client_por_peticion.get(f"{PUBLICO}/tienda-b/sucursales/{sucursal_b}/horarios").status_code == 200
    assert client_por_peticion.get(f"{PUBLICO}/tienda-a/sucursales/{sucursal_b}").status_code == 404
    assert client_por_peticion.get(f"{PUBLICO}/tienda-a/sucursales/{sucursal_b}/horarios").status_code == 404


def test_tallas_y_demas_catalogos_de_cada_tienda_son_solo_los_suyos(client_por_peticion, tiendas):
    for recurso, nombre_a, nombre_b, campo in (
        ("tallas", "TA", "TB", "codigo"),
        ("colores", "Color a", "Color b", "nombre"),
        ("materiales", "Material a", "Material b", "nombre"),
        ("temporadas", "Temporada a", "Temporada b", "nombre"),
        ("colecciones", "Coleccion a", "Coleccion b", "nombre"),
    ):
        en_a = client_por_peticion.get(f"{PUBLICO}/tienda-a/{recurso}")
        en_b = client_por_peticion.get(f"{PUBLICO}/tienda-b/{recurso}")
        assert [r[campo] for r in en_a.json()] == [nombre_a], recurso
        assert [r[campo] for r in en_b.json()] == [nombre_b], recurso

    talla_b = tiendas["b"]["talla"]
    assert client_por_peticion.get(f"{PUBLICO}/tienda-a/tallas/{talla_b}").status_code == 404
    assert client_por_peticion.get(f"{PUBLICO}/tienda-b/tallas/{talla_b}").status_code == 200


def test_zonas_de_envio_de_cada_tienda_son_solo_las_suyas(client_por_peticion, tiendas):
    en_a = client_por_peticion.get(f"{PUBLICO}/tienda-a/zonas-envio")
    en_b = client_por_peticion.get(f"{PUBLICO}/tienda-b/zonas-envio")
    assert [z["nombre"] for z in en_a.json()] == ["Zona a"]
    assert [z["nombre"] for z in en_b.json()] == ["Zona b"]
    assert client_por_peticion.get(f"{PUBLICO}/tienda-a/zonas-envio/{tiendas['b']['zona']}").status_code == 404


def test_cotizar_con_la_direccion_de_otra_tienda_es_404(client_por_peticion, tiendas):
    ajena = {"direccion_id": tiendas["b"]["direccion"], "cantidad_prendas": 1}
    propia = {"direccion_id": tiendas["a"]["direccion"], "cantidad_prendas": 1}

    assert client_por_peticion.post(f"{PUBLICO}/tienda-a/envios/cotizar", json=propia).status_code == 200
    assert client_por_peticion.post(f"{PUBLICO}/tienda-a/envios/cotizar", json=ajena).status_code == 404


# ---- Token de otra empresa ----------------------------------------------------------


def test_token_de_otra_empresa_se_trata_como_anonimo(client_por_peticion, tiendas, dos_empresas):
    """Un token de B en /public/tienda-a/...: las rutas que aceptan usuario
    opcional responden como a un anónimo (nunca 401, nunca con datos de B), y
    los datos son los de la tienda de la ruta."""
    token_b = dos_empresas.b.headers

    catalogo = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo", headers=token_b)
    assert catalogo.status_code == 200
    assert [p["nombre"] for p in catalogo.json()] == ["Producto a"]

    voz = client_por_peticion.post(f"{PUBLICO}/tienda-a/ia/voz", json={"texto": "camisa"}, headers=token_b)
    assert voz.status_code == 200
    recomendaciones = client_por_peticion.post(f"{PUBLICO}/tienda-a/ia/recomendaciones", headers=token_b)
    assert recomendaciones.status_code == 200
    evento = client_por_peticion.post(
        f"{PUBLICO}/tienda-a/ia/eventos",
        json={"tipo_evento": "vista", "producto_id": tiendas["a"]["producto"]},
        headers=token_b,
    )
    assert evento.status_code == 201


def test_el_evento_con_token_de_otra_empresa_queda_anonimo_en_la_tienda(
    client_por_peticion, db_session, tiendas, dos_empresas
):
    cuerpo = {"tipo_evento": "vista", "producto_id": tiendas["a"]["producto"]}
    original = empresa_de(db_session)
    fijar_empresa(db_session, dos_empresas.b.id)
    cliente_b = db_session.scalar(select(Usuario).where(Usuario.email == "cliente-b@example.com"))
    token = crear_access_token(cliente_b.id, [], permisos_de_usuario(db_session, cliente_b.id))
    fijar_empresa(db_session, original)
    cabeceras_cliente_b = {"Authorization": f"Bearer {token}"}

    respuesta = client_por_peticion.post(f"{PUBLICO}/tienda-a/ia/eventos", json=cuerpo, headers=cabeceras_cliente_b)
    assert respuesta.status_code == 201

    original = empresa_de(db_session)
    fijar_empresa(db_session, dos_empresas.a.id)
    eventos = db_session.scalars(select(HistorialNavegacion)).all()
    fijar_empresa(db_session, original)
    assert len(eventos) == 1
    assert eventos[0].empresa_id == dos_empresas.a.id
    assert eventos[0].cliente_id is None  # anónimo: no se le atribuyó el cliente de B


def test_token_de_la_misma_empresa_en_su_tienda_funciona_con_normalidad(client_por_peticion, tiendas, dos_empresas):
    respuesta = client_por_peticion.get(f"{PUBLICO}/tienda-a/catalogo", headers=dos_empresas.a.headers)
    assert respuesta.status_code == 200
    assert [p["nombre"] for p in respuesta.json()] == ["Producto a"]


# ---- Eventos de la tienda -----------------------------------------------------------


def test_evento_con_una_variante_de_otra_empresa_responde_404(client_por_peticion, tiendas):
    """El id recibido se resuelve con una búsqueda filtrada (PASO 4): una
    variante de B no existe para la tienda A."""
    ajena = client_por_peticion.post(
        f"{PUBLICO}/tienda-a/ia/eventos", json={"tipo_evento": "vista", "variante_id": tiendas["b"]["variante"]}
    )
    propia = client_por_peticion.post(
        f"{PUBLICO}/tienda-a/ia/eventos", json={"tipo_evento": "vista", "variante_id": tiendas["a"]["variante"]}
    )
    assert propia.status_code == 201
    assert ajena.status_code == 404


def test_evento_con_un_producto_de_otra_empresa_responde_404(client_por_peticion, tiendas):
    ajeno = client_por_peticion.post(
        f"{PUBLICO}/tienda-a/ia/eventos", json={"tipo_evento": "vista", "producto_id": tiendas["b"]["producto"]}
    )
    assert ajeno.status_code == 404

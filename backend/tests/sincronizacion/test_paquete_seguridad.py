"""E08: seguridad del paquete de descarga offline. Las 4 rutas (`/paquete`, `/paquete/catalogo`,
`/paquete/stock`, `/paquete/clientes`) solo entregan lo mínimo para vender y reservar: una LISTA BLANCA
exacta de claves (una clave nueva en el servidor hace fallar la prueba), nada de costos, límites de
stock, proveedores ni datos personales (salvo nombre, apellido y ci_nit del cliente), nada de otra
empresa y solo para quien tiene `sincronizacion.operar`.

Dos empresas con plan Profesional (las dos pueden descargar) y una sesión nueva por petición."""

import datetime as dt
from types import SimpleNamespace

import pytest

from app.core.tenant import empresa_de, fijar_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import crear_empresa, token_de
from tests.sincronizacion.ayudas import API, CLAVE, armar_reserva, construir_escenario, enviar, iniciar_sesion

RUTAS = ("/paquete", "/paquete/catalogo", "/paquete/stock", "/paquete/clientes")

# ---- Lista blanca: ruta lógica -> conjunto EXACTO de claves ------------------------------------
# La ruta lógica es la de las claves anidadas ("sucursales[].horarios[]"); la raíz es "".

_RAIZ = {"version_contrato", "generado_en"}

BLANCA_MANIFIESTO = {
    "": _RAIZ | {"aviso_desactualizado_horas", "empresa", "sucursales", "referencia", "promociones_vigentes", "reglas"},
    "empresa": {"id", "codigo", "nombre"},
    "sucursales[]": {"id", "codigo", "nombre", "direccion", "es_deposito", "horarios"},
    "sucursales[].horarios[]": {"dia_semana", "hora_apertura", "hora_cierre"},
    "referencia": {"categorias", "tallas", "colores"},
    "referencia.categorias[]": {"id", "nombre", "categoria_padre_id"},
    "referencia.tallas[]": {"id", "codigo", "orden"},
    "referencia.colores[]": {"id", "nombre", "codigo_hex"},
    "promociones_vigentes[]": {"id", "nombre", "tipo", "valor", "fecha_inicio", "fecha_fin", "alcances"},
    "promociones_vigentes[].alcances[]": {"producto_id", "categoria_id", "temporada_id"},
    "reglas": {
        "metodos_pago_offline",
        "max_operaciones_por_lote",
        "plazo_cambio_horas",
        "cambios_y_devoluciones",
        "reservas_offline",
    },
}
BLANCA_CATALOGO = {
    "": _RAIZ | {"total", "siguiente_desde_id", "items"},
    "items[]": {
        "id", "codigo", "nombre", "categoria_id", "genero", "temporada_id", "imagen_principal", "variantes",
    },
    "items[].variantes[]": {"id", "talla_id", "color_id", "sku", "codigo_barras", "precio", "descuento_unitario"},
}
BLANCA_STOCK = {
    "": _RAIZ | {"sucursal_id", "incremental", "siguiente_desde_variante_id", "items"},
    "items[]": {"variante_id", "cantidad_disponible", "actualizado_en"},
}
BLANCA_CLIENTES = {
    "": _RAIZ | {"total", "siguiente_desde_id", "items"},
    "items[]": {"id", "nombre", "apellido", "ci_nit"},
}
BLANCAS = {
    "/paquete": BLANCA_MANIFIESTO,
    "/paquete/catalogo": BLANCA_CATALOGO,
    "/paquete/stock": BLANCA_STOCK,
    "/paquete/clientes": BLANCA_CLIENTES,
}

# Nada de esto puede aparecer, ni como clave ni en el texto bruto (`sku` y `codigo_barras` sí son legítimos).
PROHIBIDAS = (
    "costo", "minimo", "maximo", "email", "correo", "telefono", "password", "hash",
    "cantidad_fisica", "cantidad_reservada", "proveedor", "margen", "token",
)


# ---- Ayudas ------------------------------------------------------------------------------------


def claves_por_ruta(nodo, ruta: str = "", acumulado: dict | None = None) -> dict[str, set[str]]:
    """Recorre TODO el JSON (diccionarios dentro de listas dentro de diccionarios...) y junta, por
    ruta lógica, la unión de las claves de los diccionarios que hay en ella."""
    acumulado = {} if acumulado is None else acumulado
    if isinstance(nodo, dict):
        acumulado.setdefault(ruta, set()).update(nodo)
        for clave, valor in nodo.items():
            claves_por_ruta(valor, f"{ruta}.{clave}" if ruta else clave, acumulado)
    elif isinstance(nodo, list):
        for elemento in nodo:
            claves_por_ruta(elemento, f"{ruta}[]", acumulado)
    return acumulado


def todas_las_claves(nodo) -> set[str]:
    return set().union(*claves_por_ruta(nodo).values())


def _ok(respuesta):
    assert respuesta.status_code == 200, f"{respuesta.request.url}: {respuesta.status_code} {respuesta.text}"
    return respuesta


def descargar(client, headers: dict, sucursal_id: int) -> dict:
    """Las 4 respuestas del paquete (cuerpo bruto y JSON) con el usuario de `headers`."""
    respuestas = {
        "/paquete": client.get(f"{API}/paquete", headers=headers),
        "/paquete/catalogo": client.get(f"{API}/paquete/catalogo", headers=headers),
        "/paquete/stock": client.get(f"{API}/paquete/stock", params={"sucursal_id": sucursal_id}, headers=headers),
        "/paquete/clientes": client.get(f"{API}/paquete/clientes", headers=headers),
    }
    return {ruta: _ok(respuesta) for ruta, respuesta in respuestas.items()}


def _crear_empresa_profesional(db, codigo: str) -> SimpleNamespace:
    """Como `dos_empresas`, pero con plan Profesional (puede descargar el paquete offline)."""
    original = empresa_de(db)
    repo = UsuarioRepository()
    empresa = crear_empresa(db, codigo, plan="profesional")
    fijar_empresa(db, empresa.id)
    try:
        admin = repo.crear(
            db,
            UsuarioCrear(nombre="Admin", apellido=codigo, email=f"admin@{codigo}.example.com", password=CLAVE),
        )
        repo.asignar_roles(db, admin, ["administrador"])
        return SimpleNamespace(id=empresa.id, codigo=codigo, headers=token_de(db, admin))
    finally:
        fijar_empresa(db, original)


def _armar_empresa(client, db, codigo: str, sufijo: str, *, con_datos_completos: bool) -> SimpleNamespace:
    """Una empresa Profesional con su escenario. Con `con_datos_completos`: una promoción vigente, una
    reserva (hay stock físico y reservado) y un cliente con ci_nit, para que toda clave aparezca."""
    empresa = _crear_empresa_profesional(db, codigo)
    escenario = construir_escenario(client, empresa.headers, db, sufijo=sufijo, codigo_empresa=codigo)
    correo_cliente = f"cliente-sync{sufijo}@example.com"
    cliente = iniciar_sesion(client, codigo, correo_cliente)
    ci_nit = f"CI{sufijo.upper().replace('-', '')}7654321"
    perfil = client.put("/api/v1/clientes/perfil", json={"ci_nit": ci_nit}, headers=cliente)
    assert perfil.status_code == 200, perfil.text
    if con_datos_completos:
        hoy = hoy_utc()
        promocion = client.post(
            "/api/v1/promociones",
            json={
                "nombre": f"Oferta sync{sufijo}",
                "tipo": "porcentaje",
                "valor": "10",
                "fecha_inicio": (hoy - dt.timedelta(days=1)).isoformat(),
                "fecha_fin": (hoy + dt.timedelta(days=30)).isoformat(),
                "alcances": [{"producto_id": escenario.producto_id}],
            },
            headers=empresa.headers,
        )
        assert promocion.status_code == 201, promocion.text
        resultado = enviar(client, escenario.cajero, [armar_reserva(escenario)]).json()["resultados"][0]
        assert resultado["estado"] == "confirmada", resultado
    return SimpleNamespace(
        empresa=empresa, e=escenario, ci_nit=ci_nit, sufijo=sufijo, correo_cliente=correo_cliente, cliente=cliente
    )


@pytest.fixture()
def mundo(client_por_peticion, db_session):
    """A y B (las dos Profesional). A, la que se descarga, tiene promoción, reserva y cliente con ci_nit."""
    a = _armar_empresa(client_por_peticion, db_session, "tienda-a", "-a", con_datos_completos=True)
    b = _armar_empresa(client_por_peticion, db_session, "tienda-b", "-b", con_datos_completos=True)
    return SimpleNamespace(client=client_por_peticion, a=a, b=b)


# ---- 1. Lista blanca de claves ------------------------------------------------------------------


@pytest.mark.parametrize("ruta", RUTAS)
def test_cada_ruta_del_paquete_devuelve_exactamente_las_claves_de_la_lista_blanca(mundo, ruta):
    respuestas = descargar(mundo.client, mundo.a.e.cajero, mundo.a.e.sucursal_id)

    real = claves_por_ruta(respuestas[ruta].json())

    # Igualdad exacta de rutas y de claves: una clave nueva (o un bloque nuevo) rompe la prueba, y una
    # que desaparece también (señal de que el escenario ya no ejercita ese dato).
    assert real == BLANCAS[ruta], {
        "sobran": {r: real[r] - BLANCAS[ruta].get(r, set()) for r in real if real[r] - BLANCAS[ruta].get(r, set())},
        "faltan": {r: BLANCAS[ruta][r] - real.get(r, set()) for r in BLANCAS[ruta] if BLANCAS[ruta][r] - real.get(r, set())},
    }


def test_la_lista_blanca_se_alimenta_de_datos_reales_y_no_solo_de_estructuras_vacias(mundo):
    """Si el escenario dejara de traer promoción, reserva o ci_nit, la lista blanca de arriba
    dejaría de comprobar esas claves: aquí se exige que el escenario las tenga."""
    r = descargar(mundo.client, mundo.a.e.cajero, mundo.a.e.sucursal_id)

    manifiesto = r["/paquete"].json()
    assert manifiesto["promociones_vigentes"] and manifiesto["promociones_vigentes"][0]["alcances"]
    assert manifiesto["sucursales"][0]["horarios"]
    assert manifiesto["referencia"]["categorias"] and manifiesto["referencia"]["tallas"] and manifiesto["referencia"]["colores"]
    catalogo = r["/paquete/catalogo"].json()
    assert catalogo["items"] and catalogo["items"][0]["variantes"]
    stock = {i["variante_id"]: i["cantidad_disponible"] for i in r["/paquete/stock"].json()["items"]}
    assert stock[mundo.a.e.v1] == 9  # 10 físicas menos 1 reservada: el disponible, no el desglose
    clientes = r["/paquete/clientes"].json()["items"]
    assert any(c["ci_nit"] == mundo.a.ci_nit for c in clientes)


# ---- 2. Nada sensible, ni en claves ni en el texto bruto ------------------------------------------


@pytest.mark.parametrize("ruta", RUTAS)
def test_ninguna_respuesta_trae_datos_sensibles_ni_en_claves_ni_en_el_texto(mundo, ruta):
    respuesta = descargar(mundo.client, mundo.a.e.cajero, mundo.a.e.sucursal_id)[ruta]
    texto = respuesta.text.lower()
    claves = {clave.lower() for clave in todas_las_claves(respuesta.json())}

    for prohibida in PROHIBIDAS:
        assert prohibida not in texto, f"{ruta}: aparece '{prohibida}' en el texto"
        assert not any(prohibida in clave for clave in claves), f"{ruta}: una clave contiene '{prohibida}'"
    # Valores concretos que nunca deben salir: correos del cliente y del cajero, la contraseña, cualquier "@".
    for secreto in (mundo.a.correo_cliente, "cajero-sync-a", "encargado-sync-a", "admin@tienda-a", CLAVE, "@"):
        assert secreto.lower() not in texto, f"{ruta}: aparece '{secreto}'"
    # Y las cabeceras de la respuesta tampoco filtran el token de quien descarga.
    assert mundo.a.e.cajero["Authorization"].split()[1] not in str(dict(respuesta.headers))


def test_las_variantes_del_catalogo_solo_traen_precio_y_descuento_nunca_el_costo(mundo):
    """El costo promedio (40.00 en el escenario) está en la base: precio de venta sí, costo no."""
    catalogo = _ok(mundo.client.get(f"{API}/paquete/catalogo", headers=mundo.a.e.cajero)).json()

    variantes = [v for p in catalogo["items"] for v in p["variantes"]]
    assert variantes
    for variante in variantes:
        assert variante["precio"] == "100.00"
        assert set(variante) == BLANCA_CATALOGO["items[].variantes[]"]
        assert "40.00" not in str(variante)


# ---- 3. Aislamiento entre empresas ----------------------------------------------------------------


def _marcas(descarga: dict, propia: SimpleNamespace) -> dict:
    """Ids (por clase) y textos distintivos de lo que descargó una empresa."""
    catalogo = descarga["/paquete/catalogo"].json()
    manifiesto = descarga["/paquete"].json()
    return {
        "productos": {p["id"] for p in catalogo["items"]},
        "variantes": {v["id"] for p in catalogo["items"] for v in p["variantes"]},
        "sucursales": {s["id"] for s in manifiesto["sucursales"]},
        "clientes": {c["id"] for c in descarga["/paquete/clientes"].json()["items"]},
        "promociones": {p["id"] for p in manifiesto["promociones_vigentes"]},
        "categorias": {c["id"] for c in manifiesto["referencia"]["categorias"]},
        "tallas": {t["id"] for t in manifiesto["referencia"]["tallas"]},
        "colores": {c["id"] for c in manifiesto["referencia"]["colores"]},
        "stock": {i["variante_id"] for i in descarga["/paquete/stock"].json()["items"]},
        "textos": (
            {propia.empresa.codigo, propia.ci_nit}
            | {p["codigo"] for p in catalogo["items"]}
            | {p["nombre"] for p in catalogo["items"]}
            | {v["sku"] for p in catalogo["items"] for v in p["variantes"]}
            | {s["codigo"] for s in manifiesto["sucursales"]}
            | {s["nombre"] for s in manifiesto["sucursales"]}
            | {p["nombre"] for p in manifiesto["promociones_vigentes"]}
            | {c["nombre"] for c in manifiesto["referencia"]["categorias"]}
            | {c["nombre"] for c in manifiesto["referencia"]["colores"]}
            | {t["codigo"] for t in manifiesto["referencia"]["tallas"]}
        ),
    }


def test_los_datos_de_una_empresa_nunca_aparecen_en_el_paquete_de_la_otra(mundo):
    de_a = descargar(mundo.client, mundo.a.e.cajero, mundo.a.e.sucursal_id)
    de_b = descargar(mundo.client, mundo.b.e.cajero, mundo.b.e.sucursal_id)
    marcas_a, marcas_b = _marcas(de_a, mundo.a), _marcas(de_b, mundo.b)

    # Cada empresa sí recibe lo suyo (evita una prueba verde por un paquete vacío)...
    for marcas in (marcas_a, marcas_b):
        for clase in ("productos", "variantes", "sucursales", "clientes", "promociones", "categorias", "tallas", "colores", "stock"):
            assert marcas[clase], clase
        assert len(marcas["textos"]) >= 8
    # ...y nada de la otra: ni un id, ni un nombre, SKU o código.
    for clase in ("productos", "variantes", "sucursales", "clientes", "promociones", "categorias", "tallas", "colores", "stock"):
        assert not marcas_a[clase] & marcas_b[clase], clase
    assert not marcas_a["textos"] & marcas_b["textos"]
    for ruta in RUTAS:
        for ajeno in marcas_b["textos"]:
            assert ajeno not in de_a[ruta].text, f"A ve '{ajeno}' de B en {ruta}"
        for ajeno in marcas_a["textos"]:
            assert ajeno not in de_b[ruta].text, f"B ve '{ajeno}' de A en {ruta}"
    # El administrador de cada empresa tampoco ve la otra (alcance global, pero no de empresa).
    admin_a = _ok(mundo.client.get(f"{API}/paquete", headers=mundo.a.empresa.headers)).json()
    assert {s["id"] for s in admin_a["sucursales"]} == {mundo.a.e.sucursal_id}
    assert admin_a["empresa"]["codigo"] == "tienda-a"


def test_la_sucursal_de_otra_empresa_no_se_puede_pedir(mundo):
    client, a, b = mundo.client, mundo.a, mundo.b
    ajena = {"sucursal_id": b.e.sucursal_id}

    # El administrador (alcance global): una sucursal de otra empresa es igual que una inexistente (404).
    en_ajena = client.get(f"{API}/paquete/stock", params=ajena, headers=a.empresa.headers)
    inexistente = client.get(f"{API}/paquete/stock", params={"sucursal_id": 999999}, headers=a.empresa.headers)
    assert en_ajena.status_code == inexistente.status_code == 404
    assert en_ajena.json() == inexistente.json()
    assert client.get(f"{API}/paquete", params=ajena, headers=a.empresa.headers).status_code == 404
    # El cajero (limitado a su sucursal): 403, y tampoco se filtra nada del stock de la otra.
    for ruta in ("/paquete/stock", "/paquete"):
        respuesta = client.get(f"{API}{ruta}", params=ajena, headers=a.e.cajero)
        assert respuesta.status_code == 403, (ruta, respuesta.text)
        assert str(b.e.v1) not in respuesta.text
    # Lo propio sí funciona (la misma petición con la sucursal de A).
    assert client.get(f"{API}/paquete/stock", params={"sucursal_id": a.e.sucursal_id}, headers=a.empresa.headers).status_code == 200
    assert client.get(f"{API}/paquete/stock", params={"sucursal_id": a.e.sucursal_id}, headers=a.e.cajero).status_code == 200
    # El administrador debe indicar la sucursal: no se adivina una.
    assert client.get(f"{API}/paquete/stock", headers=a.empresa.headers).status_code == 422


def test_el_paginado_por_clave_no_deja_pedir_filas_de_otra_empresa(mundo):
    """`desde_id` / `desde_variante_id` son solo posiciones: aunque apunten a ids de B, A recibe lo suyo."""
    client, a, b = mundo.client, mundo.a, mundo.b
    propios = {p["id"] for p in _ok(client.get(f"{API}/paquete/catalogo", headers=a.e.cajero)).json()["items"]}
    ajenos = {b.e.v1, b.e.v2}  # variantes de B (los ids de cada tabla se comparan solo con los de su tabla)

    for desde in (0, b.e.producto_id - 1, b.e.producto_id, 10**6):
        productos = _ok(client.get(f"{API}/paquete/catalogo", params={"desde_id": desde}, headers=a.e.cajero)).json()
        assert b.e.producto_id not in {p["id"] for p in productos["items"]}
        assert not {v["id"] for p in productos["items"] for v in p["variantes"]} & ajenos
        assert {p["id"] for p in productos["items"]} <= propios
        stock = _ok(
            client.get(
                f"{API}/paquete/stock",
                params={"sucursal_id": a.e.sucursal_id, "desde_variante_id": max(desde - 1, 0)},
                headers=a.e.cajero,
            )
        ).json()
        assert not {i["variante_id"] for i in stock["items"]} & ajenos
        clientes = _ok(client.get(f"{API}/paquete/clientes", params={"desde_id": max(desde - 1, 0)}, headers=a.e.cajero)).json()
        assert not {c["id"] for c in clientes["items"]} & {b.e.cliente_id}
        assert b.ci_nit not in str(clientes)


# ---- 4. ci_nit es el único dato personal ------------------------------------------------------------


def test_del_cliente_solo_salen_id_nombre_apellido_y_ci_nit(mundo):
    client, a = mundo.client, mundo.a
    perfil = {
        "telefono": "77712345",
        "ci_nit": a.ci_nit,
        "razon_social": "Razon Secreta Limitada",
        "fecha_nacimiento": "1990-05-17",
        "estatura_cm": 187,
        "preferencia_ajuste": "holgado",
        "acepta_datos_foto": True,
    }
    guardado = client.put("/api/v1/clientes/perfil", json=perfil, headers=a.cliente)
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["razon_social"] == "Razon Secreta Limitada"  # el dato existe en el servidor

    respuesta = _ok(client.get(f"{API}/paquete/clientes", headers=a.e.cajero))
    mio = [c for c in respuesta.json()["items"] if c["id"] == a.e.cliente_id]

    assert mio == [{"id": a.e.cliente_id, "nombre": "Cli", "apellido": "Sync", "ci_nit": a.ci_nit}]
    texto = respuesta.text
    for dato in ("77712345", "Razon Secreta", "1990-05-17", "holgado"):
        assert dato not in texto, dato
    for clave in ("telefono", "razon_social", "fecha_nacimiento", "estatura", "preferencia", "acepta_datos", "usuario_id"):
        assert clave not in texto, clave
    # Tampoco se cuelan por el manifiesto, el catálogo o el stock.
    for ruta in ("/paquete", "/paquete/catalogo"):
        otro = _ok(client.get(f"{API}{ruta}", headers=a.e.cajero)).text
        for dato in ("77712345", "Razon Secreta", "1990-05-17", a.ci_nit):
            assert dato not in otro, (ruta, dato)


# ---- 5. Quién puede descargar -----------------------------------------------------------------------


def _usuario_con_rol(client, admin: dict, codigo: str, rol: str, correo: str) -> dict:
    creado = client.post(
        "/api/v1/usuarios", json={"nombre": "Sin", "apellido": "Permiso", "email": correo, "password": CLAVE}, headers=admin
    )
    assert creado.status_code == 201, creado.text
    asignado = client.put(f"/api/v1/usuarios/{creado.json()['id']}/roles", json={"nombres_rol": [rol]}, headers=admin)
    assert asignado.status_code == 200, asignado.text
    return iniciar_sesion(client, codigo, correo)


def _pedir_las_cuatro(client, headers: dict, sucursal_id: int) -> dict:
    return {
        "/paquete": client.get(f"{API}/paquete", headers=headers),
        "/paquete/catalogo": client.get(f"{API}/paquete/catalogo", headers=headers),
        "/paquete/stock": client.get(f"{API}/paquete/stock", params={"sucursal_id": sucursal_id}, headers=headers),
        "/paquete/clientes": client.get(f"{API}/paquete/clientes", headers=headers),
    }


def test_un_cliente_final_y_un_usuario_sin_el_permiso_reciben_403_en_las_cuatro_rutas(mundo):
    client, a = mundo.client, mundo.a
    proveedor = _usuario_con_rol(client, a.empresa.headers, "tienda-a", "proveedor", "proveedor-sync-a@example.com")

    for quien, headers in (("cliente final", a.cliente), ("sin sincronizacion.operar", proveedor)):
        for ruta, respuesta in _pedir_las_cuatro(client, headers, a.e.sucursal_id).items():
            assert respuesta.status_code == 403, (quien, ruta, respuesta.status_code, respuesta.text)
            assert "SYNC-1" not in respuesta.text and "Camisa" not in respuesta.text  # el error no filtra datos
    # Con el permiso, las mismas peticiones funcionan (no es un 403 por una ruta mal armada).
    for ruta, respuesta in _pedir_las_cuatro(client, a.e.cajero, a.e.sucursal_id).items():
        assert respuesta.status_code == 200, (ruta, respuesta.text)


def test_sin_sesion_o_con_un_token_falso_ninguna_ruta_del_paquete_responde_datos(mundo):
    client, a = mundo.client, mundo.a
    falso = {"Authorization": "Bearer esto.no.es.un.token"}

    for headers in ({}, falso):
        for ruta, respuesta in _pedir_las_cuatro(client, headers, a.e.sucursal_id).items():
            assert respuesta.status_code == 401, (ruta, respuesta.status_code)
            assert "SYNC-1" not in respuesta.text

"""E04: las funcionalidades que incluye cada plan (4.6) y cómo las exigen las
rutas. Lo que incluye cada plan se lee de la tabla `plan`: las pruebas editan
una fila para apagar una funcionalidad y comprueban que la ruta cambia sin
tocar código.

Empresa A = Profesional (todo incluido), B = Básico (sin reportes_ia). Por HTTP
con una sesión nueva por petición. Orden de errores de 4.6: 401 -> 403
suscripcion_no_activa -> 403 plan_no_incluye_funcionalidad -> 403 falta el
permiso -> reglas de negocio."""

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.planes import (
    FUNC_GESTION_PRODUCTOS,
    FUNC_GESTION_VENTAS,
    FUNC_REPORTES_CONVENCIONALES,
    FUNC_REPORTES_IA,
    FUNC_RESERVAS,
    exigir_funcionalidad,
)
from app.core.rate_limit import limiter
from app.core.tenant import en_empresa
from app.inteligencia.schemas import FiltrosReporteVoz
from app.main import app
from app.plataforma.models import Plan, Suscripcion
from tests.comercial._datos_empresa import TOKEN_SERVICIO, iniciar_pago, reservar, sembrar_empresa

MODULO_CU = "app.inteligencia.casos_uso.cu23_generar_reportes_con_ia"
REPORTE_VOZ = "/api/v1/ia/reporte-voz"


# ---- Fixtures y ayudas -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _limpiar_limite():
    limiter.reset()  # /ia/reporte-voz: 15/min por IP, y todas las pruebas comparten la IP
    yield
    limiter.reset()


@pytest.fixture()
def vista_ventas(db_session):
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))  # conftest solo crea la de inventario
    db_session.commit()


class _InterpreteFalso:
    def parsear(self, texto):
        return FiltrosReporteVoz(tipo_reporte="reservas")


@pytest.fixture()
def sin_groq(monkeypatch):
    """Groq se sustituye por un intérprete falso (sin red ni API key)."""
    monkeypatch.setattr(f"{MODULO_CU}.obtener_parser_reporte_voz", lambda: _InterpreteFalso())


@pytest.fixture()
def mundo(client_por_peticion, dos_empresas, db_session):
    return {
        "a": sembrar_empresa(client_por_peticion, db_session, dos_empresas.a),
        "b": sembrar_empresa(client_por_peticion, db_session, dos_empresas.b),
    }


def _apagar(db, plan: str, **funcionalidades) -> None:
    """Edita la fila del plan (p. ej. `reservas=False`)."""
    fila = db.scalar(select(Plan).where(Plan.codigo == plan))
    for nombre, valor in funcionalidades.items():
        setattr(fila, nombre, valor)
    db.commit()


def _suspender(db, empresa_id: int) -> None:
    with en_empresa(db, empresa_id):
        db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada")).estado = "suspendida"
    db.commit()


def _es_error_de_plan(respuesta, funcionalidad: str, plan: str) -> bool:
    return respuesta.status_code == 403 and respuesta.json() == {
        "detail": "plan_no_incluye_funcionalidad",
        "codigo": "plan_no_incluye_funcionalidad",
        "mensaje": "Su plan no incluye esta funcionalidad",
        "funcionalidad": funcionalidad,
        "plan": plan,
    }


# ---- reportes_ia ---------------------------------------------------------------------------


def test_reportes_ia_basico_403_y_profesional_pasa(client_por_peticion, dos_empresas, vista_ventas, sin_groq):
    client = client_por_peticion

    basico = client.post(REPORTE_VOZ, json={"texto": "como van las reservas"}, headers=dos_empresas.b.headers)
    profesional = client.post(REPORTE_VOZ, json={"texto": "como van las reservas"}, headers=dos_empresas.a.headers)

    assert _es_error_de_plan(basico, "reportes_ia", "basico"), basico.text
    assert profesional.status_code == 200, profesional.text
    assert profesional.json()["tipo_reporte"] == "reservas"


def test_el_cuerpo_del_error_de_plan_trae_detail_codigo_mensaje_funcionalidad_y_plan(
    client_por_peticion, dos_empresas
):
    respuesta = client_por_peticion.post(REPORTE_VOZ, json={"texto": "ventas"}, headers=dos_empresas.b.headers)

    assert respuesta.status_code == 403
    assert set(respuesta.json()) == {"detail", "codigo", "mensaje", "funcionalidad", "plan"}
    assert respuesta.json()["detail"] == respuesta.json()["codigo"] == "plan_no_incluye_funcionalidad"
    assert respuesta.json()["funcionalidad"] == "reportes_ia"
    assert respuesta.json()["plan"] == "basico"
    assert respuesta.json()["mensaje"]


# ---- lo que pasa en los dos planes -----------------------------------------------------


@pytest.mark.parametrize("empresa", ["a", "b"])
def test_reportes_convencionales_pasan_en_ambos_planes(client_por_peticion, dos_empresas, vista_ventas, empresa):
    headers = getattr(dos_empresas, empresa).headers
    for ruta in ("ventas", "inventario", "reservas", "dashboard"):
        respuesta = client_por_peticion.get(f"/api/v1/reportes/{ruta}", headers=headers)
        assert respuesta.status_code == 200, f"{ruta}: {respuesta.text}"


@pytest.mark.parametrize("empresa", ["a", "b"])
def test_gestion_de_productos_pasa_en_ambos_planes(client_por_peticion, dos_empresas, mundo, empresa):
    headers = getattr(dos_empresas, empresa).headers
    client = client_por_peticion

    assert client.get("/api/v1/productos", headers=headers).status_code == 200
    assert client.post("/api/v1/proveedores", json={"nombre": f"Proveedor {empresa}"}, headers=headers).status_code == 201
    assert client.get("/api/v1/ordenes-compra", headers=headers).status_code == 200
    assert client.post("/api/v1/materiales", json={"nombre": "Lino"}, headers=headers).status_code == 201


@pytest.mark.parametrize("empresa", ["a", "b"])
def test_gestion_de_ventas_pasa_en_ambos_planes(client_por_peticion, dos_empresas, mundo, empresa):
    datos = mundo[empresa]
    client = client_por_peticion

    venta, pago = iniciar_pago(client, datos)  # carrito + venta digital + pago iniciado

    assert venta["id"] and pago["referencia_externa"]
    assert client.get("/api/v1/promociones", headers=datos["admin"]).status_code == 200
    assert client.get("/api/v1/envios", headers=datos["admin"]).status_code == 200
    assert client.get(f"/api/v1/pagos/{pago['id']}/estado", headers=datos["cliente"]).status_code == 200


@pytest.mark.parametrize("empresa", ["a", "b"])
def test_las_reservas_pasan_en_ambos_planes(client_por_peticion, mundo, empresa):
    datos = mundo[empresa]

    reserva = reservar(client_por_peticion, datos)

    assert reserva["id"]
    mias = client_por_peticion.get("/api/v1/reservas/mis-reservas", headers=datos["cliente"])
    assert mias.status_code == 200 and len(mias.json()) == 1


# ---- apagar una funcionalidad en la tabla del plan -------------------------------------------


def test_apagar_reservas_en_el_plan_bloquea_las_rutas_de_reservas(client_por_peticion, db_session, mundo):
    client = client_por_peticion
    reserva = reservar(client, mundo["b"])
    _apagar(db_session, "basico", reservas=False)
    b, a = mundo["b"], mundo["a"]

    for respuesta in (
        client.post(
            "/api/v1/reservas",
            json={"sucursal_id": b["sucursal_id"], "fecha_visita": b["fecha_visita"], "hora_visita_desde": "12:00:00",
                  "hora_visita_hasta": "13:00:00", "detalle": [{"variante_id": b["variante_id"], "cantidad": 1}]},
            headers=b["cliente"],
        ),
        client.get("/api/v1/reservas/mis-reservas", headers=b["cliente"]),
        client.get(f"/api/v1/reservas/{reserva['id']}", headers=b["cliente"]),
        client.delete(f"/api/v1/reservas/{reserva['id']}", headers=b["cliente"]),
        client.get(f"/api/v1/reservas/sucursal/{b['sucursal_id']}", headers=b["admin"]),
        client.put(f"/api/v1/reservas/{reserva['id']}/preparar", headers=b["admin"]),
    ):
        assert _es_error_de_plan(respuesta, "reservas", "basico"), respuesta.text

    # La tarea de servicio no se compuerta (no hay empresa de usuario), la otra empresa
    # (otro plan) y lo demás de B siguen igual.
    assert client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO).status_code == 200
    assert reservar(client, a)["id"]
    assert client.get("/api/v1/productos", headers=b["admin"]).status_code == 200


def test_apagar_gestion_de_productos_bloquea_escrituras_y_deja_las_lecturas_del_catalogo(
    client_por_peticion, db_session, dos_empresas, mundo
):
    client = client_por_peticion
    b = mundo["b"]
    headers = dos_empresas.b.headers
    _apagar(db_session, "basico", gestion_productos=False)

    escrituras = [
        client.post("/api/v1/categorias", json={"nombre": "Nueva"}, headers=headers),
        client.put("/api/v1/categorias/1", json={"nombre": "Otra"}, headers=headers),
        client.delete("/api/v1/categorias/1", headers=headers),
        client.post("/api/v1/tallas", json={"codigo": "XL", "orden": 5}, headers=headers),
        client.post("/api/v1/colores", json={"nombre": "Rojo"}, headers=headers),
        client.post("/api/v1/materiales", json={"nombre": "Seda"}, headers=headers),
        client.post("/api/v1/temporadas", json={"nombre": "Verano", "anio": 2027}, headers=headers),
        client.post("/api/v1/colecciones", json={"nombre": "Capsula"}, headers=headers),
        client.post("/api/v1/productos", json={}, headers=headers),
        client.put("/api/v1/variantes/1", json={}, headers=headers),
        client.delete("/api/v1/imagenes/1", headers=headers),
        client.post("/api/v1/proveedores", json={"nombre": "Prov"}, headers=headers),
        client.post("/api/v1/ordenes-compra", json={}, headers=headers),
        client.post("/api/v1/recepciones", json={}, headers=headers),
    ]
    for respuesta in escrituras:
        assert _es_error_de_plan(respuesta, "gestion_productos", "basico"), respuesta.text
    # La administración de productos y el abastecimiento van enteros tras la compuerta.
    for ruta in ("/api/v1/productos", "/api/v1/proveedores", "/api/v1/ordenes-compra", "/api/v1/recepciones"):
        assert _es_error_de_plan(client.get(ruta, headers=headers), "gestion_productos", "basico"), ruta

    # Las lecturas del catálogo y el inventario de sucursal NO se compuertan.
    for ruta in (
        "/api/v1/categorias",
        "/api/v1/tallas",
        "/api/v1/catalogo",
        f"/api/v1/inventario/disponibilidad?variante_id={b['variante_id']}",
        f"/api/v1/inventario/sucursal/{b['sucursal_id']}",
    ):
        assert client.get(ruta, headers=headers).status_code == 200, ruta


def test_apagar_gestion_de_ventas_bloquea_ventas_y_deja_webhook_y_qr(client_por_peticion, db_session, mundo):
    client = client_por_peticion
    b = mundo["b"]
    _, pago_qr = iniciar_pago(client, b, metodo="qr_online")  # antes de apagar: el dinero ya está en camino
    _apagar(db_session, "basico", gestion_ventas=False)

    cliente, admin = b["cliente"], b["admin"]
    for respuesta in (
        client.get("/api/v1/carrito", headers=cliente),
        client.post("/api/v1/carrito", json={"variante_id": b["variante_id"], "cantidad": 1}, headers=cliente),
        client.post("/api/v1/ventas/digital", json={"sucursal_id": b["sucursal_id"]}, headers=cliente),
        client.get("/api/v1/ventas/mis-compras", headers=cliente),
        client.post("/api/v1/devoluciones", json={}, headers=admin),
        client.get("/api/v1/promociones", headers=admin),
        client.post("/api/v1/pagos/iniciar", json={"venta_id": 1, "metodo_pago": "libelula"}, headers=cliente),
        client.post("/api/v1/pagos/caja", json={}, headers=admin),
        client.get("/api/v1/envios", headers=admin),
        client.post("/api/v1/zonas-envio", json={"ciudad_id": 1, "nombre": "Z", "tarifa_base": "5"}, headers=admin),
    ):
        assert _es_error_de_plan(respuesta, "gestion_ventas", "basico"), respuesta.text

    # Las zonas de envío se LEEN igual (lectura), y el pago que ya se movió se resuelve:
    # la pantalla QR y su confirmación no tienen sesión ni compuerta.
    assert client.get("/api/v1/zonas-envio", headers=cliente).status_code == 200
    ref = pago_qr["referencia_externa"]
    assert client.get(f"/api/v1/pagos/qr/{ref}").status_code == 200
    assert client.post(f"/api/v1/pagos/qr/{ref}/confirmar").status_code == 200


# ---- el orden de errores ---------------------------------------------------------------------


def test_orden_de_errores_401_suscripcion_plan_permiso_regla_de_negocio(
    client_por_peticion, db_session, dos_empresas, mundo
):
    client = client_por_peticion
    cliente_b = mundo["b"]["cliente"]  # no tiene el permiso de reportes
    cliente_a = mundo["a"]["cliente"]

    # 1. Sin sesión: 401 (antes que cualquier 403).
    assert client.post(REPORTE_VOZ, json={"texto": "x"}).status_code == 401

    # 2. El plan se revisa ANTES que el permiso: un cliente de B recibe el error de plan...
    assert _es_error_de_plan(client.post(REPORTE_VOZ, json={"texto": "x"}, headers=cliente_b), "reportes_ia", "basico")
    # ...y uno de A (plan completo) llega al permiso.
    sin_permiso = client.post(REPORTE_VOZ, json={"texto": "x"}, headers=cliente_a)
    assert sin_permiso.status_code == 403 and "permiso" in sin_permiso.json()["detail"].lower()
    assert sin_permiso.json()["detail"] != "plan_no_incluye_funcionalidad"

    # 3. Con plan y permiso, mandan las reglas de negocio (404 de un id que no existe).
    assert client.put("/api/v1/categorias/99999", json={"nombre": "x"}, headers=dos_empresas.a.headers).status_code == 404

    # 4. La suscripción se revisa ANTES que el plan: B suspendida recibe suscripcion_no_activa
    # aunque su plan tampoco incluya la funcionalidad.
    _suspender(db_session, dos_empresas.b.id)
    suspendida = client.post(REPORTE_VOZ, json={"texto": "x"}, headers=dos_empresas.b.headers)
    assert suspendida.status_code == 403
    assert suspendida.json()["codigo"] == "suscripcion_no_activa"
    assert suspendida.json()["estado"] == "suspendida"


# ---- el mapa de compuertas y su orden --------------------------------------------------------


def _llamadas(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _llamadas(sub)


def _compuertas(ruta: APIRoute) -> set[str]:
    """Las funcionalidades que la ruta exige, leídas de sus dependencias."""
    encontradas = set()
    for llamada in _llamadas(ruta.dependant):
        if getattr(llamada, "__qualname__", "").startswith("exigir_funcionalidad.<locals>"):
            cierre = dict(zip(llamada.__code__.co_freevars, (c.cell_contents for c in llamada.__closure__)))
            encontradas.add(cierre["funcionalidad"])
    return encontradas


def _rutas() -> dict[tuple[str, str], APIRoute]:
    return {
        (metodo, ruta.path): ruta
        for ruta in app.routes
        if isinstance(ruta, APIRoute)
        for metodo in ruta.methods
    }


MAPA = {
    FUNC_GESTION_PRODUCTOS: [
        ("GET", "/api/v1/productos"), ("POST", "/api/v1/productos"), ("PUT", "/api/v1/variantes/{variante_id}"),
        ("DELETE", "/api/v1/imagenes/{imagen_id}"), ("POST", "/api/v1/categorias"), ("PUT", "/api/v1/colores/{color_id}"),
        ("DELETE", "/api/v1/tallas/{talla_id}"), ("POST", "/api/v1/materiales"), ("POST", "/api/v1/temporadas"),
        ("DELETE", "/api/v1/colecciones/{coleccion_id}"), ("GET", "/api/v1/proveedores"),
        ("POST", "/api/v1/proveedores/{proveedor_id}/productos"), ("POST", "/api/v1/ordenes-compra"),
        ("POST", "/api/v1/recepciones"),
    ],
    FUNC_GESTION_VENTAS: [
        ("POST", "/api/v1/ventas/digital"), ("POST", "/api/v1/ventas/presencial"), ("GET", "/api/v1/carrito"),
        ("POST", "/api/v1/devoluciones"), ("GET", "/api/v1/promociones"), ("POST", "/api/v1/promociones"),
        ("POST", "/api/v1/pagos/iniciar"), ("POST", "/api/v1/pagos/caja"), ("GET", "/api/v1/pagos/{pago_id}/estado"),
        ("POST", "/api/v1/pagos/venta/{venta_id}/cancelar"), ("POST", "/api/v1/pagos/{pago_id}/anular"),
        ("POST", "/api/v1/zonas-envio"), ("PUT", "/api/v1/zonas-envio/{zona_id}"), ("DELETE", "/api/v1/zonas-envio/{zona_id}"),
        ("POST", "/api/v1/envios"), ("GET", "/api/v1/envios"), ("PUT", "/api/v1/envios/{envio_id}/estado"),
    ],
    FUNC_RESERVAS: [
        ("POST", "/api/v1/reservas"), ("GET", "/api/v1/reservas/mis-reservas"), ("DELETE", "/api/v1/reservas/{reserva_id}"),
        ("PUT", "/api/v1/reservas/{reserva_id}/preparar"),
    ],
    FUNC_REPORTES_CONVENCIONALES: [("GET", "/api/v1/reportes/ventas"), ("GET", "/api/v1/reportes/dashboard")],
    FUNC_REPORTES_IA: [("POST", "/api/v1/ia/reporte-voz")],
}

SIN_COMPUERTA = [
    ("GET", "/api/v1/categorias"), ("GET", "/api/v1/categorias/{categoria_id}"), ("GET", "/api/v1/tallas"),
    ("GET", "/api/v1/colecciones"), ("GET", "/api/v1/catalogo"), ("GET", "/api/v1/catalogo/buscar"),
    ("GET", "/api/v1/inventario/disponibilidad"), ("GET", "/api/v1/inventario/consolidado"),
    ("GET", "/api/v1/inventario/sucursal/{sucursal_id}"), ("POST", "/api/v1/inventario/movimientos"),
    ("GET", "/api/v1/favoritos"), ("GET", "/api/v1/zonas-envio"), ("GET", "/api/v1/zonas-envio/{zona_id}"),
    ("GET", "/api/v1/clientes/direcciones"),
    # Acepta peticiones sin usuario (también es pública bajo /public/{codigo}): la compuerta exige sesión.
    ("POST", "/api/v1/envios/cotizar"), ("POST", "/api/v1/public/{codigo}/envios/cotizar"),
    # Sin sesión de usuario: el dinero ya se movió o es una tarea de servicio.
    ("POST", "/api/v1/pagos/webhook/{pasarela}"), ("GET", "/api/v1/pagos/qr/{id_transaccion}"),
    ("POST", "/api/v1/pagos/qr/{id_transaccion}/confirmar"), ("POST", "/api/v1/tareas/expirar-reservas"),
    ("POST", "/api/v1/tareas/expirar-ventas-pendientes"),
    # Búsqueda y recomendador: aceptan usuario opcional.
    ("POST", "/api/v1/ia/voz"), ("POST", "/api/v1/ia/recomendaciones"), ("POST", "/api/v1/ia/eventos"),
    ("GET", "/api/v1/public/{codigo}/catalogo"), ("GET", "/api/v1/public/{codigo}/zonas-envio"),
    ("POST", "/api/v1/public/{codigo}/ia/voz"),
]


def test_el_mapa_de_compuertas_y_que_van_antes_del_permiso():
    rutas = _rutas()
    for funcionalidad, lista in MAPA.items():
        for clave in lista:
            assert clave in rutas, f"No existe la ruta {clave}"
            assert _compuertas(rutas[clave]) == {funcionalidad}, f"{clave}: {_compuertas(rutas[clave])}"
    for clave in SIN_COMPUERTA:
        assert clave in rutas, f"No existe la ruta {clave}"
        assert _compuertas(rutas[clave]) == set(), f"{clave} no debería tener compuerta de plan"

    # La compuerta va ANTES de cualquier dependencia de permiso (orden de errores).
    for lista in MAPA.values():
        for clave in lista:
            nombres = [getattr(c, "__qualname__", "") for c in (s.call for s in rutas[clave].dependant.dependencies)]
            compuerta = next(i for i, n in enumerate(nombres) if n.startswith("exigir_funcionalidad.<locals>"))
            permisos = [i for i, n in enumerate(nombres) if n.startswith("require_permission.<locals>")]
            assert all(compuerta < i for i in permisos), f"{clave}: el permiso se evalúa antes que el plan"


def test_las_rutas_de_negocio_no_exentas_declaran_su_compuerta():
    """Una ruta nueva en estos routers queda sin compuerta de plan si se olvida:
    esta prueba lo avisa. La suscripción ya la cubre `get_current_user`."""
    prefijos_compuertados = (
        "/api/v1/productos", "/api/v1/variantes", "/api/v1/imagenes", "/api/v1/proveedores", "/api/v1/ordenes-compra",
        "/api/v1/recepciones", "/api/v1/ventas", "/api/v1/carrito", "/api/v1/devoluciones", "/api/v1/promociones",
        "/api/v1/envios", "/api/v1/reservas", "/api/v1/reportes",
    )
    sin_compuerta = [
        clave
        for clave, ruta in _rutas().items()
        if clave[1].startswith(prefijos_compuertados)
        and clave[1] != "/api/v1/envios/cotizar"  # acepta peticiones sin usuario
        and not _compuertas(ruta)
    ]
    sin_compuerta += [
        clave
        for clave, ruta in _rutas().items()
        if clave[1].startswith("/api/v1/pagos")
        and not clave[1].startswith(("/api/v1/pagos/webhook/", "/api/v1/pagos/qr/"))
        and not _compuertas(ruta)
    ]
    assert sin_compuerta == []


def test_exigir_funcionalidad_con_un_nombre_invalido_lanza_al_importar():
    with pytest.raises(ValueError, match="Funcionalidad desconocida"):
        exigir_funcionalidad("gestion_de_cosas")

"""E08: el paquete de descarga offline (GET /sincronizacion/paquete, /catalogo, /stock y /clientes).

Lo que el personal baja para operar sin conexión: manifiesto (empresa, sucursales autorizadas con horario,
referencias, promociones y reglas), catálogo con precio efectivo y descuento ya calculados (paginado por
clave), stock de UNA sucursal (con modo incremental y solape fijado por el servidor) y datos mínimos de
clientes. Catálogo, stock y clientes llevan ETag (huella del cuerpo sin `generado_en`) y responden 304 con
`If-None-Match`; todo viaja comprimido si es grande. A diferencia del POST del lote, aquí SÍ se responde 403
(plan sin operación offline, suscripción no activa, sin permiso): no hay nada que guardar.

Las fechas de `stock.actualizado_en` se fijan directamente en la base (SQLite las escribe con resolución de
segundo): nada de `sleep`."""

import datetime as dt
import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.catalogo.models import Producto, ProductoVariante, Stock
from app.core.tenant import empresa_de, en_empresa, fijar_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.models import Cliente, Permiso, Plan, Rol, Sucursal, Suscripcion, Usuario, rol_permiso
from app.sincronizacion import politicas
from app.sincronizacion.schemas import PaqueteCatalogo, PaqueteClientes, PaqueteStock
from tests.conftest import crear_superadmin_de_prueba
from tests.sincronizacion.ayudas import API, STOCK_V1, STOCK_V2, armar_reserva, construir_escenario, enviar

RUTAS = ("paquete", "paquete/catalogo", "paquete/stock", "paquete/clientes")
RUTAS_CON_ETAG = (
    pytest.param("paquete/catalogo", PaqueteCatalogo, id="catalogo"),
    pytest.param("paquete/stock", PaqueteStock, id="stock"),
    pytest.param("paquete/clientes", PaqueteClientes, id="clientes"),
)
FORMATO_ETAG = re.compile(r'^"[0-9a-f]{16}"$')
FORMATO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
CACHE_CONTROL = "private, max-age=0, must-revalidate"
AYER = hoy_utc() - dt.timedelta(days=1)  # UTC, como la aplicación

SUSCRIPCION_NO_ACTIVA = [
    pytest.param({"fecha_inicio": AYER - dt.timedelta(days=30), "fecha_vencimiento": AYER}, id="vencida-por-fecha"),
    pytest.param({"estado": "suspendida"}, id="suspendida"),
    pytest.param({"estado": "cancelada"}, id="cancelada"),
]


# ---- ayudas ---------------------------------------------------------------------------------------------


def _get(client, headers, ruta, **params):
    return client.get(f"{API}/{ruta}", params=params, headers=headers)


def _ok(respuesta) -> dict:
    assert respuesta.status_code == 200, f"{respuesta.status_code} {respuesta.text}"
    return respuesta.json()


def _post(client, headers, ruta, cuerpo) -> dict:
    respuesta = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=headers)
    assert respuesta.status_code in (200, 201), f"{ruta}: {respuesta.status_code} {respuesta.text}"
    return respuesta.json()


def _ahora() -> dt.datetime:
    """UTC sin zona, como se guarda `stock.actualizado_en`."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _iso_z(instante: dt.datetime) -> str:
    return instante.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sin_hora(cuerpo: dict) -> dict:
    return {clave: valor for clave, valor in cuerpo.items() if clave != "generado_en"}


def _ids_activos(db) -> list[int]:
    db.expire_all()
    return list(db.scalars(select(Producto.id).where(Producto.activo.is_(True)).order_by(Producto.id)))


def _crear_productos(db, escenario, cantidad: int, *, prefijo: str, variantes: int = 1, precio: str = "50.00") -> list[int]:
    """`cantidad` productos activos (cada uno con `variantes` variantes, 1 o 2) directo en la base. Sin
    stock en ninguna sucursal. Devuelve sus ids."""
    primera, segunda = db.get(ProductoVariante, escenario.v1), db.get(ProductoVariante, escenario.v2)
    categoria_id = db.get(Producto, escenario.producto_id).categoria_id
    tallas = [primera.talla_id, segunda.talla_id][:variantes]
    productos = []
    for n in range(cantidad):
        codigo = f"{prefijo}-{n:04d}"
        producto = Producto(codigo=codigo, nombre=f"Producto {codigo}", categoria_id=categoria_id, precio_base=Decimal(precio))
        producto.variantes = [
            ProductoVariante(talla_id=talla, color_id=primera.color_id, sku=f"{codigo}-{k}") for k, talla in enumerate(tallas)
        ]
        productos.append(producto)
    db.add_all(productos)
    db.commit()
    return [producto.id for producto in productos]


def _producto_api(client, db, escenario, codigo: str, *, categoria_id=None, temporada_id=None, precio="100.00") -> int:
    """Un producto por la API con una sola variante (la talla y el color de `v1`). Con `categoria_id` None
    crea una categoría propia: así una promoción de categoría no alcanza a otros productos de la prueba."""
    admin = escenario.admin
    if categoria_id is None:
        categoria_id = _post(client, admin, "categorias", {"nombre": f"Cat {codigo}"})["id"]
    base = db.get(ProductoVariante, escenario.v1)
    cuerpo = {
        "codigo": codigo,
        "nombre": f"Prod {codigo}",
        "categoria_id": categoria_id,
        "precio_base": precio,
        "tallas_ids": [base.talla_id],
        "colores_ids": [base.color_id],
    }
    if temporada_id is not None:
        cuerpo["temporada_id"] = temporada_id
    return _post(client, admin, "productos", cuerpo)["id"]


def _promocion(client, escenario, nombre: str, tipo: str, valor: str, alcance: dict, *, inicio: int = -1, fin: int = 1) -> dict:
    """Una promoción con `inicio` y `fin` en días respecto de hoy (por defecto: vigente, de ayer a mañana)."""
    hoy = hoy_utc()
    return _post(
        client,
        escenario.admin,
        "promociones",
        {
            "nombre": nombre,
            "tipo": tipo,
            "valor": valor,
            "fecha_inicio": (hoy + dt.timedelta(days=inicio)).isoformat(),
            "fecha_fin": (hoy + dt.timedelta(days=fin)).isoformat(),
            "alcances": [alcance],
        },
    )


def _de_producto(client, headers, producto_id: int) -> dict:
    """El item del catálogo descargado de UN producto (página de 1 posicionada justo antes)."""
    cuerpo = _ok(_get(client, headers, "paquete/catalogo", desde_id=producto_id - 1, limite=1))
    assert [item["id"] for item in cuerpo["items"]] == [producto_id]
    return cuerpo["items"][0]


def _segunda_sucursal(client, headers, *, sufijo: str = "2", stock_v1: int | None = None, v1: int | None = None) -> int:
    ciudad = _post(client, headers, "ciudades", {"nombre": f"Potosi paq{sufijo}", "departamento": "Potosi"})
    sucursal = _post(
        client,
        headers,
        "sucursales",
        {"ciudad_id": ciudad["id"], "codigo": f"SUC-PAQ{sufijo}", "nombre": f"Sucursal paq{sufijo}", "direccion": "Av. 2"},
    )
    if stock_v1 is not None:
        _post(
            client,
            headers,
            "inventario/movimientos",
            {
                "variante_id": v1,
                "sucursal_id": sucursal["id"],
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": stock_v1,
                "costo_unitario": "40.00",
            },
        )
    return sucursal["id"]


def _fijar_actualizado_en(db, sucursal_id: int, variante_id: int, instante: dt.datetime) -> None:
    fila = db.scalar(select(Stock).where(Stock.sucursal_id == sucursal_id, Stock.variante_id == variante_id))
    assert fila is not None
    fila.actualizado_en = instante
    db.commit()


def _paginas(client, headers, ruta: str, cursor: str, **params) -> list[dict]:
    """Recorre el recurso de página en página siguiendo `siguiente_<cursor>` hasta que sea nulo."""
    paginas, desde = [], 0
    while len(paginas) < 100:
        cuerpo = _ok(_get(client, headers, ruta, **{cursor: desde}, **params))
        paginas.append(cuerpo)
        desde = cuerpo[f"siguiente_{cursor}"]
        if desde is None:
            return paginas
    raise AssertionError("la paginación no termina")


def _apagar_offline(db, plan: str = "profesional") -> None:
    fila = db.scalar(select(Plan).where(Plan.codigo == plan))
    fila.operacion_offline = False
    db.commit()


def _cambiar_suscripcion(db, empresa_id: int, **campos) -> None:
    with en_empresa(db, empresa_id):
        suscripcion = db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
        for campo, valor in campos.items():
            setattr(suscripcion, campo, valor)
    db.commit()


def _headers_de_superadmin(client, db) -> dict:
    crear_superadmin_de_prueba(db, "super@plataforma.example.com", "claveSegura123")
    respuesta = client.post(
        "/api/v1/auth/login", json={"email": "super@plataforma.example.com", "password": "claveSegura123"}
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


# ---- manifiesto -------------------------------------------------------------------------------------------


def test_el_manifiesto_trae_la_empresa_el_contrato_la_marca_de_tiempo_en_utc_y_el_aviso_de_12_horas(
    client, escenario
):
    antes = dt.datetime.now(dt.timezone.utc)
    cuerpo = _ok(_get(client, escenario.cajero, "paquete"))
    despues = dt.datetime.now(dt.timezone.utc)

    assert cuerpo["version_contrato"] == "1.0"
    assert cuerpo["aviso_desactualizado_horas"] == 12
    assert cuerpo["empresa"]["codigo"] == "fashionstore" and cuerpo["empresa"]["nombre"] == "FashionStore"
    assert isinstance(cuerpo["empresa"]["id"], int)
    assert FORMATO_UTC.match(cuerpo["generado_en"]), cuerpo["generado_en"]
    generado = dt.datetime.fromisoformat(cuerpo["generado_en"])
    assert antes - dt.timedelta(seconds=2) <= generado <= despues + dt.timedelta(seconds=2)


def test_el_cajero_y_el_encargado_ven_solo_su_sucursal_con_sus_horarios(client, db_session, escenario):
    _segunda_sucursal(client, escenario.admin)  # existe otra activa en la empresa: no debe aparecer

    for headers in (escenario.cajero, escenario.encargado):
        cuerpo = _ok(_get(client, headers, "paquete"))

        assert [s["id"] for s in cuerpo["sucursales"]] == [escenario.sucursal_id]
        sucursal = cuerpo["sucursales"][0]
        assert (sucursal["codigo"], sucursal["nombre"], sucursal["direccion"]) == ("SUC-SYNC", "Sucursal sync", "Av. 1")
        assert sucursal["es_deposito"] is False
        assert sucursal["horarios"] == [
            {"dia_semana": dia, "hora_apertura": "08:00", "hora_cierre": "20:00"} for dia in range(1, 8)
        ]


def test_el_administrador_ve_todas_las_sucursales_activas_y_no_las_dadas_de_baja(client, db_session, escenario):
    otra = _segunda_sucursal(client, escenario.admin, sufijo="2")
    baja = _segunda_sucursal(client, escenario.admin, sufijo="3")
    db_session.get(Sucursal, baja).activo = False
    db_session.commit()
    esperadas = set(db_session.scalars(select(Sucursal.id).where(Sucursal.activo.is_(True))))
    assert {escenario.sucursal_id, otra} <= esperadas and baja not in esperadas

    cuerpo = _ok(_get(client, escenario.admin, "paquete"))

    ids = [s["id"] for s in cuerpo["sucursales"]]
    assert set(ids) == esperadas and len(ids) == len(esperadas)
    assert baja not in ids
    por_id = {s["id"]: s for s in cuerpo["sucursales"]}
    assert len(por_id[escenario.sucursal_id]["horarios"]) == 7
    assert por_id[otra]["horarios"] == []  # sin horarios cargados: lista vacía, no error


def test_el_manifiesto_con_sucursal_id_trae_solo_esa_la_ajena_es_403_y_la_inexistente_404(client, db_session, escenario):
    otra = _segunda_sucursal(client, escenario.admin)

    propia = _ok(_get(client, escenario.cajero, "paquete", sucursal_id=escenario.sucursal_id))
    elegida = _ok(_get(client, escenario.admin, "paquete", sucursal_id=otra))
    ajena = _get(client, escenario.cajero, "paquete", sucursal_id=otra)
    inexistente = _get(client, escenario.admin, "paquete", sucursal_id=999999)

    assert [s["id"] for s in propia["sucursales"]] == [escenario.sucursal_id]
    assert [s["id"] for s in elegida["sucursales"]] == [otra]
    assert ajena.status_code == 403, ajena.text
    assert inexistente.status_code == 404, inexistente.text


def test_las_reglas_del_manifiesto_traen_el_plazo_de_24_horas_y_el_propio_de_la_empresa_cuando_lo_define(
    client, escenario
):
    por_defecto = _ok(_get(client, escenario.cajero, "paquete"))["reglas"]

    assert por_defecto == {
        "metodos_pago_offline": ["efectivo"],
        "max_operaciones_por_lote": 50,
        "plazo_cambio_horas": 24,
        "cambios_y_devoluciones": "solo_en_linea",
        "reservas_offline": "las registra el personal",
    }

    cambio = client.put("/api/v1/mi-empresa", json={"plazo_cambio_horas": 48}, headers=escenario.admin)
    assert cambio.status_code == 200, cambio.text
    for headers in (escenario.cajero, escenario.admin):
        assert _ok(_get(client, headers, "paquete"))["reglas"]["plazo_cambio_horas"] == 48


def test_el_manifiesto_trae_la_referencia_y_solo_las_promociones_vigentes_con_sus_alcances(client, escenario):
    _promocion(client, escenario, "Vigente paq", "porcentaje", "10", {"producto_id": escenario.producto_id})
    _promocion(client, escenario, "Vencida paq", "porcentaje", "50", {"producto_id": escenario.producto_id}, inicio=-10, fin=-2)
    _promocion(client, escenario, "Futura paq", "porcentaje", "50", {"producto_id": escenario.producto_id}, inicio=2, fin=9)

    cuerpo = _ok(_get(client, escenario.cajero, "paquete"))

    referencia = cuerpo["referencia"]
    assert "Camisas sync" in [c["nombre"] for c in referencia["categorias"]]
    assert {"S", "M"} <= {t["codigo"] for t in referencia["tallas"]}
    assert "Azul sync" in [c["nombre"] for c in referencia["colores"]]
    por_nombre = {p["nombre"]: p for p in cuerpo["promociones_vigentes"]}
    assert "Vencida paq" not in por_nombre and "Futura paq" not in por_nombre
    vigente = por_nombre["Vigente paq"]
    assert vigente["tipo"] == "porcentaje"
    assert isinstance(vigente["valor"], str) and Decimal(vigente["valor"]) == Decimal("10")
    assert vigente["alcances"] == [{"producto_id": escenario.producto_id, "categoria_id": None, "temporada_id": None}]


# ---- catálogo ---------------------------------------------------------------------------------------------


def test_un_catalogo_de_250_productos_con_limite_100_se_baja_en_3_paginas_sin_repetir_ni_omitir(
    client, db_session, escenario
):
    _crear_productos(db_session, escenario, 250 - len(_ids_activos(db_session)), prefijo="PAG")
    esperados = _ids_activos(db_session)
    assert len(esperados) == 250

    paginas = _paginas(client, escenario.cajero, "paquete/catalogo", "desde_id", limite=100)

    assert len(paginas) == 3
    assert [len(p["items"]) for p in paginas] == [100, 100, 50]
    assert [p["total"] for p in paginas] == [250, 250, 250]
    descargados = [item["id"] for pagina in paginas for item in pagina["items"]]
    assert descargados == esperados  # mismos ids, en orden, sin repetir ni omitir
    assert paginas[0]["siguiente_desde_id"] == paginas[0]["items"][-1]["id"]
    assert paginas[1]["siguiente_desde_id"] == paginas[1]["items"][-1]["id"]
    assert paginas[2]["siguiente_desde_id"] is None


def test_el_catalogo_deja_fuera_los_productos_y_las_variantes_dados_de_baja_y_cuenta_solo_activos(
    client, db_session, escenario
):
    baseline = _ok(_get(client, escenario.cajero, "paquete/catalogo", limite=500))["total"]
    inactivo, mixto = _crear_productos(db_session, escenario, 2, prefijo="BAJA", variantes=2)
    db_session.get(Producto, inactivo).activo = False
    variante_baja = db_session.get(Producto, mixto).variantes[1]
    variante_baja.activo = False
    variante_viva = db_session.get(Producto, mixto).variantes[0]
    db_session.commit()

    cuerpo = _ok(_get(client, escenario.cajero, "paquete/catalogo", limite=500))

    ids = [item["id"] for item in cuerpo["items"]]
    assert inactivo not in ids and mixto in ids
    assert cuerpo["total"] == baseline + 1  # solo el producto activo nuevo
    variantes = {v["id"] for item in cuerpo["items"] if item["id"] == mixto for v in item["variantes"]}
    assert variantes == {variante_viva.id}  # la variante de baja desapareció


def test_el_catalogo_trae_el_precio_efectivo_el_de_la_variante_o_el_del_producto_y_solo_los_campos_publicos(
    client, db_session, escenario
):
    db_session.get(ProductoVariante, escenario.v2).precio = Decimal("120.00")  # v1 hereda el 100.00 del producto
    db_session.commit()

    item = _de_producto(client, escenario.cajero, escenario.producto_id)

    precios = {v["id"]: v["precio"] for v in item["variantes"]}
    assert precios == {escenario.v1: "100.00", escenario.v2: "120.00"}
    assert all(isinstance(v["precio"], str) and v["descuento_unitario"] == "0.00" for v in item["variantes"])
    # Solo lo necesario para vender: ningún costo, margen, descripción ni dato interno.
    assert set(item) == {
        "id", "codigo", "nombre", "categoria_id", "genero", "temporada_id", "imagen_principal", "variantes",
    }
    assert set(item["variantes"][0]) == {"id", "talla_id", "color_id", "sku", "codigo_barras", "precio", "descuento_unitario"}
    assert item["codigo"] == "SYNC-1" and item["genero"] == "unisex" and item["imagen_principal"] is None


def test_el_descuento_unitario_sale_de_la_promocion_por_producto_categoria_o_temporada_y_gana_la_mayor(
    client, db_session, escenario
):
    admin = escenario.admin
    temporada_3 = _post(client, admin, "temporadas", {"nombre": "Verano paq3", "anio": 2026})["id"]
    temporada_4 = _post(client, admin, "temporadas", {"nombre": "Verano paq4", "anio": 2026})["id"]
    por_producto = _producto_api(client, db_session, escenario, "DESC-PROD")
    por_categoria = _producto_api(client, db_session, escenario, "DESC-CAT")
    por_temporada = _producto_api(client, db_session, escenario, "DESC-TEMP", temporada_id=temporada_3)
    sin_promocion = _producto_api(client, db_session, escenario, "DESC-NADA")
    # El cuarto producto cae en tres promociones a la vez: 5.00 (producto), 30.00 (categoría) y 12.00 (temporada).
    mayor = _producto_api(client, db_session, escenario, "DESC-MAYOR", temporada_id=temporada_4)
    categoria_de_mayor = _de_producto(client, escenario.cajero, mayor)["categoria_id"]
    categoria_de_cat = _de_producto(client, escenario.cajero, por_categoria)["categoria_id"]

    _promocion(client, escenario, "Prod 10%", "porcentaje", "10", {"producto_id": por_producto})
    _promocion(client, escenario, "Cat 15", "monto", "15", {"categoria_id": categoria_de_cat})
    _promocion(client, escenario, "Temp 20%", "porcentaje", "20", {"temporada_id": temporada_3})
    _promocion(client, escenario, "Mayor prod", "porcentaje", "5", {"producto_id": mayor})
    _promocion(client, escenario, "Mayor cat", "monto", "30", {"categoria_id": categoria_de_mayor})
    _promocion(client, escenario, "Mayor temp", "porcentaje", "12", {"temporada_id": temporada_4})

    def descuento(producto_id: int) -> str:
        variantes = _de_producto(client, escenario.cajero, producto_id)["variantes"]
        assert len(variantes) == 1 and variantes[0]["precio"] == "100.00"
        return variantes[0]["descuento_unitario"]

    assert descuento(por_producto) == "10.00"
    assert descuento(por_categoria) == "15.00"
    assert descuento(por_temporada) == "20.00"
    assert descuento(mayor) == "30.00"  # la mayor de las tres, no la suma ni la primera
    assert descuento(sin_promocion) == "0.00"


def test_una_promocion_vencida_futura_o_de_otro_producto_no_descuenta(client, db_session, escenario):
    objetivo = _producto_api(client, db_session, escenario, "DESC-OBJ")
    otro = _producto_api(client, db_session, escenario, "DESC-OTRO")
    _promocion(client, escenario, "Vencida", "porcentaje", "50", {"producto_id": objetivo}, inicio=-10, fin=-2)
    _promocion(client, escenario, "Futura", "porcentaje", "50", {"producto_id": objetivo}, inicio=2, fin=9)
    _promocion(client, escenario, "Ajena", "porcentaje", "50", {"producto_id": otro})

    assert _de_producto(client, escenario.cajero, objetivo)["variantes"][0]["descuento_unitario"] == "0.00"
    # Control: la promoción vigente sí aplica a su producto (la prueba no pasa por una ruta mal armada).
    assert _de_producto(client, escenario.cajero, otro)["variantes"][0]["descuento_unitario"] == "50.00"


# ---- stock ------------------------------------------------------------------------------------------------


def test_el_stock_trae_solo_la_sucursal_pedida(client, db_session, escenario):
    otra = _segunda_sucursal(client, escenario.admin, stock_v1=5, v1=escenario.v1)

    de_la_otra = _ok(_get(client, escenario.admin, "paquete/stock", sucursal_id=otra))
    de_la_propia = _ok(_get(client, escenario.admin, "paquete/stock", sucursal_id=escenario.sucursal_id))

    assert de_la_otra["sucursal_id"] == otra
    assert {i["variante_id"]: i["cantidad_disponible"] for i in de_la_otra["items"]} == {escenario.v1: 5}
    assert de_la_propia["sucursal_id"] == escenario.sucursal_id
    assert {i["variante_id"]: i["cantidad_disponible"] for i in de_la_propia["items"]} == {
        escenario.v1: STOCK_V1,
        escenario.v2: STOCK_V2,
    }
    assert FORMATO_UTC.match(de_la_propia["items"][0]["actualizado_en"])


@pytest.mark.parametrize("quien", ["cajero", "encargado"])
def test_el_personal_de_una_sucursal_baja_el_stock_de_la_suya_sin_indicarla(client, escenario, quien):
    cuerpo = _ok(_get(client, getattr(escenario, quien), "paquete/stock"))

    assert cuerpo["sucursal_id"] == escenario.sucursal_id
    assert {i["variante_id"] for i in cuerpo["items"]} == {escenario.v1, escenario.v2}


def test_cantidad_disponible_es_la_fisica_menos_la_reservada_tras_una_reserva(client, db_session, escenario):
    inicial = {i["variante_id"]: i["cantidad_disponible"] for i in _ok(_get(client, escenario.cajero, "paquete/stock"))["items"]}
    assert inicial == {escenario.v1: STOCK_V1, escenario.v2: STOCK_V2}

    resultado = enviar(client, escenario.cajero, [armar_reserva(escenario)]).json()["resultados"][0]
    assert resultado["estado"] == "confirmada", resultado

    db_session.expire_all()
    fila = db_session.scalar(select(Stock).where(Stock.variante_id == escenario.v1, Stock.sucursal_id == escenario.sucursal_id))
    assert (fila.cantidad_fisica, fila.cantidad_reservada) == (STOCK_V1, 1)  # apartada, no descontada
    despues = {i["variante_id"]: i["cantidad_disponible"] for i in _ok(_get(client, escenario.cajero, "paquete/stock"))["items"]}
    assert despues == {escenario.v1: STOCK_V1 - 1, escenario.v2: STOCK_V2}  # 9, no 10


def test_la_primera_descarga_es_completa_y_no_incremental_aunque_las_filas_sean_antiguas(client, db_session, escenario):
    viejo = _ahora() - dt.timedelta(days=30)
    for variante in (escenario.v1, escenario.v2):
        _fijar_actualizado_en(db_session, escenario.sucursal_id, variante, viejo)

    cuerpo = _ok(_get(client, escenario.cajero, "paquete/stock"))

    assert cuerpo["incremental"] is False
    assert {i["variante_id"] for i in cuerpo["items"]} == {escenario.v1, escenario.v2}
    assert cuerpo["siguiente_desde_variante_id"] is None


def test_el_stock_incremental_devuelve_la_fila_dentro_del_solape_de_120_s_y_deja_la_anterior(client, db_session, escenario):
    desde = _ahora().replace(microsecond=0)
    _fijar_actualizado_en(db_session, escenario.sucursal_id, escenario.v1, desde - dt.timedelta(seconds=100))  # dentro del solape
    _fijar_actualizado_en(db_session, escenario.sucursal_id, escenario.v2, desde - dt.timedelta(seconds=200))  # fuera

    cuerpo = _ok(_get(client, escenario.cajero, "paquete/stock", desde=_iso_z(desde)))

    assert cuerpo["incremental"] is True
    assert [i["variante_id"] for i in cuerpo["items"]] == [escenario.v1]
    assert cuerpo["items"][0]["actualizado_en"] == _iso_z(desde - dt.timedelta(seconds=100))


def test_el_stock_incremental_trae_la_fila_tocada_despues_y_acepta_desde_con_otra_zona_horaria(client, db_session, escenario):
    desde = _ahora().replace(microsecond=0)
    _fijar_actualizado_en(db_session, escenario.sucursal_id, escenario.v1, desde - dt.timedelta(seconds=600))
    _fijar_actualizado_en(db_session, escenario.sucursal_id, escenario.v2, desde + dt.timedelta(seconds=30))  # tocada después

    en_utc = _ok(_get(client, escenario.cajero, "paquete/stock", desde=_iso_z(desde)))
    en_bolivia = _ok(
        _get(client, escenario.cajero, "paquete/stock", desde=(desde - dt.timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S-04:00"))
    )

    assert [i["variante_id"] for i in en_utc["items"]] == [escenario.v2]
    assert [i["variante_id"] for i in en_bolivia["items"]] == [escenario.v2]  # el mismo instante, otra zona


def test_una_variante_sin_fila_de_stock_o_dada_de_baja_no_aparece_en_el_stock(client, db_session, escenario):
    (producto_nuevo,) = _crear_productos(db_session, escenario, 1, prefijo="SINSTK")
    variante_sin_fila = db_session.get(Producto, producto_nuevo).variantes[0].id
    assert db_session.scalar(select(Stock.id).where(Stock.variante_id == variante_sin_fila)) is None

    antes = {i["variante_id"] for i in _ok(_get(client, escenario.cajero, "paquete/stock"))["items"]}
    db_session.get(ProductoVariante, escenario.v2).activo = False
    db_session.commit()
    despues = {i["variante_id"] for i in _ok(_get(client, escenario.cajero, "paquete/stock"))["items"]}

    assert antes == {escenario.v1, escenario.v2}  # y la variante sin fila no figura (ni con cantidad 0)
    assert variante_sin_fila not in antes
    assert despues == {escenario.v1}  # la variante de baja desaparece aunque conserve su fila


def test_el_stock_se_pagina_por_variante_con_limite_pequeno(client, escenario):
    paginas = _paginas(client, escenario.cajero, "paquete/stock", "desde_variante_id", limite=1)

    assert len(paginas) == 2
    assert [[i["variante_id"] for i in p["items"]] for p in paginas] == [[escenario.v1], [escenario.v2]]
    assert paginas[0]["siguiente_desde_variante_id"] == escenario.v1
    assert paginas[1]["siguiente_desde_variante_id"] is None


# ---- clientes ---------------------------------------------------------------------------------------------


def _registrar_cliente(client, nombre: str, apellido: str, email: str) -> None:
    respuesta = client.post(
        "/api/v1/public/fashionstore/registro",
        json={"nombre": nombre, "apellido": apellido, "email": email, "password": "claveSegura123"},
    )
    assert respuesta.status_code == 201, respuesta.text


def test_los_clientes_traen_solo_id_nombre_apellido_y_ci_nit(client, db_session, escenario):
    db_session.get(Cliente, escenario.cliente_id).ci_nit = "1234567"
    db_session.commit()

    cuerpo = _ok(_get(client, escenario.cajero, "paquete/clientes", limite=1000))

    item = next(i for i in cuerpo["items"] if i["id"] == escenario.cliente_id)
    assert item == {"id": escenario.cliente_id, "nombre": "Cli", "apellido": "Ente", "ci_nit": "1234567"}
    assert cuerpo["total"] == len(cuerpo["items"]) and cuerpo["siguiente_desde_id"] is None
    assert "cliente@example.com" not in str(cuerpo)  # ni el correo ni otro dato personal


def test_los_clientes_con_usuario_inactivo_no_se_descargan(client, db_session, escenario):
    antes = _ok(_get(client, escenario.cajero, "paquete/clientes", limite=1000))
    assert escenario.cliente_id in [i["id"] for i in antes["items"]]
    db_session.get(Usuario, escenario.cliente_usuario_id).activo = False
    db_session.commit()

    despues = _ok(_get(client, escenario.cajero, "paquete/clientes", limite=1000))

    assert escenario.cliente_id not in [i["id"] for i in despues["items"]]
    assert despues["total"] == antes["total"] - 1


def test_los_clientes_se_paginan_por_clave_con_limite_2(client, escenario):
    for n in range(4):
        _registrar_cliente(client, f"Extra{n}", "Paq", f"extra-paq{n}@example.com")

    paginas = _paginas(client, escenario.cajero, "paquete/clientes", "desde_id", limite=2)

    ids = [item["id"] for pagina in paginas for item in pagina["items"]]
    assert len(paginas) >= 3 and len(ids) == len(set(ids)) == paginas[0]["total"]
    assert ids == sorted(ids)
    assert all(len(p["items"]) <= 2 for p in paginas)
    for pagina in paginas[:-1]:
        assert len(pagina["items"]) == 2 and pagina["siguiente_desde_id"] == pagina["items"][-1]["id"]
    assert paginas[-1]["siguiente_desde_id"] is None


# ---- errores y acceso -------------------------------------------------------------------------------------


def test_pedir_el_stock_de_una_sucursal_ajena_es_403_para_el_personal_de_otra(client, escenario):
    otra = _segunda_sucursal(client, escenario.admin)

    for headers in (escenario.cajero, escenario.encargado):
        assert _get(client, headers, "paquete/stock", sucursal_id=otra).status_code == 403
    # Control: la propia, indicada de forma explícita, sí se atiende.
    assert _get(client, escenario.cajero, "paquete/stock", sucursal_id=escenario.sucursal_id).status_code == 200


def test_el_administrador_debe_indicar_la_sucursal_del_stock_y_una_inexistente_es_404(client, escenario):
    sin_sucursal = _get(client, escenario.admin, "paquete/stock")
    inexistente = _get(client, escenario.admin, "paquete/stock", sucursal_id=999999)
    con_sucursal = _get(client, escenario.admin, "paquete/stock", sucursal_id=escenario.sucursal_id)

    assert sin_sucursal.status_code == 422, sin_sucursal.text
    assert inexistente.status_code == 404, inexistente.text
    assert con_sucursal.status_code == 200, con_sucursal.text


def test_sin_el_permiso_de_operar_las_cuatro_rutas_responden_403(client, db_session, escenario):
    # Se le quita al rol cajero `sincronizacion.operar` (los roles son globales y la base de la prueba es desechable).
    permiso_id = db_session.scalar(select(Permiso.id).where(Permiso.codigo == "sincronizacion.operar"))
    rol_id = db_session.scalar(select(Rol.id).where(Rol.nombre == "cajero"))
    quitados = db_session.execute(
        delete(rol_permiso).where(rol_permiso.c.rol_id == rol_id, rol_permiso.c.permiso_id == permiso_id)
    ).rowcount
    assert quitados == 1
    db_session.commit()

    for ruta in RUTAS:
        assert _get(client, escenario.cajero, ruta).status_code == 403, ruta
        # Control: el encargado conserva el permiso y la misma petición sí funciona.
        assert _get(client, escenario.encargado, ruta).status_code == 200, ruta


def test_un_cliente_de_la_tienda_sin_el_permiso_recibe_403(client, escenario, cliente_headers):
    for ruta in RUTAS:
        assert _get(client, cliente_headers, ruta).status_code == 403, ruta


def test_con_el_plan_sin_operacion_offline_las_cuatro_rutas_responden_403_plan_no_incluye_funcionalidad(
    client, db_session, escenario
):
    for ruta in RUTAS:
        assert _get(client, escenario.cajero, ruta).status_code == 200, ruta  # antes de apagar el plan
    _apagar_offline(db_session)

    for ruta in RUTAS:
        respuesta = _get(client, escenario.cajero, ruta)
        assert respuesta.status_code == 403, f"{ruta}: {respuesta.text}"
        cuerpo = respuesta.json()
        assert cuerpo["detail"] == cuerpo["codigo"] == "plan_no_incluye_funcionalidad", ruta
        assert cuerpo["funcionalidad"] == "operacion_offline" and cuerpo["plan"] == "profesional"


@pytest.mark.parametrize("cambios", SUSCRIPCION_NO_ACTIVA)
def test_con_la_suscripcion_no_activa_las_cuatro_rutas_responden_403_suscripcion_no_activa(
    client, db_session, escenario, cambios
):
    for ruta in RUTAS:
        assert _get(client, escenario.cajero, ruta).status_code == 200, ruta  # antes de cambiar la suscripción
    _cambiar_suscripcion(db_session, empresa_de(db_session), **cambios)

    for ruta in RUTAS:
        respuesta = _get(client, escenario.cajero, ruta)
        assert respuesta.status_code == 403, f"{ruta}: {respuesta.text}"
        cuerpo = respuesta.json()
        assert cuerpo["detail"] == cuerpo["codigo"] == "suscripcion_no_activa", ruta


def test_el_superadministrador_recibe_403_en_las_cuatro_rutas(client, db_session, escenario):
    original = empresa_de(db_session)
    superadmin = _headers_de_superadmin(client, db_session)
    try:
        respuestas = {ruta: _get(client, superadmin, ruta, sucursal_id=escenario.sucursal_id) for ruta in RUTAS}
    finally:
        fijar_empresa(db_session, original)

    assert {ruta: r.status_code for ruta, r in respuestas.items()} == {ruta: 403 for ruta in RUTAS}


def test_sin_token_las_cuatro_rutas_responden_401(client, escenario):
    assert {ruta: client.get(f"{API}/{ruta}").status_code for ruta in RUTAS} == {ruta: 401 for ruta in RUTAS}


# ---- aislamiento entre empresas ---------------------------------------------------------------------------


@pytest.fixture()
def a(client_por_peticion, dos_empresas, db_session):
    return construir_escenario(
        client_por_peticion, dos_empresas.a.headers, db_session, sufijo="-a", codigo_empresa="tienda-a"
    )


@pytest.fixture()
def b(client_por_peticion, dos_empresas, db_session):
    return construir_escenario(
        client_por_peticion, dos_empresas.b.headers, db_session, sufijo="-b", codigo_empresa="tienda-b"
    )


def test_el_paquete_de_una_empresa_no_trae_nada_de_la_otra(client_por_peticion, dos_empresas, a, b):
    client = client_por_peticion
    admin_a = dos_empresas.a.headers

    manifiesto_cajero = _ok(_get(client, a.cajero, "paquete"))
    manifiesto_admin = _ok(_get(client, admin_a, "paquete"))
    catalogo = _ok(_get(client, a.cajero, "paquete/catalogo"))
    stock = _ok(_get(client, a.cajero, "paquete/stock"))
    clientes = _ok(_get(client, a.cajero, "paquete/clientes"))

    assert manifiesto_cajero["empresa"]["codigo"] == "tienda-a"
    assert [s["id"] for s in manifiesto_cajero["sucursales"]] == [a.sucursal_id]
    assert [s["id"] for s in manifiesto_admin["sucursales"]] == [a.sucursal_id]  # el administrador de A no ve la sucursal de B
    assert [i["codigo"] for i in catalogo["items"]] == ["SYNC-1-a"] and catalogo["total"] == 1
    assert {i["variante_id"] for i in stock["items"]} == {a.v1, a.v2}
    assert [i["id"] for i in clientes["items"]] == [a.cliente_id] and clientes["total"] == 1
    for cuerpo in (manifiesto_cajero, manifiesto_admin, catalogo, stock, clientes):
        assert "-b" not in str(cuerpo) and "tienda-b" not in str(cuerpo)  # ningún dato con la marca de B
    # Una sucursal de B se ve igual que una inexistente (404) para el administrador de A; para el cajero, 403.
    assert _get(client, admin_a, "paquete", sucursal_id=b.sucursal_id).status_code == 404
    assert _get(client, admin_a, "paquete/stock", sucursal_id=b.sucursal_id).status_code == 404
    assert _get(client, a.cajero, "paquete/stock", sucursal_id=b.sucursal_id).status_code == 403
    # Control: B (plan Básico, que también incluye operación sin conexión) baja SU paquete, con lo suyo.
    de_b = _ok(_get(client, b.cajero, "paquete/catalogo"))
    assert [i["codigo"] for i in de_b["items"]] == ["SYNC-1-b"]
    assert _ok(_get(client, b.cajero, "paquete"))["empresa"]["codigo"] == "tienda-b"


# ---- ETag, 304, caché y compresión ------------------------------------------------------------------------


@pytest.mark.parametrize("ruta, modelo", RUTAS_CON_ETAG)
def test_el_etag_es_igual_en_dos_llamadas_seguidas_y_es_la_huella_del_cuerpo_sin_la_hora_de_generacion(
    client, escenario, ruta, modelo
):
    primera = _get(client, escenario.cajero, ruta)
    segunda = _get(client, escenario.cajero, ruta)

    assert primera.status_code == segunda.status_code == 200
    etag = primera.headers["etag"]
    assert FORMATO_ETAG.match(etag), etag  # con comillas
    assert segunda.headers["etag"] == etag
    assert primera.headers["cache-control"] == segunda.headers["cache-control"] == CACHE_CONTROL
    # La huella no depende de `generado_en`: con otra hora, el mismo ETag.
    paquete = modelo.model_validate(primera.json())
    otra_hora = paquete.model_copy(update={"generado_en": paquete.generado_en + dt.timedelta(hours=5)})
    assert f'"{politicas.calcular_etag(otra_hora)}"' == etag
    assert _sin_hora(primera.json()) == _sin_hora(segunda.json())


def test_el_etag_del_catalogo_cambia_cuando_cambia_un_precio(client, db_session, escenario):
    antes = _get(client, escenario.cajero, "paquete/catalogo")
    db_session.get(ProductoVariante, escenario.v1).precio = Decimal("111.00")
    db_session.commit()

    despues = _get(client, escenario.cajero, "paquete/catalogo")

    assert despues.headers["etag"] != antes.headers["etag"]
    precios = {v["id"]: v["precio"] for item in despues.json()["items"] if item["id"] == escenario.producto_id for v in item["variantes"]}
    assert precios[escenario.v1] == "111.00"
    # Con el ETag viejo ya no hay 304: el cliente recibe el cuerpo nuevo.
    revalidada = _get(client, {**escenario.cajero, "If-None-Match": antes.headers["etag"]}, "paquete/catalogo")
    assert revalidada.status_code == 200 and revalidada.headers["etag"] == despues.headers["etag"]


def test_el_etag_del_stock_cambia_cuando_cambia_una_cantidad(client, escenario):
    antes = _get(client, escenario.cajero, "paquete/stock")
    _post(
        client,
        escenario.admin,
        "inventario/movimientos",
        {
            "variante_id": escenario.v2,
            "sucursal_id": escenario.sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 2,
            "costo_unitario": "40.00",
        },
    )

    despues = _get(client, escenario.cajero, "paquete/stock")

    assert despues.headers["etag"] != antes.headers["etag"]
    assert {i["variante_id"]: i["cantidad_disponible"] for i in despues.json()["items"]}[escenario.v2] == STOCK_V2 + 2


def test_el_etag_de_los_clientes_cambia_cuando_se_registra_uno_nuevo(client, escenario):
    antes = _get(client, escenario.cajero, "paquete/clientes")
    _registrar_cliente(client, "Nuevo", "Paq", "nuevo-paq@example.com")

    despues = _get(client, escenario.cajero, "paquete/clientes")

    assert despues.headers["etag"] != antes.headers["etag"]
    assert despues.json()["total"] == antes.json()["total"] + 1


@pytest.mark.parametrize("ruta, modelo", RUTAS_CON_ETAG)
def test_con_if_none_match_igual_responde_304_sin_cuerpo_y_con_las_mismas_cabeceras(client, escenario, ruta, modelo):
    completa = _get(client, escenario.cajero, ruta)
    etag = completa.headers["etag"]
    assert completa.status_code == 200 and len(completa.content) > 0

    vigente = _get(client, {**escenario.cajero, "If-None-Match": etag}, ruta)
    otra_version = _get(client, {**escenario.cajero, "If-None-Match": '"0000000000000000"'}, ruta)

    assert vigente.status_code == 304
    assert vigente.content == b""
    assert vigente.headers["etag"] == etag and vigente.headers["cache-control"] == CACHE_CONTROL
    # Con un ETag que no coincide se baja el cuerpo completo (la prueba no pasa por devolver 304 siempre).
    assert otra_version.status_code == 200 and _sin_hora(otra_version.json()) == _sin_hora(completa.json())


def test_el_manifiesto_lleva_cache_control_pero_no_etag_y_no_responde_304(client, escenario):
    primera = _get(client, escenario.cajero, "paquete")
    con_condicional = _get(client, {**escenario.cajero, "If-None-Match": '"cualquiera"'}, "paquete")

    assert primera.status_code == 200
    assert primera.headers["cache-control"] == CACHE_CONTROL
    assert "etag" not in primera.headers
    assert con_condicional.status_code == 200 and "etag" not in con_condicional.headers


def test_un_catalogo_grande_viaja_comprimido_y_su_contenido_es_identico_al_pedido_sin_compresion(
    client, db_session, escenario
):
    _crear_productos(db_session, escenario, 30, prefijo="GZ", variantes=2)

    comprimida = client.get(f"{API}/paquete/catalogo", params={"limite": 500}, headers={**escenario.cajero, "Accept-Encoding": "gzip"})
    plana = client.get(f"{API}/paquete/catalogo", params={"limite": 500}, headers={**escenario.cajero, "Accept-Encoding": "identity"})

    assert comprimida.status_code == plana.status_code == 200
    assert comprimida.headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in plana.headers
    assert len(comprimida.json()["items"]) >= 31
    assert _sin_hora(comprimida.json()) == _sin_hora(plana.json())
    assert comprimida.headers["etag"] == plana.headers["etag"]

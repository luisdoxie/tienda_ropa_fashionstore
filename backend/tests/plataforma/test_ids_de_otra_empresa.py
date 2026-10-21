"""E02, PASO 4: auditoría de los ids que llegan del cliente.

El filtro automático por empresa (core/tenant.py) protege todo id que se LEE,
pero un id que llega en el cuerpo y solo se ESCRIBE como valor de FK no se lee
nunca: la base lo aceptaría aunque apunte a una fila de otra empresa (las FK son
simples). Por eso cada uno se resuelve con una búsqueda filtrada ANTES de
guardarse. Aquí el administrador de la empresa A manda ids que pertenecen a la
empresa B: la respuesta es 404 (igual que un id inexistente) y no se crea ni se
cambia nada. Con ids de su propia empresa, la operación funciona.

Se usan `client_por_peticion` (una sesión nueva y sin empresa por petición, como
producción) y `dos_empresas`. Los datos de cada empresa se siembran por la API con
el token de su administrador."""

import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.catalogo.models import Producto, Proveedor, Recepcion, Stock
from app.comercial.models import Envio, Promocion, Reserva, Venta, ZonaEnvio
from app.comercial.repository import EstadoReservaRepository
from app.core.tenant import empresa_de, fijar_empresa
from app.inteligencia.models import HistorialNavegacion
from app.plataforma.models import Empleado, Sucursal
from app.plataforma.repository import ClienteRepository, UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import token_de

API = "/api/v1"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


@contextmanager
def en_empresa(db, empresa_id):
    """Fija la empresa de `db_session` mientras dura el bloque y la deja como estaba."""
    anterior = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        yield
    finally:
        fijar_empresa(db, anterior)


def contar(db, empresa, modelo, *condiciones) -> int:
    with en_empresa(db, empresa.id):
        return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def crear_via_api(client, ruta, cuerpo, headers):
    respuesta = client.post(f"{API}{ruta}", json=cuerpo, headers=headers)
    assert respuesta.status_code == 201, f"{ruta}: {respuesta.status_code} {respuesta.text}"
    return respuesta.json()


def crear_cliente(db, empresa, nombre) -> SimpleNamespace:
    """Un usuario con rol cliente y su perfil de cliente, dentro de `empresa`."""
    with en_empresa(db, empresa.id):
        repo = UsuarioRepository()
        usuario = repo.crear(
            db,
            UsuarioCrear(
                nombre=nombre, apellido="Cliente", email=f"{nombre}@{empresa.codigo}.example.com", password="claveSegura123"
            ),
        )
        repo.asignar_roles(db, usuario, ["cliente"])
        perfil = ClienteRepository().crear_o_actualizar_perfil(db, usuario.id, None)
        return SimpleNamespace(id=perfil.id, usuario_id=usuario.id, headers=token_de(db, usuario))


def sembrar(client, db, empresa, s) -> SimpleNamespace:
    """Datos de negocio de una empresa (todo por la API con su administrador).
    `s` es un sufijo para que los códigos no se confundan al leer un fallo."""
    h = empresa.headers
    d = SimpleNamespace(empresa=empresa)
    d.ciudad = crear_via_api(client, "/ciudades", {"nombre": f"Ciudad {s}"}, h)["id"]
    d.sucursal = crear_via_api(
        client, "/sucursales", {"ciudad_id": d.ciudad, "codigo": f"SUC-{s}", "nombre": f"Sucursal {s}", "direccion": "Calle 1"}, h
    )["id"]
    d.sucursal_destino = crear_via_api(
        client, "/sucursales", {"ciudad_id": d.ciudad, "codigo": f"SUD-{s}", "nombre": f"Destino {s}", "direccion": "Calle 2"}, h
    )["id"]
    d.categoria = crear_via_api(client, "/categorias", {"nombre": f"Categoria {s}"}, h)["id"]
    d.talla = crear_via_api(client, "/tallas", {"codigo": f"M{s}", "orden": 1}, h)["id"]
    d.color = crear_via_api(client, "/colores", {"nombre": f"Rojo {s}"}, h)["id"]
    d.material = crear_via_api(client, "/materiales", {"nombre": f"Algodon {s}"}, h)["id"]
    d.temporada = crear_via_api(client, "/temporadas", {"nombre": f"Verano {s}", "anio": 2026}, h)["id"]
    d.coleccion = crear_via_api(client, "/colecciones", {"nombre": f"Coleccion {s}"}, h)["id"]
    d.producto = crear_via_api(
        client,
        "/productos",
        {
            "codigo": f"PROD-{s}",
            "nombre": f"Polera {s}",
            "categoria_id": d.categoria,
            "precio_base": "100.00",
            "tallas_ids": [d.talla],
            "colores_ids": [d.color],
        },
        h,
    )["id"]
    variantes = client.get(f"{API}/productos/{d.producto}/variantes", headers=h).json()
    d.variante = variantes[0]["id"]
    d.proveedor = crear_via_api(client, "/proveedores", {"nombre": f"Proveedor {s}"}, h)["id"]
    d.zona = crear_via_api(
        client, "/zonas-envio", {"ciudad_id": d.ciudad, "nombre": f"Zona {s}", "tarifa_base": "10.00"}, h
    )["id"]
    # Un segundo usuario (sin ficha de empleado ni cliente) para vincular a proveedores y empleados.
    d.usuario = crear_via_api(
        client,
        "/usuarios",
        {"nombre": "Otro", "apellido": s, "email": f"otro@{empresa.codigo}.example.com", "password": "claveSegura123"},
        h,
    )["id"]
    # El administrador también es empleado de la sucursal: así puede vender y cobrar.
    crear_via_api(client, "/empleados", {"usuario_id": empresa.admin_id, "sucursal_id": d.sucursal}, h)
    # Stock para vender.
    crear_via_api(client, "/inventario/ajustes", {"variante_id": d.variante, "sucursal_id": d.sucursal, "cantidad": 20}, h)
    d.cliente = crear_cliente(db, empresa, f"cli{s.lower()}")
    d.venta = crear_via_api(
        client, "/ventas/presencial", {"sucursal_id": d.sucursal, "detalle": [{"variante_id": d.variante, "cantidad": 1}]}, h
    )
    d.direccion = crear_via_api(
        client, "/clientes/direcciones", {"zona_envio_id": d.zona, "direccion": f"Av. {s}"}, d.cliente.headers
    )["id"]
    with en_empresa(db, empresa.id):
        estado = EstadoReservaRepository().obtener_por_codigo(db, "pendiente")
        reserva = Reserva(
            codigo=f"RES-{s}",
            cliente_id=d.cliente.id,
            sucursal_id=d.sucursal,
            estado_id=estado.id,
            fecha_visita=dt.date.today(),
            hora_visita_desde=dt.time(9, 0),
            hora_visita_hasta=dt.time(10, 0),
            fecha_expiracion=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2),
        )
        db.add(reserva)
        db.commit()
        d.reserva = reserva.id
    return d


@pytest.fixture()
def mundo(client_por_peticion, dos_empresas, db_session):
    """A y B con datos. Devuelve (client, A, B): los datos de A y de B."""
    a = sembrar(client_por_peticion, db_session, dos_empresas.a, "A")
    b = sembrar(client_por_peticion, db_session, dos_empresas.b, "B")
    return client_por_peticion, a, b


def intentar(client, metodo, ruta, cuerpo, headers):
    return client.request(metodo, f"{API}{ruta}", json=cuerpo, headers=headers)


def es_404(respuesta) -> bool:
    return respuesta.status_code == 404


# ---------------------------------------------------------------------------
# plataforma
# ---------------------------------------------------------------------------


def test_sucursal_crear_con_ciudad_de_otra_empresa_da_404_y_con_la_propia_funciona(mundo, db_session):
    client, a, b = mundo
    antes = contar(db_session, a.empresa, Sucursal)
    cuerpo = {"ciudad_id": b.ciudad, "codigo": "X-1", "nombre": "Nueva", "direccion": "Calle 9"}
    assert es_404(intentar(client, "POST", "/sucursales", cuerpo, a.empresa.headers))
    assert contar(db_session, a.empresa, Sucursal) == antes
    cuerpo["ciudad_id"] = a.ciudad
    assert intentar(client, "POST", "/sucursales", cuerpo, a.empresa.headers).status_code == 201


def test_sucursal_actualizar_con_ciudad_de_otra_empresa_da_404_y_no_cambia_la_ciudad(mundo, db_session):
    client, a, b = mundo
    respuesta = intentar(client, "PUT", f"/sucursales/{a.sucursal}", {"ciudad_id": b.ciudad}, a.empresa.headers)
    assert es_404(respuesta), respuesta.text
    with en_empresa(db_session, a.empresa.id):
        assert db_session.get(Sucursal, a.sucursal).ciudad_id == a.ciudad
    propia = intentar(client, "PUT", f"/sucursales/{a.sucursal}", {"ciudad_id": a.ciudad, "nombre": "Renombrada"}, a.empresa.headers)
    assert propia.status_code == 200 and propia.json()["nombre"] == "Renombrada"


def test_empleado_crear_con_usuario_de_otra_empresa_da_404(mundo, db_session):
    client, a, b = mundo
    antes = contar(db_session, a.empresa, Empleado)
    cuerpo = {"usuario_id": b.usuario, "sucursal_id": a.sucursal}
    assert es_404(intentar(client, "POST", "/empleados", cuerpo, a.empresa.headers))
    assert contar(db_session, a.empresa, Empleado) == antes
    assert intentar(client, "POST", "/empleados", {**cuerpo, "usuario_id": a.usuario}, a.empresa.headers).status_code == 201


def test_empleado_crear_con_sucursal_de_otra_empresa_da_404(mundo, db_session):
    client, a, b = mundo
    antes = contar(db_session, a.empresa, Empleado)
    cuerpo = {"usuario_id": a.usuario, "sucursal_id": b.sucursal}
    assert es_404(intentar(client, "POST", "/empleados", cuerpo, a.empresa.headers))
    assert contar(db_session, a.empresa, Empleado) == antes


def test_empleado_actualizar_con_sucursal_de_otra_empresa_da_404_y_no_cambia(mundo, db_session):
    client, a, b = mundo
    empleado_id = crear_via_api(
        client, "/empleados", {"usuario_id": a.usuario, "sucursal_id": a.sucursal}, a.empresa.headers
    )["id"]
    assert es_404(intentar(client, "PUT", f"/empleados/{empleado_id}", {"sucursal_id": b.sucursal}, a.empresa.headers))
    with en_empresa(db_session, a.empresa.id):
        assert db_session.get(Empleado, empleado_id).sucursal_id == a.sucursal
    propia = intentar(client, "PUT", f"/empleados/{empleado_id}", {"sucursal_id": a.sucursal_destino}, a.empresa.headers)
    assert propia.status_code == 200 and propia.json()["sucursal_id"] == a.sucursal_destino


# ---------------------------------------------------------------------------
# catalogo: maestro y productos
# ---------------------------------------------------------------------------


def test_categoria_con_padre_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    assert es_404(intentar(client, "POST", "/categorias", {"nombre": "Hija", "categoria_padre_id": b.categoria}, h))
    assert es_404(intentar(client, "PUT", f"/categorias/{a.categoria}", {"categoria_padre_id": b.categoria}, h))
    propia = intentar(client, "POST", "/categorias", {"nombre": "Hija", "categoria_padre_id": a.categoria}, h)
    assert propia.status_code == 201 and propia.json()["categoria_padre_id"] == a.categoria


def test_coleccion_con_temporada_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    assert es_404(intentar(client, "POST", "/colecciones", {"nombre": "Nueva", "temporada_id": b.temporada}, h))
    assert es_404(intentar(client, "PUT", f"/colecciones/{a.coleccion}", {"temporada_id": b.temporada}, h))
    propia = intentar(client, "POST", "/colecciones", {"nombre": "Nueva", "temporada_id": a.temporada}, h)
    assert propia.status_code == 201


def _producto_nuevo(a, **cambios):
    cuerpo = {
        "codigo": "PROD-NUEVO",
        "nombre": "Camisa nueva",
        "categoria_id": a.categoria,
        "precio_base": "50.00",
        "tallas_ids": [a.talla],
        "colores_ids": [a.color],
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.parametrize(
    "campo", ["categoria_id", "material_id", "temporada_id", "coleccion_id", "tallas_ids", "colores_ids"]
)
def test_producto_crear_con_referencia_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session, campo):
    client, a, b = mundo
    ajeno = {
        "categoria_id": b.categoria,
        "material_id": b.material,
        "temporada_id": b.temporada,
        "coleccion_id": b.coleccion,
        "tallas_ids": [b.talla],
        "colores_ids": [b.color],
    }[campo]
    antes = contar(db_session, a.empresa, Producto)
    respuesta = intentar(client, "POST", "/productos", _producto_nuevo(a, **{campo: ajeno}), a.empresa.headers)
    assert es_404(respuesta), respuesta.text
    assert contar(db_session, a.empresa, Producto) == antes


def test_producto_crear_con_referencias_propias_funciona(mundo):
    client, a, _b = mundo
    cuerpo = _producto_nuevo(a, material_id=a.material, temporada_id=a.temporada, coleccion_id=a.coleccion)
    respuesta = intentar(client, "POST", "/productos", cuerpo, a.empresa.headers)
    assert respuesta.status_code == 201, respuesta.text


@pytest.mark.parametrize("campo", ["categoria_id", "material_id", "temporada_id", "coleccion_id"])
def test_producto_actualizar_con_referencia_de_otra_empresa_da_404_y_no_cambia(mundo, db_session, campo):
    client, a, b = mundo
    ajeno = {
        "categoria_id": b.categoria,
        "material_id": b.material,
        "temporada_id": b.temporada,
        "coleccion_id": b.coleccion,
    }[campo]
    respuesta = intentar(client, "PUT", f"/productos/{a.producto}", {campo: ajeno}, a.empresa.headers)
    assert es_404(respuesta), respuesta.text
    with en_empresa(db_session, a.empresa.id):
        assert getattr(db_session.get(Producto, a.producto), campo) != ajeno


@pytest.mark.parametrize("campo", ["tallas_ids", "colores_ids"])
def test_generar_variantes_con_talla_o_color_de_otra_empresa_da_404(mundo, campo):
    client, a, b = mundo
    cuerpo = {"tallas_ids": [a.talla], "colores_ids": [a.color]}
    cuerpo[campo] = [b.talla if campo == "tallas_ids" else b.color]
    ruta = f"/productos/{a.producto}/variantes"
    assert es_404(intentar(client, "POST", ruta, cuerpo, a.empresa.headers))
    antes = len(client.get(f"{API}{ruta}", headers=a.empresa.headers).json())
    assert antes == 1  # solo la variante de la siembra


def test_tabla_de_medidas_con_talla_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    ruta = f"/productos/{a.producto}/medidas"
    assert es_404(intentar(client, "POST", ruta, {"talla_id": b.talla}, h))
    medida = intentar(client, "POST", ruta, {"talla_id": a.talla, "pecho_min_cm": "90"}, h)
    assert medida.status_code == 201, medida.text
    assert es_404(intentar(client, "PUT", f"{ruta}/{medida.json()['id']}", {"talla_id": b.talla}, h))
    assert client.get(f"{API}{ruta}", headers=h).json()[0]["talla_id"] == a.talla


def test_favorito_con_variante_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.cliente.headers
    assert es_404(intentar(client, "POST", "/favoritos", {"variante_id": b.variante}, h))
    assert client.get(f"{API}/favoritos", headers=h).json() == []
    assert intentar(client, "POST", "/favoritos", {"variante_id": a.variante}, h).status_code == 201


# ---------------------------------------------------------------------------
# catalogo: inventario
# ---------------------------------------------------------------------------


def _movimiento(a, **cambios):
    cuerpo = {
        "variante_id": a.variante,
        "sucursal_id": a.sucursal,
        "tipo_movimiento_codigo": "ajuste_positivo",
        "cantidad": 3,
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.parametrize("campo", ["variante_id", "sucursal_id"])
def test_movimiento_con_variante_o_sucursal_de_otra_empresa_da_404(mundo, db_session, campo):
    client, a, b = mundo
    antes = contar(db_session, a.empresa, Stock)
    ajeno = b.variante if campo == "variante_id" else b.sucursal
    respuesta = intentar(client, "POST", "/inventario/movimientos", _movimiento(a, **{campo: ajeno}), a.empresa.headers)
    assert es_404(respuesta), respuesta.text
    assert contar(db_session, a.empresa, Stock) == antes  # ni siquiera se creó una fila de stock
    ok = intentar(client, "POST", "/inventario/movimientos", _movimiento(a), a.empresa.headers)
    assert ok.status_code == 201


def test_movimiento_referencia_id_es_un_dato_libre_que_no_se_lee(mundo):
    """`referencia_id` no es FK: se guarda tal cual y nunca se usa para leer otra tabla."""
    client, a, b = mundo
    respuesta = intentar(
        client, "POST", "/inventario/movimientos", _movimiento(a, referencia_tipo="manual", referencia_id=b.venta["id"]), a.empresa.headers
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["referencia_id"] == b.venta["id"]


@pytest.mark.parametrize("campo", ["variante_id", "sucursal_id"])
def test_ajuste_con_variante_o_sucursal_de_otra_empresa_da_404(mundo, db_session, campo):
    client, a, b = mundo
    antes = contar(db_session, a.empresa, Stock)
    cuerpo = {"variante_id": a.variante, "sucursal_id": a.sucursal, "cantidad": 2}
    cuerpo[campo] = b.variante if campo == "variante_id" else b.sucursal
    assert es_404(intentar(client, "POST", "/inventario/ajustes", cuerpo, a.empresa.headers))
    assert contar(db_session, a.empresa, Stock) == antes


@pytest.mark.parametrize("campo", ["origen", "destino", "variante"])
def test_transferencia_con_sucursal_o_variante_de_otra_empresa_da_404(mundo, campo):
    client, a, b = mundo
    h = a.empresa.headers
    cuerpo = {
        "codigo": "TRF-1",
        "sucursal_origen_id": a.sucursal,
        "sucursal_destino_id": a.sucursal_destino,
        "detalle": [{"variante_id": a.variante, "cantidad": 1}],
    }
    if campo == "origen":
        cuerpo["sucursal_origen_id"] = b.sucursal
    elif campo == "destino":
        cuerpo["sucursal_destino_id"] = b.sucursal
    else:
        cuerpo["detalle"] = [{"variante_id": b.variante, "cantidad": 1}]
    assert es_404(intentar(client, "POST", "/transferencias", cuerpo, h))
    assert client.get(f"{API}/transferencias", headers=h).json() == []


def test_transferencia_entre_sucursales_propias_funciona(mundo):
    client, a, _b = mundo
    cuerpo = {
        "codigo": "TRF-OK",
        "sucursal_origen_id": a.sucursal,
        "sucursal_destino_id": a.sucursal_destino,
        "detalle": [{"variante_id": a.variante, "cantidad": 1}],
    }
    assert intentar(client, "POST", "/transferencias", cuerpo, a.empresa.headers).status_code == 201


def test_proveedor_con_usuario_de_otra_empresa_da_404(mundo, db_session):
    client, a, b = mundo
    h = a.empresa.headers
    antes = contar(db_session, a.empresa, Proveedor)
    assert es_404(intentar(client, "POST", "/proveedores", {"nombre": "Nuevo", "usuario_id": b.usuario}, h))
    assert contar(db_session, a.empresa, Proveedor) == antes
    assert es_404(intentar(client, "PUT", f"/proveedores/{a.proveedor}", {"usuario_id": b.usuario}, h))
    with en_empresa(db_session, a.empresa.id):
        assert db_session.get(Proveedor, a.proveedor).usuario_id is None
    propio = intentar(client, "POST", "/proveedores", {"nombre": "Nuevo", "usuario_id": a.usuario}, h)
    assert propio.status_code == 201 and propio.json()["usuario_id"] == a.usuario
    assert intentar(client, "PUT", f"/proveedores/{a.proveedor}", {"usuario_id": a.usuario}, h).status_code == 200


def test_producto_de_proveedor_con_producto_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    ruta = f"/proveedores/{a.proveedor}/productos"
    assert es_404(intentar(client, "POST", ruta, {"producto_id": b.producto}, h))
    assert client.get(f"{API}{ruta}", headers=h).json() == []
    assert intentar(client, "POST", ruta, {"producto_id": a.producto}, h).status_code == 201


def _orden(a, **cambios):
    cuerpo = {
        "codigo": "OC-1",
        "proveedor_id": a.proveedor,
        "sucursal_id": a.sucursal,
        "detalle": [{"variante_id": a.variante, "cantidad": 5, "costo_unitario": "40.00"}],
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.parametrize("campo", ["proveedor_id", "sucursal_id", "variante"])
def test_orden_de_compra_con_id_de_otra_empresa_da_404(mundo, campo):
    client, a, b = mundo
    h = a.empresa.headers
    if campo == "variante":
        cuerpo = _orden(a, detalle=[{"variante_id": b.variante, "cantidad": 5, "costo_unitario": "40.00"}])
    else:
        cuerpo = _orden(a, **{campo: b.proveedor if campo == "proveedor_id" else b.sucursal})
    assert es_404(intentar(client, "POST", "/ordenes-compra", cuerpo, h))
    assert client.get(f"{API}/ordenes-compra", headers=h).json() == []
    assert intentar(client, "POST", "/ordenes-compra", _orden(a), h).status_code == 201


@pytest.mark.parametrize("campo", ["proveedor_id", "sucursal_id", "variante"])
def test_orden_de_compra_actualizar_con_id_de_otra_empresa_da_404_y_no_cambia(mundo, campo):
    client, a, b = mundo
    h = a.empresa.headers
    orden = crear_via_api(client, "/ordenes-compra", _orden(a), h)
    if campo == "variante":
        cambios = {"detalle": [{"variante_id": b.variante, "cantidad": 1, "costo_unitario": "1.00"}]}
    else:
        cambios = {campo: b.proveedor if campo == "proveedor_id" else b.sucursal}
    assert es_404(intentar(client, "PUT", f"/ordenes-compra/{orden['id']}", cambios, h))
    actual = client.get(f"{API}/ordenes-compra/{orden['id']}", headers=h).json()
    assert actual["proveedor_id"] == a.proveedor and actual["sucursal_id"] == a.sucursal
    assert [linea["variante_id"] for linea in actual["detalle"]] == [a.variante]


def _recepcion(a, **cambios):
    cuerpo = {
        "codigo": "REC-1",
        "proveedor_id": a.proveedor,
        "sucursal_id": a.sucursal,
        "detalle": [{"variante_id": a.variante, "cantidad": 4, "costo_unitario": "40.00"}],
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.parametrize("campo", ["orden_compra_id", "proveedor_id", "sucursal_id", "variante"])
def test_recepcion_con_id_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session, campo):
    client, a, b = mundo
    h = a.empresa.headers
    orden_b = crear_via_api(client, "/ordenes-compra", _orden(b), b.empresa.headers)
    client.post(f"{API}/ordenes-compra/{orden_b['id']}/enviar", headers=b.empresa.headers)
    if campo == "variante":
        cuerpo = _recepcion(a, detalle=[{"variante_id": b.variante, "cantidad": 4, "costo_unitario": "40.00"}])
    elif campo == "orden_compra_id":
        cuerpo = _recepcion(a, orden_compra_id=orden_b["id"])
    else:
        cuerpo = _recepcion(a, **{campo: b.proveedor if campo == "proveedor_id" else b.sucursal})
    stock_antes = contar(db_session, a.empresa, Stock)
    assert es_404(intentar(client, "POST", "/recepciones", cuerpo, h))
    assert client.get(f"{API}/recepciones", headers=h).json() == []
    assert contar(db_session, a.empresa, Recepcion) == 0
    assert contar(db_session, a.empresa, Stock) == stock_antes
    assert intentar(client, "POST", "/recepciones", _recepcion(a), h).status_code == 201


def test_recepcion_ignora_el_empleado_id_del_cuerpo(mundo):
    """`empleado_id` está en el esquema pero el caso de uso no lo usa: la recepción
    siempre se guarda con el empleado del servidor (hoy ninguno), nunca con el del cliente."""
    client, a, b = mundo
    empleado_b = client.get(f"{API}/empleados/yo", headers=b.empresa.headers).json()["id"]
    respuesta = intentar(client, "POST", "/recepciones", _recepcion(a, empleado_id=empleado_b), a.empresa.headers)
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["empleado_id"] is None


# Parámetros de consulta que se usan solo como filtro de lectura.


def test_sucursal_de_otra_empresa_como_filtro_da_404_en_inventario_y_reportes(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    for ruta in (
        "/inventario/consolidado",
        "/inventario/alertas",
        "/inventario/valuacion",
        "/transferencias",
        "/reportes/ventas",
        "/reportes/inventario",
        "/reportes/reservas",
        "/reportes/dashboard",
    ):
        assert es_404(client.get(f"{API}{ruta}", params={"sucursal_id": b.sucursal}, headers=h)), ruta
        if ruta in ("/reportes/ventas", "/reportes/dashboard"):
            continue  # leen la vista vw_ventas_detalle, que solo existe en PostgreSQL
        assert client.get(f"{API}{ruta}", params={"sucursal_id": a.sucursal}, headers=h).status_code == 200, ruta


def test_filtros_de_lectura_con_ids_de_otra_empresa_no_devuelven_nada(mundo):
    """Variante, producto, categoría, talla, color, material y temporada ajenos como
    filtros de lectura: no se escriben en ninguna parte y el filtro de empresa los
    deja sin resultados (igual que un id inexistente)."""
    client, a, b = mundo
    h = a.empresa.headers
    for filtro in ("categoria_id", "talla_id", "color_id", "material_id", "temporada_id"):
        ajeno = getattr(b, filtro[:-3])
        respuesta = client.get(f"{API}/catalogo/buscar", params={filtro: ajeno}, headers=h)
        assert respuesta.status_code == 200 and respuesta.json() == [], filtro
    assert client.get(f"{API}/inventario/consolidado", params={"producto_id": b.producto}, headers=h).json() == []
    assert es_404(client.get(f"{API}/inventario/disponibilidad", params={"variante_id": b.variante}, headers=h))
    assert es_404(client.get(f"{API}/inventario/sucursal/{b.sucursal}", headers=h))


# ---------------------------------------------------------------------------
# comercial
# ---------------------------------------------------------------------------


def _reserva(a, **cambios):
    cuerpo = {
        "sucursal_id": a.sucursal,
        "fecha_visita": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
        "hora_visita_desde": "10:00:00",
        "hora_visita_hasta": "11:00:00",
        "detalle": [{"variante_id": a.variante, "cantidad": 1}],
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.parametrize("campo", ["sucursal_id", "variante"])
def test_reserva_con_sucursal_o_variante_de_otra_empresa_da_404(mundo, db_session, campo):
    client, a, b = mundo
    # La franja horaria se valida antes que las variantes: la sucursal necesita horario.
    visita = dt.date.today() + dt.timedelta(days=1)
    crear_via_api(
        client,
        f"/sucursales/{a.sucursal}/horarios",
        {"dia_semana": visita.isoweekday(), "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        a.empresa.headers,
    )
    antes = contar(db_session, a.empresa, Reserva)
    if campo == "variante":
        cuerpo = _reserva(a, detalle=[{"variante_id": b.variante, "cantidad": 1}])
    else:
        cuerpo = _reserva(a, sucursal_id=b.sucursal)
    assert es_404(intentar(client, "POST", "/reservas", cuerpo, a.cliente.headers))
    assert contar(db_session, a.empresa, Reserva) == antes
    assert intentar(client, "POST", "/reservas", _reserva(a), a.cliente.headers).status_code == 201


def test_seleccion_de_reserva_con_variante_de_otra_empresa_da_404(mundo, db_session):
    """SeleccionLinea.variante_id se busca entre las líneas de la propia reserva."""
    client, a, b = mundo
    with en_empresa(db_session, a.empresa.id):
        en_prueba = EstadoReservaRepository().obtener_por_codigo(db_session, "en_prueba")
        db_session.get(Reserva, a.reserva).estado_id = en_prueba.id
        db_session.commit()
    respuesta = intentar(
        client, "PUT", f"/reservas/{a.reserva}/seleccion", {"lineas": [{"variante_id": b.variante, "seleccionada": True}]}, a.empresa.headers
    )
    assert es_404(respuesta)


def test_carrito_con_variante_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.cliente.headers
    assert es_404(intentar(client, "POST", "/carrito", {"variante_id": b.variante, "cantidad": 1}, h))
    assert client.get(f"{API}/carrito", headers=h).json()["detalle"] == []
    assert intentar(client, "POST", "/carrito", {"variante_id": a.variante, "cantidad": 1}, h).status_code == 201


@pytest.mark.parametrize("campo", ["producto_id", "categoria_id", "temporada_id"])
def test_promocion_con_alcance_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session, campo):
    client, a, b = mundo
    h = a.empresa.headers
    ajeno = {"producto_id": b.producto, "categoria_id": b.categoria, "temporada_id": b.temporada}[campo]
    propio = {"producto_id": a.producto, "categoria_id": a.categoria, "temporada_id": a.temporada}[campo]
    hoy = dt.date.today()
    cuerpo = {
        "nombre": "Oferta",
        "tipo": "porcentaje",
        "valor": "10",
        "fecha_inicio": hoy.isoformat(),
        "fecha_fin": (hoy + dt.timedelta(days=5)).isoformat(),
        "alcances": [{campo: ajeno}],
    }
    antes = contar(db_session, a.empresa, Promocion)
    assert es_404(intentar(client, "POST", "/promociones", cuerpo, h))
    assert contar(db_session, a.empresa, Promocion) == antes
    cuerpo["alcances"] = [{campo: propio}]
    assert intentar(client, "POST", "/promociones", cuerpo, h).status_code == 201


@pytest.mark.parametrize("campo", ["sucursal_id", "variante", "reserva_id", "cliente_id"])
def test_venta_presencial_con_id_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session, campo):
    client, a, b = mundo
    h = a.empresa.headers
    cuerpo = {"sucursal_id": a.sucursal, "detalle": [{"variante_id": a.variante, "cantidad": 1}]}
    if campo == "sucursal_id":
        cuerpo["sucursal_id"] = b.sucursal
    elif campo == "variante":
        cuerpo["detalle"] = [{"variante_id": b.variante, "cantidad": 1}]
    elif campo == "reserva_id":
        cuerpo["reserva_id"] = b.reserva
    else:
        cuerpo["cliente_id"] = b.cliente.id
    ventas_antes = contar(db_session, a.empresa, Venta)
    respuesta = intentar(client, "POST", "/ventas/presencial", cuerpo, h)
    assert es_404(respuesta), respuesta.text
    assert contar(db_session, a.empresa, Venta) == ventas_antes
    cuerpo_propio = {
        "sucursal_id": a.sucursal,
        "detalle": [{"variante_id": a.variante, "cantidad": 1}],
        "cliente_id": a.cliente.id,
    }
    assert intentar(client, "POST", "/ventas/presencial", cuerpo_propio, h).status_code == 201


def test_venta_digital_ignora_el_reserva_id_del_cuerpo_y_rechaza_la_sucursal_ajena(mundo):
    client, a, b = mundo
    h = a.cliente.headers
    assert intentar(client, "POST", "/carrito", {"variante_id": a.variante, "cantidad": 1}, h).status_code == 201
    assert es_404(intentar(client, "POST", "/ventas/digital", {"sucursal_id": b.sucursal}, h))
    # El 404 no vació el carrito.
    assert len(client.get(f"{API}/carrito", headers=h).json()["detalle"]) == 1
    propia = intentar(client, "POST", "/ventas/digital", {"sucursal_id": a.sucursal, "reserva_id": b.reserva}, h)
    assert propia.status_code == 201, propia.text
    assert propia.json()["reserva_id"] is None


def test_devolucion_con_venta_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    cuerpo = {"venta_id": b.venta["id"], "detalle": [{"venta_detalle_id": b.venta["detalle"][0]["id"], "cantidad": 1}]}
    assert es_404(intentar(client, "POST", "/devoluciones", cuerpo, a.empresa.headers))


def test_devolucion_con_linea_de_venta_de_otra_empresa_da_404(mundo):
    """Una línea de venta de B dentro de una devolución de una venta de A no se encuentra."""
    client, a, b = mundo
    h = a.empresa.headers
    pago = intentar(client, "POST", "/pagos/caja", {"venta_id": a.venta["id"], "metodo_pago": "efectivo", "monto_recibido": "500"}, h)
    assert pago.status_code == 201, pago.text
    cuerpo = {"venta_id": a.venta["id"], "detalle": [{"venta_detalle_id": b.venta["detalle"][0]["id"], "cantidad": 1}]}
    assert es_404(intentar(client, "POST", "/devoluciones", cuerpo, h))
    propia = {"venta_id": a.venta["id"], "detalle": [{"venta_detalle_id": a.venta["detalle"][0]["id"], "cantidad": 1}]}
    assert intentar(client, "POST", "/devoluciones", propia, h).status_code == 201


def test_pagos_con_venta_de_otra_empresa_dan_404(mundo):
    client, a, b = mundo
    h = a.empresa.headers
    caja = {"venta_id": b.venta["id"], "metodo_pago": "efectivo", "monto_recibido": "500"}
    assert es_404(intentar(client, "POST", "/pagos/caja", caja, h))
    iniciar = {"venta_id": b.venta["id"], "metodo_pago": "libelula"}
    assert es_404(intentar(client, "POST", "/pagos/iniciar", iniciar, h))
    # La venta de B sigue pendiente de pago: A no pudo cobrarla.
    assert client.get(f"{API}/ventas/{b.venta['id']}/comprobante", headers=b.empresa.headers).json()["estado"] == "pendiente_pago"
    caja_propia = {**caja, "venta_id": a.venta["id"]}
    assert intentar(client, "POST", "/pagos/caja", caja_propia, h).status_code == 201


def test_zona_de_envio_con_ciudad_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session):
    client, a, b = mundo
    h = a.empresa.headers
    antes = contar(db_session, a.empresa, ZonaEnvio)
    cuerpo = {"ciudad_id": b.ciudad, "nombre": "Zona nueva", "tarifa_base": "5.00"}
    assert es_404(intentar(client, "POST", "/zonas-envio", cuerpo, h))
    assert contar(db_session, a.empresa, ZonaEnvio) == antes
    assert intentar(client, "POST", "/zonas-envio", {**cuerpo, "ciudad_id": a.ciudad}, h).status_code == 201


def test_direccion_con_zona_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    h = a.cliente.headers
    ruta = "/clientes/direcciones"
    assert es_404(intentar(client, "POST", ruta, {"zona_envio_id": b.zona, "direccion": "Calle 5"}, h))
    assert es_404(intentar(client, "PUT", f"{ruta}/{a.direccion}", {"zona_envio_id": b.zona}, h))
    guardada = client.get(f"{API}{ruta}", headers=h).json()
    assert [d["zona_envio_id"] for d in guardada] == [a.zona]
    assert intentar(client, "POST", ruta, {"zona_envio_id": a.zona, "direccion": "Calle 5"}, h).status_code == 201


def test_cotizar_envio_con_direccion_de_otra_empresa_da_404(mundo):
    client, a, b = mundo
    assert es_404(intentar(client, "POST", "/envios/cotizar", {"direccion_id": b.direccion, "cantidad_prendas": 1}, a.cliente.headers))
    propia = intentar(client, "POST", "/envios/cotizar", {"direccion_id": a.direccion, "cantidad_prendas": 1}, a.cliente.headers)
    assert propia.status_code == 200


def test_envio_con_venta_o_direccion_de_otra_empresa_da_404_y_no_crea_nada(mundo, db_session):
    client, a, b = mundo
    h = a.empresa.headers
    assert es_404(intentar(client, "POST", "/envios", {"venta_id": b.venta["id"], "direccion_id": a.direccion}, h))
    assert es_404(intentar(client, "POST", "/envios", {"venta_id": a.venta["id"], "direccion_id": b.direccion}, h))
    assert contar(db_session, a.empresa, Envio) == 0


# ---------------------------------------------------------------------------
# inteligencia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("campo", ["producto_id", "variante_id"])
def test_evento_con_producto_o_variante_de_otra_empresa_da_404_y_no_guarda_nada(mundo, db_session, campo):
    client, a, b = mundo
    h = a.cliente.headers
    ajeno = b.producto if campo == "producto_id" else b.variante
    respuesta = intentar(client, "POST", "/ia/eventos", {"tipo_evento": "vista", campo: ajeno}, h)
    assert es_404(respuesta), respuesta.text
    assert contar(db_session, a.empresa, HistorialNavegacion) == 0
    propio = a.producto if campo == "producto_id" else a.variante
    assert intentar(client, "POST", "/ia/eventos", {"tipo_evento": "vista", campo: propio}, h).status_code == 201
    assert contar(db_session, a.empresa, HistorialNavegacion) == 1


def test_evento_con_ids_inexistentes_tambien_da_404(mundo):
    client, a, _b = mundo
    assert es_404(intentar(client, "POST", "/ia/eventos", {"tipo_evento": "vista", "producto_id": 999999}, a.cliente.headers))
    assert es_404(intentar(client, "POST", "/ia/eventos", {"tipo_evento": "vista", "variante_id": 999999}, a.cliente.headers))

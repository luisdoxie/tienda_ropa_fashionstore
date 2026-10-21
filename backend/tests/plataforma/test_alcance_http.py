"""E02: el aislamiento entre empresas visto desde HTTP, como en producción
(una sesión nueva y sin empresa por petición; la empresa sale del token).

Cada empresa tiene filas propias de los 10 recursos de la prueba rápida
(producto, variante, sucursal, usuario, empleado, reserva, venta, pago,
proveedor, orden de compra). El administrador de A nunca debe ver, cambiar ni
borrar las de B: responde 404, igual que un id inexistente. La matriz
exhaustiva de todas las rutas es de la etapa E05."""

import datetime as dt

import pytest
from sqlalchemy import event, select

from app.catalogo.models import Categoria, Color, OrdenCompra, Producto, ProductoVariante, Proveedor, Talla
from app.comercial.models import EstadoPago, EstadoReserva, EstadoVenta, MetodoPago, Pago, Reserva, Venta
from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma.models import Ciudad, Cliente, Empleado, Sucursal, Usuario

RECURSOS = ("producto", "variante", "sucursal", "usuario", "empleado", "reserva", "venta", "pago", "proveedor", "orden")


def _sembrar(db, empresa_id: int, clave: str) -> dict[str, int]:
    """Una fila de cada uno de los 10 recursos dentro de `empresa_id`. El
    código de producto es el mismo en las dos empresas a propósito."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    ciudad = Ciudad(nombre=f"Ciudad {clave}")
    categoria = Categoria(nombre=f"Cat {clave}")
    talla, color = Talla(codigo="M"), Color(nombre="Negro")
    db.add_all([ciudad, categoria, talla, color])
    db.flush()
    sucursal = Sucursal(ciudad_id=ciudad.id, codigo=f"SUC-{clave}", nombre=f"Sucursal {clave}", direccion="Calle 1")
    usuario = Usuario(nombre="Per", apellido=clave, email=f"persona-{clave}@example.com", password_hash="x")
    producto = Producto(codigo="PROD-1", nombre=f"Producto {clave}", categoria_id=categoria.id, precio_base=100)
    proveedor = Proveedor(nombre=f"Proveedor {clave}")
    db.add_all([sucursal, usuario, producto, proveedor])
    db.flush()
    variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=f"SKU-{clave}")
    empleado = Empleado(usuario_id=usuario.id, sucursal_id=sucursal.id, cargo="Cajero")
    cliente = Cliente(usuario_id=usuario.id)
    orden = OrdenCompra(codigo=f"OC-{clave}", proveedor_id=proveedor.id, sucursal_id=sucursal.id)
    venta = Venta(codigo=f"V-{clave}", canal="digital", sucursal_id=sucursal.id, estado_id=db.scalar(select(EstadoVenta.id)))
    db.add_all([variante, empleado, cliente, orden, venta])
    db.flush()
    ahora = dt.datetime.now()
    reserva = Reserva(
        codigo=f"R-{clave}",
        cliente_id=cliente.id,
        sucursal_id=sucursal.id,
        estado_id=db.scalar(select(EstadoReserva.id)),
        fecha_visita=ahora.date(),
        hora_visita_desde=dt.time(10, 0),
        hora_visita_hasta=dt.time(11, 0),
        fecha_expiracion=ahora + dt.timedelta(days=1),
    )
    pago = Pago(
        venta_id=venta.id,
        metodo_pago_id=db.scalar(select(MetodoPago.id)),
        estado_id=db.scalar(select(EstadoPago.id)),
        monto=10,
    )
    db.add_all([reserva, pago])
    db.commit()
    ids = {
        "producto": producto.id,
        "variante": variante.id,
        "sucursal": sucursal.id,
        "usuario": usuario.id,
        "empleado": empleado.id,
        "reserva": reserva.id,
        "venta": venta.id,
        "pago": pago.id,
        "proveedor": proveedor.id,
        "orden": orden.id,
    }
    fijar_empresa(db, original)
    return ids


@pytest.fixture()
def datos(db_session, dos_empresas):
    return {
        "a": _sembrar(db_session, dos_empresas.a.id, "a"),
        "b": _sembrar(db_session, dos_empresas.b.id, "b"),
    }


# (recurso, método, ruta con {id}). Una operación de lectura, de cambio y de
# borrado de cada recurso, donde la API la ofrece.
OPERACIONES = [
    ("producto", "GET", "/productos/{id}"),
    ("producto", "PUT", "/productos/{id}"),
    ("producto", "DELETE", "/productos/{id}"),
    ("variante", "PUT", "/variantes/{id}"),
    ("variante", "DELETE", "/variantes/{id}"),
    ("sucursal", "GET", "/sucursales/{id}"),
    ("sucursal", "PUT", "/sucursales/{id}"),
    ("sucursal", "DELETE", "/sucursales/{id}"),
    ("usuario", "GET", "/usuarios/{id}"),
    ("usuario", "PUT", "/usuarios/{id}"),
    ("usuario", "DELETE", "/usuarios/{id}"),
    ("empleado", "GET", "/empleados/{id}"),
    ("empleado", "PUT", "/empleados/{id}"),
    ("empleado", "DELETE", "/empleados/{id}"),
    ("reserva", "GET", "/reservas/{id}"),
    ("reserva", "PUT", "/reservas/{id}/preparar"),
    ("reserva", "DELETE", "/reservas/{id}"),
    ("venta", "GET", "/ventas/{id}/comprobante"),
    ("pago", "GET", "/pagos/{id}/estado"),
    ("pago", "POST", "/pagos/{id}/anular"),
    ("proveedor", "GET", "/proveedores/{id}"),
    ("proveedor", "PUT", "/proveedores/{id}"),
    ("proveedor", "DELETE", "/proveedores/{id}"),
    ("orden", "GET", "/ordenes-compra/{id}"),
    ("orden", "PUT", "/ordenes-compra/{id}"),
    ("orden", "DELETE", "/ordenes-compra/{id}"),
]


def _llamar(client, metodo: str, ruta: str, headers: dict):
    cuerpo = {} if metodo in ("PUT", "POST") else None
    return client.request(metodo, f"/api/v1{ruta}", headers=headers, json=cuerpo)


@pytest.mark.parametrize("recurso,metodo,ruta", OPERACIONES, ids=[f"{r}-{m}" for r, m, _ in OPERACIONES])
def test_un_recurso_de_otra_empresa_responde_404(client_por_peticion, dos_empresas, datos, recurso, metodo, ruta):
    """El administrador de B opera sobre SU recurso (control: no es 404) y el
    de A, con el id del recurso de B, recibe 404."""
    id_de_b = datos["b"][recurso]

    propia = _llamar(client_por_peticion, metodo, ruta.format(id=id_de_b), dos_empresas.b.headers)
    assert propia.status_code != 404, f"el control falló ({propia.status_code}): {propia.text}"

    ajena = _llamar(client_por_peticion, metodo, ruta.format(id=id_de_b), dos_empresas.a.headers)
    assert ajena.status_code == 404, f"A pudo tocar el {recurso} de B: {ajena.status_code} {ajena.text}"


def test_el_recurso_ajeno_responde_igual_que_uno_inexistente(client_por_peticion, dos_empresas, datos):
    """No se filtra que el id existe en otra empresa: mismo estado y mismo
    cuerpo que un id que no existe en ninguna."""
    ajeno = client_por_peticion.get(f"/api/v1/productos/{datos['b']['producto']}", headers=dos_empresas.a.headers)
    inexistente = client_por_peticion.get("/api/v1/productos/999999", headers=dos_empresas.a.headers)
    assert ajeno.status_code == inexistente.status_code == 404
    assert ajeno.json() == inexistente.json()


LISTADOS = [
    ("producto", "/productos"),
    ("sucursal", "/sucursales"),
    ("usuario", "/usuarios"),
    ("empleado", "/empleados"),
    ("proveedor", "/proveedores"),
    ("orden", "/ordenes-compra"),
]


@pytest.mark.parametrize("recurso,ruta", LISTADOS, ids=[r for r, _ in LISTADOS])
def test_los_listados_no_mezclan_empresas(client_por_peticion, dos_empresas, datos, recurso, ruta):
    for propia, ajena in (("a", "b"), ("b", "a")):
        respuesta = client_por_peticion.get(f"/api/v1{ruta}?tamanio=100", headers=getattr(dos_empresas, propia).headers)
        assert respuesta.status_code == 200, respuesta.text
        ids = {fila["id"] for fila in respuesta.json()}
        assert datos[propia][recurso] in ids
        assert datos[ajena][recurso] not in ids


def test_la_empresa_del_cuerpo_la_query_y_la_cabecera_se_ignora(client_por_peticion, dos_empresas, db_session):
    """Crear como A mandando la empresa de B por todos los medios: la fila
    queda en A (la empresa sale solo del token)."""
    b = dos_empresas.b.id
    respuesta = client_por_peticion.post(
        f"/api/v1/ciudades?empresa_id={b}",
        json={"nombre": "Ciudad colada", "empresa_id": b},
        headers={**dos_empresas.a.headers, "X-Empresa-Id": str(b), "X-Empresa": "tienda-b"},
    )
    assert respuesta.status_code == 201, respuesta.text

    fijar_empresa(db_session, dos_empresas.a.id)
    assert db_session.scalar(select(Ciudad.empresa_id).where(Ciudad.id == respuesta.json()["id"])) == dos_empresas.a.id
    fijar_empresa(db_session, b)
    assert db_session.scalar(select(Ciudad.id).where(Ciudad.nombre == "Ciudad colada")) is None


def test_lo_creado_por_un_administrador_es_invisible_para_el_otro(client_por_peticion, dos_empresas):
    creada = client_por_peticion.post("/api/v1/ciudades", json={"nombre": "Solo de A"}, headers=dos_empresas.a.headers)
    assert creada.status_code == 201, creada.text
    id_ = creada.json()["id"]

    assert client_por_peticion.get(f"/api/v1/ciudades/{id_}", headers=dos_empresas.a.headers).status_code == 200
    assert client_por_peticion.get(f"/api/v1/ciudades/{id_}", headers=dos_empresas.b.headers).status_code == 404
    nombres_de_b = [c["nombre"] for c in client_por_peticion.get("/api/v1/ciudades", headers=dos_empresas.b.headers).json()]
    assert "Solo de A" not in nombres_de_b


def test_una_ruta_de_datos_sin_token_responde_401(client_por_peticion, dos_empresas, datos):
    """Sin token no hay empresa: la consulta falla cerrado y la API responde
    401 (nunca 500 ni datos)."""
    for ruta in ("/productos", "/sucursales", "/catalogo", "/categorias", "/zonas-envio"):
        respuesta = client_por_peticion.get(f"/api/v1{ruta}")
        assert respuesta.status_code == 401, (ruta, respuesta.status_code, respuesta.text)


def test_sql_con_empresa(client_por_peticion, dos_empresas, datos, db_session, capsys):
    """El SQL que ejecuta un listado lleva el predicado `empresa_id`."""
    sentencias: list[str] = []

    def espiar(conexion, cursor, statement, parametros, contexto, executemany):
        if "FROM producto " in statement or "FROM producto\n" in statement:
            sentencias.append(statement)

    motor = db_session.get_bind()
    event.listen(motor, "before_cursor_execute", espiar)
    try:
        respuesta = client_por_peticion.get("/api/v1/productos", headers=dos_empresas.a.headers)
    finally:
        event.remove(motor, "before_cursor_execute", espiar)

    assert respuesta.status_code == 200
    assert sentencias, "no se capturó el SELECT de productos"
    assert all("producto.empresa_id = ?" in s for s in sentencias), sentencias
    with capsys.disabled():
        print("\nSQL del listado de productos:\n", sentencias[0].strip())


def test_demo_dos_empresas(client_por_peticion, dos_empresas, db_session, capsys):
    """Para la prueba manual (correr con -s): lo que ve cada empresa."""
    for clave, cantidad in (("a", 3), ("b", 2)):
        empresa = getattr(dos_empresas, clave)
        for i in range(cantidad):
            respuesta = client_por_peticion.post(
                "/api/v1/ciudades", json={"nombre": f"Demo {clave} {i}"}, headers=empresa.headers
            )
            assert respuesta.status_code == 201, respuesta.text

    def ciudades(headers):
        filas = client_por_peticion.get("/api/v1/ciudades?tamanio=100", headers=headers).json()
        return sorted(c["nombre"] for c in filas if c["nombre"].startswith("Demo"))

    ve_a, ve_b = ciudades(dos_empresas.a.headers), ciudades(dos_empresas.b.headers)
    id_de_b = client_por_peticion.get("/api/v1/ciudades?tamanio=100", headers=dos_empresas.b.headers).json()[0]["id"]
    con_a = client_por_peticion.get(f"/api/v1/ciudades/{id_de_b}", headers=dos_empresas.a.headers).status_code
    con_b = client_por_peticion.get(f"/api/v1/ciudades/{id_de_b}", headers=dos_empresas.b.headers).status_code
    with capsys.disabled():
        print(f"\nA ve {len(ve_a)} ciudades y B ve {len(ve_b)}")
        print(f"GET de un recurso de B con el token de A -> {con_a}; con el token de B -> {con_b}")
    assert (len(ve_a), len(ve_b)) == (3, 2)
    assert (con_a, con_b) == (404, 200)

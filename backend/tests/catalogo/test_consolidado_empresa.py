"""E02 (multitenant), PASO 3.2: las consultas SQL en texto sobre la vista
`vw_inventario_consolidado` (consolidado, alertas y valuación) no pasan por el
filtro del ORM; `condicion_empresa` las acota. Con dos empresas, cada una ve
SOLO su inventario, tanto por el repositorio como por la API (una sesión
nueva por petición, como en producción).

Aquí vive también `sembrar_negocio`, el sembrador de datos de una empresa que
reutilizan las pruebas de reportes y de códigos de las dos empresas."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalogo import repository as catalogo_repository
from app.catalogo.models import Categoria, Color, Producto, ProductoVariante, Stock, Talla
from app.comercial.models import EstadoReserva, EstadoVenta, Reserva, Venta, VentaDetalle
from app.core.exceptions import DomainError
from app.core.tenant import EmpresaNoDefinidaError, empresa_de, fijar_empresa
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import RegistrarCliente
from app.plataforma.models import Ciudad, Sucursal
from app.plataforma.schemas import RegistroRequest


def sembrar_negocio(
    db,
    empresa_id: int,
    sufijo: str,
    *,
    fisica: int = 10,
    minimo: int = 0,
    costo: str = "10.0000",
    venta_cantidad: int = 0,
    reservas: int = 0,
) -> dict:
    """Ciudad, sucursal, categoría, producto, variante y stock de UNA empresa
    (más una venta pagada de `venta_cantidad` unidades a 100.00 y `reservas`
    reservas pendientes, si se piden). Los nombres llevan el `sufijo`
    ('Sucursal A', 'Producto A'...). Devuelve ids y nombres y deja la empresa
    de la sesión como estaba."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    ciudad = Ciudad(nombre=f"Ciudad {sufijo}", departamento="Santa Cruz")
    categoria = Categoria(nombre=f"Categoria {sufijo}")
    talla = Talla(codigo="M")
    color = Color(nombre="Negro")
    db.add_all([ciudad, categoria, talla, color])
    db.flush()
    sucursal = Sucursal(ciudad_id=ciudad.id, codigo=f"S-{sufijo}", nombre=f"Sucursal {sufijo}", direccion="Calle 1")
    producto = Producto(
        codigo=f"P-{sufijo}", nombre=f"Producto {sufijo}", categoria_id=categoria.id, precio_base=Decimal("100.00")
    )
    db.add_all([sucursal, producto])
    db.flush()
    variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=f"SKU-{sufijo}")
    db.add(variante)
    db.flush()
    db.add(
        Stock(
            variante_id=variante.id,
            sucursal_id=sucursal.id,
            cantidad_fisica=fisica,
            cantidad_reservada=0,
            stock_minimo=minimo,
            costo_promedio=Decimal(costo),
        )
    )
    datos = {
        "empresa_id": empresa_id,
        "sucursal_id": sucursal.id,
        "sucursal": f"Sucursal {sufijo}",
        "producto_id": producto.id,
        "producto": f"Producto {sufijo}",
        "variante_id": variante.id,
        "categoria_id": categoria.id,
        "venta": None,
    }
    if venta_cantidad:
        estado = db.scalar(select(EstadoVenta).where(EstadoVenta.codigo == "pagada"))
        venta = Venta(
            codigo=f"V-{sufijo}",
            canal="digital",
            sucursal_id=sucursal.id,
            estado_id=estado.id,
            subtotal=Decimal("100.00") * venta_cantidad,
            total=Decimal("100.00") * venta_cantidad,
        )
        db.add(venta)
        db.flush()
        db.add(
            VentaDetalle(
                venta_id=venta.id,
                variante_id=variante.id,
                cantidad=venta_cantidad,
                precio_unitario=Decimal("100.00"),
                costo_unitario=Decimal(costo),
                subtotal=Decimal("100.00") * venta_cantidad,
            )
        )
        datos["venta"] = f"V-{sufijo}"
    if reservas:
        usuario = RegistrarCliente().registrar(
            db,
            RegistroRequest(
                nombre="Cli", apellido=sufijo, email=f"cliente@{sufijo.lower()}.example.com", password="claveSegura123"
            ),
        )
        cliente_id = usuario.cliente.id
        pendiente = db.scalar(select(EstadoReserva).where(EstadoReserva.codigo == "pendiente"))
        hoy = dt.date.today()
        for n in range(reservas):
            db.add(
                Reserva(
                    codigo=f"RES-{sufijo}{n}",
                    cliente_id=cliente_id,
                    sucursal_id=sucursal.id,
                    estado_id=pendiente.id,
                    fecha_visita=hoy,
                    hora_visita_desde=dt.time(10, 0),
                    hora_visita_hasta=dt.time(11, 0),
                    fecha_expiracion=dt.datetime.now() + dt.timedelta(days=1),
                )
            )
    db.commit()
    fijar_empresa(db, original)
    return datos


@pytest.fixture()
def inventarios(db_session, dos_empresas):
    """A: stock 10, mínimo 2 (sin alerta), costo 10 -> valor 100.
    B: stock 3, mínimo 5 (en alerta), costo 20 -> valor 60."""
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A", fisica=10, minimo=2, costo="10.0000")
    b = sembrar_negocio(db_session, dos_empresas.b.id, "B", fisica=3, minimo=5, costo="20.0000")
    return a, b


# ---- Por el repositorio (sesión con la empresa fijada) ------------------------------------


def test_consolidado_cada_empresa_ve_solo_su_inventario(db_session, dos_empresas, inventarios):
    a, b = inventarios
    for datos, otro in ((a, b), (b, a)):
        fijar_empresa(db_session, datos["empresa_id"])
        filas = catalogo_repository.consolidado(db_session)
        assert [fila["sucursal"] for fila in filas] == [datos["sucursal"]]
        assert [fila["producto"] for fila in filas] == [datos["producto"]]
        assert {fila["empresa_id"] for fila in filas} == {datos["empresa_id"]}
        assert otro["producto"] not in {fila["producto"] for fila in filas}
        # El filtro por sucursal ajena no devuelve nada: tampoco se cuela por ahí.
        assert catalogo_repository.consolidado(db_session, sucursal_id=otro["sucursal_id"]) == []
        assert catalogo_repository.consolidado(db_session, producto_id=otro["producto_id"]) == []


def test_alertas_cada_empresa_ve_solo_las_suyas(db_session, dos_empresas, inventarios):
    a, b = inventarios
    fijar_empresa(db_session, a["empresa_id"])
    assert catalogo_repository.alertas(db_session) == []  # 10 > 2: A no tiene alertas

    fijar_empresa(db_session, b["empresa_id"])
    alertas = catalogo_repository.alertas(db_session)
    assert [fila["sucursal"] for fila in alertas] == [b["sucursal"]]
    assert alertas[0]["cantidad_disponible"] == 3
    assert catalogo_repository.alertas(db_session, sucursal_id=a["sucursal_id"]) == []


def test_valuacion_cada_empresa_suma_solo_lo_suyo(db_session, dos_empresas, inventarios):
    a, b = inventarios
    fijar_empresa(db_session, a["empresa_id"])
    valuacion_a = catalogo_repository.valuacion(db_session)
    assert [(fila["sucursal"], Decimal(str(fila["valor_total"]))) for fila in valuacion_a] == [
        (a["sucursal"], Decimal("100"))
    ]

    fijar_empresa(db_session, b["empresa_id"])
    valuacion_b = catalogo_repository.valuacion(db_session)
    assert [(fila["sucursal"], Decimal(str(fila["valor_total"]))) for fila in valuacion_b] == [
        (b["sucursal"], Decimal("60"))
    ]
    assert catalogo_repository.valuacion(db_session, sucursal_id=a["sucursal_id"]) == []


def test_las_consultas_en_texto_fallan_cerrado_sin_empresa(db_session):
    fijar_empresa(db_session, None)
    for consulta in (
        catalogo_repository.consolidado,
        catalogo_repository.alertas,
        catalogo_repository.valuacion,
    ):
        with pytest.raises(EmpresaNoDefinidaError):
            consulta(db_session)
    assert issubclass(EmpresaNoDefinidaError, DomainError)


# ---- Por la API (una sesión nueva por petición) -------------------------------------------


def test_api_inventario_consolidado_alertas_y_valuacion_por_empresa(client_por_peticion, dos_empresas, inventarios):
    a, b = inventarios
    for empresa, datos in ((dos_empresas.a, a), (dos_empresas.b, b)):
        consolidado = client_por_peticion.get("/api/v1/inventario/consolidado", headers=empresa.headers)
        assert consolidado.status_code == 200, consolidado.text
        assert [fila["sucursal"] for fila in consolidado.json()] == [datos["sucursal"]]

        valuacion = client_por_peticion.get("/api/v1/inventario/valuacion", headers=empresa.headers)
        assert valuacion.status_code == 200, valuacion.text
        assert [fila["sucursal"] for fila in valuacion.json()] == [datos["sucursal"]]

    alertas_a = client_por_peticion.get("/api/v1/inventario/alertas", headers=dos_empresas.a.headers)
    alertas_b = client_por_peticion.get("/api/v1/inventario/alertas", headers=dos_empresas.b.headers)
    assert alertas_a.json() == []
    assert [fila["sucursal"] for fila in alertas_b.json()] == [b["sucursal"]]

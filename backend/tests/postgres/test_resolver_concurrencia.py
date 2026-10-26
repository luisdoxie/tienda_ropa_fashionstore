"""E08 en PostgreSQL real: resolver conflictos de sincronización a la vez. Cada resolución corre en
su propio hilo con su propia sesión (su propia transacción), como dos encargados que pulsan el botón
al mismo tiempo.

Lo que se demuestra: dos encargados que FUERZAN la misma operación dejan UNA venta y UN ajuste (el
segundo espera a que el primero termine y devuelve lo guardado); forzar contra rechazar a la vez da un
ganador y un 409, con un estado final coherente; y forzar mientras otros lotes venden la misma
variante no se bloquea y el stock nunca queda negativo ni descuadrado del kardex."""

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Stock
from app.comercial.models import Venta
from app.core.exceptions import ConflictoError
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from app.sincronizacion.casos_uso.cu25_sincronizar_operaciones_offline import ProcesarLote, ResolverConflicto
from app.sincronizacion.models import OperacionSync
from app.sincronizacion.schemas import LoteEntrada, ResolverEntrada

from .conftest import CLAVE
from .paralelo import ejecutar_en_paralelo


def _empleado(client_pg, fabrica_pg, admin_pg, sucursal_id: int, rol: str, correo: str) -> int:
    """Un empleado de la sucursal con ese rol (el id del usuario)."""
    with fabrica_pg() as db:
        repo = UsuarioRepository()
        usuario = repo.crear(db, UsuarioCrear(nombre=rol[:5], apellido="Res", email=correo, password=CLAVE))
        repo.asignar_roles(db, usuario, [rol])
        usuario_id = usuario.id
    respuesta = client_pg.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario_id, "sucursal_id": sucursal_id, "cargo": rol},
        headers=admin_pg,
    )
    assert respuesta.status_code == 201, respuesta.text
    return usuario_id


def _operacion(sucursal_id: int, variante_id: int, cantidad: int, *, minutos: int = 10) -> dict:
    """Venta de contado a 100.00 por unidad, pagada justa."""
    total = cantidad * 100
    instante = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutos)
    return {
        "operacion_id": str(uuid.uuid4()),
        "tipo": "venta_contado",
        "sucursal_id": sucursal_id,
        "fecha_operacion": instante.isoformat(timespec="seconds"),
        "payload": {
            "cliente_id": None,
            "lineas": [
                {"variante_id": variante_id, "cantidad": cantidad, "precio_unitario": "100.00", "descuento_unitario": "0.00"}
            ],
            "total": f"{total}.00",
            "pago": {"metodo": "efectivo", "monto_recibido": f"{total}.00"},
        },
    }


def _enviar(usuario_id: int, operaciones: list[dict]):
    lote = LoteEntrada.model_validate({"version_contrato": "1.0", "operaciones": operaciones})
    return lambda db: ProcesarLote().ejecutar(db, usuario_id, lote)


def _resolver(usuario_id: int, operacion: dict, accion: str, motivo: str | None = None):
    datos = ResolverEntrada(accion=accion, motivo=motivo)
    return lambda db: ResolverConflicto().ejecutar(db, usuario_id, uuid.UUID(operacion["operacion_id"]), datos)


def _preparar(client_pg, fabrica_pg, admin_pg, escenario, faltan: int = 2):
    """(sucursal, variante, cajero, encargado_1, encargado_2, operación en conflicto que pide `faltan` más de las 10 que hay)."""
    sucursal_id, variante = escenario["sucursal_id"], escenario["variantes"][0]
    cajero = _empleado(client_pg, fabrica_pg, admin_pg, sucursal_id, "cajero", "cajero-res@example.com")
    encargado_1 = _empleado(client_pg, fabrica_pg, admin_pg, sucursal_id, "encargado_sucursal", "enc1-res@example.com")
    encargado_2 = _empleado(client_pg, fabrica_pg, admin_pg, sucursal_id, "encargado_sucursal", "enc2-res@example.com")
    operacion = _operacion(sucursal_id, variante, 10 + faltan)
    with fabrica_pg() as db:
        resultado = ProcesarLote().ejecutar(
            db, cajero, LoteEntrada.model_validate({"version_contrato": "1.0", "operaciones": [operacion]})
        )
    assert resultado.resultados[0].estado == "en_conflicto", resultado
    return sucursal_id, variante, cajero, encargado_1, encargado_2, operacion


def _contar(fabrica, modelo, *condiciones) -> int:
    with fabrica() as db:
        return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def _ajustes(fabrica) -> int:
    return _contar(fabrica, MovimientoInventario, MovimientoInventario.referencia_tipo == "sync_forzada")


def _stock(fabrica, variante_id: int, sucursal_id: int) -> tuple[int, int]:
    with fabrica() as db:
        fila = db.execute(
            select(Stock.cantidad_fisica, Stock.cantidad_reservada).where(
                Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id
            )
        ).one()
        return fila.cantidad_fisica, fila.cantidad_reservada


def _estado(fabrica, operacion: dict) -> str:
    with fabrica() as db:
        return db.scalar(
            select(OperacionSync.estado).where(OperacionSync.operacion_id == uuid.UUID(operacion["operacion_id"]))
        )


# ---- dos encargados forzando lo mismo -----------------------------------------------------------


def test_dos_encargados_que_fuerzan_a_la_vez_dejan_una_venta_y_un_ajuste(client_pg, fabrica_pg, admin_pg, escenario):
    sucursal_id, variante, _cajero, enc_1, enc_2, operacion = _preparar(client_pg, fabrica_pg, admin_pg, escenario)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [_resolver(enc_1, operacion, "forzar"), _resolver(enc_2, operacion, "forzar")]
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]  # ambos responden 200
    assert [r.valor.estado for r in resultados] == ["confirmada", "confirmada"]
    assert len({r.valor.recurso.id for r in resultados}) == 1  # la MISMA venta
    assert _contar(fabrica_pg, Venta) == 1
    assert _ajustes(fabrica_pg) == 1  # un solo ajuste positivo
    assert _stock(fabrica_pg, variante, sucursal_id) == (0, 0)  # 10 + 2 de ajuste - 12 vendidas
    with fabrica_pg() as db:
        resolucion = db.scalar(select(OperacionSync.resultado)).get("resolucion")
    assert resolucion["accion"] == "forzar" and resolucion["por_usuario_id"] in (enc_1, enc_2)


def test_seis_encargados_que_fuerzan_a_la_vez_dejan_una_sola_venta(client_pg, fabrica_pg, admin_pg, escenario):
    sucursal_id, variante, _cajero, enc_1, _enc_2, operacion = _preparar(client_pg, fabrica_pg, admin_pg, escenario)

    resultados = ejecutar_en_paralelo(fabrica_pg, [_resolver(enc_1, operacion, "forzar") for _ in range(6)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    assert _contar(fabrica_pg, Venta) == 1 and _ajustes(fabrica_pg) == 1
    assert _stock(fabrica_pg, variante, sucursal_id) == (0, 0)


# ---- forzar contra rechazar -------------------------------------------------------------------------


def test_forzar_y_rechazar_a_la_vez_dejan_un_ganador_y_un_409_con_estado_coherente(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id, variante, _cajero, enc_1, enc_2, operacion = _preparar(client_pg, fabrica_pg, admin_pg, escenario)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [_resolver(enc_1, operacion, "forzar"), _resolver(enc_2, operacion, "rechazar", "No había la prenda")]
    )

    forzar, rechazar = resultados
    assert forzar.ok != rechazar.ok  # exactamente UNA gana
    perdedora = rechazar if forzar.ok else forzar
    assert isinstance(perdedora.error, ConflictoError), perdedora.error  # la otra, 409

    estado = _estado(fabrica_pg, operacion)
    if forzar.ok:
        assert estado == "confirmada"
        assert _contar(fabrica_pg, Venta) == 1 and _ajustes(fabrica_pg) == 1
        assert _stock(fabrica_pg, variante, sucursal_id) == (0, 0)
    else:
        assert estado == "rechazada"
        assert _contar(fabrica_pg, Venta) == 0 and _ajustes(fabrica_pg) == 0
        assert _stock(fabrica_pg, variante, sucursal_id) == (10, 0)  # el rechazo no toca el stock


# ---- forzar mientras otros venden ---------------------------------------------------------------------


def test_forzar_mientras_otros_lotes_venden_la_misma_variante_no_se_bloquea_y_el_stock_no_baja_de_cero(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id, variante, cajero, enc_1, _enc_2, operacion = _preparar(client_pg, fabrica_pg, admin_pg, escenario, faltan=2)

    for _ronda in range(2):
        pedidos = [_resolver(enc_1, operacion, "forzar")] + [
            _enviar(cajero, [_operacion(sucursal_id, variante, 1, minutos=5)]) for _ in range(4)
        ]
        resultados = ejecutar_en_paralelo(fabrica_pg, pedidos)
        assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]  # sin deadlock

    fisico, reservado = _stock(fabrica_pg, variante, sucursal_id)
    assert fisico >= 0 and reservado == 0
    # El kardex cuadra con la fila de stock: el saldo es la suma de sus movimientos.
    with fabrica_pg() as db:
        movimientos = list(
            db.scalars(
                select(MovimientoInventario.cantidad)
                .where(MovimientoInventario.variante_id == variante, MovimientoInventario.sucursal_id == sucursal_id)
                .order_by(MovimientoInventario.id)
            )
        )
        saldos = list(
            db.scalars(
                select(MovimientoInventario.saldo_post)
                .where(MovimientoInventario.variante_id == variante, MovimientoInventario.sucursal_id == sucursal_id)
                .order_by(MovimientoInventario.id)
            )
        )
    assert sum(movimientos) == fisico
    assert min(saldos) >= 0  # ningún movimiento dejó el saldo negativo
    assert _estado(fabrica_pg, operacion) == "confirmada"
    assert _ajustes(fabrica_pg) <= 1

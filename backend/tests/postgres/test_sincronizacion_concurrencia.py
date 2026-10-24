"""E07 en PostgreSQL real: lotes de sincronización simultáneos. Cada lote corre en su propio
hilo con su propia sesión (su propia transacción), como dos dispositivos que sincronizan a la vez.

Lo que se demuestra: la misma operación enviada por dos lotes a la vez se procesa UNA vez
(la clave única hace esperar al segundo INSERT); lotes que piden las mismas variantes en orden
contrario no se bloquean entre sí; la última unidad no se vende dos veces; y un fallo
inesperado en un lote no frena a los demás."""

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Stock
from app.comercial.models import Venta
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from app.sincronizacion import politicas as politicas_sync
from app.sincronizacion.casos_uso.cu25_sincronizar_operaciones_offline import ProcesarLote
from app.sincronizacion.models import OperacionSync
from app.sincronizacion.schemas import LoteEntrada

from .conftest import CLAVE
from .paralelo import ejecutar_en_paralelo


def _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id: int) -> int:
    """Un cajero empleado de la sucursal (rol con sincronizacion.operar y ventas.presencial)."""
    with fabrica_pg() as db:
        repo = UsuarioRepository()
        usuario = repo.crear(
            db, UsuarioCrear(nombre="Caja", apellido="Sync", email="cajero-sync@example.com", password=CLAVE)
        )
        repo.asignar_roles(db, usuario, ["cajero"])
        usuario_id = usuario.id
    respuesta = client_pg.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario_id, "sucursal_id": sucursal_id, "cargo": "Cajero"},
        headers=admin_pg,
    )
    assert respuesta.status_code == 201, respuesta.text
    return usuario_id


def _operacion(sucursal_id: int, lineas: list[tuple[int, int]], *, operacion_id: str | None = None, minutos: int = 10) -> dict:
    """Venta de contado a 100.00 por unidad, pagada justa."""
    total = sum(cantidad for _, cantidad in lineas) * 100
    instante = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutos)
    return {
        "operacion_id": operacion_id or str(uuid.uuid4()),
        "tipo": "venta_contado",
        "sucursal_id": sucursal_id,
        "fecha_operacion": instante.isoformat(timespec="seconds"),
        "payload": {
            "cliente_id": None,
            "lineas": [
                {"variante_id": v, "cantidad": c, "precio_unitario": "100.00", "descuento_unitario": "0.00"}
                for v, c in lineas
            ],
            "total": f"{total}.00",
            "pago": {"metodo": "efectivo", "monto_recibido": f"{total}.00"},
        },
    }


def _lote(operaciones: list[dict]) -> LoteEntrada:
    return LoteEntrada.model_validate({"version_contrato": "1.0", "operaciones": operaciones})


def _enviar(usuario_id: int, operaciones: list[dict]):
    return lambda db: ProcesarLote().ejecutar(db, usuario_id, _lote(operaciones))


def _contar(fabrica, modelo) -> int:
    with fabrica() as db:
        return db.scalar(select(func.count()).select_from(modelo))


def _stock(fabrica, variante_id: int, sucursal_id: int) -> tuple[int, int]:
    with fabrica() as db:
        fila = db.execute(
            select(Stock.cantidad_fisica, Stock.cantidad_reservada).where(
                Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id
            )
        ).one()
        return fila.cantidad_fisica, fila.cantidad_reservada


# ---- la misma operación a la vez ------------------------------------------------------------


def test_dos_lotes_simultaneos_con_la_misma_operacion_dejan_una_venta_y_una_fila(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id, v1 = escenario["sucursal_id"], escenario["variantes"][0]
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id)
    operacion = _operacion(sucursal_id, [(v1, 2)])

    resultados = ejecutar_en_paralelo(fabrica_pg, [_enviar(cajero, [operacion]), _enviar(cajero, [operacion])])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    respuestas = [r.valor.resultados[0] for r in resultados]
    assert [x.estado for x in respuestas] == ["confirmada", "confirmada"]
    assert sorted(x.duplicada for x in respuestas) == [False, True]  # exactamente una es el reenvío
    assert len({x.recurso.id for x in respuestas}) == 1  # la MISMA venta
    assert _contar(fabrica_pg, OperacionSync) == 1
    assert _contar(fabrica_pg, Venta) == 1
    assert _stock(fabrica_pg, v1, sucursal_id) == (8, 0)  # descontado una sola vez
    with fabrica_pg() as db:
        assert db.scalar(select(OperacionSync.intentos)) == 2


def test_ocho_lotes_simultaneos_con_la_misma_operacion_dejan_una_sola_venta(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id, v1 = escenario["sucursal_id"], escenario["variantes"][0]
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id)
    operacion = _operacion(sucursal_id, [(v1, 1)])

    resultados = ejecutar_en_paralelo(fabrica_pg, [_enviar(cajero, [operacion]) for _ in range(8)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    respuestas = [r.valor.resultados[0] for r in resultados]
    assert all(x.estado == "confirmada" for x in respuestas)
    assert sum(x.duplicada for x in respuestas) == 7
    assert _contar(fabrica_pg, OperacionSync) == 1 and _contar(fabrica_pg, Venta) == 1
    assert _stock(fabrica_pg, v1, sucursal_id) == (9, 0)
    with fabrica_pg() as db:
        assert db.scalar(select(OperacionSync.intentos)) == 8


# ---- lotes cruzados ----------------------------------------------------------------------------


def test_lotes_que_piden_las_mismas_variantes_en_orden_contrario_no_se_bloquean(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id = escenario["sucursal_id"]
    v1, v2 = escenario["variantes"]
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id)

    for _ronda in range(2):
        resultados = ejecutar_en_paralelo(
            fabrica_pg,
            [
                _enviar(cajero, [_operacion(sucursal_id, [(v1, 1), (v2, 1)]), _operacion(sucursal_id, [(v2, 1), (v1, 1)], minutos=5)]),
                _enviar(cajero, [_operacion(sucursal_id, [(v2, 1), (v1, 1)]), _operacion(sucursal_id, [(v1, 1), (v2, 1)], minutos=5)]),
            ],
        )
        assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]  # sin deadlock
        assert all(x.estado == "confirmada" for r in resultados for x in r.valor.resultados)

    # 2 rondas x 2 lotes x 2 operaciones = 8 ventas, cada una con 1 unidad de cada variante (había 10).
    assert _contar(fabrica_pg, Venta) == 8
    assert _stock(fabrica_pg, v1, sucursal_id) == (2, 0)
    assert _stock(fabrica_pg, v2, sucursal_id) == (2, 0)


def test_seis_lotes_compiten_por_tres_unidades_y_la_ultima_no_se_vende_dos_veces(
    client_pg, fabrica_pg, admin_pg, escenario
):
    sucursal_id, v1 = escenario["sucursal_id"], escenario["variantes"][0]
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id)
    ajuste = client_pg.post(
        "/api/v1/inventario/ajustes",
        json={"variante_id": v1, "sucursal_id": sucursal_id, "cantidad": -7, "observacion": "dejar 3"},
        headers=admin_pg,
    )
    assert ajuste.status_code == 201, ajuste.text
    assert _stock(fabrica_pg, v1, sucursal_id) == (3, 0)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [_enviar(cajero, [_operacion(sucursal_id, [(v1, 1)])]) for _ in range(6)]
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    estados = sorted(r.valor.resultados[0].estado for r in resultados)
    assert estados == ["confirmada"] * 3 + ["en_conflicto"] * 3
    assert _stock(fabrica_pg, v1, sucursal_id) == (0, 0)  # sin negativos y nada apartado
    with fabrica_pg() as db:
        saldos = list(
            db.scalars(
                select(MovimientoInventario.saldo_post)
                .where(MovimientoInventario.variante_id == v1, MovimientoInventario.cantidad == -1)
                .order_by(MovimientoInventario.id)
            )
        )
        assert saldos == [2, 1, 0]
        assert db.scalar(select(func.count()).select_from(OperacionSync).where(OperacionSync.estado == "en_conflicto")) == 3


# ---- un fallo no frena a los demás --------------------------------------------------------------


def test_un_fallo_inesperado_en_un_lote_no_impide_que_otro_lote_concurrente_complete(
    client_pg, fabrica_pg, admin_pg, escenario, monkeypatch
):
    sucursal_id, v1 = escenario["sucursal_id"], escenario["variantes"][0]
    cajero = _cajero(client_pg, fabrica_pg, admin_pg, sucursal_id)

    def _falla(*args, **kwargs):
        raise RuntimeError("fallo inesperado simulado")

    monkeypatch.setattr(politicas_sync, "ejecutar_reserva", _falla)
    reserva = {
        "operacion_id": str(uuid.uuid4()),
        "tipo": "reserva",
        "sucursal_id": sucursal_id,
        "fecha_operacion": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).isoformat(timespec="seconds"),
        "payload": {
            "cliente_id": 1,
            "fecha_visita": escenario["fecha_visita"].isoformat(),
            "hora_visita_desde": "10:00",
            "hora_visita_hasta": "11:00",
            "lineas": [{"variante_id": v1, "cantidad": 1}],
        },
    }
    resultados = ejecutar_en_paralelo(
        fabrica_pg,
        [
            _enviar(cajero, [reserva, _operacion(sucursal_id, [(v1, 1)])]),
            _enviar(cajero, [_operacion(sucursal_id, [(v1, 1)])]),
        ],
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    primero, segundo = (r.valor for r in resultados)
    assert sorted(x.estado for x in primero.resultados) == ["confirmada", "error_temporal"]
    assert [x.estado for x in segundo.resultados] == ["confirmada"]
    assert _contar(fabrica_pg, Venta) == 2
    assert _contar(fabrica_pg, OperacionSync) == 2  # la del error inesperado no se guardó
    assert _stock(fabrica_pg, v1, sucursal_id) == (8, 0)

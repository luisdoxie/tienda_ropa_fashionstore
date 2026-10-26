"""Reglas del paquete `sincronizacion`: qué se rechaza y por qué, cómo se aplica cada
tipo de operación reutilizando las reglas de `comercial`, y cómo se arma el
resultado. Aquí NO se consultan las tablas de otros paquetes: solo se llama a sus
políticas (regla 2).

Los motivos son un catálogo estable: la PWA y la app móvil los usan para mostrar
el mensaje correcto sin interpretar texto."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.comercial.politicas import calcular_linea, cobrar_en_caja, crear_reserva, redondear, registrar_venta
from app.comercial.schemas import ReservaCrear, ReservaDetalleCrear
from app.core.config import get_settings
from app.core.exceptions import DomainError, NoEncontradoError, StockInsuficienteError
from app.core.security import permisos_de_usuario
from app.core.tiempo import ahora_utc_naive, hoy_utc
from app.plataforma import politicas as plataforma_politicas
from app.sincronizacion.models import OperacionSync
from app.sincronizacion.schemas import PAYLOAD_POR_TIPO, ReservaPayload, ResultadoOperacion, VentaContadoPayload

logger = logging.getLogger("app.sincronizacion")

# ---- Motivos de rechazo y de conflicto (catálogo estable) ----
SUSCRIPCION_NO_ACTIVA = "suscripcion_no_activa"
PLAN_SIN_OPERACION_OFFLINE = "plan_sin_operacion_offline"
SUCURSAL_NO_AUTORIZADA = "sucursal_no_autorizada"
SUCURSAL_INEXISTENTE = "sucursal_inexistente"
USUARIO_NO_ES_EMPLEADO = "usuario_no_es_empleado"
PERMISO_DENEGADO = "permiso_denegado"
VARIANTE_INEXISTENTE = "variante_inexistente"
VARIANTE_INACTIVA = "variante_inactiva"
CLIENTE_INEXISTENTE = "cliente_inexistente"
PAYLOAD_INVALIDO = "payload_invalido"
TIPO_NO_SOPORTADO = "tipo_no_soportado"
TOTAL_INCONSISTENTE = "total_inconsistente"
TOTAL_INVALIDO = "total_invalido"
METODO_PAGO_NO_PERMITIDO = "metodo_pago_no_permitido"
MONTO_INSUFICIENTE = "monto_insuficiente"
FECHA_FUTURA = "fecha_futura"
RESERVA_FUERA_DE_HORARIO = "reserva_fuera_de_horario"
RESERVA_VENCIDA = "reserva_vencida"
REGLA_DE_NEGOCIO = "regla_de_negocio"
STOCK_INSUFICIENTE = "stock_insuficiente"
RECHAZADA_POR_ENCARGADO = "rechazada_por_encargado"  # la guarda `rechazar` (E08)
OPERADOR_INACTIVO = "operador_inactivo"  # E08: 'forzar' revalida al operador original

# Referencia del movimiento de inventario que deja 'forzar' (E08): el kardex dice de dónde vino.
REFERENCIA_SYNC_FORZADA = "sync_forzada"

PERMISO_POR_TIPO = {"venta_contado": "ventas.presencial", "reserva": "reservas.gestionar_sucursal"}


class RechazoOperacion(Exception):
    """La operación no se puede aplicar por una regla conocida: queda `rechazada`
    con este `motivo` y este `mensaje` (en español, para mostrar)."""

    def __init__(self, motivo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.motivo = motivo
        self.mensaje = mensaje


@dataclass
class Resolucion:
    """Lo que dejó una operación confirmada."""

    recurso: dict[str, Any]
    cambio: Decimal | None = None
    avisos: list[dict[str, Any]] = field(default_factory=list)


# ---- Habilitación del plan y la suscripción ----


def motivo_bloqueo(db: Session) -> str | None:
    """Por qué la empresa de la sesión NO puede sincronizar (o None si puede). Se
    calcula una sola vez por lote. No lanza: el rechazo se guarda con su motivo (D16)."""
    situacion = plataforma_politicas.situacion_de_la_empresa(db)
    if situacion.estado != "activa":
        return SUSCRIPCION_NO_ACTIVA
    if situacion.plan is None or not situacion.plan.operacion_offline:
        return PLAN_SIN_OPERACION_OFFLINE
    return None


_MENSAJE_BLOQUEO = {
    SUSCRIPCION_NO_ACTIVA: "La suscripción de la empresa no está activa",
    PLAN_SIN_OPERACION_OFFLINE: "El plan de la empresa no incluye la operación sin conexión",
}


def mensaje_de_bloqueo(motivo: str) -> str:
    return _MENSAJE_BLOQUEO[motivo]


# ---- Validaciones del sobre y del payload ----


def a_utc_naive(fecha: dt.datetime) -> dt.datetime:
    """Fecha con zona -> UTC sin zona (como se guarda todo en la base)."""
    return fecha.astimezone(dt.timezone.utc).replace(tzinfo=None)


def validar_payload(tipo: str, payload: dict) -> BaseModel:
    esquema = PAYLOAD_POR_TIPO.get(tipo)
    if esquema is None:
        raise RechazoOperacion(TIPO_NO_SOPORTADO, f"El tipo de operación '{tipo[:30]}' no está soportado")
    try:
        return esquema.model_validate(payload)
    except ValidationError as error:
        primero = error.errors()[0]
        donde = ".".join(str(parte) for parte in primero["loc"])
        raise RechazoOperacion(PAYLOAD_INVALIDO, f"Datos inválidos en '{donde}': {primero['msg']}") from None


def validar_fecha(fecha_utc: dt.datetime) -> None:
    limite = ahora_utc_naive() + dt.timedelta(minutes=get_settings().sync_tolerancia_futuro_minutos)
    if fecha_utc > limite:
        raise RechazoOperacion(FECHA_FUTURA, "La fecha de la operación está en el futuro: revise el reloj del dispositivo")


def sucursal_existe(db: Session, sucursal_id: int) -> bool:
    try:
        plataforma_politicas.obtener_sucursal(db, sucursal_id)
    except NoEncontradoError:
        return False
    return True


def validar_actor(db: Session, usuario_id: int, permisos: set[str], tipo: str, sucursal_id: int):
    """El usuario del token debe ser empleado, tener acceso a la sucursal y el permiso del
    tipo. Devuelve su ficha de empleado."""
    empleado = plataforma_politicas.obtener_empleado_por_usuario(db, usuario_id)
    if empleado is None:
        raise RechazoOperacion(USUARIO_NO_ES_EMPLEADO, "El usuario no es un empleado y no puede registrar operaciones")
    try:
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
    except DomainError:
        raise RechazoOperacion(SUCURSAL_NO_AUTORIZADA, "El usuario no tiene acceso a esa sucursal") from None
    if PERMISO_POR_TIPO[tipo] not in permisos:
        raise RechazoOperacion(PERMISO_DENEGADO, "El usuario no tiene permiso para este tipo de operación")
    return empleado


def _validar_variantes(db: Session, variantes_ids: list[int]) -> dict[int, Any]:
    """{id: variante}. `buscar_variante` devuelve también las dadas de baja y None si no existe
    (o es de otra empresa)."""
    encontradas = {}
    for variante_id in variantes_ids:
        variante = catalogo_politicas.buscar_variante(db, variante_id)
        if variante is None:
            raise RechazoOperacion(VARIANTE_INEXISTENTE, f"La variante {variante_id} no existe")
        if not variante.activo or not variante.producto.activo:
            raise RechazoOperacion(VARIANTE_INACTIVA, f"La variante {variante_id} ya no se vende")
        encontradas[variante_id] = variante
    return encontradas


def _validar_cliente(db: Session, cliente_id: int) -> None:
    try:
        plataforma_politicas.obtener_cliente(db, cliente_id)
    except NoEncontradoError:
        raise RechazoOperacion(CLIENTE_INEXISTENTE, f"El cliente {cliente_id} no existe") from None


# ---- Ejecutores por tipo ----


def ejecutar_venta_contado(
    db: Session, usuario_id: int, empleado, sucursal_id: int, payload: VentaContadoPayload, fecha: dt.datetime
) -> Resolucion:
    """Venta de contado en efectivo (D18) con el precio de la operación (D17): registra la venta
    y la cobra en caja reutilizando las reglas de `comercial`. Nada se confirma aquí: lo hace
    el llamador al terminar la operación."""
    if payload.cliente_id is not None:
        _validar_cliente(db, payload.cliente_id)
    variantes = _validar_variantes(db, [linea.variante_id for linea in payload.lineas])

    total_calculado = Decimal("0")
    for linea in payload.lineas:
        if linea.descuento_unitario > linea.precio_unitario:
            raise RechazoOperacion(PAYLOAD_INVALIDO, "El descuento no puede superar el precio unitario")
        total_calculado += redondear((linea.precio_unitario - linea.descuento_unitario) * linea.cantidad)
    if total_calculado != payload.total:
        raise RechazoOperacion(
            TOTAL_INCONSISTENTE, "El total no coincide con la suma de las líneas (precio menos descuento por cantidad)"
        )
    if payload.total <= 0:
        raise RechazoOperacion(TOTAL_INVALIDO, "El total de la venta debe ser mayor que cero")

    if payload.pago.metodo != "efectivo":
        raise RechazoOperacion(METODO_PAGO_NO_PERMITIDO, "La venta sin conexión solo admite pago en efectivo")
    if payload.pago.monto_recibido < payload.total:
        raise RechazoOperacion(MONTO_INSUFICIENTE, "El monto recibido no cubre el total")

    # Precio distinto del actual (D17): se acepta el de la operación (el cliente pagó ese) y se avisa.
    hoy = hoy_utc()
    avisos = []
    for linea in payload.lineas:
        precio_actual, descuento_actual, _ = calcular_linea(db, variantes[linea.variante_id], linea.cantidad, hoy)
        neto_operacion = linea.precio_unitario - linea.descuento_unitario
        neto_actual = precio_actual - descuento_actual
        if neto_operacion != neto_actual:
            avisos.append(
                {
                    "codigo": "precio_distinto",
                    "variante_id": linea.variante_id,
                    "precio_operacion": str(redondear(neto_operacion)),
                    "precio_actual": str(redondear(neto_actual)),
                }
            )

    venta = registrar_venta(
        db,
        canal="presencial",
        sucursal_id=sucursal_id,
        lineas=[(linea.variante_id, linea.cantidad) for linea in payload.lineas],
        cliente_id=payload.cliente_id,
        cajero_id=empleado.id,
        reserva_id=None,
        costo_envio=Decimal("0"),
        usuario_id=usuario_id,
        commit=False,
        fecha=fecha,
        precios_pactados=[(linea.precio_unitario, linea.descuento_unitario) for linea in payload.lineas],
    )
    _, cambio = cobrar_en_caja(
        db, usuario_id, venta.id, "efectivo", payload.pago.monto_recibido, commit=False, fecha=fecha
    )
    return Resolucion(
        recurso={"tipo": "venta", "id": venta.id, "codigo": venta.codigo, "total": str(venta.total)},
        cambio=cambio,
        avisos=avisos,
    )


def ejecutar_reserva(
    db: Session, usuario_id: int, sucursal_id: int, payload: ReservaPayload, fecha: dt.datetime
) -> Resolucion:
    """Reserva a nombre de un cliente, registrada por el personal. Aparta el stock de cada línea."""
    _validar_cliente(db, payload.cliente_id)
    _validar_variantes(db, [linea.variante_id for linea in payload.lineas])
    if payload.hora_visita_desde >= payload.hora_visita_hasta:
        raise RechazoOperacion(PAYLOAD_INVALIDO, "La hora de inicio de la visita debe ser anterior a la hora de fin")
    try:
        plataforma_politicas.validar_horario_en_atencion(
            db, sucursal_id, payload.fecha_visita, payload.hora_visita_desde, payload.hora_visita_hasta
        )
    except DomainError as error:
        raise RechazoOperacion(RESERVA_FUERA_DE_HORARIO, error.mensaje) from None

    reserva = crear_reserva(
        db,
        usuario_id,
        ReservaCrear(
            sucursal_id=sucursal_id,
            fecha_visita=payload.fecha_visita,
            hora_visita_desde=payload.hora_visita_desde,
            hora_visita_hasta=payload.hora_visita_hasta,
            observacion=payload.observacion,
            detalle=[ReservaDetalleCrear(variante_id=l.variante_id, cantidad=l.cantidad) for l in payload.lineas],
        ),
        commit=False,
        cliente_id=payload.cliente_id,
        creado_en=fecha,
    )
    expiracion = reserva.fecha_expiracion
    if expiracion.tzinfo is not None:
        expiracion = a_utc_naive(expiracion)
    if expiracion <= ahora_utc_naive():
        # El llamador revierte el SAVEPOINT de la operación: el apartado se deshace.
        raise RechazoOperacion(RESERVA_VENCIDA, "La visita de la reserva ya pasó")
    return Resolucion(
        recurso={
            "tipo": "reserva",
            "id": reserva.id,
            "codigo": reserva.codigo,
            "fecha_expiracion": expiracion.isoformat(),
        }
    )


# ---- Paquete de descarga (E08) ----


def calcular_etag(paquete: BaseModel) -> str:
    """Huella del contenido del paquete SIN la marca `generado_en` (que cambia en cada lectura):
    dos descargas con los mismos datos dan el mismo ETag, y el cliente puede preguntar si cambió
    (`If-None-Match`) sin volver a bajar el cuerpo."""
    contenido = paquete.model_dump(mode="json", exclude={"generado_en"})
    texto = json.dumps(contenido, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def desde_a_utc_naive(desde: dt.datetime) -> dt.datetime:
    """El `desde` del stock incremental en UTC sin zona, menos el solape (D: el servidor lo resta
    SIEMPRE, un cliente no puede olvidarlo). Sin zona se toma como UTC."""
    if desde.tzinfo is not None:
        desde = desde.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return desde - dt.timedelta(seconds=get_settings().sync_stock_solape_segundos)


# ---- Resolver conflictos (E08, D15) ----


def revalidar_operador(db: Session, operacion: OperacionSync):
    """Antes de forzar: el operador ORIGINAL sigue pudiendo hacer lo que hizo (usuario activo,
    empleado con acceso a la sucursal y el permiso del tipo). Devuelve su ficha de empleado; si
    algo falló lanza `RechazoOperacion` (quien resuelve lo entrega como 409 y la operación sigue
    en conflicto: lo que corresponde entonces es rechazarla)."""
    try:
        plataforma_politicas.obtener_usuario(db, operacion.usuario_id)
    except NoEncontradoError:
        raise RechazoOperacion(OPERADOR_INACTIVO, "El operador que registró la operación ya no está activo") from None
    permisos = set(permisos_de_usuario(db, operacion.usuario_id))
    return validar_actor(db, operacion.usuario_id, permisos, operacion.tipo, operacion.sucursal_id)


def ajustar_faltantes(
    db: Session, operacion: OperacionSync, lineas: list[tuple[int, int]], encargado_id: int
) -> list[dict[str, int]]:
    """El AJUSTE POSITIVO de 'forzar': por cada variante, la diferencia exacta entre lo vendido
    (las líneas repetidas se suman) y el disponible (física menos reservada). El stock físico
    NUNCA queda negativo: el disponible queda en 0 y las unidades apartadas por reservas de otras
    personas no se tocan. Sin faltante (el stock se recuperó) no hay ajuste. Los movimientos
    quedan en el kardex con referencia `sync_forzada` y el encargado como actor. No confirma."""
    pedido: dict[int, int] = {}
    for variante_id, cantidad in lineas:
        pedido[variante_id] = pedido.get(variante_id, 0) + cantidad
    sucursal_id = operacion.sucursal_id
    # Bloquea (y relee) todas las filas primero, en orden: así el disponible que se lee es el real.
    catalogo_politicas.bloquear_stock_en_orden(db, [(variante_id, sucursal_id) for variante_id in pedido])
    corto = str(operacion.operacion_id)[:8]
    ajustes = []
    for variante_id in sorted(pedido):
        try:
            stock = catalogo_politicas.obtener_stock(db, variante_id, sucursal_id)
            disponible = max(stock.cantidad_fisica - stock.cantidad_reservada, 0)
        except NoEncontradoError:
            disponible = 0
        faltante = pedido[variante_id] - disponible
        if faltante <= 0:
            continue
        movimiento = catalogo_politicas.actualizar_stock_operacion(
            db,
            variante_id=variante_id,
            sucursal_id=sucursal_id,
            tipo_movimiento_codigo="ajuste_positivo",
            cantidad=faltante,
            referencia_tipo=REFERENCIA_SYNC_FORZADA,
            referencia_id=operacion.id,
            usuario_id=encargado_id,
            observacion=f"Ajuste por conflicto de sincronización {corto}: la prenda ya salió de la tienda",
            commit=False,
        )
        ajustes.append({"variante_id": variante_id, "cantidad": faltante, "movimiento_id": movimiento.id})
    return ajustes


def forzar_venta_contado(
    db: Session, operacion: OperacionSync, payload: VentaContadoPayload, encargado_id: int
) -> tuple[Resolucion, list[dict[str, int]]]:
    """Confirma una venta en conflicto: revalida al operador original, ajusta el inventario por lo
    que faltaba y ejecuta la MISMA venta de E07 (fecha de la operación, precios de la operación,
    pago en efectivo) a nombre del operador. Nada se confirma aquí; el llamador lo corre dentro
    de un SAVEPOINT."""
    empleado = revalidar_operador(db, operacion)
    _validar_variantes(db, [linea.variante_id for linea in payload.lineas])  # antes de ajustar nada
    ajustes = ajustar_faltantes(
        db, operacion, [(linea.variante_id, linea.cantidad) for linea in payload.lineas], encargado_id
    )
    resolucion = ejecutar_venta_contado(
        db, operacion.usuario_id, empleado, operacion.sucursal_id, payload, operacion.fecha_operacion
    )
    return resolucion, ajustes


def lineas_del_payload(tipo: str, modelo: BaseModel) -> list[tuple[int, int]]:
    return [(linea.variante_id, linea.cantidad) for linea in modelo.lineas]  # type: ignore[attr-defined]


def calcular_faltantes(
    db: Session, sucursal_id: int, lineas: list[tuple[int, int]], error: StockInsuficienteError
) -> list[dict[str, int]]:
    """Qué variantes no alcanzan, con el stock tal como quedó DESPUÉS de deshacer la operación
    (D15). Las líneas de una misma variante se suman. Si no se puede calcular, se usa lo que
    informó el error."""
    pedido: dict[int, int] = {}
    for variante_id, cantidad in lineas:
        pedido[variante_id] = pedido.get(variante_id, 0) + cantidad
    faltantes = []
    for variante_id, solicitado in pedido.items():
        try:
            stock = catalogo_politicas.obtener_stock(db, variante_id, sucursal_id)
            disponible = max(stock.cantidad_fisica - stock.cantidad_reservada, 0)
        except NoEncontradoError:
            disponible = 0
        if solicitado > disponible:
            faltantes.append({"variante_id": variante_id, "solicitado": solicitado, "disponible": disponible})
    if not faltantes and error.variante_id is not None:
        faltantes.append(
            {
                "variante_id": error.variante_id,
                "solicitado": error.solicitado or 0,
                "disponible": error.disponible or 0,
            }
        )
    return faltantes


# ---- Resultado ----


def construir_resultado(fila: OperacionSync, *, duplicada: bool = False) -> ResultadoOperacion:
    """El resultado que ve el cliente, a partir de lo GUARDADO en la fila."""
    guardado = fila.resultado or {}
    return ResultadoOperacion(
        operacion_id=fila.operacion_id,
        estado=fila.estado,  # type: ignore[arg-type]
        motivo=fila.motivo,
        mensaje=guardado.get("mensaje"),
        duplicada=duplicada,
        procesada_en=fila.procesada_en,
        recurso=guardado.get("recurso"),
        cambio=guardado.get("cambio"),
        avisos=guardado.get("avisos", []),
        faltantes=guardado.get("faltantes", []),
    )

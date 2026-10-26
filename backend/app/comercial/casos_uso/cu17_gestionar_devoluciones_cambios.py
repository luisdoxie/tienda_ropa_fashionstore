"""CU-17 — Gestionar devoluciones y cambios

Absorbe el antiguo CU-40 (Registrar devolución).

Actor: Cajero, Encargado de sucursal.
Precondición: la venta existe, está pagada o entregada, es de la
sucursal del empleado (salvo alcance global) y está dentro del plazo de cambio
de la empresa (24 horas por defecto, desde la fecha real de la venta).
Postcondición: la devolución queda registrada y el stock reingresa a la
sucursal.

Nota: esta etapa no dispara ningún reembolso en Pagos (CU-18; no hay un flujo
de aprobación de devolución en el alcance actual) -- solo reingresa stock
y dejó constancia. Si en el futuro se agrega reembolso, va acá, como
llamada al caso de uso de Pagos, sin duplicar la lógica de devolución."""

from sqlalchemy.orm import Session

from app.catalogo.politicas import actualizar_stock_operacion, bloquear_stock_en_orden
from app.comercial.models import Devolucion, DevolucionDetalle
from app.comercial.politicas import describir_plazo_cambio, exigir_plazo_cambio, obtener_comprobante
from app.comercial.repository import DevolucionRepository, EstadoVentaRepository, VentaRepository
from app.comercial.schemas import DevolucionCrear
from app.core.auditoria import ACCION_REGISTRAR, ENTIDAD_DEVOLUCION, ContextoAuditoria
from app.core.codigos import generar_codigo
from app.core.exceptions import DomainError, NoEncontradoError
from app.plataforma import politicas as plataforma_politicas

class ConsultarPlazoCambio:
    """Cuánto le queda a una venta para devolver o cambiar prendas. Lo ve el dueño
    de la venta o el personal de su sucursal (misma regla que el comprobante)."""

    def ejecutar(self, db: Session, venta_id: int, usuario_id: int) -> dict:
        venta = obtener_comprobante(db, venta_id, usuario_id)
        return describir_plazo_cambio(db, venta)


class RegistrarDevolucion:
    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._estados = EstadoVentaRepository()
        self._devoluciones = DevolucionRepository()

    def ejecutar(
        self, db: Session, usuario_id: int, datos: DevolucionCrear, contexto: ContextoAuditoria | None = None
    ) -> Devolucion:
        # Bloqueada hasta el commit: dos devoluciones simultáneas de la misma
        # venta se ponen en fila y la segunda suma lo que la primera ya
        # devolvió (y una anulación concurrente espera a que termine).
        venta = self._ventas.obtener_bloqueado(db, datos.venta_id)
        # El stock reingresa a la sucursal de la venta: solo su personal.
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)

        # Con el pago gateado, una venta 'pendiente_pago' nunca descontó
        # stock físico -- no hay nada real que devolver todavía.
        estado_venta = self._estados.obtener(db, venta.estado_id)
        if estado_venta.codigo not in ("pagada", "entregada"):
            raise DomainError(f"No se puede devolver una venta en estado '{estado_venta.codigo}'")
        # D19: pasado el plazo de la empresa (desde la fecha real de la venta) ya no
        # se acepta. Cada devolución se evalúa por separado contra esa fecha.
        exigir_plazo_cambio(db, venta)

        detalle_por_id = {linea.id: linea for linea in venta.detalle}

        devolucion = Devolucion(
            codigo=generar_codigo(db, "DEV", self._devoluciones.obtener_por_codigo),
            venta_id=venta.id,
            motivo=datos.motivo,
            estado="aprobada",  # esta etapa no tiene un flujo de aprobación aparte
            usuario_id=usuario_id,
        )
        db.add(devolucion)
        db.flush()

        bloquear_stock_en_orden(
            db,
            [
                (detalle_por_id[linea.venta_detalle_id].variante_id, venta.sucursal_id)
                for linea in datos.detalle
                if linea.venta_detalle_id in detalle_por_id
            ],
        )
        for linea in datos.detalle:
            detalle = detalle_por_id.get(linea.venta_detalle_id)
            if detalle is None:
                raise NoEncontradoError(f"La línea {linea.venta_detalle_id} no pertenece a la venta {venta.id}")

            ya_devuelto = self._devoluciones.cantidad_devuelta(db, linea.venta_detalle_id)
            if ya_devuelto + linea.cantidad > detalle.cantidad:
                raise DomainError(
                    f"No se puede devolver más de lo vendido en la línea {linea.venta_detalle_id} "
                    f"({ya_devuelto} ya devuelto de {detalle.cantidad})"
                )

            db.add(DevolucionDetalle(devolucion_id=devolucion.id, venta_detalle_id=detalle.id, cantidad=linea.cantidad))

            # La devolución reingresa stock (movimiento tipo 'devolucion');
            # no reabre la venta ni cambia su estado -- esta etapa no toca
            # Pagos.
            actualizar_stock_operacion(
                db,
                variante_id=detalle.variante_id,
                sucursal_id=venta.sucursal_id,
                tipo_movimiento_codigo="devolucion",
                cantidad=linea.cantidad,
                referencia_tipo="devolucion",
                referencia_id=devolucion.id,
                usuario_id=usuario_id,
                commit=False,
            )

        # Misma transacción que la devolución y el stock: si algo falló antes,
        # no queda fila. El motivo (texto libre) no se copia a la bitácora.
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_DEVOLUCION,
            devolucion.id,
            ACCION_REGISTRAR,
            {"venta_id": venta.id, "unidades": sum(linea.cantidad for linea in datos.detalle)},
        )
        db.commit()
        db.refresh(devolucion)
        return devolucion

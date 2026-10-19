"""CU-08 — Gestionar abastecimiento

Absorbe los antiguos CU-11 (Gestionar proveedores) y CU-12 (Registrar
recepción de mercadería).

Actor: Administrador (Proveedor como actor pasivo).
Precondición: sesión con el permiso abastecimiento.gestionar; los
productos a asociar (CU-05), el proveedor, la sucursal y las variantes
existen.
Postcondición: el proveedor queda activo con sus productos asociados; al
recibir mercadería, el stock físico de la sucursal aumenta, el costo
promedio queda actualizado y la recepción queda trazada en el kardex.

Caso de uso COMPUESTO: agrupa el proveedor y los productos que abastece
cada uno (una clase) y el registro de la recepción de mercadería.
`GestionarOrdenesCompra` no es un caso de uso del catálogo: es una entidad
de soporte (ver CLAUDE.md, nota sobre entidades de soporte) que la
recepción referencia de forma opcional y a la que actualiza el estado
cuando corresponde.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.models import (
    ProductoProveedor,
    Proveedor,
    OrdenCompra,
    OrdenCompraDetalle,
    Recepcion,
    RecepcionDetalle,
)
from app.catalogo.politicas import actualizar_stock_operacion
from app.catalogo.repository import (
    ProductoProveedorRepository,
    ProveedorRepository,
    OrdenCompraRepository,
    RecepcionRepository,
)
from app.catalogo.schemas import (
    ProveedorActualizar,
    ProveedorCrear,
    OrdenCompraActualizar,
    OrdenCompraCrear,
    RecepcionCrear,
)
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError
from app.plataforma import politicas as plataforma_politicas


# ---- Proveedores (antiguo CU-11: Gestionar proveedores) ----

class GestionarProveedores:
    def __init__(self) -> None:
        self._proveedores = ProveedorRepository()
        self._productos_proveedor = ProductoProveedorRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Proveedor]:
        return list(self._proveedores.listar(db, paginacion))

    def obtener(self, db: Session, proveedor_id: int) -> Proveedor:
        return self._proveedores.obtener(db, proveedor_id)

    def crear(self, db: Session, datos: ProveedorCrear) -> Proveedor:
        return self._proveedores.crear(db, datos)

    def actualizar(self, db: Session, proveedor_id: int, datos: ProveedorActualizar) -> Proveedor:
        return self._proveedores.actualizar(db, proveedor_id, datos)

    def desactivar(self, db: Session, proveedor_id: int) -> Proveedor:
        return self._proveedores.desactivar(db, proveedor_id)

    def listar_productos(self, db: Session, proveedor_id: int) -> list[ProductoProveedor]:
        self._proveedores.obtener(db, proveedor_id)  # 404 si no existe / está inactivo
        return list(self._productos_proveedor.listar_por_proveedor(db, proveedor_id))

    def agregar_producto(
        self,
        db: Session,
        proveedor_id: int,
        producto_id: int,
        costo_referencial: Decimal | None,
        dias_entrega: int | None,
    ) -> ProductoProveedor:
        self._proveedores.obtener(db, proveedor_id)  # 404 si no existe / está inactivo
        catalogo_politicas.obtener_producto(db, producto_id)  # 404 si no existe
        return self._productos_proveedor.crear(db, proveedor_id, producto_id, costo_referencial, dias_entrega)

    def quitar_producto(self, db: Session, proveedor_id: int, producto_id: int) -> None:
        self._productos_proveedor.eliminar(db, proveedor_id, producto_id)


# ---- Órdenes de compra y recepción de mercadería (antiguo CU-12: Registrar recepción de mercadería) ----

class GestionarOrdenesCompra:
    """Entidad de soporte, sin CU propio: ver docstring del módulo."""

    def __init__(self) -> None:
        self._ordenes = OrdenCompraRepository()
        self._proveedores = ProveedorRepository()

    def crear(self, db: Session, datos: OrdenCompraCrear, creado_por: int | None) -> OrdenCompra:
        self._proveedores.obtener(db, datos.proveedor_id)  # 404 si no existe / está inactivo
        plataforma_politicas.obtener_sucursal(db, datos.sucursal_id)
        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)

        if self._ordenes.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una orden de compra con ese código")

        total = sum((Decimal(linea.cantidad) * linea.costo_unitario for linea in datos.detalle), Decimal("0"))
        orden = OrdenCompra(
            codigo=datos.codigo,
            proveedor_id=datos.proveedor_id,
            sucursal_id=datos.sucursal_id,
            fecha_esperada=datos.fecha_esperada,
            estado="borrador",
            total=total,
            creado_por=creado_por,
        )
        orden.detalle = [
            OrdenCompraDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad, costo_unitario=linea.costo_unitario)
            for linea in datos.detalle
        ]
        return self._ordenes.crear(db, orden)

    def actualizar(self, db: Session, orden_id: int, datos: OrdenCompraActualizar) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado != "borrador":
            raise ConflictoError("Solo se puede editar una orden de compra en estado 'borrador'")

        if datos.proveedor_id is not None:
            self._proveedores.obtener(db, datos.proveedor_id)
            orden.proveedor_id = datos.proveedor_id
        if datos.sucursal_id is not None:
            plataforma_politicas.obtener_sucursal(db, datos.sucursal_id)
            orden.sucursal_id = datos.sucursal_id
        if datos.fecha_esperada is not None:
            orden.fecha_esperada = datos.fecha_esperada

        if datos.detalle is not None:
            for linea in datos.detalle:
                catalogo_politicas.obtener_variante(db, linea.variante_id)
            nuevas_lineas = [
                OrdenCompraDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad, costo_unitario=linea.costo_unitario)
                for linea in datos.detalle
            ]
            return self._ordenes.reemplazar_detalle(db, orden, nuevas_lineas)

        return self._ordenes.guardar(db, orden)

    def enviar(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado != "borrador":
            raise ConflictoError(f"La orden está en estado '{orden.estado}', no se puede enviar")
        orden.estado = "enviada"
        return self._ordenes.guardar(db, orden)

    def anular(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = self._ordenes.obtener(db, orden_id)
        if orden.estado not in ("borrador", "enviada"):
            raise ConflictoError("Solo se puede anular una orden en 'borrador' o 'enviada'")
        orden.estado = "anulada"
        return self._ordenes.guardar(db, orden)

    def listar(self, db: Session, proveedor_id: int | None = None, sucursal_id: int | None = None) -> list[OrdenCompra]:
        return self._ordenes.listar(db, proveedor_id, sucursal_id)

    def obtener(self, db: Session, orden_id: int) -> OrdenCompra:
        return self._ordenes.obtener(db, orden_id)


class RegistrarRecepcionMercaderia:
    def __init__(self) -> None:
        self._proveedores = ProveedorRepository()
        self._ordenes = OrdenCompraRepository()
        self._recepciones = RecepcionRepository()
        self.ordenes_compra = GestionarOrdenesCompra()

    def _actualizar_estado_orden_por_recepciones(self, db: Session, orden: OrdenCompra) -> None:
        recibido_por_variante = self._recepciones.total_recibido_por_variante(db, orden.id)
        completa = all(recibido_por_variante.get(linea.variante_id, 0) >= linea.cantidad for linea in orden.detalle)
        algo_recibido = any(recibido_por_variante.get(linea.variante_id, 0) > 0 for linea in orden.detalle)
        if completa:
            orden.estado = "recibida"
        elif algo_recibido:
            orden.estado = "parcial"

    def registrar(
        self, db: Session, datos: RecepcionCrear, empleado_id: int | None, creado_por: int | None
    ) -> Recepcion:
        self._proveedores.obtener(db, datos.proveedor_id)  # 404 si no existe / está inactivo
        plataforma_politicas.obtener_sucursal(db, datos.sucursal_id)

        orden = None
        if datos.orden_compra_id is not None:
            orden = self._ordenes.obtener(db, datos.orden_compra_id)
            if orden.estado not in ("enviada", "parcial"):
                raise DomainError(f"La orden de compra está en estado '{orden.estado}', no admite recepciones")

        if self._recepciones.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una recepción con ese código")

        recepcion = Recepcion(
            codigo=datos.codigo,
            orden_compra_id=datos.orden_compra_id,
            proveedor_id=datos.proveedor_id,
            sucursal_id=datos.sucursal_id,
            empleado_id=empleado_id,
            observacion=datos.observacion,
        )
        self._recepciones.crear(db, recepcion)  # flush: recepcion.id ya queda disponible

        # Los bloqueos de stock se toman en orden (variante_id, sucursal_id)
        # sea cual sea el orden de las líneas: evita deadlock entre dos
        # recepciones concurrentes con las mismas variantes (T3).
        catalogo_politicas.bloquear_stock_en_orden(
            db, [(linea.variante_id, datos.sucursal_id) for linea in datos.detalle]
        )

        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)  # 404 si no existe
            db.add(
                RecepcionDetalle(
                    recepcion_id=recepcion.id,
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    costo_unitario=linea.costo_unitario,
                )
            )
            # commit=False: toda la recepción (cabecera + detalle + los N
            # movimientos que genera) es UNA sola transacción. Si una línea
            # falla (p. ej. tipo de movimiento inválido), no queda nada aplicado.
            actualizar_stock_operacion(
                db,
                variante_id=linea.variante_id,
                sucursal_id=datos.sucursal_id,
                tipo_movimiento_codigo="recepcion",
                cantidad=linea.cantidad,
                costo_unitario=linea.costo_unitario,
                referencia_tipo="recepcion",
                referencia_id=recepcion.id,
                usuario_id=creado_por,
                commit=False,
            )

        db.flush()
        if orden is not None:
            self._actualizar_estado_orden_por_recepciones(db, orden)

        db.commit()
        db.refresh(recepcion)
        return recepcion

    def listar(self, db: Session, orden_compra_id: int | None = None) -> list[Recepcion]:
        return self._recepciones.listar(db, orden_compra_id)

    def obtener(self, db: Session, recepcion_id: int) -> Recepcion:
        return self._recepciones.obtener(db, recepcion_id)

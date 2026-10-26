"""CU-25 — Sincronizar operaciones offline

Actor: Vendedor, Cajero o Encargado (el que registró las operaciones sin conexión).
Precondición: sesión con el permiso `sincronizacion.operar`, plan con operación
sin conexión y suscripción activa (si no, cada operación queda rechazada con su
motivo, D16).
Postcondición: cada operación queda guardada como `confirmada`, `rechazada` o
`en_conflicto` y es consultable; reenviar la misma operación no la repite.

Caso de uso COMPUESTO, con cuatro clases de control: `ProcesarLote` (recibe el lote y
resuelve cada operación), `ConsultarOperaciones` (el estado de lo enviado),
`DescargarPaquete` (E08: los datos que el cliente baja para operar sin conexión) y
`ResolverConflicto` (E08: un encargado fuerza o rechaza una operación en conflicto).

Cómo se procesa un lote (D12-D17):
- Las operaciones se toman en orden de `fecha_operacion` (la más antigua primero), no
  de llegada: si dos ventas piden la última unidad, gana la que ocurrió antes.
- Cada una reserva primero su clave única (empresa, operación): si ya existía es un
  reenvío y se devuelve lo guardado, sin repetir nada (idempotencia).
- Cada una se aplica en su propio SAVEPOINT y se CONFIRMA al terminar (commit por
  operación): una mala no tumba a las demás, y si la respuesta HTTP se pierde lo ya
  procesado está guardado. Un fallo inesperado no se guarda (`error_temporal`): el
  cliente reintenta con la misma `operacion_id`.
- Sin stock suficiente, la operación se deshace entera y queda `en_conflicto`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
import uuid

from sqlalchemy.orm import Session

from app.core.auditoria import (
    ACCION_RESOLVER_CONFLICTO,
    ACCION_SINCRONIZAR_LOTE,
    ENTIDAD_LOTE_SYNC,
    ENTIDAD_OPERACION_SYNC,
    ContextoAuditoria,
)
from app.catalogo import politicas as catalogo_politicas
from app.comercial import politicas as comercial_politicas
from app.core.config import get_settings
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import (
    ConflictoError,
    DomainError,
    NoEncontradoError,
    PermisoDenegadoError,
    StockInsuficienteError,
)
from app.core.permisos import PERMISO_SINCRONIZACION_SUPERVISAR, PERMISO_SINCRONIZAR
from app.core.security import permisos_de_usuario
from app.core.tenant import exigir_empresa
from app.core.tiempo import ahora_utc_naive, hoy_utc
from app.plataforma import politicas as plataforma_politicas
from app.sincronizacion import politicas
from app.sincronizacion.models import TIPOS, OperacionSync
from app.sincronizacion.repository import OperacionSyncRepository
from app.sincronizacion.schemas import (
    MAX_OPERACIONES_POR_LOTE,
    VERSION_CONTRATO,
    AlcancePromocionPaquete,
    CategoriaPaquete,
    ClientePaquete,
    ColorPaquete,
    EmpresaPaquete,
    FiltrosOperaciones,
    HorarioPaquete,
    LoteEntrada,
    LoteRespuesta,
    OperacionEntrada,
    OperacionSyncDetalle,
    OperacionSyncPagina,
    OperacionSyncRespuesta,
    PaqueteCatalogo,
    PaqueteClientes,
    PaqueteManifiesto,
    PaqueteStock,
    ProductoPaquete,
    PromocionPaquete,
    ReferenciaPaquete,
    ReglasPaquete,
    ResolverEntrada,
    ResultadoOperacion,
    ResumenLote,
    StockPaquete,
    SucursalPaquete,
    TallaPaquete,
    VariantePaquete,
)

logger = logging.getLogger("app.sincronizacion")


class _Lote:
    """Lo que se calcula UNA vez por lote y se pasa a cada operación."""

    def __init__(self, lote_id: str, usuario_id: int, dispositivo: str | None, bloqueo: str | None, permisos: set[str]):
        self.lote_id = lote_id
        self.usuario_id = usuario_id
        self.dispositivo = dispositivo
        self.bloqueo = bloqueo
        self.permisos = permisos


def _etiqueta(texto: str | None) -> str:
    """Un texto libre del cliente, apto para una línea de log (sin espacios ni símbolos)."""
    return re.sub(r"[^\w.\-]", "_", texto or "-")[:60]


class ProcesarLote:
    def __init__(self) -> None:
        self._operaciones = OperacionSyncRepository()

    def ejecutar(
        self, db: Session, usuario_id: int, lote: LoteEntrada, contexto: ContextoAuditoria | None = None
    ) -> LoteRespuesta:
        if lote.version_contrato != VERSION_CONTRATO:
            raise DomainError(f"version_contrato '{lote.version_contrato[:10]}' no soportada: use '{VERSION_CONTRATO}'")
        empresa_id = exigir_empresa(db)
        if lote.empresa_id is not None and lote.empresa_id != empresa_id:
            raise PermisoDenegadoError("El lote es de otra empresa")

        inicio = time.perf_counter()
        ctx = _Lote(
            lote_id=uuid.uuid4().hex[:8],
            usuario_id=usuario_id,
            dispositivo=lote.dispositivo,
            bloqueo=politicas.motivo_bloqueo(db),
            permisos=set(permisos_de_usuario(db, usuario_id)),
        )
        logger.info(
            "sync_lote_recibido lote=%s empresa=%s usuario=%s ops=%s disp=%s",
            ctx.lote_id, empresa_id, usuario_id, len(lote.operaciones), _etiqueta(lote.dispositivo),
        )  # fmt: skip

        # Orden total y estable: por cuándo OCURRIERON, y a igual fecha por posición en la petición.
        orden = sorted(
            range(len(lote.operaciones)),
            key=lambda i: (politicas.a_utc_naive(lote.operaciones[i].fecha_operacion), i),
        )
        resultados: dict[int, ResultadoOperacion] = {}
        for posicion in orden:
            resultados[posicion] = self._procesar_operacion(db, ctx, lote.operaciones[posicion])

        en_orden = [resultados[i] for i in range(len(lote.operaciones))]
        resumen = ResumenLote(
            total=len(en_orden),
            confirmadas=sum(r.estado == "confirmada" for r in en_orden),
            rechazadas=sum(r.estado == "rechazada" for r in en_orden),
            en_conflicto=sum(r.estado == "en_conflicto" for r in en_orden),
            errores_temporales=sum(r.estado == "error_temporal" for r in en_orden),
            duplicadas=sum(r.duplicada for r in en_orden),
        )
        self._registrar_bitacora(db, contexto, ctx, resumen, en_orden)
        milisegundos = int((time.perf_counter() - inicio) * 1000)
        logger.info(
            "sync_lote_fin lote=%s conf=%s rech=%s confl=%s dup=%s temp=%s ms=%s",
            ctx.lote_id, resumen.confirmadas, resumen.rechazadas, resumen.en_conflicto,
            resumen.duplicadas, resumen.errores_temporales, milisegundos,
        )  # fmt: skip
        return LoteRespuesta(procesado_en=ahora_utc_naive(), resumen=resumen, resultados=en_orden)

    # -- una operación --------------------------------------------------------------

    def _procesar_operacion(self, db: Session, ctx: _Lote, entrada: OperacionEntrada) -> ResultadoOperacion:
        inicio = time.perf_counter()
        resultado = self._resolver(db, ctx, entrada)
        logger.info(
            "sync_operacion lote=%s op=%s tipo=%s estado=%s motivo=%s dup=%s ms=%s",
            ctx.lote_id, str(entrada.operacion_id)[:8], _etiqueta(entrada.tipo), resultado.estado,
            resultado.motivo or "-", int(resultado.duplicada), int((time.perf_counter() - inicio) * 1000),
        )  # fmt: skip
        return resultado

    def _resolver(self, db: Session, ctx: _Lote, entrada: OperacionEntrada) -> ResultadoOperacion:
        if entrada.tipo not in TIPOS:
            # La tabla solo admite los tipos conocidos: no hay dónde guardarla. El rechazo es
            # determinista, así que reenviarla da lo mismo.
            return ResultadoOperacion(
                operacion_id=entrada.operacion_id,
                estado="rechazada",
                motivo=politicas.TIPO_NO_SOPORTADO,
                mensaje=f"El tipo de operación '{entrada.tipo[:20]}' no está soportado",
            )

        fecha_utc = politicas.a_utc_naive(entrada.fecha_operacion)
        sucursal_valida = politicas.sucursal_existe(db, entrada.sucursal_id)
        try:
            fila = self._operaciones.reservar_clave(
                db,
                sucursal_id=entrada.sucursal_id if sucursal_valida else None,
                usuario_id=ctx.usuario_id,
                operacion_id=entrada.operacion_id,
                tipo=entrada.tipo,
                estado="en_proceso",
                payload=entrada.payload,
                fecha_operacion=fecha_utc,
                dispositivo=ctx.dispositivo,
                intentos=1,
            )
        except Exception:
            logger.exception("sync_error lote=%s op=%s fase=reservar", ctx.lote_id, str(entrada.operacion_id)[:8])
            db.rollback()
            return self._error_temporal(entrada)

        if fila is None:
            return self._duplicada(db, ctx, entrada)

        estado, motivo, guardado = self._aplicar(db, ctx, entrada, fecha_utc, sucursal_valida)
        if estado == "error_temporal":
            return self._error_temporal(entrada)

        try:
            fila.estado = estado
            fila.motivo = motivo
            fila.resultado = guardado
            fila.procesada_en = ahora_utc_naive()
            db.commit()
        except Exception:
            logger.exception("sync_error lote=%s op=%s fase=confirmar", ctx.lote_id, str(entrada.operacion_id)[:8])
            db.rollback()
            return self._error_temporal(entrada)
        return politicas.construir_resultado(fila)

    def _aplicar(
        self, db: Session, ctx: _Lote, entrada: OperacionEntrada, fecha_utc, sucursal_valida: bool
    ) -> tuple[str, str | None, dict]:
        """Aplica la operación en su SAVEPOINT. Devuelve (estado, motivo, resultado a guardar).
        `error_temporal` = fallo inesperado: ya se revirtió todo y no se guarda nada."""
        try:
            with db.begin_nested():
                resolucion = self._ejecutar(db, ctx, entrada, fecha_utc, sucursal_valida)
        except StockInsuficienteError as error:
            # El SAVEPOINT ya deshizo todo: ni stock descontado ni apartado (D15).
            modelo = politicas.validar_payload(entrada.tipo, entrada.payload)
            faltantes = politicas.calcular_faltantes(
                db, entrada.sucursal_id, politicas.lineas_del_payload(entrada.tipo, modelo), error
            )
            return "en_conflicto", politicas.STOCK_INSUFICIENTE, {"mensaje": error.mensaje, "faltantes": faltantes}
        except politicas.RechazoOperacion as rechazo:
            return "rechazada", rechazo.motivo, self._guardado_de_rechazo(rechazo.mensaje, entrada, sucursal_valida)
        except DomainError as error:
            return "rechazada", politicas.REGLA_DE_NEGOCIO, self._guardado_de_rechazo(error.mensaje, entrada, sucursal_valida)
        except Exception:
            logger.exception("sync_error lote=%s op=%s fase=aplicar", ctx.lote_id, str(entrada.operacion_id)[:8])
            db.rollback()  # incluye la fila `en_proceso`: no queda nada guardado
            return "error_temporal", None, {}

        guardado = {
            "mensaje": None,
            "recurso": resolucion.recurso,
            "cambio": str(resolucion.cambio) if resolucion.cambio is not None else None,
            "avisos": resolucion.avisos,
            "faltantes": [],
        }
        return "confirmada", None, guardado

    @staticmethod
    def _guardado_de_rechazo(mensaje: str, entrada: OperacionEntrada, sucursal_valida: bool) -> dict:
        guardado: dict = {"mensaje": mensaje}
        if not sucursal_valida:
            guardado["sucursal_solicitada"] = entrada.sucursal_id  # la FK de la fila quedó en NULL
        return guardado

    def _ejecutar(self, db: Session, ctx: _Lote, entrada: OperacionEntrada, fecha_utc, sucursal_valida: bool):
        """Las reglas de la operación, en el orden de la especificación. Lanza `RechazoOperacion`
        o el error de negocio que corresponda; nada se confirma aquí."""
        if ctx.bloqueo is not None:
            raise politicas.RechazoOperacion(ctx.bloqueo, politicas.mensaje_de_bloqueo(ctx.bloqueo))
        modelo = politicas.validar_payload(entrada.tipo, entrada.payload)
        politicas.validar_fecha(fecha_utc)
        if not sucursal_valida:
            raise politicas.RechazoOperacion(politicas.SUCURSAL_INEXISTENTE, "La sucursal no existe")
        empleado = politicas.validar_actor(db, ctx.usuario_id, ctx.permisos, entrada.tipo, entrada.sucursal_id)
        if entrada.tipo == "venta_contado":
            return politicas.ejecutar_venta_contado(db, ctx.usuario_id, empleado, entrada.sucursal_id, modelo, fecha_utc)
        return politicas.ejecutar_reserva(db, ctx.usuario_id, entrada.sucursal_id, modelo, fecha_utc)

    # -- duplicadas y errores -----------------------------------------------------------

    def _duplicada(self, db: Session, ctx: _Lote, entrada: OperacionEntrada) -> ResultadoOperacion:
        """Ya se había procesado: se devuelve lo guardado (el payload nuevo se ignora)."""
        try:
            guardada = self._operaciones.obtener_por_operacion(db, entrada.operacion_id)
            self._operaciones.sumar_intento(db, guardada)
            db.commit()
            db.refresh(guardada)
            return politicas.construir_resultado(guardada, duplicada=True)
        except Exception:
            logger.exception("sync_error lote=%s op=%s fase=duplicada", ctx.lote_id, str(entrada.operacion_id)[:8])
            db.rollback()
            return self._error_temporal(entrada)

    @staticmethod
    def _error_temporal(entrada: OperacionEntrada) -> ResultadoOperacion:
        return ResultadoOperacion(
            operacion_id=entrada.operacion_id,
            estado="error_temporal",
            mensaje="No se pudo procesar ahora: reintente con la misma operación",
        )

    # -- bitácora ---------------------------------------------------------------------------

    @staticmethod
    def _registrar_bitacora(
        db: Session,
        contexto: ContextoAuditoria | None,
        ctx: _Lote,
        resumen: ResumenLote,
        resultados: list[ResultadoOperacion],
    ) -> None:
        """UNA fila por lote (la de cada operación ya está en `operacion_sync`). Sin payloads."""
        if contexto is None:
            return
        no_confirmadas = [
            {"operacion_id": str(r.operacion_id), "estado": r.estado, "motivo": r.motivo}
            for r in resultados
            if r.estado != "confirmada"
        ][:50]
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_LOTE_SYNC,
            None,
            ACCION_SINCRONIZAR_LOTE,
            {
                "lote": ctx.lote_id,
                "dispositivo": ctx.dispositivo,
                "resumen": resumen.model_dump(),
                "no_confirmadas": no_confirmadas,
            },
        )
        db.commit()


class ConsultarOperaciones:
    """El estado de lo enviado. Cada usuario ve las suyas; con `sincronizacion.supervisar`,
    las de su alcance (toda la empresa, o su sucursal si está limitado a una)."""

    def __init__(self) -> None:
        self._operaciones = OperacionSyncRepository()

    @staticmethod
    def _alcance(db: Session, usuario_id: int) -> tuple[bool, int | None]:
        """(supervisa, sucursal a la que está limitado o None si ve toda la empresa)."""
        if PERMISO_SINCRONIZACION_SUPERVISAR not in set(permisos_de_usuario(db, usuario_id)):
            return False, None
        return True, plataforma_politicas.sucursal_asignada(db, usuario_id)

    def listar(
        self, db: Session, usuario_id: int, filtros: FiltrosOperaciones, paginacion: ParametrosPaginacion
    ) -> OperacionSyncPagina:
        supervisa, sucursal_propia = self._alcance(db, usuario_id)
        sucursal_id = filtros.sucursal_id
        if supervisa:
            if sucursal_propia is not None:
                if sucursal_id is not None and sucursal_id != sucursal_propia:
                    raise PermisoDenegadoError("No tenés acceso a esa sucursal")
                sucursal_id = sucursal_propia
            solo_usuario = filtros.usuario_id
        else:
            solo_usuario = usuario_id  # sin supervisar solo ve lo propio, pida lo que pida
        filas, total = self._operaciones.listar(
            db,
            usuario_id=solo_usuario,
            sucursal_id=sucursal_id,
            estado=filtros.estado,
            tipo=filtros.tipo,
            desde=_desde(filtros.desde),
            hasta=_hasta(filtros.hasta),
            offset=paginacion.offset,
            limite=paginacion.tamanio,
        )
        return OperacionSyncPagina(
            total=total,
            pagina=paginacion.pagina,
            tamanio=paginacion.tamanio,
            items=[_a_respuesta(fila) for fila in filas],
        )

    def obtener(self, db: Session, usuario_id: int, operacion_id: uuid.UUID) -> OperacionSyncDetalle:
        """404 si no existe, es de otra empresa o está fuera del alcance de quien pregunta."""
        supervisa, sucursal_propia = self._alcance(db, usuario_id)
        fila = self._operaciones.obtener_por_operacion(db, operacion_id)
        if fila is None:
            raise NoEncontradoError("Operación no encontrada")
        if supervisa:
            if sucursal_propia is not None and fila.sucursal_id != sucursal_propia and fila.usuario_id != usuario_id:
                raise NoEncontradoError("Operación no encontrada")
        elif fila.usuario_id != usuario_id:
            raise NoEncontradoError("Operación no encontrada")
        # El payload (puede traer datos del cliente) solo lo ve quien supervisa.
        return OperacionSyncDetalle(**_a_respuesta(fila).model_dump(), payload=fila.payload if supervisa else None)


class DescargarPaquete:
    """El subconjunto de datos que el cliente descarga para operar sin conexión (E08): manifiesto
    (sucursales autorizadas con horario, referencias, promociones y reglas), catálogo con precios y
    descuentos ya calculados, stock conocido de UNA sucursal (con modo incremental) y datos mínimos
    de clientes. Todo se filtra por la empresa de la sesión y por la sucursal que el usuario puede
    operar; nunca sale un costo, un margen, un límite de stock ni un dato personal más allá del
    nombre, el apellido y el ci_nit del cliente. Cada respuesta lleva `generado_en`: el instante en
    que el servidor leyó los datos, con el que el cliente decide mostrar "información desactualizada".
    """

    # ---- manifiesto ----

    def manifiesto(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> PaqueteManifiesto:
        generado_en = ahora_utc_naive()
        empresa = plataforma_politicas.obtener_empresa(db, exigir_empresa(db))
        sucursales = plataforma_politicas.listar_sucursales_autorizadas(db, usuario_id, sucursal_id)
        categorias, tallas, colores = catalogo_politicas.listar_referencia_para_paquete(db)
        promociones = comercial_politicas.listar_promociones_vigentes(db, hoy_utc())
        ajustes = get_settings()
        return PaqueteManifiesto(
            generado_en=generado_en,
            aviso_desactualizado_horas=ajustes.sync_aviso_desactualizado_horas,
            empresa=EmpresaPaquete(id=empresa.id, codigo=empresa.codigo, nombre=empresa.nombre),
            sucursales=[
                SucursalPaquete(
                    id=sucursal.id,
                    codigo=sucursal.codigo,
                    nombre=sucursal.nombre,
                    direccion=sucursal.direccion,
                    es_deposito=sucursal.es_deposito,
                    horarios=[
                        HorarioPaquete(
                            dia_semana=horario.dia_semana,
                            hora_apertura=horario.hora_apertura,
                            hora_cierre=horario.hora_cierre,
                        )
                        for horario in horarios
                    ],
                )
                for sucursal, horarios in sucursales
            ],
            referencia=ReferenciaPaquete(
                categorias=[
                    CategoriaPaquete(id=c.id, nombre=c.nombre, categoria_padre_id=c.categoria_padre_id)
                    for c in categorias
                ],
                tallas=[TallaPaquete(id=t.id, codigo=t.codigo, orden=t.orden) for t in tallas],
                colores=[ColorPaquete(id=c.id, nombre=c.nombre, codigo_hex=c.codigo_hex) for c in colores],
            ),
            promociones_vigentes=[
                PromocionPaquete(
                    id=p.id,
                    nombre=p.nombre,
                    tipo=p.tipo,
                    valor=p.valor,
                    fecha_inicio=p.fecha_inicio,
                    fecha_fin=p.fecha_fin,
                    alcances=[
                        AlcancePromocionPaquete(
                            producto_id=a.producto_id, categoria_id=a.categoria_id, temporada_id=a.temporada_id
                        )
                        for a in p.alcances
                    ],
                )
                for p in promociones
            ],
            reglas=ReglasPaquete(
                metodos_pago_offline=["efectivo"],
                max_operaciones_por_lote=MAX_OPERACIONES_POR_LOTE,
                plazo_cambio_horas=plataforma_politicas.obtener_plazo_cambio_horas(db),
                cambios_y_devoluciones="solo_en_linea",
                reservas_offline="las registra el personal",
            ),
        )

    # ---- catálogo ----

    def catalogo(self, db: Session, desde_id: int, limite: int) -> PaqueteCatalogo:
        """Una página por clave. El descuento de cada variante sale de UNA consulta de promociones
        por página (no una por variante) con la misma regla que `calcular_linea`."""
        generado_en = ahora_utc_naive()
        productos, total, hay_mas = catalogo_politicas.listar_catalogo_para_paquete(db, desde_id, limite)
        promociones = comercial_politicas.promociones_vigentes_por_producto(
            db, [(p.id, p.categoria_id, p.temporada_id) for p in productos], hoy_utc()
        )
        items = []
        for producto in productos:
            variantes = []
            for variante in producto.variantes:
                precio = catalogo_politicas.obtener_precio_efectivo(variante)
                descuento = comercial_politicas.mejor_descuento(precio, promociones[producto.id])
                variantes.append(
                    VariantePaquete(
                        id=variante.id,
                        talla_id=variante.talla_id,
                        color_id=variante.color_id,
                        sku=variante.sku,
                        codigo_barras=variante.codigo_barras,
                        precio=comercial_politicas.redondear(precio),
                        descuento_unitario=comercial_politicas.redondear(descuento),
                    )
                )
            items.append(
                ProductoPaquete(
                    id=producto.id,
                    codigo=producto.codigo,
                    nombre=producto.nombre,
                    categoria_id=producto.categoria_id,
                    genero=producto.genero,
                    temporada_id=producto.temporada_id,
                    imagen_principal=catalogo_politicas.imagen_principal_url(producto),
                    variantes=variantes,
                )
            )
        return PaqueteCatalogo(
            generado_en=generado_en,
            total=total,
            siguiente_desde_id=productos[-1].id if hay_mas else None,
            items=items,
        )

    # ---- stock ----

    def stock(
        self,
        db: Session,
        usuario_id: int,
        sucursal_id: int | None,
        desde: dt.datetime | None,
        desde_variante_id: int,
        limite: int,
    ) -> PaqueteStock:
        """El stock conocido de UNA sucursal: `cantidad_disponible` (física menos reservada), nada
        más. Sin `desde` es la descarga completa; con `desde` solo las filas modificadas desde
        entonces menos el solape que fija el servidor (reaplicar una fila es inofensivo: el cliente
        la REEMPLAZA)."""
        generado_en = ahora_utc_naive()
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        if sucursal_id is None:
            # Alcance global: no hay una sucursal "propia" que asumir. Un dispositivo opera una a la vez.
            raise DomainError("Indique sucursal_id: el stock se descarga de una sucursal a la vez", 422)
        filas, hay_mas = catalogo_politicas.listar_stock_para_paquete(
            db, sucursal_id, None if desde is None else politicas.desde_a_utc_naive(desde), desde_variante_id, limite
        )
        return PaqueteStock(
            generado_en=generado_en,
            sucursal_id=sucursal_id,
            incremental=desde is not None,
            siguiente_desde_variante_id=filas[-1].variante_id if hay_mas else None,
            items=[
                StockPaquete(
                    variante_id=fila.variante_id,
                    cantidad_disponible=fila.cantidad_fisica - fila.cantidad_reservada,
                    actualizado_en=fila.actualizado_en,
                )
                for fila in filas
            ],
        )

    # ---- clientes ----

    def clientes(self, db: Session, desde_id: int, limite: int) -> PaqueteClientes:
        """Solo id, nombre, apellido y ci_nit (hace falta para facturar a un cliente conocido). Los
        cambios de un cliente existente no se detectan sin fecha de modificación: el cliente
        refresca la lista completa cuando el usuario lo pide."""
        generado_en = ahora_utc_naive()
        filas, total, hay_mas = plataforma_politicas.listar_clientes_minimos(db, desde_id, limite)
        return PaqueteClientes(
            generado_en=generado_en,
            total=total,
            siguiente_desde_id=filas[-1][0] if hay_mas else None,
            items=[ClientePaquete(id=id_, nombre=nombre, apellido=apellido, ci_nit=ci_nit) for id_, nombre, apellido, ci_nit in filas],
        )


class ResolverConflicto:
    """Un encargado (o el administrador) cierra una operación `en_conflicto` (D15, E08):

    - `forzar` (solo ventas): la prenda YA salió de la tienda y el cliente ya pagó en efectivo.
      Registra un ajuste POSITIVO de inventario por el faltante exacto (kardex con referencia
      `sync_forzada`) y confirma la venta tal como la hizo el operador original (su fecha, sus
      precios, a su nombre). El stock físico nunca queda negativo.
    - `rechazar` (cualquier tipo): la operación pasa a `rechazada` con el motivo escrito. Como el
      conflicto no dejó efectos, no hay nada que deshacer en el inventario; el efectivo cobrado en
      tienda se devuelve fuera del sistema.

    `confirmada` y `rechazada` son finales. Repetir la MISMA acción sobre una operación ya resuelta
    con ella devuelve lo guardado sin tocar nada; la acción contraria es 409. La fila se lee con
    bloqueo, así que dos resoluciones simultáneas se ponen en fila. Todo (ajuste, venta, estado,
    notificación al operador y bitácora) va en UNA transacción."""

    def __init__(self) -> None:
        self._operaciones = OperacionSyncRepository()

    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        operacion_id: uuid.UUID,
        datos: ResolverEntrada,
        contexto: ContextoAuditoria | None = None,
    ) -> OperacionSyncDetalle:
        sucursal_propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
        fila = self._operaciones.obtener_bloqueada(db, operacion_id)
        # Fuera de su alcance (otra empresa, o la sucursal de otro) se ve igual que inexistente.
        if fila is None or (sucursal_propia is not None and fila.sucursal_id != sucursal_propia):
            raise NoEncontradoError("Operación no encontrada")

        previa = (fila.resultado or {}).get("resolucion")
        if fila.estado != "en_conflicto":
            if previa is not None and previa.get("accion") == datos.accion:
                return _a_detalle(fila)  # ya resuelta así: idempotente
            raise ConflictoError(_mensaje_no_resoluble(fila, previa))

        if datos.accion == "forzar":
            self._forzar(db, usuario_id, fila, datos)
        else:
            self._rechazar(db, usuario_id, fila, datos)
        self._avisar_y_auditar(db, usuario_id, contexto, fila, datos)
        db.commit()
        db.refresh(fila)
        return _a_detalle(fila)

    # -- las dos acciones ---------------------------------------------------------------

    @staticmethod
    def _resolucion(usuario_id: int, datos: ResolverEntrada, ajustes: list[dict]) -> dict:
        return {
            "accion": datos.accion,
            "por_usuario_id": usuario_id,
            "en": ahora_utc_naive().replace(microsecond=0).isoformat(),
            "motivo": datos.motivo,
            "ajustes": ajustes,
        }

    def _forzar(self, db: Session, usuario_id: int, fila: OperacionSync, datos: ResolverEntrada) -> None:
        if fila.tipo != "venta_contado":
            raise ConflictoError("Las reservas en conflicto solo se pueden rechazar")
        try:
            payload = politicas.validar_payload(fila.tipo, fila.payload)
            with db.begin_nested():  # si algo falla, ni ajuste ni venta: la operación sigue en conflicto
                resolucion, ajustes = politicas.forzar_venta_contado(db, fila, payload, usuario_id)
        except politicas.RechazoOperacion as rechazo:
            raise ConflictoError(rechazo.mensaje) from None
        except DomainError as error:
            raise ConflictoError(error.mensaje) from None
        fila.estado = "confirmada"
        fila.motivo = None
        fila.procesada_en = ahora_utc_naive()
        fila.resultado = {
            "mensaje": None,
            "recurso": resolucion.recurso,
            "cambio": str(resolucion.cambio) if resolucion.cambio is not None else None,
            "avisos": resolucion.avisos,
            "faltantes": [],
            "resolucion": self._resolucion(usuario_id, datos, ajustes),
        }

    def _rechazar(self, db: Session, usuario_id: int, fila: OperacionSync, datos: ResolverEntrada) -> None:
        anterior = fila.resultado or {}
        fila.estado = "rechazada"
        fila.motivo = politicas.RECHAZADA_POR_ENCARGADO
        fila.procesada_en = ahora_utc_naive()
        fila.resultado = {
            "mensaje": datos.motivo,
            "recurso": None,
            "cambio": None,
            "avisos": [],
            "faltantes": anterior.get("faltantes", []),  # lo que faltaba, como contexto de la decisión
            "resolucion": self._resolucion(usuario_id, datos, []),
        }

    # -- aviso al operador y bitácora -------------------------------------------------------

    @staticmethod
    def _avisar_y_auditar(
        db: Session, usuario_id: int, contexto: ContextoAuditoria | None, fila: OperacionSync, datos: ResolverEntrada
    ) -> None:
        corto = str(fila.operacion_id)[:8]
        objeto = "venta" if fila.tipo == "venta_contado" else "reserva"
        if datos.accion == "forzar":
            mensaje = f"Tu {objeto} {corto} fue confirmada por un encargado"
        else:
            mensaje = f"Tu {objeto} {corto} fue rechazada por un encargado: {datos.motivo}"
        plataforma_politicas.crear_notificacion(
            db,
            fila.usuario_id,
            titulo="Operación sincronizada resuelta",
            mensaje=mensaje[:400],
            tipo="sincronizacion",
            referencia_id=fila.id,
            commit=False,
        )
        resolucion = fila.resultado["resolucion"]
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_OPERACION_SYNC,
            fila.id,
            ACCION_RESOLVER_CONFLICTO,
            {
                "operacion_id": str(fila.operacion_id),
                "tipo": fila.tipo,
                "decision": datos.accion,
                "ajustes": resolucion["ajustes"],
                "motivo": datos.motivo,
            },
        )


def _mensaje_no_resoluble(fila: OperacionSync, previa: dict | None) -> str:
    if previa is not None:
        resuelta = "confirmada" if previa.get("accion") == "forzar" else "rechazada"
        return f"La operación ya fue {resuelta} por un encargado y no se puede resolver de otra forma"
    if fila.estado == "en_proceso":
        return "La operación todavía se está procesando"
    return f"La operación está {fila.estado}: solo se resuelven las que están en conflicto"


def _desde(fecha: dt.date | None) -> dt.datetime | None:
    return None if fecha is None else dt.datetime.combine(fecha, dt.time.min)


def _hasta(fecha: dt.date | None) -> dt.datetime | None:
    """Exclusivo: las 00:00 del día siguiente (el `hasta` del filtro es inclusivo)."""
    return None if fecha is None else dt.datetime.combine(fecha + dt.timedelta(days=1), dt.time.min)


def _a_respuesta(fila: OperacionSync) -> OperacionSyncRespuesta:
    guardado = fila.resultado or {}
    return OperacionSyncRespuesta(
        operacion_id=fila.operacion_id,
        tipo=fila.tipo,
        estado=fila.estado,
        motivo=fila.motivo,
        mensaje=guardado.get("mensaje"),
        sucursal_id=fila.sucursal_id,
        usuario_id=fila.usuario_id,
        fecha_operacion=fila.fecha_operacion,
        recibida_en=fila.recibida_en,
        procesada_en=fila.procesada_en,
        intentos=fila.intentos,
        dispositivo=fila.dispositivo,
        recurso=guardado.get("recurso"),
        cambio=guardado.get("cambio"),
        avisos=guardado.get("avisos", []),
        faltantes=guardado.get("faltantes", []),
        resolucion=guardado.get("resolucion"),
    )


def _a_detalle(fila: OperacionSync) -> OperacionSyncDetalle:
    """El detalle CON payload, para quien supervisa o resuelve."""
    return OperacionSyncDetalle(**_a_respuesta(fila).model_dump(), payload=fila.payload)

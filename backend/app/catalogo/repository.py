import datetime as dt
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import func, or_, select, text, tuple_, update
from sqlalchemy.orm import Session, selectinload

from app.catalogo.models import (
    ActivoProbador,
    Categoria,
    Coleccion,
    Color,
    Favorito,
    Material,
    MovimientoInventario,
    OrdenCompra,
    OrdenCompraDetalle,
    ProbadorGeneracion,
    Producto,
    ProductoImagen,
    ProductoProveedor,
    ProductoVariante,
    Proveedor,
    Recepcion,
    RecepcionDetalle,
    Stock,
    TablaMedida,
    Talla,
    Temporada,
    TipoMovimiento,
    Transferencia,
)
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    ColeccionActualizar,
    ColeccionCrear,
    ColorActualizar,
    ColorCrear,
    FiltrosCatalogo,
    MaterialActualizar,
    MaterialCrear,
    ProductoActualizar,
    ProductoCrear,
    ProveedorActualizar,
    ProveedorCrear,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    TallaActualizar,
    TallaCrear,
    TemporadaActualizar,
    TemporadaCrear,
    VarianteActualizar,
)
from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave
from app.core.tenant import condicion_empresa


# ---- Catálogo ----


def _id_por_texto(db: Session, columna_id, columna_texto, texto: str | None) -> int | None:
    """Id de la primera fila cuyo texto coincide sin distinguir mayúsculas
    (igualdad exacta, no patrón: el texto puede venir de un LLM). No filtra
    por `activo`."""
    if not texto:
        return None
    return db.scalar(select(columna_id).where(func.lower(columna_texto) == texto.strip().lower()))


class CategoriaRepository(CRUDBase[Categoria, CategoriaCrear, CategoriaActualizar]):
    def __init__(self) -> None:
        super().__init__(Categoria)

    def listar_hijos(self, db: Session, categoria_id: int) -> list[Categoria]:
        return list(
            db.scalars(
                select(Categoria).where(
                    Categoria.categoria_padre_id == categoria_id, Categoria.activo.is_(True)
                )
            )
        )

    def tiene_productos_activos(self, db: Session, categoria_id: int) -> bool:
        return (
            db.scalar(select(Producto).where(Producto.categoria_id == categoria_id, Producto.activo.is_(True)))
            is not None
        )

    def listar_nombres_activos(self, db: Session) -> list[str]:
        return list(db.scalars(select(Categoria.nombre).where(Categoria.activo.is_(True))))

    def id_por_nombre(self, db: Session, nombre: str | None) -> int | None:
        return _id_por_texto(db, Categoria.id, Categoria.nombre, nombre)


class TallaRepository(CRUDBaseSinActivo[Talla, TallaCrear, TallaActualizar]):
    def __init__(self) -> None:
        super().__init__(Talla)

    def listar(self, db, paginacion, filtros=None):
        consulta = self._aplicar_alcance(self._consulta_base())
        consulta = consulta.order_by(Talla.orden, Talla.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def obtener_por_codigo(self, db: Session, codigo: str) -> Talla | None:
        return db.scalar(select(Talla).where(Talla.codigo == codigo))

    def listar_por_ids(self, db: Session, talla_ids: Iterable[int]) -> dict[int, Talla]:
        ids = set(talla_ids)
        if not ids:
            return {}
        return {talla.id: talla for talla in db.scalars(select(Talla).where(Talla.id.in_(ids)))}

    def listar_codigos(self, db: Session) -> list[str]:
        return list(db.scalars(select(Talla.codigo)))

    def id_por_codigo(self, db: Session, codigo: str | None) -> int | None:
        return _id_por_texto(db, Talla.id, Talla.codigo, codigo)

    def crear(self, db: Session, datos: TallaCrear, commit: bool = True) -> Talla:
        if self.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una talla con ese código")
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: TallaActualizar, commit: bool = True) -> Talla:
        if datos.codigo is not None:
            existente = self.obtener_por_codigo(db, datos.codigo)
            if existente is not None and existente.id != id_:
                raise ConflictoError("Ya existe una talla con ese código")
        return super().actualizar(db, id_, datos, commit)


class ColorRepository(CRUDBaseSinActivo[Color, ColorCrear, ColorActualizar]):
    def __init__(self) -> None:
        super().__init__(Color)

    def listar_por_ids(self, db: Session, color_ids: Iterable[int]) -> dict[int, Color]:
        ids = set(color_ids)
        if not ids:
            return {}
        return {color.id: color for color in db.scalars(select(Color).where(Color.id.in_(ids)))}

    def listar_nombres(self, db: Session) -> list[str]:
        return list(db.scalars(select(Color.nombre)))

    def id_por_nombre(self, db: Session, nombre: str | None) -> int | None:
        return _id_por_texto(db, Color.id, Color.nombre, nombre)


class MaterialRepository(CRUDBaseSinActivo[Material, MaterialCrear, MaterialActualizar]):
    def __init__(self) -> None:
        super().__init__(Material)

    def listar_nombres(self, db: Session) -> list[str]:
        return list(db.scalars(select(Material.nombre)))

    def id_por_nombre(self, db: Session, nombre: str | None) -> int | None:
        return _id_por_texto(db, Material.id, Material.nombre, nombre)


class TemporadaRepository(CRUDBase[Temporada, TemporadaCrear, TemporadaActualizar]):
    def __init__(self) -> None:
        super().__init__(Temporada)

    def listar_nombres_vigentes(self, db: Session) -> list[str]:
        return list(db.scalars(select(Temporada.nombre).where(Temporada.activo.is_(True)).distinct()))

    def id_por_nombre(self, db: Session, nombre: str | None) -> int | None:
        return _id_por_texto(db, Temporada.id, Temporada.nombre, nombre)

    def _existe_duplicada(self, db: Session, nombre: str, anio: int, excluir_id: int | None = None) -> bool:
        consulta = select(Temporada).where(Temporada.nombre == nombre, Temporada.anio == anio)
        if excluir_id is not None:
            consulta = consulta.where(Temporada.id != excluir_id)
        return db.scalar(consulta) is not None

    def crear(self, db: Session, datos: TemporadaCrear, commit: bool = True) -> Temporada:
        if self._existe_duplicada(db, datos.nombre, datos.anio):
            raise ConflictoError("Ya existe una temporada con ese nombre y año")
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: TemporadaActualizar, commit: bool = True) -> Temporada:
        if datos.nombre is not None or datos.anio is not None:
            actual = self.obtener(db, id_)
            nombre = datos.nombre if datos.nombre is not None else actual.nombre
            anio = datos.anio if datos.anio is not None else actual.anio
            if self._existe_duplicada(db, nombre, anio, excluir_id=id_):
                raise ConflictoError("Ya existe una temporada con ese nombre y año")
        return super().actualizar(db, id_, datos, commit)


class ColeccionRepository(CRUDBase[Coleccion, ColeccionCrear, ColeccionActualizar]):
    def __init__(self) -> None:
        super().__init__(Coleccion)


def _variantes_con_stock(sucursal_id: int | None = None):
    """Subconsulta de los `variante_id` con stock disponible (> 0), en
    cualquier sucursal o en `sucursal_id`. La comparten `buscar_publico`
    (como subconsulta, sin traer los ids a Python) y
    `StockRepository.listar_variantes_con_stock`."""
    consulta = select(Stock.variante_id).where(Stock.cantidad_disponible > 0)
    if sucursal_id is not None:
        consulta = consulta.where(Stock.sucursal_id == sucursal_id)
    return consulta


class ProductoRepository(CRUDBase[Producto, ProductoCrear, ProductoActualizar]):
    def __init__(self) -> None:
        super().__init__(Producto)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Producto | None:
        return db.scalar(select(Producto).where(Producto.codigo == codigo))

    def crear(
        self, db: Session, datos: ProductoCrear, creado_por: int | None, commit: bool = True
    ) -> Producto:
        # ProductoCrear trae tallas_ids/colores_ids para la combinatoria de
        # variantes (las resuelve GestionarProductos); acá solo se persiste la fila
        # de producto en sí.
        campos = datos.model_dump(exclude={"tallas_ids", "colores_ids"})
        existente = self.obtener_por_codigo(db, datos.codigo)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un producto con ese código")
            for campo, valor in campos.items():
                setattr(existente, campo, valor)
            existente.activo = True
            confirmar(db, commit)
            db.refresh(existente)
            return existente
        producto = Producto(**campos, creado_por=creado_por)
        db.add(producto)
        confirmar(db, commit)
        db.refresh(producto)
        return producto

    def listar_publico(self, db: Session, paginacion: ParametrosPaginacion) -> list[Producto]:
        consulta = (
            select(Producto)
            .where(Producto.activo.is_(True))
            .options(selectinload(Producto.imagenes))
            .order_by(Producto.id)
            .offset(paginacion.offset)
            .limit(paginacion.tamanio)
        )
        return list(db.scalars(consulta).all())

    def buscar_publico(
        self, db: Session, paginacion: ParametrosPaginacion, filtros: FiltrosCatalogo
    ) -> list[Producto]:
        consulta = select(Producto).where(Producto.activo.is_(True)).options(selectinload(Producto.imagenes))

        if filtros.texto:
            patron = f"%{filtros.texto}%"
            consulta = consulta.where(or_(Producto.nombre.ilike(patron), Producto.descripcion.ilike(patron)))
        if filtros.categoria_id is not None:
            consulta = consulta.where(Producto.categoria_id == filtros.categoria_id)
        if filtros.material_id is not None:
            consulta = consulta.where(Producto.material_id == filtros.material_id)
        if filtros.temporada_id is not None:
            consulta = consulta.where(Producto.temporada_id == filtros.temporada_id)
        if filtros.genero is not None:
            consulta = consulta.where(Producto.genero == filtros.genero)
        if filtros.precio_min is not None:
            consulta = consulta.where(Producto.precio_base >= filtros.precio_min)
        if filtros.precio_max is not None:
            consulta = consulta.where(Producto.precio_base <= filtros.precio_max)

        necesita_variante = (
            filtros.talla_id is not None or filtros.color_id is not None or filtros.solo_disponibles
        )
        if necesita_variante:
            consulta = consulta.join(ProductoVariante, ProductoVariante.producto_id == Producto.id)
            if filtros.talla_id is not None:
                consulta = consulta.where(ProductoVariante.talla_id == filtros.talla_id)
            if filtros.color_id is not None:
                consulta = consulta.where(ProductoVariante.color_id == filtros.color_id)
            if filtros.solo_disponibles:
                consulta = consulta.where(
                    ProductoVariante.activo.is_(True),
                    ProductoVariante.id.in_(_variantes_con_stock(filtros.sucursal_id)),
                )
            consulta = consulta.distinct()

        consulta = consulta.order_by(Producto.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def listar_por_ids_publico(self, db: Session, producto_ids: list[int]) -> list[Producto]:
        """Para GET /catalogo/variantes/detalle: resuelve foto de producto
        para un lote de producto_id (lo usa 'stock bajo' del dashboard,
        que ya conoce el producto_id vía inventario/alertas)."""
        consulta = (
            select(Producto).where(Producto.id.in_(set(producto_ids))).options(selectinload(Producto.imagenes))
        )
        return list(db.scalars(consulta).all())

    def obtener_publico_detalle(self, db: Session, producto_id: int) -> Producto:
        producto = db.scalar(
            select(Producto)
            .where(Producto.id == producto_id, Producto.activo.is_(True))
            .options(selectinload(Producto.variantes), selectinload(Producto.imagenes))
        )
        if producto is None:
            raise NoEncontradoError("Producto no encontrado")
        return producto


class VarianteRepository(CRUDBase[ProductoVariante, VarianteActualizar, VarianteActualizar]):
    def __init__(self) -> None:
        super().__init__(ProductoVariante)

    def listar_por_producto(self, db: Session, producto_id: int) -> list[ProductoVariante]:
        return list(
            db.scalars(
                select(ProductoVariante).where(
                    ProductoVariante.producto_id == producto_id, ProductoVariante.activo.is_(True)
                )
            )
        )

    def obtener_por_combinacion(
        self, db: Session, producto_id: int, talla_id: int, color_id: int
    ) -> ProductoVariante | None:
        return db.scalar(
            select(ProductoVariante).where(
                ProductoVariante.producto_id == producto_id,
                ProductoVariante.talla_id == talla_id,
                ProductoVariante.color_id == color_id,
            )
        )

    def listar_ids_de_temporada_vigente(self, db: Session) -> set[int]:
        """Variantes activas de productos activos cuya temporada está vigente."""
        return set(
            db.scalars(
                select(ProductoVariante.id)
                .join(Producto, Producto.id == ProductoVariante.producto_id)
                .join(Temporada, Temporada.id == Producto.temporada_id)
                .where(ProductoVariante.activo.is_(True), Producto.activo.is_(True), Temporada.activo.is_(True))
            )
        )

    def listar_ids_por_producto(self, db: Session, producto_id: int) -> set[int]:
        return set(db.scalars(select(ProductoVariante.id).where(ProductoVariante.producto_id == producto_id)))

    def listar_productos_por_variantes(
        self, db: Session, variante_ids: list[int]
    ) -> list[tuple[int, Producto]]:
        """(variante_id, Producto con imágenes) por cada variante pedida."""
        filas = db.execute(
            select(ProductoVariante.id, Producto)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .where(ProductoVariante.id.in_(variante_ids))
            .options(selectinload(Producto.imagenes))
        ).all()
        return [(variante_id, producto) for variante_id, producto in filas]

    def obtener_por_sku(self, db: Session, sku: str) -> ProductoVariante | None:
        return db.scalar(select(ProductoVariante).where(ProductoVariante.sku == sku))

    def listar_para_detalle_publico(
        self, db: Session, variante_ids: list[int]
    ) -> list[tuple[ProductoVariante, Producto, Talla, Color]]:
        """Para GET /catalogo/variantes/detalle: resuelve producto+imagen
        (+talla/color, para el carrito de la app) para un lote de
        variantes, lo usa 'se vendió hoy' del dashboard (una Venta solo
        trae variante_id, no nombre ni foto) y el carrito de compra de
        Flutter (mismo problema: CarritoDetalleRespuesta solo trae
        variante_id)."""
        consulta = (
            select(ProductoVariante, Producto, Talla, Color)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .join(Talla, Talla.id == ProductoVariante.talla_id)
            .join(Color, Color.id == ProductoVariante.color_id)
            .where(ProductoVariante.id.in_(set(variante_ids)))
            .options(selectinload(Producto.imagenes))
        )
        return [tuple(fila) for fila in db.execute(consulta).all()]

    def obtener_por_codigo_barras(self, db: Session, codigo_barras: str) -> ProductoVariante | None:
        return db.scalar(select(ProductoVariante).where(ProductoVariante.codigo_barras == codigo_barras))

    def buscar_para_venta(
        self, db: Session, texto: str, limite: int = 20
    ) -> list[tuple[ProductoVariante, Producto, Talla, Color]]:
        """Para la caja (POS): resuelve una variante por código de barras
        exacto (lector físico) o texto libre sobre sku/nombre/código de
        producto. `productos_router` es de administración (requiere
        catalogo.gestionar, ver su docstring); esto lo usa el cajero, que
        solo tiene catalogo.ver."""
        patron = f"%{texto}%"
        consulta = (
            select(ProductoVariante, Producto, Talla, Color)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .join(Talla, Talla.id == ProductoVariante.talla_id)
            .join(Color, Color.id == ProductoVariante.color_id)
            .where(ProductoVariante.activo.is_(True), Producto.activo.is_(True))
            .where(
                or_(
                    ProductoVariante.codigo_barras == texto,
                    ProductoVariante.sku.ilike(patron),
                    Producto.nombre.ilike(patron),
                    Producto.codigo.ilike(patron),
                )
            )
            .order_by(Producto.nombre)
            .limit(limite)
        )
        return [tuple(fila) for fila in db.execute(consulta).all()]


class TablaMedidaRepository:
    """No hereda de CRUDBase: tabla_medida no tiene columna `activo`, las
    filas se eliminan físicamente (igual que horario_sucursal)."""

    def listar_por_producto(self, db: Session, producto_id: int) -> list[TablaMedida]:
        return list(db.scalars(select(TablaMedida).where(TablaMedida.producto_id == producto_id)))

    def listar_por_categoria(self, db: Session, categoria_id: int) -> list[TablaMedida]:
        return list(db.scalars(select(TablaMedida).where(TablaMedida.categoria_id == categoria_id)))

    def obtener(self, db: Session, producto_id: int, medida_id: int) -> TablaMedida:
        medida = db.scalar(
            select(TablaMedida).where(TablaMedida.id == medida_id, TablaMedida.producto_id == producto_id)
        )
        if medida is None:
            raise NoEncontradoError("Medida no encontrada")
        return medida

    def crear(self, db: Session, producto_id: int, datos: TablaMedidaCrear) -> TablaMedida:
        medida = TablaMedida(producto_id=producto_id, **datos.model_dump())
        db.add(medida)
        db.commit()
        db.refresh(medida)
        return medida

    def actualizar(
        self, db: Session, producto_id: int, medida_id: int, datos: TablaMedidaActualizar
    ) -> TablaMedida:
        medida = self.obtener(db, producto_id, medida_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(medida, campo, valor)
        db.commit()
        db.refresh(medida)
        return medida

    def eliminar(self, db: Session, producto_id: int, medida_id: int) -> None:
        medida = self.obtener(db, producto_id, medida_id)
        db.delete(medida)
        db.commit()


class ImagenRepository:
    """No hereda de CRUDBase: producto_imagen no tiene columna `activo`,
    las filas se eliminan físicamente (después de borrar el archivo real
    en Cloudinary, ver GestionarProductos.eliminar_imagen)."""

    def listar_por_producto(self, db: Session, producto_id: int) -> list[ProductoImagen]:
        return list(
            db.scalars(
                select(ProductoImagen)
                .where(ProductoImagen.producto_id == producto_id)
                .order_by(ProductoImagen.orden)
            )
        )

    def obtener(self, db: Session, imagen_id: int) -> ProductoImagen:
        imagen = obtener_por_clave(db, ProductoImagen, imagen_id)
        if imagen is None:
            raise NoEncontradoError("Imagen no encontrada")
        return imagen

    def crear(
        self, db: Session, producto_id: int, public_id: str, color_id: int | None, orden: int
    ) -> ProductoImagen:
        imagen = ProductoImagen(producto_id=producto_id, color_id=color_id, url=public_id, orden=orden)
        db.add(imagen)
        db.commit()
        db.refresh(imagen)
        return imagen

    def eliminar(self, db: Session, imagen_id: int) -> None:
        imagen = self.obtener(db, imagen_id)
        db.delete(imagen)
        db.commit()

    def marcar_principal(self, db: Session, imagen: ProductoImagen) -> ProductoImagen:
        db.execute(
            update(ProductoImagen)
            .where(ProductoImagen.producto_id == imagen.producto_id, ProductoImagen.id != imagen.id)
            .values(es_principal=False)
        )
        imagen.es_principal = True
        db.commit()
        db.refresh(imagen)
        return imagen


class FavoritoRepository:
    """Composite PK (cliente_id, variante_id), sin columna `activo`."""

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[Favorito]:
        return list(
            db.scalars(
                select(Favorito)
                .where(Favorito.cliente_id == cliente_id)
                .options(selectinload(Favorito.variante).selectinload(ProductoVariante.producto))
                .order_by(Favorito.creado_en.desc())
            )
        )

    def obtener(self, db: Session, cliente_id: int, variante_id: int) -> Favorito | None:
        return obtener_por_clave(db, Favorito, (cliente_id, variante_id))

    def agregar(self, db: Session, cliente_id: int, variante_id: int) -> Favorito:
        existente = self.obtener(db, cliente_id, variante_id)
        if existente is not None:
            return existente  # agregar un favorito ya agregado es idempotente
        favorito = Favorito(cliente_id=cliente_id, variante_id=variante_id)
        db.add(favorito)
        db.commit()
        db.refresh(favorito)
        return favorito

    def quitar(self, db: Session, cliente_id: int, variante_id: int) -> None:
        favorito = self.obtener(db, cliente_id, variante_id)
        if favorito is None:
            raise NoEncontradoError("Favorito no encontrado")
        db.delete(favorito)
        db.commit()


# ---- Inventario ----


# La misma vista que documenta docs/fashionstore_esquema.sql. Cruza
# producto/producto_variante/talla/color y stock (de este paquete) con
# sucursal (de `plataforma`): es una vista de reportes ya definida en el
# esquema, no una consulta cruda del código a tablas de otro paquete, así
# que vive acá igual que la migración que la crea.
# NO EDITAR: la usa la migración 14ba109668a9 (congelada como V1). La vista
# con empresa_id es VW_INVENTARIO_CONSOLIDADO_V2_SQL.
VW_INVENTARIO_CONSOLIDADO_SQL = """
CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN talla t             ON t.id = v.talla_id
JOIN color c             ON c.id = v.color_id
JOIN sucursal s          ON s.id = st.sucursal_id
"""

# V2 (multitenant, E01): igual que V1 más `empresa_id` AL FINAL de la lista de
# columnas y cada JOIN exige la misma empresa. La crea la migración
# multitenant_empresa_plan_suscripcion, que lleva este SQL copiado (embebido);
# tests/plataforma/test_vistas_empresa.py comprueba que ambos coinciden.
VW_INVENTARIO_CONSOLIDADO_V2_SQL = """
CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario,
        st.empresa_id       AS empresa_id
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id AND v.empresa_id = st.empresa_id
JOIN producto p          ON p.id = v.producto_id AND p.empresa_id = st.empresa_id
JOIN talla t             ON t.id = v.talla_id AND t.empresa_id = st.empresa_id
JOIN color c             ON c.id = v.color_id AND c.empresa_id = st.empresa_id
JOIN sucursal s          ON s.id = st.sucursal_id AND s.empresa_id = st.empresa_id
"""


class StockRepository:
    """No hereda de CRUDBase: `stock` no tiene columna `activo` (una fila
    de stock existe o no existe; no se "desactiva") y su creación necesita
    ir bloqueada junto con el resto de `registrar_movimiento`/`reservar_stock`,
    algo que el CRUD genérico no contempla."""

    def obtener_o_crear_bloqueado(self, db: Session, variante_id: int, sucursal_id: int) -> Stock:
        """Devuelve la fila de stock lista para modificar dentro de la
        transacción actual. En Postgres la trae con SELECT FOR UPDATE para
        evitar condiciones de carrera entre movimientos concurrentes sobre
        la misma variante+sucursal; en SQLite (tests) no existe FOR UPDATE,
        así que se omite ahí."""
        consulta = select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        stock = db.scalars(consulta).one_or_none()
        if stock is None:
            stock = Stock(
                variante_id=variante_id,
                sucursal_id=sucursal_id,
                cantidad_fisica=0,
                cantidad_reservada=0,
                costo_promedio=Decimal("0"),
            )
            db.add(stock)
            db.flush()
        return stock

    def bloquear_existentes(self, db: Session, claves: list[tuple[int, int]]) -> list[Stock]:
        """Bloquea de una vez las filas de stock que YA existen para las
        claves (variante_id, sucursal_id) dadas, en orden ascendente por esas
        dos columnas (ORDER BY + FOR UPDATE en Postgres: las filas se bloquean
        en el orden en que se devuelven). Dos lotes concurrentes con las mismas
        variantes en distinto orden de líneas toman así los bloqueos en el
        mismo orden y no se interbloquean (deadlock). No crea filas ni lanza
        error por las que falten: eso lo sigue haciendo
        `obtener_o_crear_bloqueado` línea por línea. Usar vía
        `catalogo.politicas.bloquear_stock_en_orden`."""
        if not claves:
            return []
        consulta = (
            select(Stock)
            .where(tuple_(Stock.variante_id, Stock.sucursal_id).in_(claves))
            .order_by(Stock.variante_id, Stock.sucursal_id)
        )
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        return list(db.scalars(consulta.execution_options(populate_existing=True)))

    def obtener(self, db: Session, stock_id: int) -> Stock:
        stock = obtener_por_clave(db, Stock, stock_id)
        if stock is None:
            raise NoEncontradoError("Stock no encontrado")
        return stock

    def obtener_por_variante_sucursal(self, db: Session, variante_id: int, sucursal_id: int) -> Stock | None:
        return db.scalar(
            select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        )

    def listar_por_variante(self, db: Session, variante_id: int) -> list[Stock]:
        return list(db.scalars(select(Stock).where(Stock.variante_id == variante_id)))

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Stock]:
        return list(
            db.scalars(select(Stock).where(Stock.sucursal_id == sucursal_id).order_by(Stock.variante_id))
        )

    def listar_variantes_con_stock(self, db: Session, sucursal_id: int | None = None) -> set[int]:
        """Para `inteligencia` (P6.2) y `catalogo` (CU-06, `solo_disponibles`):
        variantes con stock disponible, en cualquier sucursal si no se pasa
        `sucursal_id`, o en esa sola si se pasa."""
        return set(db.scalars(_variantes_con_stock(sucursal_id).distinct()))

    def disponible_por_variante(
        self, db: Session, variante_ids: Iterable[int], sucursal_id: int | None = None
    ) -> dict[int, int]:
        """`variante_id` -> unidades disponibles (suma entre sucursales, o la
        de `sucursal_id` si se pasa) en una sola consulta agrupada. Una
        variante sin stock registrado no aparece en el resultado (el llamador
        la cuenta como 0)."""
        ids = set(variante_ids)
        if not ids:
            return {}
        consulta = (
            select(Stock.variante_id, func.sum(Stock.cantidad_disponible))
            .where(Stock.variante_id.in_(ids))
            .group_by(Stock.variante_id)
        )
        if sucursal_id is not None:
            consulta = consulta.where(Stock.sucursal_id == sucursal_id)
        return {variante_id: int(total) for variante_id, total in db.execute(consulta)}

    def actualizar_limites(
        self, db: Session, stock: Stock, stock_minimo: int | None, stock_maximo: int | None, commit: bool = True
    ) -> Stock:
        if stock_minimo is not None:
            stock.stock_minimo = stock_minimo
        if stock_maximo is not None:
            stock.stock_maximo = stock_maximo
        confirmar(db, commit)
        db.refresh(stock)
        return stock


class MovimientoRepository:
    """Libro inmutable: solo `crear` y consultas de lectura. No hay
    `actualizar` ni `eliminar` a propósito (ver models.MovimientoInventario)."""

    def crear(self, db: Session, movimiento: MovimientoInventario) -> MovimientoInventario:
        db.add(movimiento)
        db.flush()
        return movimiento

    def listar_por_variante_sucursal(
        self, db: Session, variante_id: int, sucursal_id: int
    ) -> list[MovimientoInventario]:
        return list(
            db.scalars(
                select(MovimientoInventario)
                .where(
                    MovimientoInventario.variante_id == variante_id,
                    MovimientoInventario.sucursal_id == sucursal_id,
                )
                .order_by(MovimientoInventario.id)
            )
        )


class TipoMovimientoRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> TipoMovimiento:
        tipo = db.scalar(select(TipoMovimiento).where(TipoMovimiento.codigo == codigo))
        if tipo is None:
            raise NoEncontradoError(f"Tipo de movimiento '{codigo}' no encontrado")
        return tipo

    def listar(self, db: Session) -> list[TipoMovimiento]:
        return list(db.scalars(select(TipoMovimiento).order_by(TipoMovimiento.id)))


class TransferenciaRepository:
    """No hereda de CRUDBase: `transferencia` no tiene columna `activo`,
    su ciclo de vida es la máquina de estados `estado` (pendiente ->
    en_transito -> recibida, o anulada), no un borrado lógico."""

    def crear(self, db: Session, transferencia: Transferencia, commit: bool = True) -> Transferencia:
        db.add(transferencia)
        confirmar(db, commit)
        db.refresh(transferencia)
        return transferencia

    def obtener_por_codigo(self, db: Session, codigo: str) -> Transferencia | None:
        return db.scalar(select(Transferencia).where(Transferencia.codigo == codigo))

    def obtener(self, db: Session, transferencia_id: int) -> Transferencia:
        transferencia = db.scalar(
            select(Transferencia)
            .where(Transferencia.id == transferencia_id)
            .options(selectinload(Transferencia.detalle))
        )
        if transferencia is None:
            raise NoEncontradoError("Transferencia no encontrada")
        return transferencia

    def obtener_bloqueado(self, db: Session, transferencia_id: int) -> Transferencia:
        """Igual que obtener(), pero con SELECT FOR UPDATE (Postgres) y
        populate_existing=True: dos envíos (o dos recepciones) simultáneos de
        la misma transferencia se serializan y el segundo ve el estado ya
        cambiado en vez de pasar ambos el chequeo. Mismo patrón que
        comercial.repository.VentaRepository.obtener_bloqueado."""
        consulta = (
            select(Transferencia)
            .where(Transferencia.id == transferencia_id)
            .options(selectinload(Transferencia.detalle))
        )
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        transferencia = db.scalars(consulta.execution_options(populate_existing=True)).one_or_none()
        if transferencia is None:
            raise NoEncontradoError("Transferencia no encontrada")
        return transferencia

    def listar(self, db: Session, sucursal_id: int | None = None) -> list[Transferencia]:
        consulta = select(Transferencia).options(selectinload(Transferencia.detalle)).order_by(
            Transferencia.id.desc()
        )
        if sucursal_id is not None:
            consulta = consulta.where(
                (Transferencia.sucursal_origen_id == sucursal_id)
                | (Transferencia.sucursal_destino_id == sucursal_id)
            )
        return list(db.scalars(consulta))


def _filas_a_dicts(db: Session, consulta: str, parametros: dict) -> list[dict]:
    filas = db.execute(text(consulta), parametros).mappings().all()
    return [dict(fila) for fila in filas]


def consolidado(db: Session, sucursal_id: int | None = None, producto_id: int | None = None) -> list[dict]:
    condicion_tenant, parametros = condicion_empresa(db)
    condiciones = [condicion_tenant]
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    if producto_id is not None:
        condiciones.append("producto_id = :producto_id")
        parametros["producto_id"] = producto_id
    consulta = "SELECT * FROM vw_inventario_consolidado WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY producto_id, variante_id, sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)


def alertas(db: Session, sucursal_id: int | None = None) -> list[dict]:
    condicion_tenant, parametros = condicion_empresa(db)
    condiciones = [condicion_tenant, "cantidad_disponible <= stock_minimo"]
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    consulta = "SELECT * FROM vw_inventario_consolidado WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY producto_id, variante_id, sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)


def valuacion(db: Session, sucursal_id: int | None = None) -> list[dict]:
    condicion_tenant, parametros = condicion_empresa(db)
    consulta = (
        "SELECT sucursal_id, sucursal, SUM(valor_inventario) AS valor_total "
        "FROM vw_inventario_consolidado WHERE " + condicion_tenant
    )
    if sucursal_id is not None:
        consulta += " AND sucursal_id = :sucursal_id"
        parametros["sucursal_id"] = sucursal_id
    consulta += " GROUP BY sucursal_id, sucursal ORDER BY sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)


# ---- Abastecimiento ----


class ProveedorRepository(CRUDBase[Proveedor, ProveedorCrear, ProveedorActualizar]):
    def __init__(self) -> None:
        super().__init__(Proveedor)

    def obtener_por_nit(self, db: Session, nit: str) -> Proveedor | None:
        return db.scalar(select(Proveedor).where(Proveedor.nit == nit))

    def crear(self, db: Session, datos: ProveedorCrear, commit: bool = True) -> Proveedor:
        existente = self.obtener_por_nit(db, datos.nit) if datos.nit is not None else None
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un proveedor con ese NIT")
            for campo, valor in datos.model_dump().items():
                setattr(existente, campo, valor)
            existente.activo = True
            confirmar(db, commit)
            db.refresh(existente)
            return existente
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: ProveedorActualizar, commit: bool = True) -> Proveedor:
        if datos.nit is not None:
            existente = self.obtener_por_nit(db, datos.nit)
            if existente is not None and existente.id != id_:
                raise ConflictoError("Ya existe un proveedor con ese NIT")
        return super().actualizar(db, id_, datos, commit)


class ProductoProveedorRepository:
    """PK compuesta (proveedor_id, producto_id), sin `activo`: se quita con
    DELETE físico (igual que favorito)."""

    def listar_por_proveedor(self, db: Session, proveedor_id: int) -> list[ProductoProveedor]:
        return list(
            db.scalars(select(ProductoProveedor).where(ProductoProveedor.proveedor_id == proveedor_id))
        )

    def obtener(self, db: Session, proveedor_id: int, producto_id: int) -> ProductoProveedor | None:
        return obtener_por_clave(db, ProductoProveedor, (proveedor_id, producto_id))

    def crear(
        self,
        db: Session,
        proveedor_id: int,
        producto_id: int,
        costo_referencial: Decimal | None,
        dias_entrega: int | None,
    ) -> ProductoProveedor:
        existente = self.obtener(db, proveedor_id, producto_id)
        if existente is not None:
            raise ConflictoError("Ese proveedor ya está asociado a ese producto")
        relacion = ProductoProveedor(
            proveedor_id=proveedor_id,
            producto_id=producto_id,
            costo_referencial=costo_referencial,
            dias_entrega=dias_entrega,
        )
        db.add(relacion)
        db.commit()
        db.refresh(relacion)
        return relacion

    def eliminar(self, db: Session, proveedor_id: int, producto_id: int) -> None:
        relacion = self.obtener(db, proveedor_id, producto_id)
        if relacion is None:
            raise NoEncontradoError("Ese proveedor no está asociado a ese producto")
        db.delete(relacion)
        db.commit()


class OrdenCompraRepository:
    """No hereda de CRUDBase: `orden_compra` no tiene columna `activo`, su
    ciclo de vida es la máquina de estados `estado` (borrador -> enviada ->
    parcial/recibida, o anulada), y crear/actualizar manejan también las
    líneas de `detalle` como parte de la misma operación."""

    def obtener_por_codigo(self, db: Session, codigo: str) -> OrdenCompra | None:
        return db.scalar(select(OrdenCompra).where(OrdenCompra.codigo == codigo))

    def obtener(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = db.scalar(
            select(OrdenCompra).where(OrdenCompra.id == orden_id).options(selectinload(OrdenCompra.detalle))
        )
        if orden is None:
            raise NoEncontradoError("Orden de compra no encontrada")
        return orden

    def listar(self, db: Session, proveedor_id: int | None = None, sucursal_id: int | None = None) -> list[OrdenCompra]:
        consulta = select(OrdenCompra).options(selectinload(OrdenCompra.detalle)).order_by(OrdenCompra.id.desc())
        if proveedor_id is not None:
            consulta = consulta.where(OrdenCompra.proveedor_id == proveedor_id)
        if sucursal_id is not None:
            consulta = consulta.where(OrdenCompra.sucursal_id == sucursal_id)
        return list(db.scalars(consulta))

    def crear(self, db: Session, orden: OrdenCompra) -> OrdenCompra:
        db.add(orden)
        db.commit()
        db.refresh(orden)
        return orden

    def reemplazar_detalle(self, db: Session, orden: OrdenCompra, lineas: list[OrdenCompraDetalle]) -> OrdenCompra:
        orden.detalle = lineas
        orden.total = sum((linea.cantidad * linea.costo_unitario for linea in lineas), Decimal("0"))
        db.commit()
        db.refresh(orden)
        return orden

    def guardar(self, db: Session, orden: OrdenCompra) -> OrdenCompra:
        db.commit()
        db.refresh(orden)
        return orden


class RecepcionRepository:
    """Igual que movimiento_inventario: una vez creada, la recepción no se
    edita ni se borra (es el respaldo de los movimientos que generó)."""

    def obtener_por_codigo(self, db: Session, codigo: str) -> Recepcion | None:
        return db.scalar(select(Recepcion).where(Recepcion.codigo == codigo))

    def obtener(self, db: Session, recepcion_id: int) -> Recepcion:
        recepcion = db.scalar(
            select(Recepcion).where(Recepcion.id == recepcion_id).options(selectinload(Recepcion.detalle))
        )
        if recepcion is None:
            raise NoEncontradoError("Recepción no encontrada")
        return recepcion

    def listar(self, db: Session, orden_compra_id: int | None = None) -> list[Recepcion]:
        consulta = select(Recepcion).options(selectinload(Recepcion.detalle)).order_by(Recepcion.id.desc())
        if orden_compra_id is not None:
            consulta = consulta.where(Recepcion.orden_compra_id == orden_compra_id)
        return list(db.scalars(consulta))

    def crear(self, db: Session, recepcion: Recepcion) -> Recepcion:
        db.add(recepcion)
        db.flush()
        return recepcion

    def total_recibido_por_variante(self, db: Session, orden_compra_id: int) -> dict[int, int]:
        """Suma de cantidad_recepcion_detalle por variante_id, entre todas
        las recepciones vinculadas a esta orden. Se usa para decidir si la
        orden pasa a 'parcial' o 'recibida'."""
        filas = db.execute(
            select(RecepcionDetalle.variante_id, RecepcionDetalle.cantidad)
            .join(Recepcion, Recepcion.id == RecepcionDetalle.recepcion_id)
            .where(Recepcion.orden_compra_id == orden_compra_id)
        ).all()
        totales: dict[int, int] = {}
        for variante_id, cantidad in filas:
            totales[variante_id] = totales.get(variante_id, 0) + cantidad
        return totales


# ---- Probador ----


class ActivoRepository:
    """No hereda de CRUDBase: activo_probador no tiene borrado lógico (no
    hay endpoint de borrado en el enunciado; un asset rechazado se
    conserva como historial y se puede subir otro para la misma
    variante+tipo, gracias al índice único parcial `WHERE estado <> 'rechazado'`)."""

    def listar_por_variante(self, db: Session, variante_id: int) -> list[ActivoProbador]:
        return list(
            db.scalars(
                select(ActivoProbador)
                .where(ActivoProbador.variante_id == variante_id)
                .order_by(ActivoProbador.creado_en.desc())
            )
        )

    def obtener(self, db: Session, activo_id: int) -> ActivoProbador:
        activo = obtener_por_clave(db, ActivoProbador, activo_id)
        if activo is None:
            raise NoEncontradoError("Asset de probador no encontrado")
        return activo

    def crear(
        self,
        db: Session,
        variante_id: int,
        tipo: str,
        public_id: str,
        ancho_px: int,
        alto_px: int,
        creado_por: int | None,
    ) -> ActivoProbador:
        activo = ActivoProbador(
            variante_id=variante_id,
            tipo=tipo,
            url=public_id,
            ancho_px=ancho_px,
            alto_px=alto_px,
            estado="pendiente",
            creado_por=creado_por,
        )
        db.add(activo)
        db.commit()
        db.refresh(activo)
        return activo

    def marcar_validado(self, db: Session, activo: ActivoProbador) -> ActivoProbador:
        activo.estado = "validado"
        db.commit()
        db.refresh(activo)
        return activo


class GeneracionRepository:
    """No hereda de CRUDBase: probador_generacion no tiene borrado lógico
    (es un caché de resultados, no un catálogo administrable)."""

    def buscar_completado(
        self,
        db: Session,
        hash_foto: str,
        variante_id: int,
        *,
        cliente_id: int | None = None,
        proveedor: str | None = None,
    ) -> ProbadorGeneracion | None:
        """El caché es por cliente y por proveedor: la generación de otro
        cliente no se reusa (consultar() la rechazaría) ni la de otro
        proveedor de IA. Sin cliente_id / proveedor no filtra por ese campo."""
        consulta = select(ProbadorGeneracion).where(
            ProbadorGeneracion.hash_foto == hash_foto,
            ProbadorGeneracion.variante_id == variante_id,
            ProbadorGeneracion.estado == "completado",
        )
        if cliente_id is not None:
            consulta = consulta.where(ProbadorGeneracion.cliente_id == cliente_id)
        if proveedor is not None:
            consulta = consulta.where(ProbadorGeneracion.proveedor == proveedor)
        return db.scalar(consulta.order_by(ProbadorGeneracion.id.desc()).limit(1))

    def contar_desde(self, db: Session, cliente_id: int, desde: dt.datetime) -> int:
        return db.scalar(
            select(func.count())
            .select_from(ProbadorGeneracion)
            .where(
                ProbadorGeneracion.cliente_id == cliente_id,
                ProbadorGeneracion.creado_en >= desde,
                # Un intento fallido (proveedor caído, timeout) no gasta cupo.
                ProbadorGeneracion.estado != "fallido",
            )
        )

    def obtener(self, db: Session, generacion_id: int) -> ProbadorGeneracion:
        generacion = obtener_por_clave(db, ProbadorGeneracion, generacion_id)
        if generacion is None:
            raise NoEncontradoError("Generación no encontrada")
        return generacion

    def crear(self, db: Session, cliente_id: int, variante_id: int, hash_foto: str) -> ProbadorGeneracion:
        generacion = ProbadorGeneracion(
            cliente_id=cliente_id, variante_id=variante_id, hash_foto=hash_foto, estado="en_proceso"
        )
        db.add(generacion)
        db.commit()
        db.refresh(generacion)
        return generacion

    def marcar_completado(
        self, db: Session, generacion_id: int, url_resultado: str, proveedor: str
    ) -> ProbadorGeneracion:
        generacion = self.obtener(db, generacion_id)
        generacion.estado = "completado"
        generacion.url_resultado = url_resultado
        generacion.proveedor = proveedor
        db.commit()
        db.refresh(generacion)
        return generacion

    def marcar_fallido(self, db: Session, generacion_id: int, mensaje_error: str) -> ProbadorGeneracion:
        generacion = self.obtener(db, generacion_id)
        generacion.estado = "fallido"
        generacion.mensaje_error = mensaje_error[:300]
        db.commit()
        db.refresh(generacion)
        return generacion

    def listar_reciente_por_cliente(self, db: Session, cliente_id: int, limite: int) -> list[ProbadorGeneracion]:
        consulta = (
            select(ProbadorGeneracion)
            .where(ProbadorGeneracion.cliente_id == cliente_id)
            .order_by(ProbadorGeneracion.creado_en.desc())
            .limit(limite)
        )
        return list(db.scalars(consulta))

    def contar_por_periodo(self, db: Session, desde: dt.date, hasta: dt.date) -> list[dict]:
        """Para `inteligencia` (reportes): generaciones por estado en el período.
        `probador_generacion` no tiene `sucursal_id` -- sin filtro posible
        por sucursal, es una limitación real del esquema, no un descuido."""
        hasta_exclusiva = hasta + dt.timedelta(days=1)
        consulta = (
            select(ProbadorGeneracion.estado, func.count(ProbadorGeneracion.id).label("cantidad"))
            .where(ProbadorGeneracion.creado_en >= desde, ProbadorGeneracion.creado_en < hasta_exclusiva)
            .group_by(ProbadorGeneracion.estado)
            .order_by(ProbadorGeneracion.estado)
        )
        return [dict(fila) for fila in db.execute(consulta).mappings().all()]

"""CU-06 — Consultar y buscar catálogo

Absorbe los antiguos CU-09 (Consultar catálogo) y CU-10 (Buscar y filtrar
prendas).

Actor: Cliente (la búsqueda de variantes para venta la usa también la caja).
Precondición: ninguna (accesible sin sesión).
Postcondición: el cliente visualiza el catálogo de productos disponibles,
el detalle de una prenda y las prendas que cumplen su búsqueda.

Caso de uso COMPUESTO: incluye el detalle de una prenda, el lookup de
imágenes que usa el dashboard del back office y la búsqueda de variantes
para venta (es la misma operación de "buscar", con otro consumidor).
"""

from sqlalchemy.orm import Session

from app.catalogo.politicas import a_item_catalogo, imagen_principal_url, obtener_precio_efectivo
from app.catalogo.repository import ProductoRepository, StockRepository, VarianteRepository
from app.catalogo.schemas import (
    CatalogoDetalleRespuesta,
    CatalogoItemRespuesta,
    ImagenRespuesta,
    ProductoImagenLookupItem,
    VarianteCatalogoRespuesta,
    FiltrosCatalogo,
)
from app.core import storage
from app.core.deps import ParametrosPaginacion


# ---- Consultar catálogo (antiguo CU-09: Consultar catálogo) ----

class ConsultarCatalogo:
    def __init__(self) -> None:
        self._productos = ProductoRepository()
        self._variantes = VarianteRepository()
        self._stock = StockRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[CatalogoItemRespuesta]:
        productos = self._productos.listar_publico(db, paginacion)
        return [a_item_catalogo(p) for p in productos]

    def _disponibilidad_por_variante(
        self, db: Session, variante_ids: list[int], sucursal_id: int | None
    ) -> dict[int, int]:
        """Sin `sucursal_id`, "disponible" es la suma entre todas las
        sucursales (mismo criterio que usa `inteligencia` para decidir si
        una variante tiene stock); con `sucursal_id`, la de esa sucursal
        sola. Una sola consulta agrupada para todas las variantes. Nunca
        None: sin stock registrado es 0, no una ausencia de dato (el antiguo
        CU-09 ya no distingue ambos casos)."""
        disponible = self._stock.disponible_por_variante(db, variante_ids, sucursal_id)
        return {variante_id: disponible.get(variante_id, 0) for variante_id in variante_ids}

    def obtener_detalle(
        self, db: Session, producto_id: int, sucursal_id: int | None = None
    ) -> CatalogoDetalleRespuesta:
        producto = self._productos.obtener_publico_detalle(db, producto_id)

        activas = [v for v in producto.variantes if v.activo]
        disponibles = self._disponibilidad_por_variante(db, [v.id for v in activas], sucursal_id)
        variantes = [
            VarianteCatalogoRespuesta(
                id=v.id,
                talla_id=v.talla_id,
                color_id=v.color_id,
                sku=v.sku,
                precio_efectivo=obtener_precio_efectivo(v),
                cantidad_disponible=disponibles[v.id],
            )
            for v in activas
        ]
        imagenes = [ImagenRespuesta.from_modelo(img, storage.url_catalogo(img.url)) for img in producto.imagenes]

        return CatalogoDetalleRespuesta(
            id=producto.id,
            codigo=producto.codigo,
            nombre=producto.nombre,
            descripcion=producto.descripcion,
            categoria_id=producto.categoria_id,
            material_id=producto.material_id,
            temporada_id=producto.temporada_id,
            coleccion_id=producto.coleccion_id,
            genero=producto.genero,
            precio_base=producto.precio_base,
            admite_probador=producto.admite_probador,
            variantes=variantes,
            imagenes=imagenes,
        )

    def resolver_imagen_lookup(
        self, db: Session, variante_ids: list[int] | None, producto_ids: list[int] | None
    ) -> list[ProductoImagenLookupItem]:
        """Resuelve nombre+foto en lote para el dashboard del back office.
        No filtra por `activo`: quien llama ya conoce estos ids por una
        venta o una alerta de stock real, así que interesa mostrar la
        prenda aunque haya quedado inactiva después."""
        resultados: list[ProductoImagenLookupItem] = []
        if variante_ids:
            for variante, producto, talla, color in self._variantes.listar_para_detalle_publico(db, variante_ids):
                resultados.append(
                    ProductoImagenLookupItem(
                        variante_id=variante.id,
                        producto_id=producto.id,
                        producto_nombre=producto.nombre,
                        imagen_principal=imagen_principal_url(producto),
                        talla_codigo=talla.codigo,
                        color_nombre=color.nombre,
                    )
                )
        if producto_ids:
            for producto in self._productos.listar_por_ids_publico(db, producto_ids):
                resultados.append(
                    ProductoImagenLookupItem(
                        producto_id=producto.id,
                        producto_nombre=producto.nombre,
                        imagen_principal=imagen_principal_url(producto),
                    )
                )
        return resultados


# ---- Buscar y filtrar prendas (antiguo CU-10: Buscar y filtrar prendas) ----

class BuscarFiltrarPrendas:
    def __init__(self) -> None:
        self._productos = ProductoRepository()
        self._variantes = VarianteRepository()

    def buscar(
        self, db: Session, paginacion: ParametrosPaginacion, filtros: FiltrosCatalogo
    ) -> list[CatalogoItemRespuesta]:
        productos = self._productos.buscar_publico(db, paginacion, filtros)
        return [a_item_catalogo(p) for p in productos]

    def buscar_para_venta(self, db: Session, texto: str):
        """Para la caja (POS): resuelve una variante por código de barras
        exacto (lector físico) o texto libre sobre sku/nombre/código de
        producto."""
        return self._variantes.buscar_para_venta(db, texto)

from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.catalogo.casos_uso.cu05_gestionar_catalogo import (
    GestionarCategorias,
    GestionarColecciones,
    GestionarColores,
    GestionarMateriales,
    GestionarProductos,
    GestionarTallas,
    GestionarTemporadas,
)
from app.catalogo.casos_uso.cu06_consultar_buscar_catalogo import BuscarFiltrarPrendas, ConsultarCatalogo
from app.catalogo.casos_uso.cu07_gestionar_favoritos import GestionarFavoritos
from app.catalogo.casos_uso.cu08_gestionar_abastecimiento import GestionarProveedores, RegistrarRecepcionMercaderia
from app.catalogo.casos_uso.cu09_gestionar_inventario import (
    ConsultarDisponibilidadSucursal,
    ConsultarInventarioGlobal,
    RegistrarMovimientoInventario,
)
from app.catalogo.casos_uso.cu10_gestionar_assets_probador import CargarAssetsProbador
from app.catalogo.casos_uso.cu11_probar_prenda_con_ia import GenerarPruebaRealistaIA
from app.catalogo.politicas import obtener_precio_efectivo
from app.catalogo.schemas import (
    ActivoRespuesta,
    AjusteCrear,
    AssetsVarianteRespuesta,
    CatalogoDetalleRespuesta,
    CatalogoItemRespuesta,
    CategoriaActualizar,
    CategoriaCrear,
    CategoriaRespuesta,
    ColeccionActualizar,
    ColeccionCrear,
    ColeccionRespuesta,
    ColorActualizar,
    ColorCrear,
    ColorRespuesta,
    ConsolidadoRespuesta,
    DisponibilidadRespuesta,
    FavoritoCrear,
    FavoritoRespuesta,
    FiltrosCatalogo,
    GeneracionEstadoRespuesta,
    GeneracionIniciadaRespuesta,
    Genero,
    ImagenRespuesta,
    LimitesActualizar,
    MaterialActualizar,
    MaterialCrear,
    MaterialRespuesta,
    MovimientoCrear,
    MovimientoRespuesta,
    OrdenCompraActualizar,
    OrdenCompraCrear,
    OrdenCompraRespuesta,
    ProductoActualizar,
    ProductoCrear,
    ProductoImagenLookupItem,
    ProductoProveedorCrear,
    ProductoProveedorRespuesta,
    ProductoRespuesta,
    ProveedorActualizar,
    ProveedorCrear,
    ProveedorRespuesta,
    RecepcionCrear,
    RecepcionRespuesta,
    StockRespuesta,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    TablaMedidaRespuesta,
    TallaActualizar,
    TallaCrear,
    TallaRecomendadaRespuesta,
    TallaRequest,
    TallaRespuesta,
    TemporadaActualizar,
    TemporadaCrear,
    TemporadaRespuesta,
    TipoActivo,
    TipoMovimientoRespuesta,
    TransferenciaCrear,
    TransferenciaRespuesta,
    ValuacionRespuesta,
    VarianteActualizar,
    VarianteBusquedaRespuesta,
    VarianteRespuesta,
    VariantesGenerarRequest,
)
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.permisos import (
    PERMISO_ABASTECIMIENTO,
    PERMISO_CATALOGO,
    PERMISO_CATALOGO_VER,
    PERMISO_INVENTARIO_GESTIONAR,
    PERMISO_INVENTARIO_VER,
    PERMISO_PROBADOR,
)
from app.core.planes import FUNC_GESTION_PRODUCTOS, exigir_funcionalidad
from app.core.rate_limit import limiter
from app.core.security import get_current_user, require_permission


# ---- Catálogo ----


def paginacion_catalogo(
    pagina: int = Query(default=1, ge=1), tamanio: int = Query(default=20, ge=1, le=50)
) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)

admin_catalogo_requerido = Depends(require_permission(PERMISO_CATALOGO))
# Compuerta del plan (gestion_productos) ANTES del permiso, para respetar el
# orden de errores: 401 -> suscripcion_no_activa -> plan_no_incluye_funcionalidad
# -> falta el permiso. Va en las escrituras del catálogo (las lecturas de las
# tablas de apoyo no se compuertan) y en todo productos/variantes/imágenes.
plan_gestion_productos = Depends(exigir_funcionalidad(FUNC_GESTION_PRODUCTOS))
gestion_catalogo_requerida = [plan_gestion_productos, admin_catalogo_requerido]

cu_categorias = GestionarCategorias()
cu_tallas = GestionarTallas()
cu_colores = GestionarColores()
cu_materiales = GestionarMateriales()
cu_temporadas = GestionarTemporadas()
cu_colecciones = GestionarColecciones()
cu_productos = GestionarProductos()
cu_consultar_catalogo = ConsultarCatalogo()
cu_buscar_prendas = BuscarFiltrarPrendas()
cu_favoritos = GestionarFavoritos()

# ---- /api/v1/categorias ---------------------------------------------------

categorias_router = APIRouter(prefix="/api/v1/categorias", tags=["categorias"])


@categorias_router.get("", response_model=list[CategoriaRespuesta])
def listar_categorias(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[CategoriaRespuesta]:
    return cu_categorias.listar(db, paginacion)


@categorias_router.get("/{categoria_id}", response_model=CategoriaRespuesta)
def obtener_categoria(categoria_id: int, db: Session = Depends(get_db)) -> CategoriaRespuesta:
    return cu_categorias.obtener(db, categoria_id)


@categorias_router.post(
    "", response_model=CategoriaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_categoria(datos: CategoriaCrear, db: Session = Depends(get_db)) -> CategoriaRespuesta:
    return cu_categorias.crear(db, datos)


@categorias_router.put(
    "/{categoria_id}", response_model=CategoriaRespuesta, dependencies=gestion_catalogo_requerida
)
def actualizar_categoria(
    categoria_id: int, datos: CategoriaActualizar, db: Session = Depends(get_db)
) -> CategoriaRespuesta:
    return cu_categorias.actualizar(db, categoria_id, datos)


@categorias_router.delete(
    "/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida
)
def desactivar_categoria(categoria_id: int, db: Session = Depends(get_db)) -> None:
    cu_categorias.desactivar(db, categoria_id)


# ---- /api/v1/tallas -----------------------------------------------------

tallas_router = APIRouter(prefix="/api/v1/tallas", tags=["tallas"])


@tallas_router.get("", response_model=list[TallaRespuesta])
def listar_tallas(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[TallaRespuesta]:
    return cu_tallas.listar(db, paginacion)


@tallas_router.get("/{talla_id}", response_model=TallaRespuesta)
def obtener_talla(talla_id: int, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.obtener(db, talla_id)


@tallas_router.post(
    "", response_model=TallaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_talla(datos: TallaCrear, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.crear(db, datos)


@tallas_router.put("/{talla_id}", response_model=TallaRespuesta, dependencies=gestion_catalogo_requerida)
def actualizar_talla(talla_id: int, datos: TallaActualizar, db: Session = Depends(get_db)) -> TallaRespuesta:
    return cu_tallas.actualizar(db, talla_id, datos)


@tallas_router.delete("/{talla_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida)
def eliminar_talla(talla_id: int, db: Session = Depends(get_db)) -> None:
    cu_tallas.eliminar(db, talla_id)


# ---- /api/v1/colores -------------------------------------------------------

colores_router = APIRouter(prefix="/api/v1/colores", tags=["colores"])


@colores_router.get("", response_model=list[ColorRespuesta])
def listar_colores(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ColorRespuesta]:
    return cu_colores.listar(db, paginacion)


@colores_router.get("/{color_id}", response_model=ColorRespuesta)
def obtener_color(color_id: int, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.obtener(db, color_id)


@colores_router.post(
    "", response_model=ColorRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_color(datos: ColorCrear, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.crear(db, datos)


@colores_router.put("/{color_id}", response_model=ColorRespuesta, dependencies=gestion_catalogo_requerida)
def actualizar_color(color_id: int, datos: ColorActualizar, db: Session = Depends(get_db)) -> ColorRespuesta:
    return cu_colores.actualizar(db, color_id, datos)


@colores_router.delete("/{color_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida)
def eliminar_color(color_id: int, db: Session = Depends(get_db)) -> None:
    cu_colores.eliminar(db, color_id)


# ---- /api/v1/materiales ---------------------------------------------------

materiales_router = APIRouter(prefix="/api/v1/materiales", tags=["materiales"])


@materiales_router.get("", response_model=list[MaterialRespuesta])
def listar_materiales(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[MaterialRespuesta]:
    return cu_materiales.listar(db, paginacion)


@materiales_router.get("/{material_id}", response_model=MaterialRespuesta)
def obtener_material(material_id: int, db: Session = Depends(get_db)) -> MaterialRespuesta:
    return cu_materiales.obtener(db, material_id)


@materiales_router.post(
    "", response_model=MaterialRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_material(datos: MaterialCrear, db: Session = Depends(get_db)) -> MaterialRespuesta:
    return cu_materiales.crear(db, datos)


@materiales_router.put(
    "/{material_id}", response_model=MaterialRespuesta, dependencies=gestion_catalogo_requerida
)
def actualizar_material(
    material_id: int, datos: MaterialActualizar, db: Session = Depends(get_db)
) -> MaterialRespuesta:
    return cu_materiales.actualizar(db, material_id, datos)


@materiales_router.delete(
    "/{material_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida
)
def eliminar_material(material_id: int, db: Session = Depends(get_db)) -> None:
    cu_materiales.eliminar(db, material_id)


# ---- /api/v1/temporadas ---------------------------------------------------

temporadas_router = APIRouter(prefix="/api/v1/temporadas", tags=["temporadas"])


@temporadas_router.get("", response_model=list[TemporadaRespuesta])
def listar_temporadas(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[TemporadaRespuesta]:
    return cu_temporadas.listar(db, paginacion)


@temporadas_router.get("/{temporada_id}", response_model=TemporadaRespuesta)
def obtener_temporada(temporada_id: int, db: Session = Depends(get_db)) -> TemporadaRespuesta:
    return cu_temporadas.obtener(db, temporada_id)


@temporadas_router.post(
    "", response_model=TemporadaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_temporada(datos: TemporadaCrear, db: Session = Depends(get_db)) -> TemporadaRespuesta:
    return cu_temporadas.crear(db, datos)


@temporadas_router.put(
    "/{temporada_id}", response_model=TemporadaRespuesta, dependencies=gestion_catalogo_requerida
)
def actualizar_temporada(
    temporada_id: int, datos: TemporadaActualizar, db: Session = Depends(get_db)
) -> TemporadaRespuesta:
    return cu_temporadas.actualizar(db, temporada_id, datos)


@temporadas_router.delete(
    "/{temporada_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida
)
def desactivar_temporada(temporada_id: int, db: Session = Depends(get_db)) -> None:
    cu_temporadas.desactivar(db, temporada_id)


# ---- /api/v1/colecciones ---------------------------------------------------

colecciones_router = APIRouter(prefix="/api/v1/colecciones", tags=["colecciones"])


@colecciones_router.get("", response_model=list[ColeccionRespuesta])
def listar_colecciones(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ColeccionRespuesta]:
    return cu_colecciones.listar(db, paginacion)


@colecciones_router.get("/{coleccion_id}", response_model=ColeccionRespuesta)
def obtener_coleccion(coleccion_id: int, db: Session = Depends(get_db)) -> ColeccionRespuesta:
    return cu_colecciones.obtener(db, coleccion_id)


@colecciones_router.post(
    "", response_model=ColeccionRespuesta, status_code=status.HTTP_201_CREATED, dependencies=gestion_catalogo_requerida
)
def crear_coleccion(datos: ColeccionCrear, db: Session = Depends(get_db)) -> ColeccionRespuesta:
    return cu_colecciones.crear(db, datos)


@colecciones_router.put(
    "/{coleccion_id}", response_model=ColeccionRespuesta, dependencies=gestion_catalogo_requerida
)
def actualizar_coleccion(
    coleccion_id: int, datos: ColeccionActualizar, db: Session = Depends(get_db)
) -> ColeccionRespuesta:
    return cu_colecciones.actualizar(db, coleccion_id, datos)


@colecciones_router.delete(
    "/{coleccion_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=gestion_catalogo_requerida
)
def desactivar_coleccion(coleccion_id: int, db: Session = Depends(get_db)) -> None:
    cu_colecciones.desactivar(db, coleccion_id)


# ---- /api/v1/productos -----------------------------------------------------
# Estos son de administración (alta/edición de catálogo). El catálogo que
# ve el cliente es otro conjunto de endpoints públicos, GET /api/v1/catalogo/*
# — acá todo requiere permiso de administrador, GET incluido.

productos_router = APIRouter(prefix="/api/v1/productos", tags=["productos"], dependencies=gestion_catalogo_requerida)


@productos_router.get("", response_model=list[ProductoRespuesta])
def listar_productos(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ProductoRespuesta]:
    return cu_productos.listar(db, paginacion)


@productos_router.get("/{producto_id}", response_model=ProductoRespuesta)
def obtener_producto(producto_id: int, db: Session = Depends(get_db)) -> ProductoRespuesta:
    return cu_productos.obtener(db, producto_id)


@productos_router.post("", response_model=ProductoRespuesta, status_code=status.HTTP_201_CREATED)
def crear_producto(
    datos: ProductoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ProductoRespuesta:
    return cu_productos.crear(db, datos, creado_por=usuario.id)


@productos_router.put("/{producto_id}", response_model=ProductoRespuesta)
def actualizar_producto(
    producto_id: int, datos: ProductoActualizar, db: Session = Depends(get_db)
) -> ProductoRespuesta:
    return cu_productos.actualizar(db, producto_id, datos)


@productos_router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_producto(producto_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.desactivar(db, producto_id)


# ---- /api/v1/productos/{id}/variantes y /api/v1/variantes/{id} -------------


@productos_router.get("/{producto_id}/variantes", response_model=list[VarianteRespuesta])
def listar_variantes(producto_id: int, db: Session = Depends(get_db)) -> list[VarianteRespuesta]:
    variantes = cu_productos.listar_variantes(db, producto_id)
    return [VarianteRespuesta.from_modelo(v) for v in variantes]


@productos_router.post(
    "/{producto_id}/variantes", response_model=list[VarianteRespuesta], status_code=status.HTTP_201_CREATED
)
def agregar_variantes(
    producto_id: int, datos: VariantesGenerarRequest, db: Session = Depends(get_db)
) -> list[VarianteRespuesta]:
    variantes = cu_productos.agregar_variantes(db, producto_id, datos)
    return [VarianteRespuesta.from_modelo(v) for v in variantes]


variantes_router = APIRouter(prefix="/api/v1/variantes", tags=["variantes"], dependencies=gestion_catalogo_requerida)


@variantes_router.put("/{variante_id}", response_model=VarianteRespuesta)
def actualizar_variante(
    variante_id: int, datos: VarianteActualizar, db: Session = Depends(get_db)
) -> VarianteRespuesta:
    variante = cu_productos.actualizar_variante(db, variante_id, datos)
    return VarianteRespuesta.from_modelo(variante)


@variantes_router.delete("/{variante_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_variante(variante_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.desactivar_variante(db, variante_id)


# ---- /api/v1/productos/{id}/medidas -----------------------------------------


@productos_router.get("/{producto_id}/medidas", response_model=list[TablaMedidaRespuesta])
def listar_medidas(producto_id: int, db: Session = Depends(get_db)) -> list[TablaMedidaRespuesta]:
    return cu_productos.listar_medidas(db, producto_id)


@productos_router.post(
    "/{producto_id}/medidas", response_model=TablaMedidaRespuesta, status_code=status.HTTP_201_CREATED
)
def crear_medida(
    producto_id: int, datos: TablaMedidaCrear, db: Session = Depends(get_db)
) -> TablaMedidaRespuesta:
    return cu_productos.crear_medida(db, producto_id, datos)


@productos_router.put("/{producto_id}/medidas/{medida_id}", response_model=TablaMedidaRespuesta)
def actualizar_medida(
    producto_id: int, medida_id: int, datos: TablaMedidaActualizar, db: Session = Depends(get_db)
) -> TablaMedidaRespuesta:
    return cu_productos.actualizar_medida(db, producto_id, medida_id, datos)


@productos_router.delete("/{producto_id}/medidas/{medida_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_medida(producto_id: int, medida_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.eliminar_medida(db, producto_id, medida_id)


# ---- /api/v1/productos/{id}/imagenes y /api/v1/imagenes/{id} ---------------
# La subida pasa siempre por el backend: el cliente nunca ve el api_secret
# de Cloudinary ni sube directo. Ver core/storage.py.


@productos_router.post(
    "/{producto_id}/imagenes", response_model=ImagenRespuesta, status_code=status.HTTP_201_CREATED
)
async def subir_imagen(
    producto_id: int,
    archivo: UploadFile = File(...),
    color_id: int | None = Form(default=None),
    es_principal: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> ImagenRespuesta:
    contenido = await archivo.read()
    imagen, url = cu_productos.subir_imagen(
        db, producto_id, contenido, archivo.content_type, color_id, es_principal
    )
    return ImagenRespuesta.from_modelo(imagen, url)


imagenes_router = APIRouter(prefix="/api/v1/imagenes", tags=["imagenes"], dependencies=gestion_catalogo_requerida)


@imagenes_router.delete("/{imagen_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_imagen(imagen_id: int, db: Session = Depends(get_db)) -> None:
    cu_productos.eliminar_imagen(db, imagen_id)


@imagenes_router.put("/{imagen_id}/principal", response_model=ImagenRespuesta)
def marcar_imagen_principal(imagen_id: int, db: Session = Depends(get_db)) -> ImagenRespuesta:
    imagen, url = cu_productos.marcar_imagen_principal(db, imagen_id)
    return ImagenRespuesta.from_modelo(imagen, url)


# ---- /api/v1/catalogo (público) --------------------------------------------

catalogo_router = APIRouter(prefix="/api/v1/catalogo", tags=["catalogo"])


@catalogo_router.get("", response_model=list[CatalogoItemRespuesta])
@limiter.limit("60/minute")
def listar_catalogo(
    request: Request,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(paginacion_catalogo),
) -> list[CatalogoItemRespuesta]:
    return cu_consultar_catalogo.listar(db, paginacion)


@catalogo_router.get("/buscar", response_model=list[CatalogoItemRespuesta])
@limiter.limit("30/minute")
def buscar_catalogo(
    request: Request,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(paginacion_catalogo),
    q: str | None = Query(default=None, description="Texto libre sobre nombre y descripción"),
    categoria_id: int | None = None,
    talla_id: int | None = None,
    color_id: int | None = None,
    material_id: int | None = None,
    temporada_id: int | None = None,
    genero: Genero | None = None,
    precio_min: Decimal | None = None,
    precio_max: Decimal | None = None,
    sucursal_id: int | None = None,
    solo_disponibles: bool = False,
) -> list[CatalogoItemRespuesta]:
    filtros = FiltrosCatalogo(
        texto=q,
        categoria_id=categoria_id,
        talla_id=talla_id,
        color_id=color_id,
        material_id=material_id,
        temporada_id=temporada_id,
        genero=genero,
        precio_min=precio_min,
        precio_max=precio_max,
        sucursal_id=sucursal_id,
        solo_disponibles=solo_disponibles,
    )
    return cu_buscar_prendas.buscar(db, paginacion, filtros)


@catalogo_router.get(
    "/variantes/buscar",
    response_model=list[VarianteBusquedaRespuesta],
    dependencies=[Depends(require_permission(PERMISO_CATALOGO_VER))],
)
def buscar_variantes_para_venta(
    q: str = Query(min_length=1, description="Código de barras exacto, sku, nombre o código de producto"),
    db: Session = Depends(get_db),
) -> list[VarianteBusquedaRespuesta]:
    filas = cu_buscar_prendas.buscar_para_venta(db, q)
    return [
        VarianteBusquedaRespuesta(
            variante_id=variante.id,
            producto_id=producto.id,
            producto_nombre=producto.nombre,
            producto_codigo=producto.codigo,
            talla_codigo=talla.codigo,
            color_nombre=color.nombre,
            sku=variante.sku,
            codigo_barras=variante.codigo_barras,
            precio_efectivo=obtener_precio_efectivo(variante),
        )
        for variante, producto, talla, color in filas
    ]


@catalogo_router.get("/variantes/detalle", response_model=list[ProductoImagenLookupItem])
def obtener_detalle_para_dashboard(
    variante_ids: str | None = Query(default=None, description="IDs de variante separados por coma"),
    producto_ids: str | None = Query(default=None, description="IDs de producto separados por coma"),
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
) -> list[ProductoImagenLookupItem]:
    v_ids = [int(x) for x in variante_ids.split(",") if x] if variante_ids else None
    p_ids = [int(x) for x in producto_ids.split(",") if x] if producto_ids else None
    return cu_consultar_catalogo.resolver_imagen_lookup(db, v_ids, p_ids)


@catalogo_router.get("/{producto_id}", response_model=CatalogoDetalleRespuesta)
def obtener_detalle_catalogo(
    producto_id: int,
    sucursal_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CatalogoDetalleRespuesta:
    return cu_consultar_catalogo.obtener_detalle(db, producto_id, sucursal_id)


# ---- /api/v1/favoritos (requiere sesión de cliente) -------------------------

favoritos_router = APIRouter(prefix="/api/v1/favoritos", tags=["favoritos"])


@favoritos_router.get("", response_model=list[FavoritoRespuesta])
def listar_favoritos(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FavoritoRespuesta]:
    return cu_favoritos.listar(db, usuario.id)


@favoritos_router.post("", response_model=FavoritoRespuesta, status_code=status.HTTP_201_CREATED)
def agregar_favorito(
    datos: FavoritoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> FavoritoRespuesta:
    return cu_favoritos.agregar(db, usuario.id, datos.variante_id)


@favoritos_router.delete("/{variante_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_favorito(
    variante_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    cu_favoritos.quitar(db, usuario.id, variante_id)


_routers_catalogo = [
    categorias_router,
    tallas_router,
    colores_router,
    materiales_router,
    temporadas_router,
    colecciones_router,
    productos_router,
    variantes_router,
    imagenes_router,
    catalogo_router,
    favoritos_router,
]


# ---- Inventario ----


ver_requerido = Depends(require_permission(PERMISO_INVENTARIO_VER))
gestionar_requerido = Depends(require_permission(PERMISO_INVENTARIO_GESTIONAR))

cu_consultar_disponibilidad = ConsultarDisponibilidadSucursal()
cu_consultar_inventario = ConsultarInventarioGlobal()
cu_registrar_movimiento = RegistrarMovimientoInventario()


# ---- /api/v1/inventario/disponibilidad (público) -----------------------------
# Lo consume el catálogo/detalle para mostrar disponibilidad por sucursal.
# Vive separado del resto (sin `ver_requerido`) porque cualquiera lo puede
# consultar, igual que /api/v1/catalogo.

publico_router = APIRouter(prefix="/api/v1/inventario", tags=["inventario"])


@publico_router.get("/disponibilidad", response_model=list[DisponibilidadRespuesta])
def consultar_disponibilidad(
    variante_id: int = Query(...),
    sucursal_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[DisponibilidadRespuesta]:
    return list(cu_consultar_disponibilidad.ejecutar(db, variante_id, sucursal_id))


# ---- /api/v1/inventario (administración) --------------------------------------

inventario_router = APIRouter(prefix="/api/v1/inventario", tags=["inventario"], dependencies=[ver_requerido])


@inventario_router.get("/tipos-movimiento", response_model=list[TipoMovimientoRespuesta])
def listar_tipos_movimiento(db: Session = Depends(get_db)) -> list[TipoMovimientoRespuesta]:
    return list(cu_registrar_movimiento.listar_tipos_movimiento(db))


@inventario_router.get("/consolidado", response_model=list[ConsolidadoRespuesta])
def listar_consolidado(
    sucursal_id: int | None = Query(default=None),
    producto_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConsolidadoRespuesta]:
    filas = cu_consultar_inventario.listar_consolidado(db, usuario.id, sucursal_id, producto_id)
    return [ConsolidadoRespuesta(**fila) for fila in filas]


@inventario_router.get("/alertas", response_model=list[ConsolidadoRespuesta])
def listar_alertas(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConsolidadoRespuesta]:
    return [ConsolidadoRespuesta(**fila) for fila in cu_consultar_inventario.listar_alertas(db, usuario.id, sucursal_id)]


@inventario_router.get("/valuacion", response_model=list[ValuacionRespuesta])
def listar_valuacion(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ValuacionRespuesta]:
    return [ValuacionRespuesta(**fila) for fila in cu_consultar_inventario.listar_valuacion(db, usuario.id, sucursal_id)]


@inventario_router.get("/sucursal/{sucursal_id}", response_model=list[StockRespuesta])
def listar_stock_por_sucursal(
    sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StockRespuesta]:
    return list(cu_consultar_inventario.listar_stock_por_sucursal(db, usuario.id, sucursal_id))


@inventario_router.get("/stock/{variante_id}/{sucursal_id}", response_model=StockRespuesta)
def obtener_stock(
    variante_id: int, sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> StockRespuesta:
    return cu_consultar_inventario.obtener_stock(db, usuario.id, variante_id, sucursal_id)


@inventario_router.get("/stock", response_model=list[StockRespuesta])
def listar_stock_por_variante(
    variante_id: int = Query(...), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StockRespuesta]:
    return list(cu_consultar_inventario.listar_stock_por_variante(db, usuario.id, variante_id))


@inventario_router.put("/stock/{stock_id}/limites", response_model=StockRespuesta, dependencies=[gestionar_requerido])
def actualizar_limites_stock(
    stock_id: int, datos: LimitesActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> StockRespuesta:
    return cu_consultar_inventario.actualizar_limites(db, usuario.id, stock_id, datos.stock_minimo, datos.stock_maximo)


@inventario_router.get("/movimientos", response_model=list[MovimientoRespuesta])
def listar_kardex(
    variante_id: int = Query(...),
    sucursal_id: int = Query(...),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MovimientoRespuesta]:
    movimientos = cu_registrar_movimiento.listar_kardex(db, usuario.id, variante_id, sucursal_id)
    codigos = cu_registrar_movimiento.mapa_codigos_tipo_movimiento(db)
    return [MovimientoRespuesta.from_modelo(m, codigos[m.tipo_movimiento_id]) for m in movimientos]


@inventario_router.post(
    "/movimientos",
    response_model=MovimientoRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[gestionar_requerido],
)
def registrar_movimiento(
    datos: MovimientoCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MovimientoRespuesta:
    movimiento = cu_registrar_movimiento.registrar_movimiento(db, usuario.id, datos)
    # actualizar_stock_operacion ya validó que el código exista (si no,
    # hubiera lanzado antes de llegar acá): se reusa el mismo valor en vez
    # de volver a consultar `tipo_movimiento` desde el inventario_router.
    return MovimientoRespuesta.from_modelo(movimiento, datos.tipo_movimiento_codigo)


# Sin POST /reservas ni /liberaciones sueltos: reservar_stock/liberar_stock
# son pasos internos de reservas (CU-12) y ventas (CU-13/CU-14). Moverlos
# a mano desincronizaba cantidad_reservada de las reservas reales y trababa
# su expiración automática.


@inventario_router.post(
    "/ajustes", response_model=MovimientoRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido]
)
def registrar_ajuste(
    datos: AjusteCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> MovimientoRespuesta:
    movimiento = cu_registrar_movimiento.registrar_ajuste(
        db, datos.variante_id, datos.sucursal_id, datos.cantidad, usuario.id, datos.observacion
    )
    codigo = "ajuste_positivo" if datos.cantidad > 0 else "ajuste_negativo"
    return MovimientoRespuesta.from_modelo(movimiento, codigo)


# ---- /api/v1/transferencias ----------------------------------------------------
# Recurso propio (no cuelga de /inventario en la URL) pero vive en este
# paquete: transferencia/transferencia_detalle son tablas de inventario.

transferencias_router = APIRouter(
    prefix="/api/v1/transferencias", tags=["transferencias"], dependencies=[ver_requerido]
)


@transferencias_router.get("", response_model=list[TransferenciaRespuesta])
def listar_transferencias(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TransferenciaRespuesta]:
    return list(cu_registrar_movimiento.listar_transferencias(db, usuario.id, sucursal_id))


@transferencias_router.get("/{transferencia_id}", response_model=TransferenciaRespuesta)
def obtener_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.obtener_transferencia(db, usuario.id, transferencia_id)


@transferencias_router.post(
    "", response_model=TransferenciaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido]
)
def crear_transferencia(
    datos: TransferenciaCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.crear_transferencia(db, datos, usuario.id)


@transferencias_router.post(
    "/{transferencia_id}/enviar", response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def enviar_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.enviar_transferencia(db, transferencia_id, usuario.id)


@transferencias_router.post(
    "/{transferencia_id}/recibir", response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def recibir_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.recibir_transferencia(db, transferencia_id, usuario.id)


@transferencias_router.delete(
    "/{transferencia_id}", status_code=status.HTTP_200_OK, response_model=TransferenciaRespuesta, dependencies=[gestionar_requerido]
)
def anular_transferencia(
    transferencia_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TransferenciaRespuesta:
    return cu_registrar_movimiento.anular_transferencia(db, usuario.id, transferencia_id)


_routers_inventario = [publico_router, inventario_router, transferencias_router]


# ---- Abastecimiento ----


admin_abastecimiento_requerido = Depends(require_permission(PERMISO_ABASTECIMIENTO))
# El abastecimiento forma parte de la gestión de producto (compuerta del plan).
gestion_abastecimiento_requerida = [plan_gestion_productos, admin_abastecimiento_requerido]

cu_gestionar_proveedores = GestionarProveedores()
cu_registrar_recepcion = RegistrarRecepcionMercaderia()

# ---- /api/v1/proveedores -------------------------------------------------------

proveedores_router = APIRouter(
    prefix="/api/v1/proveedores", tags=["proveedores"], dependencies=gestion_abastecimiento_requerida
)


@proveedores_router.get("", response_model=list[ProveedorRespuesta])
def listar_proveedores(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[ProveedorRespuesta]:
    return cu_gestionar_proveedores.listar(db, paginacion)


@proveedores_router.get("/{proveedor_id}", response_model=ProveedorRespuesta)
def obtener_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.obtener(db, proveedor_id)


@proveedores_router.post("", response_model=ProveedorRespuesta, status_code=status.HTTP_201_CREATED)
def crear_proveedor(datos: ProveedorCrear, db: Session = Depends(get_db)) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.crear(db, datos)


@proveedores_router.put("/{proveedor_id}", response_model=ProveedorRespuesta)
def actualizar_proveedor(
    proveedor_id: int, datos: ProveedorActualizar, db: Session = Depends(get_db)
) -> ProveedorRespuesta:
    return cu_gestionar_proveedores.actualizar(db, proveedor_id, datos)


@proveedores_router.delete("/{proveedor_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_proveedores.desactivar(db, proveedor_id)


# ---- /api/v1/proveedores/{id}/productos ----------------------------------------

productos_proveedor_router = APIRouter(
    prefix="/api/v1/proveedores/{proveedor_id}/productos", tags=["proveedores"], dependencies=gestion_abastecimiento_requerida
)


@productos_proveedor_router.get("", response_model=list[ProductoProveedorRespuesta])
def listar_productos_proveedor(proveedor_id: int, db: Session = Depends(get_db)) -> list[ProductoProveedorRespuesta]:
    return cu_gestionar_proveedores.listar_productos(db, proveedor_id)


@productos_proveedor_router.post(
    "", response_model=ProductoProveedorRespuesta, status_code=status.HTTP_201_CREATED
)
def agregar_producto_proveedor(
    proveedor_id: int, datos: ProductoProveedorCrear, db: Session = Depends(get_db)
) -> ProductoProveedorRespuesta:
    return cu_gestionar_proveedores.agregar_producto(
        db, proveedor_id, datos.producto_id, datos.costo_referencial, datos.dias_entrega
    )


@productos_proveedor_router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_producto_proveedor(proveedor_id: int, producto_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_proveedores.quitar_producto(db, proveedor_id, producto_id)


# ---- /api/v1/ordenes-compra -----------------------------------------------------
# OrdenCompra es soporte de CU-08 (ver docstring del caso de uso), no un CU
# propio del catálogo.

ordenes_compra_router = APIRouter(
    prefix="/api/v1/ordenes-compra", tags=["ordenes-compra"], dependencies=gestion_abastecimiento_requerida
)


@ordenes_compra_router.get("", response_model=list[OrdenCompraRespuesta])
def listar_ordenes_compra(
    proveedor_id: int | None = None, sucursal_id: int | None = None, db: Session = Depends(get_db)
) -> list[OrdenCompraRespuesta]:
    return list(cu_registrar_recepcion.ordenes_compra.listar(db, proveedor_id, sucursal_id))


@ordenes_compra_router.get("/{orden_id}", response_model=OrdenCompraRespuesta)
def obtener_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.obtener(db, orden_id)


@ordenes_compra_router.post("", response_model=OrdenCompraRespuesta, status_code=status.HTTP_201_CREATED)
def crear_orden_compra(
    datos: OrdenCompraCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.crear(db, datos, usuario.id)


@ordenes_compra_router.put("/{orden_id}", response_model=OrdenCompraRespuesta)
def actualizar_orden_compra(
    orden_id: int, datos: OrdenCompraActualizar, db: Session = Depends(get_db)
) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.actualizar(db, orden_id, datos)


@ordenes_compra_router.post("/{orden_id}/enviar", response_model=OrdenCompraRespuesta)
def enviar_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.enviar(db, orden_id)


@ordenes_compra_router.delete("/{orden_id}", response_model=OrdenCompraRespuesta)
def anular_orden_compra(orden_id: int, db: Session = Depends(get_db)) -> OrdenCompraRespuesta:
    return cu_registrar_recepcion.ordenes_compra.anular(db, orden_id)


# ---- /api/v1/recepciones ---------------------------------------------------------

recepciones_router = APIRouter(
    prefix="/api/v1/recepciones", tags=["recepciones"], dependencies=gestion_abastecimiento_requerida
)


@recepciones_router.get("", response_model=list[RecepcionRespuesta])
def listar_recepciones(orden_compra_id: int | None = None, db: Session = Depends(get_db)) -> list[RecepcionRespuesta]:
    return list(cu_registrar_recepcion.listar(db, orden_compra_id))


@recepciones_router.get("/{recepcion_id}", response_model=RecepcionRespuesta)
def obtener_recepcion(recepcion_id: int, db: Session = Depends(get_db)) -> RecepcionRespuesta:
    return cu_registrar_recepcion.obtener(db, recepcion_id)


@recepciones_router.post("", response_model=RecepcionRespuesta, status_code=status.HTTP_201_CREATED)
def crear_recepcion(
    datos: RecepcionCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> RecepcionRespuesta:
    return cu_registrar_recepcion.registrar(db, datos, empleado_id=None, creado_por=usuario.id)


_routers_abastecimiento = [proveedores_router, productos_proveedor_router, ordenes_compra_router, recepciones_router]


# ---- Probador ----


admin_probador_requerido = Depends(require_permission(PERMISO_PROBADOR))

cu_cargar_assets = CargarAssetsProbador()
cu_generar_ia = GenerarPruebaRealistaIA()

assets_probador_router = APIRouter(prefix="/api/v1/probador/assets", tags=["probador"], dependencies=[admin_probador_requerido])

uso_router = APIRouter(prefix="/api/v1/probador", tags=["probador"])


@assets_probador_router.get("", response_model=list[ActivoRespuesta])
def listar_assets(
    variante_id: int = Query(...), db: Session = Depends(get_db)
) -> list[ActivoRespuesta]:
    activos = cu_cargar_assets.listar(db, variante_id)
    return [ActivoRespuesta.from_modelo(a, url) for a, url in activos]


@assets_probador_router.post("", response_model=ActivoRespuesta, status_code=status.HTTP_201_CREATED)
def subir_asset(
    variante_id: int = Form(...),
    tipo: TipoActivo = Form(...),
    archivo: UploadFile = File(...),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivoRespuesta:
    contenido = archivo.file.read()
    activo, url = cu_cargar_assets.subir(db, variante_id, tipo, contenido, archivo.content_type, usuario.id)
    return ActivoRespuesta.from_modelo(activo, url)


@assets_probador_router.put("/{activo_id}/validar", response_model=ActivoRespuesta)
def validar_asset(activo_id: int, db: Session = Depends(get_db)) -> ActivoRespuesta:
    activo, url = cu_cargar_assets.validar(db, activo_id)
    return ActivoRespuesta.from_modelo(activo, url)


# ---- Uso del probador (cliente) ----------------------------------------------


@uso_router.get("/variante/{variante_id}/assets", response_model=AssetsVarianteRespuesta)
def obtener_assets_uso(
    variante_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> AssetsVarianteRespuesta:
    overlay, overlay_url, flatlay, flatlay_url = cu_cargar_assets.obtener_assets(db, variante_id)
    return AssetsVarianteRespuesta(
        overlay=ActivoRespuesta.from_modelo(overlay, overlay_url),
        flatlay=ActivoRespuesta.from_modelo(flatlay, flatlay_url) if flatlay else None,
    )


@uso_router.post("/generar", response_model=GeneracionIniciadaRespuesta, status_code=status.HTTP_202_ACCEPTED)
def iniciar_generacion(
    background_tasks: BackgroundTasks,
    variante_id: int = Form(...),
    archivo: UploadFile = File(...),  # una sola imagen por petición: un único UploadFile, no una lista
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GeneracionIniciadaRespuesta:
    contenido = archivo.file.read()
    generacion, desde_cache = cu_generar_ia.iniciar(
        db, usuario.id, variante_id, contenido, archivo.content_type, background_tasks
    )
    return GeneracionIniciadaRespuesta(
        id=generacion.id, estado=generacion.estado, url_resultado=generacion.url_resultado, desde_cache=desde_cache
    )


@uso_router.get("/generar/{generacion_id}", response_model=GeneracionEstadoRespuesta)
def consultar_generacion(
    generacion_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> GeneracionEstadoRespuesta:
    generacion = cu_generar_ia.consultar(db, usuario.id, generacion_id)
    return GeneracionEstadoRespuesta.model_validate(generacion)


@uso_router.post("/talla", response_model=TallaRecomendadaRespuesta)
def recomendar_talla(
    datos: TallaRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> TallaRecomendadaRespuesta:
    return cu_generar_ia.recomendar_talla(db, datos)


_routers_probador = [assets_probador_router, uso_router]


# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de arriba, publicados bajo el código de la tienda
# (D02, D10). La empresa la fija `contexto_empresa` (core/tenant.py) desde el
# código de la ruta; `_codigo_tienda` solo documenta el parámetro en OpenAPI.
# No se copian handlers: así la ruta vieja y la nueva no se desincronizan, y los
# `@limiter.limit` viajan con la función.


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)

for _ruta, _handler, _modelo in (
    ("/categorias", listar_categorias, list[CategoriaRespuesta]),
    ("/categorias/{categoria_id}", obtener_categoria, CategoriaRespuesta),
    ("/tallas", listar_tallas, list[TallaRespuesta]),
    ("/tallas/{talla_id}", obtener_talla, TallaRespuesta),
    ("/colores", listar_colores, list[ColorRespuesta]),
    ("/colores/{color_id}", obtener_color, ColorRespuesta),
    ("/materiales", listar_materiales, list[MaterialRespuesta]),
    ("/materiales/{material_id}", obtener_material, MaterialRespuesta),
    ("/temporadas", listar_temporadas, list[TemporadaRespuesta]),
    ("/temporadas/{temporada_id}", obtener_temporada, TemporadaRespuesta),
    ("/colecciones", listar_colecciones, list[ColeccionRespuesta]),
    ("/colecciones/{coleccion_id}", obtener_coleccion, ColeccionRespuesta),
    ("/catalogo", listar_catalogo, list[CatalogoItemRespuesta]),
    ("/catalogo/buscar", buscar_catalogo, list[CatalogoItemRespuesta]),  # antes de /{producto_id}
    ("/catalogo/{producto_id}", obtener_detalle_catalogo, CatalogoDetalleRespuesta),
    ("/inventario/disponibilidad", consultar_disponibilidad, list[DisponibilidadRespuesta]),
):
    publico_tienda_router.add_api_route(_ruta, _handler, methods=["GET"], response_model=_modelo)


routers = _routers_catalogo + _routers_probador + _routers_inventario + _routers_abastecimiento + [publico_tienda_router]

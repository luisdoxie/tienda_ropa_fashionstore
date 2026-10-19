"""CU-05 — Gestionar catálogo: maestro y productos

Absorbe los antiguos CU-07 (Gestionar catálogo maestro) y CU-08 (Gestionar
productos, variantes e imágenes).

Actor: Administrador.
Precondición: sesión de administrador con el permiso catalogo.gestionar.
Postcondición: categorías, tallas, colores, materiales, temporadas y
colecciones quedan disponibles para armar productos; el producto, sus
variantes talla-color, su tabla de medidas y sus imágenes quedan
disponibles para el catálogo público.

Caso de uso COMPUESTO: agrupa seis entidades CRUD triviales del catálogo
maestro (una clase pequeña por entidad) y la gestión de productos
(producto + variantes + tabla de medidas + imágenes en una sola clase con
varios métodos públicos).
"""

import re

from sqlalchemy.orm import Session

from app.catalogo.models import (
    Categoria,
    Coleccion,
    Color,
    Material,
    Producto,
    Talla,
    Temporada,
    ProductoImagen,
    ProductoVariante,
    TablaMedida,
)
from app.catalogo.repository import (
    CategoriaRepository,
    ColeccionRepository,
    ColorRepository,
    MaterialRepository,
    TallaRepository,
    TemporadaRepository,
    ImagenRepository,
    ProductoRepository,
    TablaMedidaRepository,
    VarianteRepository,
)
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    ColeccionActualizar,
    ColeccionCrear,
    ColorActualizar,
    ColorCrear,
    MaterialActualizar,
    MaterialCrear,
    TallaActualizar,
    TallaCrear,
    TemporadaActualizar,
    TemporadaCrear,
    ProductoActualizar,
    ProductoCrear,
    TablaMedidaActualizar,
    TablaMedidaCrear,
    VarianteActualizar,
    VariantesGenerarRequest,
)
from app.core import storage
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.repository import confirmar


# ---- Catálogo maestro (antiguo CU-07: Gestionar catálogo maestro) ----

class GestionarCategorias:
    def __init__(self) -> None:
        self._repo = CategoriaRepository()

    def _crearia_ciclo(self, db: Session, categoria_id: int, nuevo_padre_id: int) -> bool:
        """True si engancharle `nuevo_padre_id` como padre de `categoria_id`
        crea un ciclo (incluye el caso trivial de ser su propio padre)."""
        actual: int | None = nuevo_padre_id
        visitados: set[int] = set()
        while actual is not None:
            if actual == categoria_id:
                return True
            if actual in visitados:
                break
            visitados.add(actual)
            padre = self._repo.buscar(db, actual)
            actual = padre.categoria_padre_id if padre else None
        return False

    def _validar_padre(self, db: Session, categoria_id: int | None, categoria_padre_id: int | None) -> None:
        if categoria_padre_id is None:
            return
        padre = self._repo.buscar(db, categoria_padre_id)
        if padre is None or not padre.activo:
            raise NoEncontradoError("Categoría padre no encontrada")
        if categoria_id is not None and self._crearia_ciclo(db, categoria_id, categoria_padre_id):
            raise DomainError("Una categoría no puede ser su propio padre ni crear un ciclo")

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Categoria]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, categoria_id: int) -> Categoria:
        return self._repo.obtener(db, categoria_id)

    def crear(self, db: Session, datos: CategoriaCrear) -> Categoria:
        self._validar_padre(db, None, datos.categoria_padre_id)
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, categoria_id: int, datos: CategoriaActualizar) -> Categoria:
        if datos.categoria_padre_id is not None:
            self._validar_padre(db, categoria_id, datos.categoria_padre_id)
        return self._repo.actualizar(db, categoria_id, datos)

    def desactivar(self, db: Session, categoria_id: int) -> Categoria:
        if self._repo.listar_hijos(db, categoria_id):
            raise ConflictoError("No se puede desactivar: la categoría tiene subcategorías activas")
        if self._repo.tiene_productos_activos(db, categoria_id):
            raise ConflictoError("No se puede desactivar: la categoría tiene productos activos")
        return self._repo.desactivar(db, categoria_id)


class GestionarTallas:
    """Sin columna `activo` (CRUDBaseSinActivo): se eliminan físicamente."""

    def __init__(self) -> None:
        self._repo = TallaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Talla]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, talla_id: int) -> Talla:
        return self._repo.obtener(db, talla_id)

    def crear(self, db: Session, datos: TallaCrear) -> Talla:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, talla_id: int, datos: TallaActualizar) -> Talla:
        return self._repo.actualizar(db, talla_id, datos)

    def eliminar(self, db: Session, talla_id: int) -> None:
        self._repo.eliminar(db, talla_id)


class GestionarColores:
    def __init__(self) -> None:
        self._repo = ColorRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Color]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, color_id: int) -> Color:
        return self._repo.obtener(db, color_id)

    def crear(self, db: Session, datos: ColorCrear) -> Color:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, color_id: int, datos: ColorActualizar) -> Color:
        return self._repo.actualizar(db, color_id, datos)

    def eliminar(self, db: Session, color_id: int) -> None:
        self._repo.eliminar(db, color_id)


class GestionarMateriales:
    def __init__(self) -> None:
        self._repo = MaterialRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Material]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, material_id: int) -> Material:
        return self._repo.obtener(db, material_id)

    def crear(self, db: Session, datos: MaterialCrear) -> Material:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, material_id: int, datos: MaterialActualizar) -> Material:
        return self._repo.actualizar(db, material_id, datos)

    def eliminar(self, db: Session, material_id: int) -> None:
        self._repo.eliminar(db, material_id)


class GestionarTemporadas:
    def __init__(self) -> None:
        self._repo = TemporadaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Temporada]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, temporada_id: int) -> Temporada:
        return self._repo.obtener(db, temporada_id)

    def crear(self, db: Session, datos: TemporadaCrear) -> Temporada:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, temporada_id: int, datos: TemporadaActualizar) -> Temporada:
        temporada = self._repo.obtener(db, temporada_id)
        inicio = datos.fecha_inicio if "fecha_inicio" in datos.model_fields_set else temporada.fecha_inicio
        fin = datos.fecha_fin if "fecha_fin" in datos.model_fields_set else temporada.fecha_fin
        if inicio and fin and fin <= inicio:
            raise DomainError("fecha_fin debe ser posterior a fecha_inicio")
        return self._repo.actualizar(db, temporada_id, datos)

    def desactivar(self, db: Session, temporada_id: int) -> Temporada:
        return self._repo.desactivar(db, temporada_id)


class GestionarColecciones:
    def __init__(self) -> None:
        self._repo = ColeccionRepository()
        self._temporadas = TemporadaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Coleccion]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, coleccion_id: int) -> Coleccion:
        return self._repo.obtener(db, coleccion_id)

    def crear(self, db: Session, datos: ColeccionCrear) -> Coleccion:
        if datos.temporada_id is not None:
            self._temporadas.obtener(db, datos.temporada_id)
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, coleccion_id: int, datos: ColeccionActualizar) -> Coleccion:
        if datos.temporada_id is not None:
            self._temporadas.obtener(db, datos.temporada_id)
        return self._repo.actualizar(db, coleccion_id, datos)

    def desactivar(self, db: Session, coleccion_id: int) -> Coleccion:
        return self._repo.desactivar(db, coleccion_id)


# ---- Productos, variantes e imágenes (antiguo CU-08: Gestionar productos, variantes e imágenes) ----

CONTENT_TYPES_PERMITIDOS = {"image/jpeg", "image/png", "image/webp"}
TAMANIO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10MB

# CLAUDE.md: "Alcance del probador virtual: solo prendas superiores
# masculinas (poleras, camisas, chamarras)". No hay columna en `categoria`
# para marcar esto, así que se resuelve por nombre. Si el admin manda
# admite_probador=True en una categoría que no matchea acá, se ignora.
PALABRAS_TORSO_SUPERIOR = {"polera", "camisa", "chamarra"}


class GestionarProductos:
    def __init__(self) -> None:
        self._categorias = CategoriaRepository()
        self._materiales = MaterialRepository()
        self._temporadas = TemporadaRepository()
        self._colecciones = ColeccionRepository()
        self._tallas = TallaRepository()
        self._colores = ColorRepository()
        self._productos = ProductoRepository()
        self._variantes = VarianteRepository()
        self._medidas = TablaMedidaRepository()
        self._imagenes = ImagenRepository()

    # -- Helpers privados ---------------------------------------------------

    def _es_torso_superior(self, db: Session, categoria: Categoria) -> bool:
        actual: Categoria | None = categoria
        visitados: set[int] = set()
        while actual is not None and actual.id not in visitados:
            visitados.add(actual.id)
            nombre = actual.nombre.strip().lower()
            if any(palabra in nombre for palabra in PALABRAS_TORSO_SUPERIOR):
                return True
            actual = self._categorias.buscar(db, actual.categoria_padre_id) if actual.categoria_padre_id else None
        return False

    def _resolver_admite_probador(self, db: Session, categoria_id: int, admite_probador_pedido: bool) -> bool:
        if not admite_probador_pedido:
            return False
        categoria = self._categorias.obtener(db, categoria_id)
        return self._es_torso_superior(db, categoria)

    def _validar_referencias_producto(
        self,
        db: Session,
        categoria_id: int | None,
        material_id: int | None,
        temporada_id: int | None,
        coleccion_id: int | None,
    ) -> None:
        if categoria_id is not None:
            self._categorias.obtener(db, categoria_id)
        if material_id is not None:
            self._materiales.obtener(db, material_id)
        if temporada_id is not None:
            self._temporadas.obtener(db, temporada_id)
        if coleccion_id is not None:
            self._colecciones.obtener(db, coleccion_id)

    def _slug_color(self, nombre: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", nombre).upper()

    def _sku_unico(self, db: Session, sku_base: str) -> str:
        sku = sku_base
        sufijo = 2
        while self._variantes.obtener_por_sku(db, sku) is not None:
            sku = f"{sku_base}-{sufijo}"
            sufijo += 1
        return sku

    def _obtener_tallas(self, db: Session, tallas_ids: list[int]) -> list[Talla]:
        ids_unicos = set(tallas_ids)
        tallas = list(self._tallas.listar_por_ids(db, ids_unicos).values())
        if len(tallas) != len(ids_unicos):
            raise NoEncontradoError("Una o más tallas no existen")
        return tallas

    def _obtener_colores(self, db: Session, colores_ids: list[int]) -> list[Color]:
        ids_unicos = set(colores_ids)
        colores = list(self._colores.listar_por_ids(db, ids_unicos).values())
        if len(colores) != len(ids_unicos):
            raise NoEncontradoError("Uno o más colores no existen")
        return colores

    # -- Producto -------------------------------------------------------------

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Producto]:
        return list(self._productos.listar(db, paginacion))

    def obtener(self, db: Session, producto_id: int) -> Producto:
        return self._productos.obtener(db, producto_id)

    def crear(self, db: Session, datos: ProductoCrear, creado_por: int | None) -> Producto:
        self._validar_referencias_producto(
            db, datos.categoria_id, datos.material_id, datos.temporada_id, datos.coleccion_id
        )

        admite_probador_real = self._resolver_admite_probador(db, datos.categoria_id, datos.admite_probador)
        datos = datos.model_copy(update={"admite_probador": admite_probador_real})

        # Producto + variantes son UNA unidad de trabajo: un solo commit al
        # final. Si fallan las tallas/colores/variantes, se revierte también
        # el producto (antes quedaba un producto sin variantes).
        try:
            producto = self._productos.crear(db, datos, creado_por, commit=False)
            self.generar_variantes(db, producto, datos.tallas_ids, datos.colores_ids, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(producto)
        return producto

    def actualizar(self, db: Session, producto_id: int, datos: ProductoActualizar) -> Producto:
        producto = self._productos.obtener(db, producto_id)
        self._validar_referencias_producto(
            db, datos.categoria_id, datos.material_id, datos.temporada_id, datos.coleccion_id
        )

        cambia_categoria = "categoria_id" in datos.model_fields_set
        cambia_probador = "admite_probador" in datos.model_fields_set
        if cambia_categoria or cambia_probador:
            categoria_id = datos.categoria_id if cambia_categoria else producto.categoria_id
            admite_probador_pedido = datos.admite_probador if cambia_probador else producto.admite_probador
            datos = datos.model_copy(
                update={"admite_probador": self._resolver_admite_probador(db, categoria_id, admite_probador_pedido)}
            )

        return self._productos.actualizar(db, producto_id, datos)

    def desactivar(self, db: Session, producto_id: int) -> Producto:
        return self._productos.desactivar(db, producto_id)

    # -- Variantes --------------------------------------------------------------

    def generar_variantes(
        self,
        db: Session,
        producto: Producto,
        tallas_ids: list[int],
        colores_ids: list[int],
        commit: bool = True,
    ) -> list[ProductoVariante]:
        """Combinatoria talla × color con SKU {codigo_producto}-{codigo_talla}-{codigo_color}.

        Si una combinación ya existe y está activa, se salta: llamar esto de
        nuevo agregando un color no duplica las variantes que ya estaban. Si
        existe pero fue desactivada, se reactiva (mismo sku) en vez de
        quedar huérfana para siempre.

        `commit=False`: deja las variantes en flush y no confirma (lo usa
        `crear` para que producto y variantes se confirmen juntos)."""
        tallas = self._obtener_tallas(db, tallas_ids)
        colores = self._obtener_colores(db, colores_ids)

        creadas: list[ProductoVariante] = []
        for talla in tallas:
            for color in colores:
                existente = self._variantes.obtener_por_combinacion(db, producto.id, talla.id, color.id)
                if existente is not None:
                    if not existente.activo:
                        existente.activo = True
                        creadas.append(existente)
                    continue
                sku_base = f"{producto.codigo}-{talla.codigo}-{self._slug_color(color.nombre)}".upper()
                sku = self._sku_unico(db, sku_base)
                variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=sku)
                db.add(variante)
                creadas.append(variante)

        confirmar(db, commit)
        for variante in creadas:
            db.refresh(variante)
        return creadas

    def agregar_variantes(self, db: Session, producto_id: int, datos: VariantesGenerarRequest) -> list[ProductoVariante]:
        producto = self._productos.obtener(db, producto_id)
        return self.generar_variantes(db, producto, datos.tallas_ids, datos.colores_ids)

    def listar_variantes(self, db: Session, producto_id: int) -> list[ProductoVariante]:
        self._productos.obtener(db, producto_id)  # 404 si no existe
        return self._variantes.listar_por_producto(db, producto_id)

    def actualizar_variante(self, db: Session, variante_id: int, datos: VarianteActualizar) -> ProductoVariante:
        if datos.codigo_barras is not None:
            existente = self._variantes.obtener_por_codigo_barras(db, datos.codigo_barras)
            if existente is not None and existente.id != variante_id:
                raise ConflictoError("Ya existe una variante con ese código de barras")
        if datos.activo is False:
            # TODO(P3.1): bloquear si stock.cantidad_fisica > 0. Cuando se
            # implemente, esto llama a catalogo.politicas, nunca consulta
            # la tabla stock directamente.
            pass
        return self._variantes.actualizar(db, variante_id, datos)

    def desactivar_variante(self, db: Session, variante_id: int) -> ProductoVariante:
        # Mismo TODO que actualizar_variante: bloquear si hay stock físico.
        return self._variantes.desactivar(db, variante_id)

    # -- Tabla de medidas ---------------------------------------------------------

    def listar_medidas(self, db: Session, producto_id: int) -> list[TablaMedida]:
        self._productos.obtener(db, producto_id)  # 404 si no existe
        return list(self._medidas.listar_por_producto(db, producto_id))

    def crear_medida(self, db: Session, producto_id: int, datos: TablaMedidaCrear) -> TablaMedida:
        self._productos.obtener(db, producto_id)
        self._tallas.obtener(db, datos.talla_id)
        return self._medidas.crear(db, producto_id, datos)

    def actualizar_medida(
        self, db: Session, producto_id: int, medida_id: int, datos: TablaMedidaActualizar
    ) -> TablaMedida:
        if datos.talla_id is not None:
            self._tallas.obtener(db, datos.talla_id)
        return self._medidas.actualizar(db, producto_id, medida_id, datos)

    def eliminar_medida(self, db: Session, producto_id: int, medida_id: int) -> None:
        self._medidas.eliminar(db, producto_id, medida_id)

    # -- Imágenes de producto ------------------------------------------------------

    def subir_imagen(
        self,
        db: Session,
        producto_id: int,
        contenido: bytes,
        content_type: str | None,
        color_id: int | None,
        es_principal: bool,
    ) -> tuple[ProductoImagen, str]:
        self._productos.obtener(db, producto_id)
        if color_id is not None:
            self._colores.obtener(db, color_id)

        if content_type not in CONTENT_TYPES_PERMITIDOS:
            raise DomainError("El archivo debe ser una imagen (jpeg, png o webp)")
        if len(contenido) > TAMANIO_MAXIMO_BYTES:
            raise DomainError("La imagen supera el tamaño máximo permitido (10MB)")

        public_id = storage.subir_imagen(contenido, storage.carpeta_producto(producto_id))

        orden = len(self._imagenes.listar_por_producto(db, producto_id))
        imagen = self._imagenes.crear(db, producto_id, public_id, color_id, orden)

        if es_principal:
            imagen = self._imagenes.marcar_principal(db, imagen)

        return imagen, storage.url_catalogo(public_id)

    def eliminar_imagen(self, db: Session, imagen_id: int) -> None:
        imagen = self._imagenes.obtener(db, imagen_id)
        # Primero se borra el archivo real; si eso falla, la fila de la base
        # se conserva (mejor una referencia a un archivo que sigue vivo que
        # perder la referencia a uno que capaz no se borró).
        storage.eliminar_imagen(imagen.url)
        self._imagenes.eliminar(db, imagen_id)

    def marcar_imagen_principal(self, db: Session, imagen_id: int) -> tuple[ProductoImagen, str]:
        imagen = self._imagenes.obtener(db, imagen_id)
        imagen = self._imagenes.marcar_principal(db, imagen)
        return imagen, storage.url_catalogo(imagen.url)

"""Carga las prendas del dataset (catalogo.json + JPG + overlays PNG) al
catálogo y al probador virtual. Idempotente y reanudable.

Por cada prenda del JSON:
  1. Producto `FS-{id}` (categoría Poleras, Polos, Camisetas deportivas o
     Chamarras; género según el dataset; tallas L y XL; precio fijo) vía
     GestionarProductos.crear(). Hombre y la chamarra (unisex) admiten el
     probador; las prendas de mujer no.
  2. Foto JPG de catálogo -> fashionstore/productos/{producto_id}/ vía
     GestionarProductos.subir_imagen().
  3. Overlay PNG (solo si admite probador) -> fashionstore/probador/{variante_base_id}/
     vía CargarAssetsProbador.subir(), y validado. Las demás tallas reutilizan el
     mismo archivo (CargarAssetsProbador.clonar_a_variante), sin volver a
     subirlo. Es la imagen de la prenda que usa el modo generativo.

`cargar_prenda` es reutilizable: `scripts.poblar_demo` la llama una vez por
prenda y por organización.

Por defecto NO escribe nada (dry-run): muestra lo que haría y genera una
hoja de vista previa de los overlays. Para escribir de verdad
hace falta --ejecutar. Cada corrida real deja un manifiesto en backups/
con todo lo creado, que sirve para deshacer con --revertir.

Uso (desde backend/):
    python -m scripts.seed_prendas_probador --origen "<carpeta>"
    python -m scripts.seed_prendas_probador --origen "<carpeta>" --solo 10005 --ejecutar
    python -m scripts.seed_prendas_probador --origen "<carpeta>" --ejecutar
    python -m scripts.seed_prendas_probador --revertir backups/manifiesto_prendas_XXXX.json --ejecutar

Variables de entorno para --ejecutar: DATABASE_URL, JWT_SECRET_KEY (la
exige Settings, cualquier valor sirve acá) y CLOUDINARY_*.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image, ImageDraw

DIR_BACKUPS = Path(__file__).resolve().parent.parent / "backups"

TAMANIO_MAXIMO_PNG = 3 * 1024 * 1024  # mismo límite que CargarAssetsProbador
LADO_MINIMO_PX = 512
TALLAS = ["L", "XL"]

CATEGORIA_PADRE = "Ropa superior"
CATEGORIA_POR_TIPO = {"Tshirts": "Poleras", "Jackets": "Chamarras"}
# Categoría según el tipo de prenda que deduce `_tipo_y_precio`.
CATEGORIA_POR_PRENDA = {
    "Polera": "Poleras",
    "Polo": "Polos",
    "Camiseta": "Camisetas deportivas",
    "Chamarra": "Chamarras",
}
# Polos y Camisetas deportivas cuelgan de Poleras: el backend reconoce el torso superior (el
# que admite probador) por el nombre de la categoría o el de sus ancestros (CU-05,
# PALABRAS_TORSO_SUPERIOR: polera, camisa, chamarra), y ni "Polos" ni "Camisetas" lo contienen.
CATEGORIA_MADRE = {"Polos": "Poleras", "Camisetas deportivas": "Poleras"}

COLORES: dict[str, tuple[str, str]] = {
    "White": ("Blanco", "#FFFFFF"),
    "Black": ("Negro", "#1A1A1A"),
    "Blue": ("Azul", "#1D4ED8"),
    "Navy Blue": ("Azul marino", "#1E3A5F"),
    "Red": ("Rojo", "#DC2626"),
    "Grey": ("Gris", "#9CA3AF"),
    "Yellow": ("Amarillo", "#FACC15"),
}

PRECIO_POLERA = Decimal("149.00")
PRECIO_POLO_JERSEY = Decimal("189.00")
PRECIO_CHAMARRA = Decimal("399.00")

USOS = {"Sports": "deportivo", "Casual": "casual"}

# Palabras del nombre original que no aportan al nombre en español: género,
# tipo de prenda (ya va como prefijo) y abreviaturas del dataset.
_PALABRAS_DESCARTADAS = {
    "men", "mens", "men's", "women", "women's", "womens", "as", "ss",
    "t-shirt", "t-shirts", "tshirt", "tshirts", "jersey", "jerseys",
    "jacket", "jackets", "polo",
}


# ---- Mapeos (sin base de datos) ---------------------------------------------


@dataclass
class PrendaPlan:
    id_dataset: int
    codigo: str
    nombre: str
    descripcion: str
    categoria: str
    color: str
    color_hex: str
    temporada: str
    anio: int
    fecha_inicio: dt.date
    fecha_fin: dt.date
    precio: Decimal
    ruta_jpg: Path
    ruta_png: Path
    genero: str = "hombre"
    admite_probador: bool = True


def _tipo_y_precio(item: dict) -> tuple[str, Decimal]:
    nombre = item["productDisplayName"].lower()
    if item["articleType"] == "Jackets":
        return "Chamarra", PRECIO_CHAMARRA
    if "polo" in nombre:
        return "Polo", PRECIO_POLO_JERSEY
    if "jersey" in nombre:
        return "Camiseta", PRECIO_POLO_JERSEY
    return "Polera", PRECIO_POLERA


def precio_con_factor(base: Decimal, factor: Decimal) -> Decimal:
    """`base` x `factor` a la decena más cercana menos 1 (149, 159, 169...).
    Con factor 1 los precios base (149, 189 y 399) quedan igual."""
    decenas = (base * factor / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (decenas * 10 - 1).quantize(Decimal("0.01"))


def genero_de(item: dict) -> str:
    """Género del producto según el dataset. La chamarra del dataset es de corte
    femenino y se ofrece también a hombres: va como unisex."""
    if item["articleType"] == "Jackets":
        return "unisex"
    if item.get("gender") == "Men":
        return "hombre"
    if item.get("gender") == "Women":
        return "mujer"
    return "unisex"


def _nombre_es(item: dict, tipo: str, color_es: str) -> str:
    palabras = item["productDisplayName"].split()
    marca = palabras[0]
    colores = {p.lower() for p in item["baseColour"].split()}
    modelo = [
        p
        for p in palabras[1:]
        if p.lower() not in _PALABRAS_DESCARTADAS and p.lower() not in colores and p.lower() != marca.lower()
    ]
    partes = [tipo, marca, *modelo]
    return f"{' '.join(partes)} ({color_es})"[:120]


def _temporada(item: dict) -> tuple[str, int, dt.date, dt.date]:
    anio = int(item["year"])
    # Hemisferio sur (Bolivia).
    if item["season"] == "Summer":
        return "Verano", anio, dt.date(anio, 12, 1), dt.date(anio + 1, 2, 28)
    if item["season"] == "Fall":
        return "Otoño", anio, dt.date(anio, 3, 1), dt.date(anio, 5, 31)
    if item["season"] == "Winter":
        return "Invierno", anio, dt.date(anio, 6, 1), dt.date(anio, 8, 31)
    return "Primavera", anio, dt.date(anio, 9, 1), dt.date(anio, 11, 30)


def leer_catalogo(origen: Path) -> list[dict]:
    return json.loads((origen / "catalogo.json").read_text(encoding="utf-8"))


def planificar(
    origen: Path,
    solo: set[int] | None,
    *,
    factor_precio: Decimal = Decimal("1"),
    temporada: tuple[str, int, dt.date, dt.date] | None = None,
) -> list[PrendaPlan]:
    """Una `PrendaPlan` por prenda del `catalogo.json` (o solo las de `solo`).
    `factor_precio` ajusta el precio base de cada tipo de prenda y `temporada`
    reemplaza la del dataset (que es de 2010 a 2012)."""
    items = leer_catalogo(origen)
    planes: list[PrendaPlan] = []
    for item in items:
        if solo and item["id"] not in solo:
            continue
        if item["articleType"] not in CATEGORIA_POR_TIPO:
            raise ValueError(f"{item['id']}: articleType '{item['articleType']}' sin categoría mapeada")
        if item["baseColour"] not in COLORES:
            raise ValueError(f"{item['id']}: color '{item['baseColour']}' sin mapeo")
        color_es, color_hex = COLORES[item["baseColour"]]
        tipo, precio_base = _tipo_y_precio(item)
        nombre_temporada, anio, inicio, fin = temporada if temporada is not None else _temporada(item)
        uso = USOS.get(item.get("usage", ""), item.get("usage", "").lower())
        genero = genero_de(item)
        planes.append(
            PrendaPlan(
                id_dataset=item["id"],
                codigo=f"FS-{item['id']}",
                nombre=_nombre_es(item, tipo, color_es),
                descripcion=f"{item['productDisplayName']}. Uso {uso}.",
                categoria=CATEGORIA_POR_PRENDA[tipo],
                color=color_es,
                color_hex=color_hex,
                temporada=nombre_temporada,
                anio=anio,
                fecha_inicio=inicio,
                fecha_fin=fin,
                precio=precio_con_factor(precio_base, factor_precio),
                ruta_jpg=origen / item["archivo"],
                ruta_png=origen / item["overlay"],
                genero=genero,
                admite_probador=genero in ("hombre", "unisex"),
            )
        )
    return planes


# ---- PNG del overlay ----------------------------------------------------------


def preparar_png(contenido: bytes) -> tuple[bytes, Image.Image]:
    """Deja el PNG por debajo de 3MB sin perder el canal alfa. Primero
    re-comprime sin pérdida; si no alcanza, reduce el tamaño de a 10%."""
    imagen = Image.open(io.BytesIO(contenido))
    imagen.load()
    if imagen.mode != "RGBA":
        imagen = imagen.convert("RGBA")
    if len(contenido) <= TAMANIO_MAXIMO_PNG:
        return contenido, imagen

    escala = 1.0
    while True:
        actual = imagen
        if escala < 1.0:
            nuevo = (round(imagen.width * escala), round(imagen.height * escala))
            if min(nuevo) < LADO_MINIMO_PX:
                raise ValueError("No se pudo bajar el PNG de 3MB sin quedar por debajo de 512px")
            actual = imagen.resize(nuevo, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        actual.save(buffer, format="PNG", optimize=True)
        if buffer.tell() <= TAMANIO_MAXIMO_PNG:
            return buffer.getvalue(), actual
        escala -= 0.1


# ---- Vista previa -------------------------------------------------------------


def generar_vista_previa(planes_con_imagen: list[tuple[PrendaPlan, Image.Image]], destino: Path) -> None:
    celda_w, celda_h, columnas = 240, 320, 6
    filas = (len(planes_con_imagen) + columnas - 1) // columnas
    hoja = Image.new("RGB", (celda_w * columnas, (celda_h + 20) * filas), "#EAE4DA")
    dibujo = ImageDraw.Draw(hoja)
    for i, (plan, imagen) in enumerate(planes_con_imagen):
        miniatura = imagen.copy()
        miniatura.thumbnail((celda_w, celda_h))
        ox = (i % columnas) * celda_w + (celda_w - miniatura.width) // 2
        oy = (i // columnas) * (celda_h + 20) + (celda_h - miniatura.height) // 2
        hoja.paste(miniatura, (ox, oy), miniatura)
        dibujo.text(((i % columnas) * celda_w + 6, (i // columnas) * (celda_h + 20) + celda_h), plan.codigo, fill="#1C1713")
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino)


# ---- Ejecución real ------------------------------------------------------------


class Manifiesto:
    """Registro de todo lo creado en una corrida. Se guarda a disco después
    de cada paso, así una corrida cortada a mitad igual se puede revertir."""

    CLAVES = ["categorias", "colores", "temporadas", "productos", "variantes", "imagenes", "activos", "public_ids"]

    def __init__(self, ruta: Path, host: str):
        self.ruta = ruta
        self.datos: dict = {"creado_en": dt.datetime.now().isoformat(timespec="seconds"), "host": host}
        self.datos.update({clave: [] for clave in self.CLAVES})

    def agregar(self, clave: str, valor) -> None:
        self.datos[clave].append(valor)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.datos, indent=2, ensure_ascii=False), encoding="utf-8")


def _anotar(manifiesto: Manifiesto | None, clave: str, valor) -> None:
    if manifiesto is not None:
        manifiesto.agregar(clave, valor)


def _host_de_la_base() -> str:
    from app.core.database import engine

    return f"{engine.url.host}:{engine.url.port}/{engine.url.database}"


def etiqueta_destino() -> str:
    """Nombre de la base y si es local o remota. Los manifiestos de `scripts.poblar_demo`
    guardan esto y NO el host ni el puerto del servidor."""
    from app.core.database import engine

    local = engine.url.host in (None, "", "localhost", "127.0.0.1")
    return f"base:{engine.url.database}:{'local' if local else 'remota'}"


def _obtener_o_crear_categoria(db, manifiesto: Manifiesto | None, nombre: str, padre_id: int | None) -> int:
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarCategorias
    from app.catalogo.models import Categoria
    from app.catalogo.schemas import CategoriaCrear

    existente = db.query(Categoria).filter(Categoria.nombre.ilike(nombre), Categoria.activo.is_(True)).first()
    if existente:
        return existente.id
    categoria = GestionarCategorias().crear(db, CategoriaCrear(nombre=nombre, categoria_padre_id=padre_id))
    _anotar(manifiesto, "categorias", categoria.id)
    return categoria.id


def _categoria_de_prenda(db, manifiesto: Manifiesto | None, nombre: str, raiz_id: int) -> int:
    """La categoría de la prenda, con su madre (Poleras) si es un Polo o una Camiseta deportiva."""
    madre = CATEGORIA_MADRE.get(nombre)
    padre_id = _obtener_o_crear_categoria(db, manifiesto, madre, raiz_id) if madre else raiz_id
    return _obtener_o_crear_categoria(db, manifiesto, nombre, padre_id)


def _obtener_o_crear_color(db, manifiesto: Manifiesto | None, nombre: str, hexa: str) -> int:
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarColores
    from app.catalogo.models import Color
    from app.catalogo.schemas import ColorCrear

    existente = db.query(Color).filter(Color.nombre.ilike(nombre)).first()
    if existente:
        return existente.id
    color = GestionarColores().crear(db, ColorCrear(nombre=nombre, codigo_hex=hexa))
    _anotar(manifiesto, "colores", color.id)
    return color.id


def _obtener_o_crear_temporada(db, manifiesto: Manifiesto | None, plan: PrendaPlan) -> int:
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarTemporadas
    from app.catalogo.models import Temporada
    from app.catalogo.schemas import TemporadaCrear

    existente = db.query(Temporada).filter(Temporada.nombre == plan.temporada, Temporada.anio == plan.anio).first()
    if existente:
        return existente.id
    temporada = GestionarTemporadas().crear(
        db,
        TemporadaCrear(
            nombre=plan.temporada, anio=plan.anio, fecha_inicio=plan.fecha_inicio, fecha_fin=plan.fecha_fin
        ),
    )
    _anotar(manifiesto, "temporadas", temporada.id)
    return temporada.id


def _es_error_de_red(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if type(exc).__module__.startswith("cloudinary"):  # Cloudinary envuelve el error de red en su Error
        texto = str(exc)
        return any(p in texto for p in ("ConnectionReset", "ProtocolError", "Timeout", "Connection aborted", "RemoteDisconnected"))
    return False


def reintentar(operacion, *, intentos: int = 4, espera: float = 3.0):
    """Repite una subida a Cloudinary si la red la corta (conexión reiniciada, tiempo agotado), con
    espera creciente. Solo se usa en operaciones cuya primera acción es la subida, así que repetirlas
    no deja filas a medias. Cualquier otro error (validación, base de datos) se propaga de inmediato."""
    for n in range(1, intentos + 1):
        try:
            return operacion()
        except Exception as exc:  # noqa: BLE001 -- se vuelve a lanzar si no es de red
            if n == intentos or not _es_error_de_red(exc):
                raise
            print(f"  (red) {type(exc).__name__}: reintento {n}/{intentos - 1} en {espera * n:.0f} s")
            time.sleep(espera * n)


def exigir_cloudinary() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        sys.exit("Faltan las variables CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET")


@dataclass
class ContextoCarga:
    """Lo que `cargar_prenda` necesita y se arma una sola vez por empresa."""

    cu_productos: object
    cu_assets: object
    tallas: dict[str, int]  # código de talla -> id
    codigos_tallas: list[str]  # en orden: la primera lleva el overlay y las demás lo reutilizan
    padre_id: int
    manifiesto: Manifiesto | None = None


def preparar_contexto(db, codigos_tallas: list[str], manifiesto: Manifiesto | None = None) -> ContextoCarga:
    """Dentro de la empresa ya fijada en la sesión: cada empresa tiene sus
    propias tallas y categorías."""
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarProductos
    from app.catalogo.casos_uso.cu10_gestionar_assets_probador import CargarAssetsProbador
    from app.catalogo.models import Talla

    tallas = {t.codigo: t.id for t in db.query(Talla).filter(Talla.codigo.in_(codigos_tallas))}
    faltantes = set(codigos_tallas) - set(tallas)
    if faltantes:
        sys.exit(f"Faltan las tallas {sorted(faltantes)}: correr antes scripts.seed_catalogo")
    padre_id = _obtener_o_crear_categoria(db, manifiesto, CATEGORIA_PADRE, None)
    return ContextoCarga(GestionarProductos(), CargarAssetsProbador(), tallas, list(codigos_tallas), padre_id, manifiesto)


def cargar_prenda(db, plan: PrendaPlan, ctx: ContextoCarga, *, con_fotos: bool = True) -> None:
    """Producto con sus variantes, foto de catálogo y, si admite probador, el
    overlay validado en todas las tallas. Idempotente: lo que ya existe se
    deja como está. Con `con_fotos=False` solo crea el producto y sus variantes."""
    from app.catalogo.models import ActivoProbador, Producto, ProductoImagen, ProductoVariante
    from app.catalogo.schemas import ProductoCrear

    manifiesto = ctx.manifiesto
    print(f"\n[{plan.codigo}] {plan.nombre}")
    categoria_id = _categoria_de_prenda(db, manifiesto, plan.categoria, ctx.padre_id)
    color_id = _obtener_o_crear_color(db, manifiesto, plan.color, plan.color_hex)
    temporada_id = _obtener_o_crear_temporada(db, manifiesto, plan)

    producto = db.query(Producto).filter(Producto.codigo == plan.codigo).one_or_none()
    if producto is None:
        producto = ctx.cu_productos.crear(
            db,
            ProductoCrear(
                codigo=plan.codigo,
                nombre=plan.nombre,
                descripcion=plan.descripcion,
                categoria_id=categoria_id,
                temporada_id=temporada_id,
                genero=plan.genero,
                precio_base=plan.precio,
                admite_probador=plan.admite_probador,
                tallas_ids=[ctx.tallas[c] for c in ctx.codigos_tallas],
                colores_ids=[color_id],
            ),
            creado_por=None,
        )
        _anotar(manifiesto, "productos", producto.id)
        for variante in ctx.cu_productos.listar_variantes(db, producto.id):
            _anotar(manifiesto, "variantes", variante.id)
        print(f"  producto creado id={producto.id}")
    else:
        print(f"  producto ya existía id={producto.id}")
    if plan.admite_probador and not producto.admite_probador:
        sys.exit(f"  {plan.codigo} quedó con admite_probador=false: revisar la categoría")
    if not con_fotos:
        return

    if db.query(ProductoImagen).filter(ProductoImagen.producto_id == producto.id).count() == 0:
        contenido_jpg = plan.ruta_jpg.read_bytes()
        imagen, _ = reintentar(
            lambda: ctx.cu_productos.subir_imagen(db, producto.id, contenido_jpg, "image/jpeg", color_id, es_principal=True)
        )
        _anotar(manifiesto, "imagenes", imagen.id)
        _anotar(manifiesto, "public_ids", imagen.url)
        print(f"  foto de catálogo subida ({imagen.url})")
    else:
        print("  foto de catálogo ya existía")

    if not plan.admite_probador:
        print("  sin probador (prenda de mujer)")
        return

    variantes = {
        v.talla_id: v
        for v in db.query(ProductoVariante).filter(
            ProductoVariante.producto_id == producto.id, ProductoVariante.color_id == color_id
        )
    }
    primera = ctx.codigos_tallas[0]
    variante_base = variantes[ctx.tallas[primera]]

    def overlay_de(variante_id: int) -> ActivoProbador | None:
        return (
            db.query(ActivoProbador)
            .filter(
                ActivoProbador.variante_id == variante_id,
                ActivoProbador.tipo == "overlay_2d",
                ActivoProbador.estado != "rechazado",
            )
            .one_or_none()
        )

    base = overlay_de(variante_base.id)
    if base is None:
        png, _ = preparar_png(plan.ruta_png.read_bytes())
        base, _ = reintentar(lambda: ctx.cu_assets.subir(db, variante_base.id, "overlay_2d", png, "image/png", None))
        _anotar(manifiesto, "activos", base.id)
        _anotar(manifiesto, "public_ids", base.url)
        base, _ = ctx.cu_assets.validar(db, base.id)
        print(f"  overlay subido y validado ({base.url})")
    else:
        print(f"  overlay ya existía en talla {primera}")

    for codigo_talla in ctx.codigos_tallas[1:]:
        variante = variantes[ctx.tallas[codigo_talla]]
        if overlay_de(variante.id) is None:
            copia = ctx.cu_assets.clonar_a_variante(db, base.id, variante.id)
            _anotar(manifiesto, "activos", copia.id)
            print(f"  overlay asignado a talla {codigo_talla}")


def cargar(planes: list[PrendaPlan], empresa: str | None = None) -> None:
    import app.main  # noqa: F401  (registra todos los modelos y configura Cloudinary)
    from scripts._empresa import abrir_sesion

    exigir_cloudinary()

    host = _host_de_la_base()
    marca = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    manifiesto = Manifiesto(DIR_BACKUPS / f"manifiesto_prendas_{marca}.json", host)
    print(f"Base destino: {host}")
    print(f"Manifiesto:   {manifiesto.ruta}")

    db, _empresa = abrir_sesion(empresa)
    try:
        ctx = preparar_contexto(db, TALLAS, manifiesto)
        for plan in planes:
            cargar_prenda(db, plan, ctx)
    finally:
        db.close()

    if manifiesto.ruta.exists():
        print(f"\nListo. Para deshacer: python -m scripts.seed_prendas_probador --revertir \"{manifiesto.ruta}\" --ejecutar")
    else:
        print("\nListo. No se creó nada nuevo (todo ya existía).")


def revertir(ruta_manifiesto: Path, ejecutar: bool, empresa: str | None = None) -> None:
    datos = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
    resumen = {clave: len(datos.get(clave, [])) for clave in Manifiesto.CLAVES}
    print(f"Manifiesto de {datos['creado_en']} contra {datos['host']}")
    print(f"Se eliminaría: {resumen}")
    if not ejecutar:
        print("(dry-run: agregar --ejecutar para eliminar)")
        return

    import app.main  # noqa: F401
    from app.catalogo.models import Categoria, Color, Producto, ProductoImagen, ProductoVariante, Temporada
    from app.core import storage
    from app.catalogo.models import ActivoProbador
    from scripts._empresa import abrir_sesion

    host = etiqueta_destino() if str(datos["host"]).startswith("base:") else _host_de_la_base()
    if host != datos["host"]:
        sys.exit(f"La base actual ({host}) no es la del manifiesto ({datos['host']}). No se toca nada.")

    # Borrado físico a propósito: deshace un seed recién creado, sin ventas
    # ni stock asociados. Si alguna fila ya tiene uso (FK), la transacción
    # entera se revierte y Cloudinary no se toca.
    db, _empresa = abrir_sesion(empresa)
    try:
        for modelo, clave in (
            (ActivoProbador, "activos"),
            (ProductoImagen, "imagenes"),
            (ProductoVariante, "variantes"),
            (Producto, "productos"),
            (Temporada, "temporadas"),
            (Color, "colores"),
        ):
            ids = datos.get(clave, [])
            if ids:
                db.query(modelo).filter(modelo.id.in_(ids)).delete(synchronize_session=False)
        for categoria_id in reversed(datos.get("categorias", [])):  # hijas antes que el padre
            db.query(Categoria).filter(Categoria.id == categoria_id).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        sys.exit(f"No se pudo revertir la base (nada cambió): {exc}")
    finally:
        db.close()
    print("Filas eliminadas de la base.")

    for public_id in dict.fromkeys(datos.get("public_ids", [])):
        try:
            storage.eliminar_imagen(public_id)
            print(f"  Cloudinary: eliminado {public_id}")
        except Exception as exc:  # noqa: BLE001 -- se informa y se sigue con el resto
            print(f"  Cloudinary: no se pudo eliminar {public_id}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origen", type=Path, help="Carpeta con catalogo.json, los JPG y overlays/")
    parser.add_argument("--solo", type=int, nargs="*", help="Ids del dataset a procesar (por defecto, todos)")
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    parser.add_argument("--revertir", type=Path, help="Manifiesto de una corrida anterior a deshacer")
    parser.add_argument("--empresa", help="Código de la empresa (por defecto SEED_EMPRESA o 'fashionstore')")
    args = parser.parse_args()

    if args.revertir:
        revertir(args.revertir, args.ejecutar, args.empresa)
        return
    if not args.origen:
        parser.error("--origen es obligatorio")

    planes = planificar(args.origen, set(args.solo) if args.solo else None)
    if not planes:
        sys.exit("Ninguna prenda coincide con --solo")

    if args.ejecutar:
        cargar(planes, args.empresa)
        return

    vista: list[tuple[PrendaPlan, Image.Image]] = []
    for plan in planes:
        original = plan.ruta_png.read_bytes()
        png, imagen = preparar_png(original)
        vista.append((plan, imagen))
        comprimido = f" -> {len(png) / 1048576:.2f}MB {imagen.size}" if png is not original else ""
        print(
            f"{plan.codigo:9} {plan.categoria:20} {plan.genero:8} {plan.precio:>7} Bs  {plan.color:12} "
            f"{plan.temporada} {plan.anio}  {plan.nombre}\n"
            f"          png {len(original) / 1048576:.2f}MB{comprimido}"
        )
    destino = DIR_BACKUPS / "vista_previa_overlays.png"
    generar_vista_previa(vista, destino)
    print(f"\n{len(planes)} prendas, tallas {TALLAS}. Vista previa: {destino}")
    print("(dry-run: no se escribió nada en la base ni en Cloudinary; agregar --ejecutar)")


if __name__ == "__main__":
    main()

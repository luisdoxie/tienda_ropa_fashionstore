"""Carga las prendas del dataset (catalogo.json + JPG + overlays PNG) al
catálogo y al probador virtual. Idempotente y reanudable.

Por cada prenda del JSON:
  1. Producto `FS-{id}` (categoría Poleras/Chamarras, género hombre, tallas
     L y XL, precio fijo) vía GestionarProductos.crear().
  2. Foto JPG de catálogo -> fashionstore/productos/{producto_id}/ vía
     GestionarProductos.subir_imagen().
  3. Overlay PNG -> fashionstore/probador/{variante_L_id}/ vía
     CargarAssetsProbador.subir(), y validado. La variante XL reutiliza el
     mismo archivo (CargarAssetsProbador.clonar_a_variante), sin volver a
     subirlo. Es la imagen de la prenda que usa el modo generativo.

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
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

DIR_BACKUPS = Path(__file__).resolve().parent.parent / "backups"

TAMANIO_MAXIMO_PNG = 3 * 1024 * 1024  # mismo límite que CargarAssetsProbador
LADO_MINIMO_PX = 512
TALLAS = ["L", "XL"]

CATEGORIA_PADRE = "Ropa superior"
CATEGORIA_POR_TIPO = {"Tshirts": "Poleras", "Jackets": "Chamarras"}

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


def _tipo_y_precio(item: dict) -> tuple[str, Decimal]:
    nombre = item["productDisplayName"].lower()
    if item["articleType"] == "Jackets":
        return "Chamarra", PRECIO_CHAMARRA
    if "polo" in nombre:
        return "Polo", PRECIO_POLO_JERSEY
    if "jersey" in nombre:
        return "Camiseta", PRECIO_POLO_JERSEY
    return "Polera", PRECIO_POLERA


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


def planificar(origen: Path, solo: set[int] | None) -> list[PrendaPlan]:
    items = json.loads((origen / "catalogo.json").read_text(encoding="utf-8"))
    planes: list[PrendaPlan] = []
    for item in items:
        if solo and item["id"] not in solo:
            continue
        if item["articleType"] not in CATEGORIA_POR_TIPO:
            raise ValueError(f"{item['id']}: articleType '{item['articleType']}' sin categoría mapeada")
        if item["baseColour"] not in COLORES:
            raise ValueError(f"{item['id']}: color '{item['baseColour']}' sin mapeo")
        color_es, color_hex = COLORES[item["baseColour"]]
        tipo, precio = _tipo_y_precio(item)
        temporada, anio, inicio, fin = _temporada(item)
        uso = USOS.get(item.get("usage", ""), item.get("usage", "").lower())
        planes.append(
            PrendaPlan(
                id_dataset=item["id"],
                codigo=f"FS-{item['id']}",
                nombre=_nombre_es(item, tipo, color_es),
                descripcion=f"{item['productDisplayName']}. Uso {uso}.",
                categoria=CATEGORIA_POR_TIPO[item["articleType"]],
                color=color_es,
                color_hex=color_hex,
                temporada=temporada,
                anio=anio,
                fecha_inicio=inicio,
                fecha_fin=fin,
                precio=precio,
                ruta_jpg=origen / item["archivo"],
                ruta_png=origen / item["overlay"],
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


def _host_de_la_base() -> str:
    from app.core.database import engine

    return f"{engine.url.host}:{engine.url.port}/{engine.url.database}"


def _obtener_o_crear_categoria(db, manifiesto: Manifiesto, nombre: str, padre_id: int | None) -> int:
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarCategorias
    from app.catalogo.models import Categoria
    from app.catalogo.schemas import CategoriaCrear

    existente = db.query(Categoria).filter(Categoria.nombre.ilike(nombre), Categoria.activo.is_(True)).first()
    if existente:
        return existente.id
    categoria = GestionarCategorias().crear(db, CategoriaCrear(nombre=nombre, categoria_padre_id=padre_id))
    manifiesto.agregar("categorias", categoria.id)
    return categoria.id


def _obtener_o_crear_color(db, manifiesto: Manifiesto, nombre: str, hexa: str) -> int:
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarColores
    from app.catalogo.models import Color
    from app.catalogo.schemas import ColorCrear

    existente = db.query(Color).filter(Color.nombre.ilike(nombre)).first()
    if existente:
        return existente.id
    color = GestionarColores().crear(db, ColorCrear(nombre=nombre, codigo_hex=hexa))
    manifiesto.agregar("colores", color.id)
    return color.id


def _obtener_o_crear_temporada(db, manifiesto: Manifiesto, plan: PrendaPlan) -> int:
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
    manifiesto.agregar("temporadas", temporada.id)
    return temporada.id


def cargar(planes: list[PrendaPlan]) -> None:
    import app.main  # noqa: F401  (registra todos los modelos y configura Cloudinary)
    from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarProductos
    from app.catalogo.models import Producto, ProductoImagen, ProductoVariante, Talla
    from app.catalogo.schemas import ProductoCrear
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.catalogo.casos_uso.cu10_gestionar_assets_probador import CargarAssetsProbador
    from app.catalogo.models import ActivoProbador

    cu_productos = GestionarProductos()
    cu_assets = CargarAssetsProbador()
    settings = get_settings()
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        sys.exit("Faltan las variables CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET")

    host = _host_de_la_base()
    marca = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    manifiesto = Manifiesto(DIR_BACKUPS / f"manifiesto_prendas_{marca}.json", host)
    print(f"Base destino: {host}")
    print(f"Manifiesto:   {manifiesto.ruta}")

    db = SessionLocal()
    try:
        tallas = {t.codigo: t.id for t in db.query(Talla).filter(Talla.codigo.in_(TALLAS))}
        faltantes = set(TALLAS) - set(tallas)
        if faltantes:
            sys.exit(f"Faltan las tallas {sorted(faltantes)}: correr antes scripts.seed_catalogo")

        padre_id = _obtener_o_crear_categoria(db, manifiesto, CATEGORIA_PADRE, None)

        for plan in planes:
            print(f"\n[{plan.codigo}] {plan.nombre}")
            categoria_id = _obtener_o_crear_categoria(db, manifiesto, plan.categoria, padre_id)
            color_id = _obtener_o_crear_color(db, manifiesto, plan.color, plan.color_hex)
            temporada_id = _obtener_o_crear_temporada(db, manifiesto, plan)

            producto = db.query(Producto).filter(Producto.codigo == plan.codigo).one_or_none()
            if producto is None:
                producto = cu_productos.crear(
                    db,
                    ProductoCrear(
                        codigo=plan.codigo,
                        nombre=plan.nombre,
                        descripcion=plan.descripcion,
                        categoria_id=categoria_id,
                        temporada_id=temporada_id,
                        genero="hombre",
                        precio_base=plan.precio,
                        admite_probador=True,
                        tallas_ids=[tallas[c] for c in TALLAS],
                        colores_ids=[color_id],
                    ),
                    creado_por=None,
                )
                manifiesto.agregar("productos", producto.id)
                for variante in cu_productos.listar_variantes(db, producto.id):
                    manifiesto.agregar("variantes", variante.id)
                print(f"  producto creado id={producto.id}")
            else:
                print(f"  producto ya existía id={producto.id}")
            if not producto.admite_probador:
                sys.exit(f"  {plan.codigo} quedó con admite_probador=false: revisar la categoría")

            if db.query(ProductoImagen).filter(ProductoImagen.producto_id == producto.id).count() == 0:
                imagen, _ = cu_productos.subir_imagen(
                    db, producto.id, plan.ruta_jpg.read_bytes(), "image/jpeg", color_id, es_principal=True
                )
                manifiesto.agregar("imagenes", imagen.id)
                manifiesto.agregar("public_ids", imagen.url)
                print(f"  foto de catálogo subida ({imagen.url})")
            else:
                print("  foto de catálogo ya existía")

            variantes = {
                v.talla_id: v
                for v in db.query(ProductoVariante).filter(
                    ProductoVariante.producto_id == producto.id, ProductoVariante.color_id == color_id
                )
            }
            variante_base = variantes[tallas[TALLAS[0]]]

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
                base, _ = cu_assets.subir(db, variante_base.id, "overlay_2d", png, "image/png", None)
                manifiesto.agregar("activos", base.id)
                manifiesto.agregar("public_ids", base.url)
                base, _ = cu_assets.validar(db, base.id)
                print(f"  overlay subido y validado ({base.url})")
            else:
                print(f"  overlay ya existía en talla {TALLAS[0]}")

            for codigo_talla in TALLAS[1:]:
                variante = variantes[tallas[codigo_talla]]
                if overlay_de(variante.id) is None:
                    copia = cu_assets.clonar_a_variante(db, base.id, variante.id)
                    manifiesto.agregar("activos", copia.id)
                    print(f"  overlay asignado a talla {codigo_talla}")
    finally:
        db.close()

    if manifiesto.ruta.exists():
        print(f"\nListo. Para deshacer: python -m scripts.seed_prendas_probador --revertir \"{manifiesto.ruta}\" --ejecutar")
    else:
        print("\nListo. No se creó nada nuevo (todo ya existía).")


def revertir(ruta_manifiesto: Path, ejecutar: bool) -> None:
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
    from app.core.database import SessionLocal
    from app.catalogo.models import ActivoProbador

    host = _host_de_la_base()
    if host != datos["host"]:
        sys.exit(f"La base actual ({host}) no es la del manifiesto ({datos['host']}). No se toca nada.")

    # Borrado físico a propósito: deshace un seed recién creado, sin ventas
    # ni stock asociados. Si alguna fila ya tiene uso (FK), la transacción
    # entera se revierte y Cloudinary no se toca.
    db = SessionLocal()
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
    args = parser.parse_args()

    if args.revertir:
        revertir(args.revertir, args.ejecutar)
        return
    if not args.origen:
        parser.error("--origen es obligatorio")

    planes = planificar(args.origen, set(args.solo) if args.solo else None)
    if not planes:
        sys.exit("Ninguna prenda coincide con --solo")

    if args.ejecutar:
        cargar(planes)
        return

    vista: list[tuple[PrendaPlan, Image.Image]] = []
    for plan in planes:
        original = plan.ruta_png.read_bytes()
        png, imagen = preparar_png(original)
        vista.append((plan, imagen))
        comprimido = f" -> {len(png) / 1048576:.2f}MB {imagen.size}" if png is not original else ""
        print(
            f"{plan.codigo:9} {plan.categoria:9} {plan.precio:>7} Bs  {plan.color:12} "
            f"{plan.temporada} {plan.anio}  {plan.nombre}\n"
            f"          png {len(original) / 1048576:.2f}MB{comprimido}"
        )
    destino = DIR_BACKUPS / "vista_previa_overlays.png"
    generar_vista_previa(vista, destino)
    print(f"\n{len(planes)} prendas, tallas {TALLAS}. Vista previa: {destino}")
    print("(dry-run: no se escribió nada en la base ni en Cloudinary; agregar --ejecutar)")


if __name__ == "__main__":
    main()

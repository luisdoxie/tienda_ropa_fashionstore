"""Lo que comparten las pruebas de `scripts.poblar_demo` en SQLite y en PostgreSQL: una carpeta de
fotos de mentira que trae los metadatos reales de las 24 prendas, y un Cloudinary simulado."""

import io
import itertools
import json
from pathlib import Path

from PIL import Image

from app.core import storage

# (id, género, tipo, color, temporada, año, uso, nombre): los metadatos reales de catalogo.json
PRENDAS = [
    (10003, "Women", "Tshirts", "White", "Fall", 2011, "Sports", "Nike Women As Nike Eleme White T-Shirt"),
    (10005, "Men", "Tshirts", "Blue", "Fall", 2011, "Sports", "Nike Men As Ss Trainin Blue T-Shirts"),
    (10006, "Men", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Men AS T90 Black Tshirts"),
    (10007, "Women", "Tshirts", "White", "Fall", 2011, "Sports", "Nike Women As Trophy Swo White T-Shirts"),
    (10008, "Men", "Tshirts", "Navy Blue", "Fall", 2011, "Sports", "Nike Men Town Navy Blue T-Shirts"),
    (10009, "Men", "Tshirts", "Red", "Fall", 2011, "Sports", "Nike Men Town Round Red Neck T-Shirts"),
    (10010, "Men", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Men As Showdown F Black T-Shirts"),
    (10017, "Women", "Jackets", "Blue", "Fall", 2011, "Sports", "Nike Women As The Windru Blue Jackets"),
    (10019, "Women", "Tshirts", "White", "Fall", 2011, "Sports", "Nike Women As Miler Ss White T-Shirts"),
    (10022, "Men", "Tshirts", "Blue", "Fall", 2011, "Sports", "Nike Men Blue Polo Tshirts"),
    (10026, "Women", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Women As Challenger Black T-Shirts"),
    (10027, "Women", "Tshirts", "White", "Fall", 2011, "Sports", "Nike Women's White Tshirt"),
    (10028, "Women", "Tshirts", "White", "Fall", 2011, "Sports", "Nike Women As Club Jerse White T-Shirts"),
    (10030, "Women", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Women As See The Win Black T-Shirts"),
    (10032, "Men", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Men AS FCB Core T Black T-shirts"),
    (14006, "Men", "Tshirts", "Black", "Fall", 2011, "Sports", "Nike Men Solid Black Jerseys"),
    (15348, "Men", "Tshirts", "Black", "Fall", 2011, "Casual", "Nike Men Special Edition 3 Star Polo Black Tshirts"),
    (2620, "Men", "Tshirts", "Blue", "Fall", 2010, "Sports", "Nike Men's Colors Team India T-shirt"),
    (28639, "Men", "Tshirts", "White", "Summer", 2012, "Sports", "Nike Men White T-shirt"),
    (3730, "Men", "Tshirts", "Yellow", "Summer", 2011, "Sports", "CSK Mens Fangear Yellow Jersey"),
    (38606, "Men", "Tshirts", "White", "Summer", 2012, "Casual", "Nike Men Printed Boxed White T-shirt"),
    (38608, "Men", "Tshirts", "Grey", "Summer", 2012, "Casual", "Nike Men Grey T-shirt"),
    (38639, "Men", "Tshirts", "Blue", "Summer", 2012, "Casual", "Nike Men Blue Cricket Blue Polo Tshirt"),
    (5433, "Men", "Tshirts", "Red", "Summer", 2011, "Casual", "Nike Men's Speed Fury Red T-shirt"),
]  # fmt: skip


def crear_carpeta(ruta: Path) -> Path:
    """catalogo.json con las 24 prendas, un JPG y un PNG con transparencia por cada una."""
    (ruta / "overlays").mkdir(exist_ok=True)
    jpg = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(jpg, "JPEG")
    png = io.BytesIO()
    imagen = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
    imagen.paste((20, 20, 20, 255), (100, 100, 500, 700))
    imagen.save(png, "PNG")
    items = []
    for id_, genero, tipo, color, temporada, anio, uso, nombre in PRENDAS:
        (ruta / f"{id_}.jpg").write_bytes(jpg.getvalue())
        (ruta / "overlays" / f"{id_}.png").write_bytes(png.getvalue())
        items.append({
            "id": id_, "archivo": f"{id_}.jpg", "overlay": f"overlays/{id_}.png", "gender": genero,
            "masterCategory": "Apparel", "subCategory": "Topwear", "articleType": tipo, "baseColour": color,
            "season": temporada, "year": anio, "usage": uso, "productDisplayName": nombre,
        })  # fmt: skip
    (ruta / "catalogo.json").write_text(json.dumps(items), encoding="utf-8")
    return ruta


def simular_cloudinary(monkeypatch) -> list[str]:
    """Nada sale a la red: cada subida devuelve un public_id y se anota en la lista devuelta."""
    contador = itertools.count(1)
    subidos: list[str] = []

    def subir(contenido, carpeta_destino, *, formato_forzado=None):
        public_id = f"{carpeta_destino}/img{next(contador)}"
        subidos.append(public_id)
        return public_id

    monkeypatch.setattr(storage, "subir_imagen", subir)
    monkeypatch.setattr(storage, "url_catalogo", lambda public_id, ancho=None, alto=None: f"https://img/{public_id}")
    monkeypatch.setattr(storage, "url_probador", lambda public_id: f"https://img/{public_id}.png")
    return subidos

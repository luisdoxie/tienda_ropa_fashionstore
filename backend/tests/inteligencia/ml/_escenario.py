"""Escenario compartido de las pruebas del ML con base de datos (CU-24 y el script de carga): organizaciones pequeñas
pobladas con `scripts.poblar_demo` (sin fotos) y su historial sintético cargado con la MISMA función que usa
`scripts.seed_ml_sintetico`, pero reducido (40 semanas, 80 clientes) para que sea rápido."""

import dataclasses
import datetime as dt

from sqlalchemy import text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.tenant import en_empresa
from app.plataforma import politicas
from scripts.demo_organizaciones import por_codigo
from scripts.poblar_demo import seed
from scripts.seed_ml_sintetico import cargar_historial, generar

PASSWORD = "claveSegura123"
FIN = dt.date(2026, 10, 25)  # domingo: la última semana completa es la que termina ese día
SEMANAS = 40
CLIENTES = 80


def organizaciones():
    """FashionStore y Chaski Sport (Profesional, con ML) y Pampa Casual (Básico, sin ML), con pocas prendas pero de
    varias categorías (Poleras, Polos, Camisetas deportivas y Chamarras)."""
    return (
        dataclasses.replace(por_codigo("fashionstore"), prendas=(10005, 10003, 10017, 14006, 10022)),
        dataclasses.replace(por_codigo("chaski-sport"), prendas=(10005, 10017, 14006, 10022)),
        dataclasses.replace(por_codigo("pampa-casual"), prendas=(38606, 14006, 10022)),
    )


def poblar(db, carpeta) -> None:
    """Las tres organizaciones con su catálogo, sus tiendas, sus cajeros y su stock (sin fotos)."""
    seed(db, ejecutar=True, password=PASSWORD, origen=carpeta, organizaciones=organizaciones(), con_fotos=False)


def crear_vista_de_ventas(db) -> None:
    """La vista que lee la serie diaria. SQLite (las pruebas) no la tiene por defecto; PostgreSQL la trae de la migración."""
    db.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db.commit()


def id_de(db, codigo: str) -> int:
    empresa = politicas.obtener_empresa_por_codigo(db, codigo)
    assert empresa is not None, codigo
    return empresa.id


def cargar_historia(db, codigo: str, *, semanas: int = SEMANAS, clientes: int = CLIENTES, perfil: str = "A"):
    """Genera y carga el historial de la empresa. Devuelve (empresa_id, catalogo, historial, resumen)."""
    empresa_id = id_de(db, codigo)
    with en_empresa(db, empresa_id):
        catalogo, historial = generar(db, codigo, semanas=semanas, clientes=clientes, perfil=perfil, semilla=42, fin=FIN)
        resumen = cargar_historial(db, historial, catalogo, codigo)
    return empresa_id, catalogo, historial, resumen

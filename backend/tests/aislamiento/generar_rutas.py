"""Generador del esqueleto de `rutas_esperadas.py` (E05, 4.1). Herramienta de
desarrollo, NO es una prueba: no empieza por `test_`.

    python -m tests.aislamiento.generar_rutas            # imprime el esqueleto
    python -m tests.aislamiento.generar_rutas --escribir  # crea rutas_esperadas.py

Deduce la clase de cada ruta con reglas simples. Lo que no puede deducir con
seguridad lo marca con la nota "REVISAR" y la suite falla (`test_sin_marcas_revisar`)
mientras exista la marca. Nunca pisa un `rutas_esperadas.py` existente: el archivo
se revisa a mano y esa revisión es el valor del registro.
"""

import sys
from pathlib import Path

from .introspeccion import METODOS_IGNORADOS, funcionalidades_de, permisos_de, rutas_api

PREFIJO = "/api/v1"
DESTINO = Path(__file__).with_name("rutas_esperadas.py")

# Rutas que operan sobre el propio usuario o su carrito/favoritos.
PROPIAS = {
    "/auth/yo",
    "/carrito",
    "/carrito/aplicar-promocion",
    "/clientes/perfil",
    "/empleados/yo",
    "/favoritos",
    "/notificaciones",
    "/reservas/mis-reservas",
    "/ventas/mis-compras",
}
# carrito/{variante_id} y favoritos/{variante_id}: id de variante dentro de lo propio.
PROPIAS_CON_ID = ("/carrito/", "/favoritos/")
# Parámetros de ruta que NO son el id de un recurso de empresa.
PARAMETROS_NO_RECURSO = {"codigo", "pasarela", "id_transaccion"}


def _parametros(path: str) -> list[str]:
    return [t[1:-1] for t in path.split("/") if t.startswith("{") and t.endswith("}")]


def clasificar(metodo: str, path: str) -> tuple[str, bool]:
    """(clase, dudosa). `dudosa` pide revisión humana."""
    corta = path.removeprefix(PREFIJO)
    if corta == "/health" or (corta.startswith("/auth/") and corta != "/auth/yo"):
        return "AUTH", False
    if corta.startswith("/public"):
        return "PUBLICA", False
    if corta.startswith("/plataforma"):
        return "PLATAFORMA", False
    if corta.startswith("/mi-empresa"):
        return "MI_EMPRESA", False
    if corta.startswith("/pagos/webhook") or corta.startswith("/pagos/qr"):
        return "PASARELA", False
    if corta.startswith("/tareas"):
        return "SERVICIO", False
    if corta in PROPIAS or corta.startswith(PROPIAS_CON_ID):
        return "PROPIA", False
    parametros = [p for p in _parametros(corta) if p not in PARAMETROS_NO_RECURSO]
    if parametros:
        return "POR_ID", False
    if metodo == "GET":
        return "LISTADO", False
    return "CREA_O_ACCION", False


def construir() -> list[tuple[str, str, str, list[str], list[str], str]]:
    filas = []
    for ruta in rutas_api():
        permisos, funciones = permisos_de(ruta), funcionalidades_de(ruta)
        for metodo in sorted(ruta.methods - METODOS_IGNORADOS):
            clase, dudosa = clasificar(metodo, ruta.path)
            nota = ""
            sin_permiso = not permisos
            if clase in {"CREA_O_ACCION", "PROPIA"} and sin_permiso:
                dudosa = True  # ¿alta con ids en el cuerpo o acción propia? lo decide una persona
            if dudosa:
                nota = "REVISAR"
            elif sin_permiso and clase in {"POR_ID", "LISTADO", "CREA_O_ACCION", "PROPIA"}:
                nota = "solo autenticado"
            filas.append((ruta.path, metodo, clase, permisos, funciones, nota))
    return sorted(filas, key=lambda f: (f[0], f[1]))


def _literal(valor: list[str]) -> str:
    return repr(valor[0]) if len(valor) == 1 else ("None" if not valor else repr(tuple(valor)))


def renderizar() -> str:
    lineas = [
        '"""Registro de TODAS las rutas del backend (E05, 4.1). Una entrada por (método, ruta).',
        "",
        "Lo lee la suite de aislamiento: si agregas una ruta a la app y no aparece aquí,",
        "`test_registro_de_rutas.py` falla y dice cómo clasificarla.",
        "",
        "  clase         POR_ID | LISTADO | CREA_O_ACCION | PROPIA | PUBLICA | PLATAFORMA |",
        "                MI_EMPRESA | PASARELA | SERVICIO | AUTH",
        "  permiso       código que exige la ruta (o None; en clases de negocio sin permiso",
        '                la nota debe empezar por "solo autenticado")',
        "  funcionalidad código del plan que exige la ruta (o None)",
        "  cobertura     MATRIZ (la recorre una prueba parametrizada de su clase) o EXENTA",
        "                (la nota es obligatoria: razón por escrito, mínimo 20 caracteres)",
        '"""',
        "",
        "from typing import NamedTuple",
        "",
        'POR_ID = "POR_ID"',
        'LISTADO = "LISTADO"',
        'CREA_O_ACCION = "CREA_O_ACCION"',
        'PROPIA = "PROPIA"',
        'PUBLICA = "PUBLICA"',
        'PLATAFORMA = "PLATAFORMA"',
        'MI_EMPRESA = "MI_EMPRESA"',
        'PASARELA = "PASARELA"',
        'SERVICIO = "SERVICIO"',
        'AUTH = "AUTH"',
        'MATRIZ = "MATRIZ"',
        'EXENTA = "EXENTA"',
        "",
        "",
        "class Ruta(NamedTuple):",
        "    clase: str",
        "    permiso: str | tuple | None",
        "    funcionalidad: str | None",
        "    cobertura: str = MATRIZ",
        '    nota: str = ""',
        "",
        "",
        "RUTAS: dict[tuple[str, str], Ruta] = {",
    ]
    for path, metodo, clase, permisos, funciones, nota in construir():
        partes = [clase, _literal(permisos), _literal(funciones), "MATRIZ"]
        if nota:
            partes.append(repr(nota))
        lineas.append(f"    ({metodo!r}, {path!r}): Ruta({', '.join(partes)}),")
    lineas.append("}")
    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    texto = renderizar()
    if "--escribir" in sys.argv:
        if DESTINO.exists():
            print(f"{DESTINO.name} ya existe: no se pisa (se revisa a mano).", file=sys.stderr)
            return 1
        DESTINO.write_text(texto, encoding="utf-8")
        print(f"escrito {DESTINO} ({texto.count(chr(10))} líneas)")
        return 0
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

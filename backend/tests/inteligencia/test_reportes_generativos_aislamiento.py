"""CU-23 (E09): aislamiento entre empresas. Dos empresas Profesional con los MISMOS nombres de sucursales,
categorías y productos pero cifras distintas (A con m=1, B con m=3): cada token ve solo lo suyo, y la
bitácora de cada una guarda solo sus consultas, sin el texto que escribió el usuario."""

import pytest

from tests.inteligencia.ayudas_reportes_generativos import API, ejecutar, filas_de

PERIODO = {"tipo": "este_mes"}

# (reporte, filtros extra, función que saca de las filas un valor comparable de A) -> B es el triple
TOTALES = {
    "ventas_por_sucursal": {},
    "productos_mas_vendidos": {},
    "ventas_por_periodo": {"agrupacion": "mes"},
    "comparacion_sucursales": {"agrupacion": "mes"},
    "ingresos_por_categoria": {},
}


def _total(filas: list[dict]) -> float:
    return round(sum(f.get("total_ventas", f.get("total_vendido", 0.0)) for f in filas), 2)


@pytest.mark.parametrize("reporte", sorted(TOTALES))
def test_cada_empresa_ve_solo_sus_cifras(client_por_peticion, mundo_ia, reporte):
    cuerpo = {"tipo_reporte": reporte, "periodo": PERIODO, **TOTALES[reporte]}

    en_a = filas_de(ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud=cuerpo))
    en_b = filas_de(ejecutar(client_por_peticion, mundo_ia.b.headers, solicitud=cuerpo))

    assert _total(en_a) == 740.0  # A: 4 ventas efectivas
    assert _total(en_b) == 2220.0  # B: las mismas ventas, triplicadas (m=3): nada de A se mezcla


def test_existencias_de_cada_empresa(client_por_peticion, mundo_ia):
    en_a = filas_de(ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud={"tipo_reporte": "productos_menor_existencia"}))
    en_b = filas_de(ejecutar(client_por_peticion, mundo_ia.b.headers, solicitud={"tipo_reporte": "productos_menor_existencia"}))

    assert {f["producto"]: f["disponible"] for f in en_a} == {"Camisa Lino": 8, "Polera Básica": 11, "Camisa Oxford": 14}
    assert {f["producto"]: f["disponible"] for f in en_b} == {"Camisa Lino": 24, "Polera Básica": 33, "Camisa Oxford": 42}


def test_los_nombres_resueltos_son_ids_de_la_empresa_del_token(client_por_peticion, mundo_ia):
    cuerpo = {"tipo_reporte": "ventas_por_sucursal", "periodo": PERIODO, "sucursales": ["Centro"]}

    en_a = ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud=cuerpo).json()
    en_b = ejecutar(client_por_peticion, mundo_ia.b.headers, solicitud=cuerpo).json()

    assert en_a["solicitud"]["sucursales"] == [{"id": mundo_ia.datos_a["sucursales"]["centro"], "nombre": "Centro"}]
    assert en_b["solicitud"]["sucursales"] == [{"id": mundo_ia.datos_b["sucursales"]["centro"], "nombre": "Centro"}]
    assert mundo_ia.datos_a["sucursales"]["centro"] != mundo_ia.datos_b["sucursales"]["centro"]
    assert en_a["reporte"]["filas"][0]["total_ventas"] == 350.0 and en_b["reporte"]["filas"][0]["total_ventas"] == 1050.0


def test_una_sucursal_de_la_otra_empresa_se_ve_como_inexistente(client_por_peticion, db_session, mundo_ia):
    """El nombre existe SOLO en la empresa B: para A es como si no existiera (ambigua con SUS sucursales)."""
    from app.core.tenant import empresa_de, fijar_empresa
    from app.plataforma.models import Ciudad, Sucursal

    original = empresa_de(db_session)
    fijar_empresa(db_session, mundo_ia.b.id)
    ciudad = Ciudad(nombre="Ciudad B", departamento="Santa Cruz")
    db_session.add(ciudad)
    db_session.flush()
    db_session.add(Sucursal(ciudad_id=ciudad.id, codigo="SOL", nombre="Solo De B", direccion="Calle B"))
    db_session.commit()
    fijar_empresa(db_session, original)

    solicitud = {"tipo_reporte": "ventas_por_sucursal", "periodo": PERIODO, "sucursales": ["Solo De B"]}
    desde_a = ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud=solicitud).json()
    desde_b = ejecutar(client_por_peticion, mundo_ia.b.headers, solicitud=solicitud).json()

    assert desde_a["estado"] == "ambigua" and "Solo De B" not in desde_a["sugerencias"]
    assert desde_b["estado"] == "ok"


def test_la_bitacora_guarda_la_consulta_sin_el_texto_y_solo_en_su_empresa(client_por_peticion, mundo_ia):
    texto = "ventas por sucursal este mes marcador-privado-9x"

    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto=texto).json()
    assert cuerpo["estado"] == "ok"
    de_a = client_por_peticion.get(f"{API.removesuffix('/reportes-ia')}/bitacora?entidad=reporte_ia", headers=mundo_ia.a.headers).json()
    de_b = client_por_peticion.get(f"{API.removesuffix('/reportes-ia')}/bitacora?entidad=reporte_ia", headers=mundo_ia.b.headers).json()

    assert de_a["total"] == 1 and de_b["total"] == 0  # la consulta de A no aparece en la bitácora de B
    fila = de_a["items"][0]
    assert fila["accion"] == "ejecutar" and fila["entidad"] == "reporte_ia"
    datos = fila["datos"]
    assert datos["tipo_reporte"] == "ventas_por_sucursal" and datos["estado"] == "ok" and datos["interprete"] == "reglas"
    assert datos["origen"] == "texto" and datos["filas"] == 2 and datos["truncado"] is False
    assert datos["periodo"] == {"desde": "2026-09-01", "hasta": "2026-09-20"}
    assert "duracion_ms" in datos
    assert "marcador-privado" not in str(fila)  # ni el texto ni los nombres que escribió


def test_una_solicitud_rechazada_deja_una_fila_rechazar(client_por_peticion, mundo_ia):
    ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud={"tipo_reporte": "usuarios"})

    de_a = client_por_peticion.get(f"{API.removesuffix('/reportes-ia')}/bitacora?entidad=reporte_ia", headers=mundo_ia.a.headers).json()

    assert [(f["accion"], f["datos"]["estado"]) for f in de_a["items"]] == [("rechazar", "no_soportada")]


def test_interpretar_no_deja_bitacora(client_por_peticion, mundo_ia):
    client_por_peticion.post(f"{API}/interpretar", json={"texto": "ventas por sucursal este mes"}, headers=mundo_ia.a.headers)

    de_a = client_por_peticion.get(f"{API.removesuffix('/reportes-ia')}/bitacora?entidad=reporte_ia", headers=mundo_ia.a.headers).json()

    assert de_a["total"] == 0

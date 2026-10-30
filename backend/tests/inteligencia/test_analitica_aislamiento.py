"""Analítica ML por HTTP (CU-24, E12): AISLAMIENTO entre empresas. La empresa sale SIEMPRE del token; lo que una
empresa entrena, consulta o descarga jamás mezcla datos, modelos ni nombres de la otra. SQLite en memoria; el mismo
escenario con PostgreSQL real está en tests/postgres/test_analitica_pg.py.

Escenario: A = FashionStore (5 prendas) y B = Chaski Sport (4 prendas, otro perfil de compra), ambas Profesional, con su
historial sintético. La fecha de la aplicación se fija en `HOY` (el día siguiente al fin del historial) para que el
entrenamiento por HTTP use los mismos datos que `entrenar()` y la prueba no dependa del reloj."""

import datetime as dt
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.comercial import politicas as comercial_politicas
from app.core.deps import ParametrosPeriodo
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso import cu24_analizar_con_machine_learning as cu24
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    CACHE_MODELOS,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
)
from app.inteligencia.ml import anomalias as ml_anomalias
from app.inteligencia.ml import demanda as ml_demanda
from app.inteligencia.ml import persistencia
from app.inteligencia.ml.limites import ML_MAX_CLIENTES, ML_MAX_SEMANAS
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma.models import Sucursal
from tests.inteligencia._analitica_comun import (
    FIN,
    HOY,
    cabeceras_de,
    cargar_historia,
    entrenar,
    id_de,
    poblar_mundo,
    usuario_de,
)
from tests.inteligencia.test_analitica_anomalias_reposicion import (
    _artefacto,
    _como_dicts,
    _disponible_a_mano,
    _filas_de_comercial,
    _fijar_disponible,
)

REPO = ModeloMLRepository()
A, B = "fashionstore", "chaski-sport"
RUTA = "/api/v1/analitica"


@pytest.fixture()
def mundo(db_session, tmp_path, monkeypatch, client_por_peticion):
    """A y B pobladas, con historial y SIN entrenar. Trae las cabeceras de cada administrador y el cliente HTTP."""
    monkeypatch.setattr(cu24, "hoy_utc", lambda: HOY)  # `entrenar` por HTTP usa hasta = HOY - 1 = FIN
    poblar_mundo(db_session, tmp_path)
    cargar_historia(db_session, A)
    cargar_historia(db_session, B, perfil="B")
    ids = {A: id_de(db_session, A), B: id_de(db_session, B)}
    for empresa_id in ids.values():
        CACHE_MODELOS.invalidar(empresa_id)  # la caché es del proceso: ningún modelo de una prueba anterior
    yield SimpleNamespace(
        db=db_session,
        http=client_por_peticion,
        id=ids,
        h={A: cabeceras_de(db_session, A), B: cabeceras_de(db_session, B)},
    )
    for empresa_id in ids.values():
        CACHE_MODELOS.invalidar(empresa_id)


@pytest.fixture()
def entrenado(mundo):
    """Lo mismo, con las dos empresas entrenadas (versión 1 de cada tipo)."""
    entrenar(mundo.db, A)
    entrenar(mundo.db, B)
    return mundo


def _get(mundo, empresa: str, ruta: str, **params):
    return mundo.http.get(f"{RUTA}{ruta}", headers=mundo.h[empresa], params=params or None)


def _ok(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _lunes(dia: dt.date) -> dt.date:
    return dia - dt.timedelta(days=dia.weekday())


def _serie(mundo, empresa: str, hasta: dt.date = FIN) -> list[dict]:
    """La serie diaria por categoría de ESA empresa, calculada directamente con `comercial` (sin pasar por la analítica)."""
    with en_empresa(mundo.db, mundo.id[empresa]):
        periodo = ParametrosPeriodo(desde=hasta - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=hasta)
        return comercial_politicas.reporte_ventas_serie_diaria(mundo.db, periodo, desglose=("categoria",))


def _rfm(mundo, empresa: str) -> list[dict]:
    with en_empresa(mundo.db, mundo.id[empresa]):
        return comercial_politicas.reporte_rfm_clientes(mundo.db, FIN, dias=365, tope=ML_MAX_CLIENTES)


def _unidades_por_categoria_y_semana(serie: list[dict]) -> dict[int, dict[dt.date, float]]:
    resultado: dict[int, dict[dt.date, float]] = {}
    for fila in serie:
        semanas = resultado.setdefault(fila["categoria_id"], {})
        semanas[_lunes(fila["dia"])] = semanas.get(_lunes(fila["dia"]), 0.0) + float(fila["unidades"])
    return resultado


def _historico_esperado(serie: list[dict], respuesta_categoria: dict) -> list[float]:
    """Las 12 semanas reales de una categoría según LA SERIE de la empresa, en las mismas semanas que devolvió la API."""
    por_semana = _unidades_por_categoria_y_semana(serie).get(respuesta_categoria["categoria_id"], {})
    return [por_semana.get(dt.date.fromisoformat(p["etiqueta"]), 0.0) for p in respuesta_categoria["historico"]]


def _texto(cuerpo) -> str:
    return json.dumps(cuerpo, ensure_ascii=False)


def _cadenas(valor):
    """Todas las cadenas (valores y claves) de un JSON."""
    if isinstance(valor, dict):
        for clave, v in valor.items():
            yield clave
            yield from _cadenas(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _cadenas(v)
    elif isinstance(valor, str):
        yield valor


# ---- La demanda y los segmentos de cada empresa salen solo de sus datos ----------------------------------------------------


@pytest.mark.parametrize("empresa, otra", [(A, B), (B, A)])
def test_la_demanda_http_usa_solo_las_categorias_y_las_ventas_de_la_empresa_del_token(entrenado, empresa, otra):
    cuerpo = _ok(_get(entrenado, empresa, "/demanda", semanas=4))
    serie, serie_otra = _serie(entrenado, empresa), _serie(entrenado, otra)
    propias = {f["categoria_id"]: f["categoria"] for f in serie}
    ajenas = {f["categoria_id"]: f["categoria"] for f in serie_otra}
    assert propias and ajenas and not set(propias) & set(ajenas)  # cada empresa tiene SUS filas de categoría

    # Las categorías de la respuesta son las del catálogo con ventas de la empresa (id y nombre), ninguna de la otra.
    de_la_respuesta = {c["categoria_id"]: c["categoria"] for c in cuerpo["categorias"]}
    assert de_la_respuesta == propias
    assert not set(de_la_respuesta) & set(ajenas)
    assert cuerpo["total_empresa"]["categoria_id"] is None

    # El histórico de cada categoría es lo vendido por la empresa, semana a semana; el total es su suma.
    assert any(sum(c["historico"][i]["valor"] for i in range(12)) > 0 for c in cuerpo["categorias"])  # no es trivial
    for categoria in cuerpo["categorias"]:
        assert [p["valor"] for p in categoria["historico"]] == _historico_esperado(serie, categoria), categoria["categoria"]
    por_semana = [sum(c["historico"][i]["valor"] for c in cuerpo["categorias"]) for i in range(12)]
    assert [p["valor"] for p in cuerpo["total_empresa"]["historico"]] == por_semana
    # Y NO coincide con lo que vendió la otra empresa en esas mismas semanas.
    semanas = [dt.date.fromisoformat(p["etiqueta"]) for p in cuerpo["total_empresa"]["historico"]]
    de_la_otra = [
        sum(unidades.get(s, 0.0) for unidades in _unidades_por_categoria_y_semana(serie_otra).values()) for s in semanas
    ]
    assert [p["valor"] for p in cuerpo["total_empresa"]["historico"]] != de_la_otra

    # El modelo que respondió es el de la empresa: sus filas de entrenamiento y su rango de datos son los suyos.
    with en_empresa(entrenado.db, entrenado.id[empresa]):
        fila = REPO.obtener_activo(entrenado.db, TIPO_DEMANDA)
        assert fila.empresa_id == entrenado.id[empresa]
        assert cuerpo["modelo"]["version"] == fila.version == 1
        assert cuerpo["modelo"]["filas_entrenamiento"] == fila.filas_entrenamiento


def test_la_demanda_de_una_empresa_difiere_de_la_de_la_otra(entrenado):
    de_a, de_b = _ok(_get(entrenado, A, "/demanda")), _ok(_get(entrenado, B, "/demanda"))
    assert de_a["modelo"]["version"] == de_b["modelo"]["version"] == 1  # misma versión, modelos distintos
    assert {c["categoria_id"] for c in de_a["categorias"]}.isdisjoint({c["categoria_id"] for c in de_b["categorias"]})
    for campo in ("historico", "prediccion"):
        assert [p["valor"] for p in de_a["total_empresa"][campo]] != [p["valor"] for p in de_b["total_empresa"][campo]], campo
    assert de_a["total_empresa"]["total_predicho"] != de_b["total_empresa"]["total_predicho"]
    assert de_a["metricas"] != de_b["metricas"]
    # Una consulta de B en medio no altera lo que ve A (la caché de modelos no mezcla empresas).
    assert _ok(_get(entrenado, A, "/demanda")) == de_a


@pytest.mark.parametrize("empresa, otra", [(A, B), (B, A)])
def test_los_segmentos_http_salen_solo_de_los_clientes_de_la_empresa_del_token(entrenado, empresa, otra):
    cuerpo = _ok(_get(entrenado, empresa, "/segmentos"))
    propios, ajenos = _rfm(entrenado, empresa), _rfm(entrenado, otra)
    assert len(propios) >= 30 and ajenos

    # Los clientes segmentados y el dinero son exactamente los de la empresa (la ventana RFM del entrenamiento).
    assert cuerpo["clientes_segmentados"] == sum(s["clientes"] for s in cuerpo["segmentos"]) == len(propios)
    esperado_monto = sum(float(f["monto_total"]) for f in propios)
    assert sum(s["monto_total"] for s in cuerpo["segmentos"]) == pytest.approx(esperado_monto, abs=0.05 * len(cuerpo["segmentos"]))
    assert sum(float(f["monto_total"]) for f in ajenos) != pytest.approx(esperado_monto, abs=1.0)  # la otra vende otra cosa

    # La dispersión son clientes de la empresa (sin id): cada punto (frecuencia, monto) existe en SU lista de compras.
    assert 0 < len(cuerpo["dispersion"]) <= 300
    existentes = {(int(f["frecuencia"]), round(float(f["monto_total"]), 2)) for f in propios}
    assert {(p["frecuencia"], round(p["monto"], 2)) for p in cuerpo["dispersion"]} <= existentes
    assert all(set(p) == {"segmento_id", "frecuencia", "monto"} for p in cuerpo["dispersion"])  # nunca un cliente_id


def test_los_segmentos_de_una_empresa_difieren_de_los_de_la_otra(entrenado):
    de_a, de_b = _ok(_get(entrenado, A, "/segmentos")), _ok(_get(entrenado, B, "/segmentos"))
    assert de_a["modelo"]["version"] == de_b["modelo"]["version"] == 1
    montos = lambda c: [(s["nombre"], s["clientes"], s["monto_total"]) for s in c["segmentos"]]  # noqa: E731
    assert montos(de_a) != montos(de_b)
    assert de_a["dispersion"] != de_b["dispersion"]
    assert _ok(_get(entrenado, A, "/segmentos")) == de_a


# ---- Sin entrenar, entrenar y los ids/parámetros que manda el cliente ------------------------------------------------------


@pytest.mark.parametrize("entrenada, consulta", [(A, B), (B, A)])
def test_una_empresa_sin_entrenar_recibe_409_aunque_la_otra_tenga_su_modelo(mundo, entrenada, consulta):
    entrenar(mundo.db, entrenada)  # SOLO una de las dos
    for ruta in ("/demanda", "/segmentos", "/anomalias", "/reposicion"):
        respuesta = _get(mundo, consulta, ruta)
        assert respuesta.status_code == 409, (ruta, respuesta.text)
        assert respuesta.json()["codigo"] == "modelo_no_entrenado"
        assert _get(mundo, entrenada, ruta).status_code == 200  # control: la que sí entrenó, responde

    estado = _ok(_get(mundo, consulta, "/estado"))
    assert [(m["entrenado"], m["estado"], m["version"]) for m in estado["modelos"]] == [(False, "sin_entrenar", None)] * 3
    panel = _ok(_get(mundo, consulta, "/panel"))
    assert all(panel[b] is None for b in ("demanda", "segmentos", "anomalias", "reposicion")) and len(panel["avisos"]) == 4
    with en_empresa(mundo.db, mundo.id[consulta]):
        assert mundo.db.scalars(select(ModeloML)).all() == []  # y consultar no entrena nada


def test_entrenar_a_por_http_no_cambia_el_estado_ni_la_version_de_b(mundo):
    entrenar(mundo.db, B)
    estado_b = _ok(_get(mundo, B, "/estado"))
    demanda_b = _ok(_get(mundo, B, "/demanda"))
    anomalias_b = _ok(_get(mundo, B, "/anomalias", dias=365))
    reposicion_b = _ok(_get(mundo, B, "/reposicion"))
    assert [m["version"] for m in estado_b["modelos"]] == [1, 1, 1]

    for esperada in (1, 2):  # entrenar A dos veces: A sube a la versión 2, B se queda como estaba
        respuesta = mundo.http.post(f"{RUTA}/entrenar", headers=mundo.h[A], json={})
        assert respuesta.status_code == 200, respuesta.text
        assert [(r["tipo"], r["estado"], r["version"]) for r in respuesta.json()["resultados"]] == [
            (TIPO_DEMANDA, "entrenado", esperada),
            (TIPO_SEGMENTOS, "entrenado", esperada),
            (TIPO_ANOMALIAS, "entrenado", esperada),
        ]

    assert [m["version"] for m in _ok(_get(mundo, A, "/estado"))["modelos"]] == [2, 2, 2]
    assert _ok(_get(mundo, B, "/estado")) == estado_b  # misma versión, misma fecha de entrenamiento, mismas métricas
    assert _ok(_get(mundo, B, "/demanda")) == demanda_b
    assert _ok(_get(mundo, B, "/anomalias", dias=365)) == anomalias_b
    assert _ok(_get(mundo, B, "/reposicion")) == reposicion_b
    with en_empresa(mundo.db, mundo.id[B]):
        assert sorted((m.tipo, m.version, m.activo) for m in mundo.db.scalars(select(ModeloML))) == [
            (TIPO_ANOMALIAS, 1, True),
            (TIPO_DEMANDA, 1, True),
            (TIPO_SEGMENTOS, 1, True),
        ]
    with en_empresa(mundo.db, mundo.id[A]):
        assert sorted((m.tipo, m.version, m.activo) for m in mundo.db.scalars(select(ModeloML))) == [
            (TIPO_ANOMALIAS, 1, False),
            (TIPO_ANOMALIAS, 2, True),
            (TIPO_DEMANDA, 1, False),
            (TIPO_DEMANDA, 2, True),
            (TIPO_SEGMENTOS, 1, False),
            (TIPO_SEGMENTOS, 2, True),
        ]


def test_un_categoria_id_de_otra_empresa_es_404_igual_que_uno_inexistente(entrenado):
    de_b = _ok(_get(entrenado, B, "/demanda"))
    id_de_b = de_b["categorias"][0]["categoria_id"]
    de_a = _ok(_get(entrenado, A, "/demanda"))
    id_de_a = de_a["categorias"][0]["categoria_id"]
    assert id_de_b not in {c["categoria_id"] for c in de_a["categorias"]}

    ajena = _get(entrenado, A, "/demanda", categoria_id=id_de_b)
    inexistente = _get(entrenado, A, "/demanda", categoria_id=9_999_999)
    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json()  # el cuerpo no delata que existe en otra empresa
    assert de_b["categorias"][0]["categoria"] not in _texto(ajena.json())

    # Controles: cada empresa sí ve su propia categoría (la prueba no pasa por una ruta mal armada).
    propia = _ok(_get(entrenado, A, "/demanda", categoria_id=id_de_a))
    assert [c["categoria_id"] for c in propia["categorias"]] == [id_de_a]
    assert [c["categoria_id"] for c in _ok(_get(entrenado, B, "/demanda", categoria_id=id_de_b))["categorias"]] == [id_de_b]
    assert _get(entrenado, B, "/demanda", categoria_id=id_de_a).status_code == 404  # y al revés


def test_un_empresa_id_en_la_query_o_en_el_cuerpo_no_cambia_nada(entrenado):
    id_b = entrenado.id[B]
    for ruta in ("/estado", "/demanda", "/segmentos", "/anomalias", "/reposicion", "/panel"):
        sin = _ok(_get(entrenado, A, ruta))
        con = _ok(_get(entrenado, A, ruta, empresa_id=id_b))
        assert con == sin, ruta
        assert _ok(_get(entrenado, B, ruta)) != sin, ruta  # control: B de verdad responde distinto

    # Entrenar con `empresa_id` en la query entrena a la empresa del token (A: versión 2) y no toca a B.
    respuesta = entrenado.http.post(f"{RUTA}/entrenar?empresa_id={id_b}", headers=entrenado.h[A], json={"tipos": [TIPO_SEGMENTOS]})
    assert respuesta.status_code == 200, respuesta.text
    assert [(r["tipo"], r["version"]) for r in respuesta.json()["resultados"]] == [(TIPO_SEGMENTOS, 2)]
    assert [m["version"] for m in _ok(_get(entrenado, A, "/estado"))["modelos"]] == [1, 2, 1]
    assert [m["version"] for m in _ok(_get(entrenado, B, "/estado"))["modelos"]] == [1, 1, 1]
    # En el cuerpo ni siquiera se admite: el esquema rechaza campos extra.
    en_cuerpo = entrenado.http.post(f"{RUTA}/entrenar", headers=entrenado.h[A], json={"empresa_id": id_b})
    assert en_cuerpo.status_code == 422
    assert [m["version"] for m in _ok(_get(entrenado, B, "/estado"))["modelos"]] == [1, 1, 1]


def test_el_panel_de_a_no_contiene_nombres_ni_sucursales_ni_correos_de_b(entrenado):
    panel_a, panel_b = _ok(_get(entrenado, A, "/panel")), _ok(_get(entrenado, B, "/panel"))
    texto_a, texto_b = _texto(panel_a), _texto(panel_b)
    assert all(panel_a[b] is not None for b in ("demanda", "segmentos", "anomalias", "reposicion"))  # completo: no es trivial

    with en_empresa(entrenado.db, entrenado.id[B]):
        sucursales_b = {s.nombre for s in entrenado.db.scalars(select(Sucursal))} | {s.codigo for s in entrenado.db.scalars(select(Sucursal))}
    with en_empresa(entrenado.db, entrenado.id[A]):
        sucursales_a = {s.nombre for s in entrenado.db.scalars(select(Sucursal))} | {s.codigo for s in entrenado.db.scalars(select(Sucursal))}
    nombres_b = {c["categoria"] for c in panel_b["demanda"]["categorias"]}
    nombres_a = {c["categoria"] for c in panel_a["demanda"]["categorias"]}
    prohibidas = (
        (sucursales_b - sucursales_a)
        | {"Chaski Sport", "chaski-sport", "chaski", usuario_de(entrenado.db, B).email}
        | (nombres_b - nombres_a)
    )
    assert sucursales_b - sucursales_a  # las sucursales de B existen y no son las de A
    for cadena in prohibidas:
        assert cadena not in texto_a, cadena
    # Y la búsqueda sí encuentra lo que debe: los nombres propios están en su panel (la comprobación puede fallar).
    assert all(nombre in texto_a for nombre in nombres_a)
    assert all(nombre in texto_b for nombre in nombres_b)
    # Desde que el panel trae las anomalías por sucursal, sus nombres SÍ aparecen: solo pueden ser los de la propia empresa
    # (el caso con anomalías de verdad está en `test_las_anomalias_de_cada_empresa_son_de_sus_sucursales`).
    assert not any(s in texto_a for s in sucursales_b - sucursales_a)
    assert not any(s in texto_b for s in sucursales_a - sucursales_b)
    for panel, propias in ((panel_a, sucursales_a), (panel_b, sucursales_b)):
        assert {a["sucursal"] for a in panel["anomalias"]["anomalias"]} <= propias


def test_el_artefacto_del_modelo_nunca_sale_en_ninguna_respuesta(entrenado):
    secretos: list[str] = []
    with en_empresa(entrenado.db, entrenado.id[A]):
        for tipo in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS):
            fila = REPO.obtener_activo(entrenado.db, tipo, con_artefacto=True)
            assert len(fila.artefacto) > 100
            secretos += [fila.artefacto_sha256, fila.artefacto[:24].hex(), fila.artefacto[:30].hex().upper(), repr(fila.artefacto[:20])]
    with en_empresa(entrenado.db, entrenado.id[B]):
        secretos.append(REPO.obtener_activo(entrenado.db, TIPO_DEMANDA, con_artefacto=True).artefacto_sha256)
        secretos.append(REPO.obtener_activo(entrenado.db, TIPO_ANOMALIAS, con_artefacto=True).artefacto_sha256)

    respuestas = {
        "estado": _get(entrenado, A, "/estado"),
        "demanda": _get(entrenado, A, "/demanda", semanas=12),
        "demanda_categoria": _get(entrenado, A, "/demanda", categoria_id=_ok(_get(entrenado, A, "/demanda"))["categorias"][0]["categoria_id"]),
        "segmentos": _get(entrenado, A, "/segmentos"),
        "anomalias": _get(entrenado, A, "/anomalias", dias=365),
        "reposicion": _get(entrenado, A, "/reposicion", semanas=12),
        "panel": _get(entrenado, A, "/panel"),
        "entrenar": entrenado.http.post(f"{RUTA}/entrenar", headers=entrenado.h[A], json={}),
    }
    base64_largo = re.compile(r"^[A-Za-z0-9+/_-]{100,}={0,2}$")
    hexadecimal_largo = re.compile(r"[0-9a-fA-F]{32,}")
    for nombre, respuesta in respuestas.items():
        assert respuesta.status_code == 200, (nombre, respuesta.text)
        cuerpo, texto = respuesta.json(), respuesta.text
        claves = {c for c in _cadenas(cuerpo) if isinstance(c, str)}
        assert not [c for c in _cadenas(cuerpo) if re.search(r"artefacto|sha256|huella|pickle|joblib", c, re.IGNORECASE)], nombre
        assert not [c for c in _cadenas(cuerpo) if base64_largo.match(c)], nombre  # ningún base64 de longitud grande
        assert not hexadecimal_largo.findall(texto), nombre  # ni la huella ni bytes en hexadecimal
        for secreto in secretos:
            assert secreto not in texto, (nombre, secreto[:12])
        assert claves  # (la respuesta tenía contenido que revisar)
    # Ni los esquemas de salida declaran un campo de artefacto (propiedades de cada esquema de la analítica).
    esquemas = entrenado.http.get("/openapi.json").json()["components"]["schemas"]
    de_la_analitica = [
        "EstadoAnalitica", "EstadoModelo", "DatosDisponibles", "EntrenarRespuesta", "ResultadoEntrenamiento", "DemandaRespuesta",
        "DemandaCategoria", "MetricasDemanda", "SegmentosRespuesta", "SegmentoCliente", "PuntoDispersion", "PanelAnalitico",
        "KpiAnalitico", "PuntoSerie", "AnomaliaVenta", "AnomaliasRespuesta", "ItemReposicion", "ReposicionRespuesta",
    ]  # fmt: skip
    assert all(nombre in esquemas for nombre in de_la_analitica)
    for nombre in de_la_analitica:
        assert not [p for p in esquemas[nombre]["properties"] if re.search(r"artefacto|sha256|huella|bytes", p, re.IGNORECASE)], nombre


# ---- La caché de modelos y las filas copiadas -----------------------------------------------------------------------------


def test_la_cache_de_modelos_no_mezcla_dos_empresas_con_la_misma_version(entrenado):
    a, b = entrenado.id[A], entrenado.id[B]
    CACHE_MODELOS.invalidar(a)
    CACHE_MODELOS.invalidar(b)
    assert CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1) is None and CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1) is None

    de_a = _ok(_get(entrenado, A, "/demanda"))  # caliente la caché: A v1
    de_b = _ok(_get(entrenado, B, "/demanda"))  # luego B v1, MISMA versión y MISMO tipo
    modelo_a, modelo_b = CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1), CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1)
    assert modelo_a is not None and modelo_b is not None and modelo_a is not modelo_b
    assert {c["id"] for c in modelo_a["categorias"]}.isdisjoint({c["id"] for c in modelo_b["categorias"]})
    prediccion_a = [(p.categoria_id, p.unidades) for p in ml_demanda.predecir_demanda(modelo_a, 4)]
    prediccion_b = [(p.categoria_id, p.unidades) for p in ml_demanda.predecir_demanda(modelo_b, 4)]
    assert prediccion_a != prediccion_b  # A v1 y B v1 predicen distinto

    # Con las dos en caché, cada una sigue respondiendo con SU modelo (y A no cambió por haber consultado B).
    assert _ok(_get(entrenado, A, "/demanda")) == de_a and _ok(_get(entrenado, B, "/demanda")) == de_b
    assert {c["categoria_id"] for c in de_a["categorias"]} == {c["id"] for c in modelo_a["categorias"]}
    assert {c["categoria_id"] for c in de_b["categorias"]} == {c["id"] for c in modelo_b["categorias"]}

    # Entrenar A invalida SOLO la caché de A.
    assert entrenado.http.post(f"{RUTA}/entrenar", headers=entrenado.h[A], json={"tipos": [TIPO_DEMANDA]}).status_code == 200
    assert CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1) is None and CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1) is modelo_b


def _copiar_modelo(mundo, origen: str, destino: str, tipo: str) -> None:
    """Copia la fila de `origen` (con su artefacto y su huella) como versión vigente de `destino`: lo que haría quien
    tuviera escritura directa en la base."""
    with en_empresa(mundo.db, mundo.id[origen]):
        fila = REPO.obtener_activo(mundo.db, tipo, con_artefacto=True)
        datos = {
            c: getattr(fila, c)
            for c in (
                "tipo", "version", "metricas", "parametros", "artefacto", "artefacto_sha256", "artefacto_bytes",
                "filas_entrenamiento", "datos_desde", "datos_hasta",
            )
        }  # fmt: skip
    with en_empresa(mundo.db, mundo.id[destino]):
        mundo.db.add(ModeloML(activo=True, **datos))
        mundo.db.commit()
    CACHE_MODELOS.invalidar(mundo.id[destino])


def test_un_modelo_de_b_copiado_como_fila_de_a_no_sirve_para_a(mundo):
    """Endurecimiento: el artefacto lleva su empresa y `_cargar` la comprueba; una fila copiada se rechaza con 409."""
    entrenar(mundo.db, B, [TIPO_DEMANDA])
    _copiar_modelo(mundo, B, A, TIPO_DEMANDA)  # A no entrenó nada: solo tiene la fila copiada de B
    respuesta = _get(mundo, A, "/demanda")
    assert respuesta.status_code == 409 and respuesta.json()["detail"] == "modelo_obsoleto"
    assert "categorias" not in respuesta.json()


def test_entrenar_a_con_b_ya_entrenada_deja_a_su_propio_modelo_con_sus_datos(mundo):
    entrenar(mundo.db, B, [TIPO_DEMANDA])
    propia_de_b = _ok(_get(mundo, B, "/demanda"))
    # El administrador de A solo crea modelos propios: su versión 1 se entrena con SUS datos, no con los de B.
    respuesta = mundo.http.post(f"{RUTA}/entrenar", headers=mundo.h[A], json={"tipos": [TIPO_DEMANDA]})
    assert respuesta.status_code == 200, respuesta.text
    de_a = _ok(_get(mundo, A, "/demanda"))
    categorias_a, categorias_b = {f["categoria_id"] for f in _serie(mundo, A)}, {f["categoria_id"] for f in _serie(mundo, B)}
    assert {c["categoria_id"] for c in de_a["categorias"]} == categorias_a
    assert {c["categoria_id"] for c in propia_de_b["categorias"]} == categorias_b
    assert de_a["modelo"]["version"] == propia_de_b["modelo"]["version"] == 1
    with en_empresa(mundo.db, mundo.id[A]):
        fila_a = REPO.obtener_activo(mundo.db, TIPO_DEMANDA, con_artefacto=True)
    with en_empresa(mundo.db, mundo.id[B]):
        fila_b = REPO.obtener_activo(mundo.db, TIPO_DEMANDA, con_artefacto=True)
    assert fila_a.artefacto_sha256 != fila_b.artefacto_sha256 and fila_a.id != fila_b.id
    assert persistencia.huella(fila_a.artefacto) == fila_a.artefacto_sha256


# ---- /estado muestra los datos de la empresa ------------------------------------------------------------------------------


@pytest.mark.parametrize("empresa, otra", [(A, B), (B, A)])
def test_el_estado_muestra_las_semanas_categorias_y_clientes_de_la_empresa_del_token(entrenado, empresa, otra):
    datos = _ok(_get(entrenado, empresa, "/estado"))["datos"]
    serie, rfm = _serie(entrenado, empresa), _rfm(entrenado, empresa)
    esperado = {
        "semanas_con_ventas": len({_lunes(f["dia"]) for f in serie}),
        "categorias_con_ventas": len({f["categoria_id"] for f in serie}),
        "clientes_con_compras": len(rfm),
    }
    assert datos == esperado
    assert min(esperado.values()) > 0

    ajeno = {
        "semanas_con_ventas": len({_lunes(f["dia"]) for f in _serie(entrenado, otra)}),
        "categorias_con_ventas": len({f["categoria_id"] for f in _serie(entrenado, otra)}),
        "clientes_con_compras": len(_rfm(entrenado, otra)),
    }
    assert ajeno != esperado  # la otra empresa tiene cifras distintas: la prueba distingue de verdad
    assert datos != ajeno

    # Y los modelos que lista son los suyos (rango de datos y filas de entrenamiento de su fila).
    modelos = {m["tipo"]: m for m in _ok(_get(entrenado, empresa, "/estado"))["modelos"]}
    with en_empresa(entrenado.db, entrenado.id[empresa]):
        for tipo, modelo in modelos.items():
            fila = REPO.obtener_activo(entrenado.db, tipo)
            assert (modelo["version"], modelo["filas_entrenamiento"], modelo["datos_hasta"]) == (
                fila.version, fila.filas_entrenamiento, fila.datos_hasta.isoformat(),
            )  # fmt: skip


# ---- Anomalías y reposición (E12b): cada empresa con su modelo y su stock ---------------------------------------------------


def _sucursales(mundo, empresa: str) -> dict[int, str]:
    with en_empresa(mundo.db, mundo.id[empresa]):
        return {s.id: s.nombre for s in mundo.db.scalars(select(Sucursal))}


@pytest.mark.parametrize("empresa, otra", [(A, B), (B, A)])
def test_las_anomalias_de_cada_empresa_son_de_sus_sucursales_y_coinciden_con_su_propio_detector(entrenado, empresa, otra):
    cuerpo = _ok(_get(entrenado, empresa, "/anomalias", dias=365))
    propias, ajenas = _sucursales(entrenado, empresa), _sucursales(entrenado, otra)
    assert cuerpo["anomalias"], "con 365 días el escenario debe marcar algo (la liquidación inyectada)"
    assert set(propias).isdisjoint(ajenas)

    ids = {a["sucursal_id"] for a in cuerpo["anomalias"]}
    assert ids <= set(propias) and not ids & set(ajenas)
    assert {a["sucursal"] for a in cuerpo["anomalias"]} <= set(propias.values())
    texto = _texto(cuerpo)
    assert not any(nombre in texto for nombre in set(ajenas.values()) - set(propias.values()))
    # Es lo que da el detector con el artefacto DE ESA empresa y SUS filas; con el de la otra daría otra cosa o nada.
    propio = _artefacto(entrenado.db, entrenado.id[empresa], TIPO_ANOMALIAS)
    filas = _filas_de_comercial(entrenado.db, entrenado.id[empresa], 365)
    esperadas = _como_dicts(ml_anomalias.detectar_anomalias(propio, filas, FIN, 365))
    assert cuerpo["anomalias"] == esperadas
    ajeno = _artefacto(entrenado.db, entrenado.id[otra], TIPO_ANOMALIAS)
    assert set(ajeno["sucursales"]).isdisjoint(propio["sucursales"])  # cada modelo conoce solo las sucursales de su empresa
    assert ml_anomalias.detectar_anomalias(ajeno, filas, FIN, 365) == []  # con el modelo de la otra empresa no se evalúa nada


def test_el_modelo_de_anomalias_de_a_no_se_usa_para_b(mundo):
    entrenar(mundo.db, A, [TIPO_ANOMALIAS])
    ok = _get(mundo, A, "/anomalias", dias=365)
    assert ok.status_code == 200 and ok.json()["anomalias"]

    respuesta = _get(mundo, B, "/anomalias", dias=365)

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "modelo_no_entrenado"
    assert respuesta.json()["tipo"] == TIPO_ANOMALIAS and "anomalias" not in respuesta.json()


def test_un_modelo_de_anomalias_de_b_copiado_como_fila_de_a_no_sirve_para_a(mundo):
    entrenar(mundo.db, B, [TIPO_ANOMALIAS])
    _copiar_modelo(mundo, B, A, TIPO_ANOMALIAS)  # A solo tiene la fila copiada de B

    respuesta = _get(mundo, A, "/anomalias", dias=365)

    assert respuesta.status_code == 409 and respuesta.json()["detail"] == "modelo_obsoleto"
    assert "anomalias" not in respuesta.json()
    assert _get(mundo, B, "/anomalias", dias=365).status_code == 200  # control: el de B sigue sirviendo a B


@pytest.mark.parametrize("empresa, otra", [(A, B), (B, A)])
def test_el_disponible_de_la_reposicion_es_solo_el_stock_de_la_empresa_del_token(entrenado, empresa, otra):
    cuerpo, de_la_otra = _ok(_get(entrenado, empresa, "/reposicion")), _ok(_get(entrenado, otra, "/reposicion"))
    propias = {i["categoria_id"] for i in cuerpo["items"]}
    assert propias and propias.isdisjoint({i["categoria_id"] for i in de_la_otra["items"]})

    for item in cuerpo["items"]:
        assert item["disponible"] == _disponible_a_mano(entrenado.db, entrenado.id[empresa], item["categoria_id"]), item["categoria"]
        # La misma categoría vista desde la OTRA empresa no existe: no hay stock que sumar.
        assert _disponible_a_mano(entrenado.db, entrenado.id[otra], item["categoria_id"]) == 0
    assert sum(i["disponible"] for i in cuerpo["items"]) > 0
    assert sum(i["disponible"] for i in cuerpo["items"]) != sum(i["disponible"] for i in de_la_otra["items"])


def test_cambiar_el_stock_de_una_empresa_no_mueve_la_reposicion_de_la_otra(entrenado):
    antes_a, antes_b = _ok(_get(entrenado, A, "/reposicion")), _ok(_get(entrenado, B, "/reposicion"))
    categoria_b, categoria_a = antes_b["items"][0]["categoria_id"], antes_a["items"][0]["categoria_id"]

    _fijar_disponible(entrenado.db, entrenado.id[B], categoria_b, 777_777)
    despues_a, despues_b = _ok(_get(entrenado, A, "/reposicion")), _ok(_get(entrenado, B, "/reposicion"))
    assert despues_a == antes_a  # A no se enteró
    item_b = next(i for i in despues_b["items"] if i["categoria_id"] == categoria_b)
    assert item_b["disponible"] == 777_777 and item_b["estado"] == "ok" and despues_b != antes_b

    _fijar_disponible(entrenado.db, entrenado.id[A], categoria_a, 0)
    final_a, final_b = _ok(_get(entrenado, A, "/reposicion")), _ok(_get(entrenado, B, "/reposicion"))
    assert final_b == despues_b  # y B tampoco se enteró del cambio de A
    item_a = next(i for i in final_a["items"] if i["categoria_id"] == categoria_a)
    assert item_a["disponible"] == 0 and item_a["estado"] == "critico" and final_a != despues_a

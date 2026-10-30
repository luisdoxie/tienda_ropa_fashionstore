"""`scripts.evaluar_ml` (E11, paso 10/11): la tabla de evaluación que se pega en la documentación. Las pruebas de
formato usan resultados armados a mano (sin base ni entrenamiento) para forzar CUMPLE y NO CUMPLE; las de punta a
punta usan el escenario del CU-24 (SQLite en memoria) y comprueban que el script NO escribe nada."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.comercial.models import Venta
from app.core.tenant import en_empresa, fijar_empresa
from app.inteligencia.models import ModeloML
from app.plataforma.models import Empresa
from scripts import evaluar_ml
from scripts.evaluar_ml import (
    ANCHO_MAXIMO,
    Contexto,
    EvaluacionDemanda,
    EvaluacionSegmentos,
    Pureza,
    calcular_pureza,
    criterios_demanda,
    describir_base,
    formatear_demanda,
    formatear_informe,
    formatear_segmentos,
    main,
)
from tests.inteligencia.ml._escenario import FIN, cargar_historia, crear_vista_de_ventas, id_de, poblar
from tests.scripts._prendas_falsas import crear_carpeta


# ---- Resultados armados a mano -------------------------------------------------------------------------------------------


def _metricas_buenas() -> dict:
    return {
        "mae": 10.0, "rmse": 14.0, "r2": 0.80, "mae_base": 12.0, "rmse_base": 17.0, "r2_base": 0.55, "mejora_mae_pct": 16.6667,
        "modelo_elegido": "ridge", "filas_train": 300, "filas_test": 48,
        "validacion_cruzada": {
            "ridge": {"mae_medio": 11.1}, "mezcla": {"mae_medio": 11.5}, "random_forest": {"mae_medio": 12.3},
        },
    }  # fmt: skip


def _demanda(metricas: dict | None = None, **extra) -> EvaluacionDemanda:
    parametros = {"n_semanas": 78, "n_categorias": 4, "segundos_entrenamiento": 3.456}
    return EvaluacionDemanda("ok", metricas=metricas or _metricas_buenas(), parametros=parametros, tamano_artefacto=123456, **extra)


def _segmentos(silhouette: float = 0.40, nombre: str = "Campeones") -> EvaluacionSegmentos:
    return EvaluacionSegmentos(
        "ok",
        metricas={
            "k": 3, "silhouette": silhouette, "n_clientes": 400,
            "curva_codo": [{"k": 2, "inercia": 900.5}, {"k": 3, "inercia": 600.25}],
            "curva_silhouette": [{"k": 2, "silhouette": 0.31}, {"k": 3, "silhouette": silhouette}],
        },  # fmt: skip
        segmentos=[
            {"id": 0, "nombre": nombre, "n_clientes": 150, "pct_clientes": 37.5, "recencia_media": 12.3, "frecuencia_media": 9.1,
             "monto_medio": 1500.0, "monto_total": 225000.0},
            {"id": 1, "nombre": "Hibernando", "n_clientes": 250, "pct_clientes": 62.5, "recencia_media": 210.0, "frecuencia_media": 1.2,
             "monto_medio": 120.0, "monto_total": 30000.0},
        ],  # fmt: skip
        segundos=0.5,
    )


def _contexto(**cambios) -> Contexto:
    import datetime as dt

    datos = dict(
        base="fashionstore_dev", ubicacion="local", empresa="fashionstore", plan="Profesional", fuente="memoria",
        detalle_fuente="historial sintetico en memoria", corte=dt.date(2026, 10, 25), desde=dt.date(2025, 4, 28),
        hasta=dt.date(2026, 10, 25), ultima_fecha=dt.date(2026, 10, 25),
    )  # fmt: skip
    datos.update(cambios)
    return Contexto(**datos)


# ---- Formato -------------------------------------------------------------------------------------------------------------


def test_el_informe_trae_las_cuatro_secciones_y_cada_metrica():
    pureza = Pureza(campeones_total=40, campeones_bien=38, dormidos_total=50, dormidos_bien=45)
    texto = formatear_informe(_contexto(), _demanda(), _segmentos(), pureza)

    for seccion in ("EVALUACION DE MODELOS", "DEMANDA SEMANAL", "SEGMENTOS DE CLIENTES", "HONESTIDAD Y LIMITACIONES", "PUREZA"):
        assert seccion in texto
    for metrica in ("MAE", "RMSE", "R2", "Mejora de MAE", "Linea base", "Modelo (ridge)"):
        assert metrica in texto
    for candidato in ("ridge", "mezcla", "random_forest"):  # la validacion cruzada de cada candidato
        assert candidato in texto
    assert "10,00" in texto and "12,00" in texto and "0,80" in texto and "16,7 %" in texto  # decimales a la española
    assert "123.456" in texto  # bytes del artefacto
    assert "Filas de entrenamiento" in texto and "Filas de prueba" in texto and "Semanas usadas" in texto
    for dato in ("k elegido", "Silhouette", "Inercia", "Rec.(d)", "Monto total", "Hibernando"):
        assert dato in texto
    assert "fashionstore_dev (local)" in texto and "Plan: Profesional" in texto and "2026-10-25" in texto


def test_los_tres_criterios_cumplen_con_un_caso_bueno():
    criterios = criterios_demanda(_metricas_buenas())
    assert [c.cumple for c in criterios] == [True, True, True]
    texto = formatear_demanda(_demanda())
    assert texto.count("NO CUMPLE") == 0 and texto.count("CUMPLE") == 3


def test_los_tres_criterios_no_cumplen_con_un_caso_malo():
    malas = {**_metricas_buenas(), "mae": 14.0, "mae_base": 12.0, "r2": 0.30, "mejora_mae_pct": -16.7}
    assert [c.cumple for c in criterios_demanda(malas)] == [False, False, False]
    texto = formatear_demanda(_demanda(malas))
    assert texto.count("NO CUMPLE") == 3


def test_los_umbrales_no_se_reinterpretan_en_el_limite():
    # Justo en el umbral: R2 = 0,50 y mejora = 5 % cumplen; un poco menos, no. MAE igual al de la base cumple (<=).
    en_el_limite = {**_metricas_buenas(), "mae": 12.0, "mae_base": 12.0, "r2": 0.50, "mejora_mae_pct": 5.0}
    assert [c.cumple for c in criterios_demanda(en_el_limite)] == [True, True, True]
    justo_debajo = {**en_el_limite, "r2": 0.4999, "mejora_mae_pct": 4.99}
    assert [c.cumple for c in criterios_demanda(justo_debajo)] == [True, False, False]
    sin_numeros = {**_metricas_buenas(), "r2": None, "mejora_mae_pct": None}  # no se puede afirmar: NO CUMPLE
    assert [c.cumple for c in criterios_demanda(sin_numeros)] == [True, False, False]


def test_silhouette_y_pureza_tienen_su_propio_veredicto():
    bueno = formatear_segmentos(_segmentos(0.40), Pureza(40, 38, 50, 45))
    assert "NO CUMPLE" not in bueno and bueno.count("CUMPLE") == 3  # silhouette + dos purezas
    malo = formatear_segmentos(_segmentos(0.10), Pureza(40, 20, 50, 10))
    assert malo.count("NO CUMPLE") == 3
    sin_clientes_del_arquetipo = formatear_segmentos(_segmentos(0.40), Pureza())
    assert sin_clientes_del_arquetipo.count("NO CUMPLE") == 2 and "n/d" in sin_clientes_del_arquetipo


def test_datos_insuficientes_imprime_el_motivo_en_vez_de_la_tabla():
    motivo = "Se necesitan al menos 26 semanas con ventas y hay 10."
    demanda = EvaluacionDemanda("datos_insuficientes", motivo=motivo)
    segmentos = EvaluacionSegmentos("datos_insuficientes", motivo="Se necesitan al menos 30 clientes con compras y hay 3.")
    texto = formatear_informe(_contexto(), demanda, segmentos, None)

    assert motivo in texto and "30 clientes" in texto and "datos_insuficientes" in texto
    assert "Linea base" not in texto and "CUMPLE" not in texto and "+--" not in texto
    assert "HONESTIDAD Y LIMITACIONES" in texto  # el cierre sale igual


def test_ninguna_linea_pasa_de_100_columnas_ni_siquiera_con_nombres_larguisimos():
    nombre_largo = "Segmento con un nombre desmesuradamente largo " * 3
    texto = formatear_informe(
        _contexto(empresa="x" * 60, detalle_fuente="y" * 150), _demanda(), _segmentos(nombre=nombre_largo), Pureza(40, 38, 50, 45)
    )
    ancho = max(len(linea) for linea in texto.splitlines())
    assert ancho <= ANCHO_MAXIMO == 100
    assert all(ord(c) < 128 for c in texto)  # ASCII puro: ni tildes ni ñ


def test_cierre_de_honestidad_tiene_entre_4_y_6_lineas_fijas():
    cierre = evaluar_ml.formatear_limitaciones().splitlines()
    puntos = [linea for linea in cierre if linea.startswith("- ")]
    assert 4 <= len(puntos) <= 6
    unido = " ".join(puntos).lower()
    for idea in ("sinteticos", "promocion", "intervalo de confianza", "mediana", "hold-out", "semilla"):
        assert idea in unido


def test_no_imprime_la_url_ni_el_host_ni_la_contrasena():
    from sqlalchemy.engine import make_url

    url = make_url("postgresql+psycopg://postgres:secreta@servidor-remoto.ejemplo.com:5432/fashionstore_prod")
    base, ubicacion = describir_base(url)
    assert (base, ubicacion) == ("fashionstore_prod", "remota")
    assert describir_base(make_url("postgresql+psycopg://u:p@localhost/fashionstore_dev")) == ("fashionstore_dev", "local")
    assert describir_base(make_url("sqlite://"))[1] == "en memoria"

    texto = formatear_informe(_contexto(base=base, ubicacion=ubicacion), _demanda(), _segmentos(), None)
    for prohibido in ("://", "secreta", "servidor-remoto", "postgres:", "psycopg"):
        assert prohibido not in texto
    assert "(remota)" in texto


def test_pureza_compara_el_arquetipo_real_con_el_nombre_del_segmento():
    clientes = [SimpleNamespace(n=i, arquetipo=a) for i, a in enumerate(["campeon", "campeon", "dormido", "dormido", "dormido", "leal", "campeon"])]
    segmentos = [{"id": 0, "nombre": "Campeones"}, {"id": 1, "nombre": "Campeones 2"}, {"id": 2, "nombre": "Por reactivar"}, {"id": 3, "nombre": "Leales"}]
    # El cliente 6 (campeon) no tiene segmento: no compró en la ventana, no cuenta.
    asignaciones = {0: 0, 1: 3, 2: 2, 3: 2, 4: 3, 5: 3}
    pureza = calcular_pureza(clientes, asignaciones, segmentos)
    assert (pureza.campeones_total, pureza.campeones_bien) == (2, 1)
    assert (pureza.dormidos_total, pureza.dormidos_bien) == (3, 2)
    assert calcular_pureza(clientes, {1: 1}, segmentos).campeones_bien == 1  # "Campeones 2" también empieza por "Campeones"


# ---- De punta a punta (escenario del CU-24, SQLite en memoria) ----------------------------------------------------------


@pytest.fixture()
def mundo(db_session, tmp_path):
    poblar(db_session, crear_carpeta(tmp_path))
    crear_vista_de_ventas(db_session)
    return db_session


def _conectar(mundo, monkeypatch, codigo: str = "fashionstore") -> int:
    empresa_id = id_de(mundo, codigo)

    def abrir(_codigo=None):
        fijar_empresa(mundo, empresa_id)
        return mundo, mundo.get(Empresa, empresa_id)

    monkeypatch.setattr("scripts._empresa.abrir_sesion", abrir)
    return empresa_id


def _contar(db, empresa_id, modelo) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(modelo))


def test_fuente_base_entrena_con_lo_que_hay_y_no_crea_ninguna_fila(mundo, monkeypatch, capsys):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    _conectar(mundo, monkeypatch)
    antes = (_contar(mundo, fs, Venta), _contar(mundo, fs, ModeloML))

    main(["--empresa", "fashionstore", "--fuente", "base", "--fin", FIN.isoformat()])
    salida = capsys.readouterr().out

    assert (_contar(mundo, fs, Venta), _contar(mundo, fs, ModeloML)) == antes
    assert antes[1] == 0  # nunca guarda un modelo: el CU-24 es quien lo hace
    for texto in ("DEMANDA SEMANAL", "SEGMENTOS DE CLIENTES", "Modelo (", "Linea base", "HONESTIDAD Y LIMITACIONES", "Fuente        : base"):
        assert texto in salida
    assert "PUREZA" not in salida  # la base no conoce la verdad de arquetipos
    assert "://" not in salida and max(len(linea) for linea in salida.splitlines()) <= ANCHO_MAXIMO
    assert "(en memoria)" in salida  # el nombre de la base de pruebas, nunca su URL


def test_fuente_memoria_genera_el_historial_sin_insertar_y_si_imprime_la_pureza(mundo, monkeypatch, capsys):
    fs = _conectar(mundo, monkeypatch)
    antes = (_contar(mundo, fs, Venta), _contar(mundo, fs, ModeloML))
    assert antes[0] == 0  # la empresa aun no tiene historial

    main(["--empresa", "fashionstore", "--fuente", "memoria", "--semanas", "40", "--clientes", "80", "--fin", FIN.isoformat()])
    salida = capsys.readouterr().out
    print(salida)  # solo se ve con -s o si la prueba falla

    assert (_contar(mundo, fs, Venta), _contar(mundo, fs, ModeloML)) == antes
    corrida = " ".join(salida.split())  # la línea de la fuente se parte a 100 columnas: se compara sin saltos
    for texto in ("DEMANDA SEMANAL", "SEGMENTOS DE CLIENTES", "PUREZA", "campeon", "dormido", "40 semanas, 80 clientes", "Plan: Profesional"):
        assert texto in corrida
    assert salida.count("CUMPLE") >= 5  # 3 criterios de demanda + silhouette + 2 purezas (CUMPLE o NO CUMPLE)
    assert "://" not in salida and max(len(linea) for linea in salida.splitlines()) <= ANCHO_MAXIMO


def test_fuente_base_sin_historial_dice_datos_insuficientes_sin_romper(mundo, monkeypatch, capsys):
    fs = _conectar(mundo, monkeypatch)
    main(["--empresa", "fashionstore", "--fin", FIN.isoformat()])  # la fuente por defecto es la base
    salida = capsys.readouterr().out
    assert "datos_insuficientes" in salida and "Linea base" not in salida
    assert _contar(mundo, fs, ModeloML) == 0

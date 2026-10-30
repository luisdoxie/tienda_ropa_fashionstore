"""E12, CU-24: plan, suscripción, permisos, alcance y tasa de las 7 rutas de `/api/v1/analitica` (las 5 de la E12a más
`/anomalias` y `/reposicion` de la E12b).

Orden de errores que se vigila: 401 sin token, 403 `suscripcion_no_activa`, 403 `plan_no_incluye_funcionalidad`
(`analitica_ml`), 403 por permiso (`reportes.ver`) o por alcance (la analítica es de toda la empresa) y, recién
después, las reglas de negocio. Límites: 30/minuto en los GET y 3/minuto en `POST /entrenar`.

El escenario sale de `mundo_ia` (A y B Profesional, con ventas y una sucursal) más una empresa Básico propia y
empresas descartables (suscripción vencida o suspendida, plan sin `analitica_ml`). Ninguna prueba entrena un modelo
de verdad: lo que se prueba es la compuerta, no el cálculo."""

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from app.core.tenant import en_empresa, sin_filtro
from app.inteligencia.models import ModeloML
from app.plataforma.models import Bitacora, Plan, Suscripcion
from tests.conftest import crear_empresa
from tests.inteligencia.ayudas_exportacion import personal_de

API = "/api/v1/analitica"
RUTAS = [
    ("GET", "/estado"), ("GET", "/demanda"), ("GET", "/segmentos"), ("GET", "/anomalias"), ("GET", "/reposicion"),
    ("GET", "/panel"), ("POST", "/entrenar"),
]  # fmt: skip
RUTAS_NUEVAS = [("GET", "/anomalias"), ("GET", "/reposicion")]
IDS_RUTAS = [f"{m} {r}" for m, r in RUTAS]
RUTAS_GET = [(m, r) for m, r in RUTAS if m == "GET"]
IDS_GET = [f"{m} {r}" for m, r in RUTAS_GET]
MENSAJE_ALCANCE = "La analítica es de toda la empresa"
LEJOS = dt.date(2020, 1, 1)  # una fecha que, con cualquier "hoy" que fije un fixture, deja la suscripción vencida


def pedir(client, metodo, ruta, headers=None, **extras):
    """La petición mínima a una ruta de la analítica (el POST lleva un cuerpo válido)."""
    if metodo == "POST":
        extras.setdefault("json", {})
    return client.request(metodo, f"{API}{ruta}", headers=headers or {}, **extras)


def cambiar_suscripcion(db, empresa_id: int, **valores) -> None:
    """Como la dejaría el tiempo o una tarea: directo en la base (la suscripción es de la empresa, hay que saltar el filtro)."""
    db.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.empresa_id == empresa_id).values(**valores)),
        execution_options={"synchronize_session": False},
    )
    db.commit()


def modelos_guardados(db, empresa_id: int) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(ModeloML))


def filas_de_bitacora(db, empresa_id: int) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.entidad == "modelo_ml"))


def descartable(db, codigo: str, plan: str = "profesional") -> SimpleNamespace:
    """Una empresa propia de la prueba, con su administrador y un cajero (sin `reportes.ver`)."""
    empresa = crear_empresa(db, codigo, plan=plan)
    return SimpleNamespace(
        id=empresa.id,
        codigo=codigo,
        admin=personal_de(db, empresa.id, "administrador", f"admin@{codigo}.example.com"),
        cajero=personal_de(db, empresa.id, "cajero", f"cajero@{codigo}.example.com"),
    )


@pytest.fixture()
def mundo(db_session, mundo_ia):
    """A y B (Profesional, con ventas), el personal de A y una empresa Básico con su administrador y su cajero."""
    centro = mundo_ia.datos_a["sucursales"]["centro"]
    a_id = mundo_ia.a.id
    return SimpleNamespace(
        a=mundo_ia.a,
        b=mundo_ia.b,
        cajero=personal_de(db_session, a_id, "cajero", "cajero@tienda-a.example.com", centro),
        encargado=personal_de(db_session, a_id, "encargado_sucursal", "encargado@tienda-a.example.com", centro),
        encargado_sin_ficha=personal_de(db_session, a_id, "encargado_sucursal", "sinficha@tienda-a.example.com"),
        cliente=personal_de(db_session, a_id, "cliente", "cliente@tienda-a.example.com"),
        basica=descartable(db_session, "tienda-basica", plan="basico"),
    )


# ---- Plan -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_el_plan_basico_recibe_403_plan_no_incluye_funcionalidad_en_cada_ruta(client_por_peticion, mundo, metodo, ruta):
    respuesta = pedir(client_por_peticion, metodo, ruta, mundo.basica.admin)

    assert respuesta.status_code == 403
    assert respuesta.json() == {
        "detail": "plan_no_incluye_funcionalidad",
        "codigo": "plan_no_incluye_funcionalidad",
        "mensaje": "Su plan no incluye esta funcionalidad",
        "funcionalidad": "analitica_ml",
        "plan": "basico",
    }


def test_el_entrenamiento_rechazado_por_plan_no_deja_modelo_ni_bitacora(client_por_peticion, db_session, mundo):
    respuesta = pedir(client_por_peticion, "POST", "/entrenar", mundo.basica.admin, json={"tipos": ["demanda_semanal"]})

    assert respuesta.status_code == 403
    assert modelos_guardados(db_session, mundo.basica.id) == 0
    assert filas_de_bitacora(db_session, mundo.basica.id) == 0


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_un_plan_profesional_editado_sin_analitica_ml_recibe_403_aunque_tenga_el_permiso(
    client_por_peticion, db_session, metodo, ruta
):
    """El plan se lee de la tabla `plan`, no del nombre: un plan nuevo que solo apaga `analitica_ml` basta para cerrar la puerta."""
    db_session.add(
        Plan(
            codigo="profesional-sin-ml", nombre="Profesional sin ML", max_sucursales=10, reportes_convencionales=True,
            reportes_ia=True, operacion_offline=True, analitica_ml=False, copias_seguridad=True, gestion_productos=True,
            gestion_ventas=True, reservas=True,
        )
    )  # fmt: skip
    db_session.commit()
    empresa = descartable(db_session, "sin-ml", plan="profesional-sin-ml")

    # Control: el administrador de esa empresa SÍ tiene `reportes.ver` y el plan SÍ incluye los reportes convencionales.
    control = client_por_peticion.get("/api/v1/reportes/inventario", headers=empresa.admin)
    assert control.status_code == 200, control.text

    respuesta = pedir(client_por_peticion, metodo, ruta, empresa.admin)

    assert respuesta.status_code == 403
    cuerpo = respuesta.json()
    assert (cuerpo["detail"], cuerpo["funcionalidad"], cuerpo["plan"]) == ("plan_no_incluye_funcionalidad", "analitica_ml", "profesional-sin-ml")


# ---- Suscripción ------------------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["vencida", "suspendida"])
@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_una_suscripcion_no_activa_da_403_suscripcion_no_activa_en_cada_ruta(
    client_por_peticion, db_session, mundo_ia, metodo, ruta, estado
):  # `mundo_ia` crea la vista de ventas que lee /estado en el control
    empresa = descartable(db_session, f"susc-{estado}")
    if metodo == "GET" and ruta == "/estado":
        # Control: antes de tocar la suscripción la misma empresa sí entra.
        assert pedir(client_por_peticion, metodo, ruta, empresa.admin).status_code == 200
    if estado == "vencida":
        cambiar_suscripcion(db_session, empresa.id, fecha_inicio=LEJOS, fecha_vencimiento=LEJOS + dt.timedelta(days=30))
    else:
        cambiar_suscripcion(db_session, empresa.id, estado="suspendida")

    respuesta = pedir(client_por_peticion, metodo, ruta, empresa.admin)

    assert respuesta.status_code == 403
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "suscripcion_no_activa"
    assert cuerpo["estado"] == estado


# ---- Sin sesión, permiso y alcance ------------------------------------------------------------------


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_sin_token_o_con_un_token_basura_da_401(client_por_peticion, mundo, metodo, ruta):
    assert pedir(client_por_peticion, metodo, ruta).status_code == 401
    assert pedir(client_por_peticion, metodo, ruta, {"Authorization": "Bearer esto.no.es-un-token"}).status_code == 401


@pytest.mark.parametrize("quien", ["cliente", "cajero"])
@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_un_cliente_o_un_cajero_sin_reportes_ver_recibe_403_de_permiso(client_por_peticion, mundo, metodo, ruta, quien):
    respuesta = pedir(client_por_peticion, metodo, ruta, getattr(mundo, quien))

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "Falta el permiso 'reportes.ver'"


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_un_encargado_con_sucursal_tiene_reportes_ver_pero_recibe_403_de_alcance(client_por_peticion, db_session, mundo, metodo, ruta):
    respuesta = pedir(client_por_peticion, metodo, ruta, mundo.encargado)

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == MENSAJE_ALCANCE  # no es el de permiso: el encargado SÍ tiene reportes.ver
    assert modelos_guardados(db_session, mundo.a.id) == 0  # el entrenamiento rechazado no dejó nada


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_un_encargado_sin_ficha_de_empleado_tampoco_entra(client_por_peticion, mundo, metodo, ruta):
    respuesta = pedir(client_por_peticion, metodo, ruta, mundo.encargado_sin_ficha)

    assert respuesta.status_code == 403
    assert "analitica_ml" not in respuesta.text  # el plan de A sí la incluye: es una negativa de alcance, no de plan


def test_el_administrador_de_la_empresa_entra_sin_modelo_entrenado(client_por_peticion, mundo):
    estado = pedir(client_por_peticion, "GET", "/estado", mundo.a.headers)
    panel = pedir(client_por_peticion, "GET", "/panel", mundo.a.headers)

    assert estado.status_code == 200 and panel.status_code == 200
    assert {m["estado"] for m in estado.json()["modelos"]} == {"sin_entrenar"}
    # Sin modelo, predecir, segmentar, detectar anomalías y sugerir reposición son reglas de negocio (409), no de acceso.
    for ruta in ("/demanda", "/segmentos", "/anomalias", "/reposicion"):
        respuesta = pedir(client_por_peticion, "GET", ruta, mundo.a.headers)
        assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "modelo_no_entrenado", (ruta, respuesta.text)


# ---- Orden de errores ---------------------------------------------------------------------------------


@pytest.mark.parametrize("metodo, ruta", RUTAS, ids=IDS_RUTAS)
def test_el_plan_se_comprueba_antes_que_el_permiso(client_por_peticion, mundo, metodo, ruta):
    """Un cajero (sin reportes.ver) en una empresa Básico recibe el 403 de PLAN; en una Profesional, el de PERMISO."""
    en_basico = pedir(client_por_peticion, metodo, ruta, mundo.basica.cajero)
    en_profesional = pedir(client_por_peticion, metodo, ruta, mundo.cajero)

    assert en_basico.status_code == 403 and en_basico.json()["detail"] == "plan_no_incluye_funcionalidad"
    assert en_profesional.status_code == 403 and en_profesional.json()["detail"] == "Falta el permiso 'reportes.ver'"


def test_la_suscripcion_se_comprueba_antes_que_el_plan_y_el_permiso(client_por_peticion, db_session):
    """Cajero (sin permiso) de una empresa Básico (sin plan) con la suscripción suspendida: gana la suscripción."""
    empresa = descartable(db_session, "orden-susc", plan="basico")
    cambiar_suscripcion(db_session, empresa.id, estado="suspendida")

    for metodo, ruta in RUTAS:
        respuesta = pedir(client_por_peticion, metodo, ruta, empresa.cajero)
        assert respuesta.status_code == 403 and respuesta.json()["detail"] == "suscripcion_no_activa", (metodo, ruta, respuesta.text)


@pytest.mark.parametrize("metodo, ruta, parametros", [
    ("GET", "/demanda", {"semanas": 99}),
    ("GET", "/demanda", {"categoria_id": 0}),
    ("GET", "/anomalias", {"dias": 3}),
    ("GET", "/reposicion", {"semanas": 99}),
    ("POST", "/entrenar", None),
], ids=["semanas-fuera-de-rango", "categoria-invalida", "dias-fuera-de-rango", "semanas-de-reposicion-fuera-de-rango", "cuerpo-invalido"])  # fmt: skip
def test_las_reglas_de_negocio_y_la_validacion_llegan_despues_del_plan(client_por_peticion, mundo, metodo, ruta, parametros):
    """Una petición mal formada de una empresa Básico recibe el 403 de plan, nunca el 422: no se le dice nada de la ruta."""
    extras = {"params": parametros} if parametros is not None else {"json": {"tipos": ["no_existe"], "empresa_id": 1}}

    respuesta = pedir(client_por_peticion, metodo, ruta, mundo.basica.admin, **extras)

    assert respuesta.status_code == 403 and respuesta.json()["detail"] == "plan_no_incluye_funcionalidad"


PARAMETROS_INVALIDOS = [
    ("/demanda", {"semanas": 99}),
    ("/anomalias", {"dias": 3}),
    ("/anomalias", {"dias": 400}),
    ("/reposicion", {"semanas": 99}),
    ("/reposicion", {"semanas": 0}),
]


@pytest.mark.parametrize("ruta, parametros", PARAMETROS_INVALIDOS, ids=[f"{r}-{p}" for r, p in PARAMETROS_INVALIDOS])
def test_el_alcance_se_comprueba_antes_que_la_validacion_de_parametros(client_por_peticion, mundo, ruta, parametros):
    """El alcance global es una dependencia del router (corre antes de validar la query y el cuerpo)."""
    respuesta = pedir(client_por_peticion, "GET", ruta, mundo.encargado, params=parametros)

    assert respuesta.status_code == 403 and respuesta.json()["detail"] == MENSAJE_ALCANCE


@pytest.mark.parametrize("ruta, parametros", PARAMETROS_INVALIDOS, ids=[f"{r}-{p}" for r, p in PARAMETROS_INVALIDOS])
def test_un_parametro_fuera_de_rango_del_administrador_si_da_422(client_por_peticion, mundo, ruta, parametros):
    """Contraste del anterior: con acceso, la misma validación responde 422 (la prueba de arriba no pasa por no validar nada)."""
    respuesta = pedir(client_por_peticion, "GET", ruta, mundo.a.headers, params=parametros)

    assert respuesta.status_code == 422


# ---- La empresa sale del token, nunca del cliente -----------------------------------------------------


@pytest.mark.parametrize("metodo, ruta", RUTAS_GET, ids=IDS_GET)
def test_un_empresa_id_en_la_query_se_ignora(client_por_peticion, mundo, metodo, ruta):
    base = pedir(client_por_peticion, metodo, ruta, mundo.a.headers)
    con_id_ajeno = pedir(client_por_peticion, metodo, ruta, mundo.a.headers, params={"empresa_id": mundo.b.id})
    con_id_basico = pedir(client_por_peticion, metodo, ruta, mundo.a.headers, params={"empresa_id": mundo.basica.id})

    assert base.status_code in (200, 409)
    assert (con_id_ajeno.status_code, con_id_ajeno.json()) == (base.status_code, base.json())
    # Si se hiciera caso al parámetro, A quedaría con el plan Básico de la otra empresa y recibiría 403.
    assert (con_id_basico.status_code, con_id_basico.json()) == (base.status_code, base.json())

    # Y al revés: la empresa Básico no se "cuela" en un plan Profesional nombrando a A.
    intento = pedir(client_por_peticion, metodo, ruta, mundo.basica.admin, params={"empresa_id": mundo.a.id})
    assert intento.status_code == 403 and intento.json()["detail"] == "plan_no_incluye_funcionalidad"


def test_un_empresa_id_en_el_cuerpo_de_entrenar_da_422_y_no_entrena(client_por_peticion, db_session, mundo):
    cuerpo = {"tipos": ["demanda_semanal"], "empresa_id": mundo.b.id}

    respuesta = pedir(client_por_peticion, "POST", "/entrenar", mundo.a.headers, json=cuerpo)

    assert respuesta.status_code == 422
    assert "empresa_id" in respuesta.text
    assert modelos_guardados(db_session, mundo.a.id) == modelos_guardados(db_session, mundo.b.id) == 0
    assert filas_de_bitacora(db_session, mundo.a.id) == filas_de_bitacora(db_session, mundo.b.id) == 0
    # Contraste: el mismo cuerpo sin el campo extra es válido.
    assert pedir(client_por_peticion, "POST", "/entrenar", mundo.a.headers, json={"tipos": ["demanda_semanal"]}).status_code == 200


# ---- Tasa ---------------------------------------------------------------------------------------------


def test_la_cuarta_llamada_a_entrenar_en_un_minuto_da_429(client_por_peticion, mundo):
    estados = [pedir(client_por_peticion, "POST", "/entrenar", mundo.a.headers).status_code for _ in range(4)]

    assert estados == [200, 200, 200, 429]


def test_la_llamada_31_a_estado_en_un_minuto_da_429(client_por_peticion, mundo):
    estados = [pedir(client_por_peticion, "GET", "/estado", mundo.a.headers).status_code for _ in range(31)]

    assert estados[:30] == [200] * 30 and estados[30] == 429


@pytest.mark.parametrize("metodo, ruta", RUTAS_NUEVAS, ids=[f"{m} {r}" for m, r in RUTAS_NUEVAS])
def test_la_llamada_31_a_las_rutas_nuevas_en_un_minuto_da_429(client_por_peticion, mundo, metodo, ruta):
    # Sin modelo entrenado cada llamada responde 409 (regla de negocio): lo que se vigila es que la 31 sea 429.
    estados = [pedir(client_por_peticion, metodo, ruta, mundo.a.headers).status_code for _ in range(31)]

    assert estados[:30] == [409] * 30 and estados[30] == 429


def test_el_limite_de_entrenar_no_gasta_el_de_los_get(client_por_peticion, mundo):
    """Cada ruta lleva su propio balde: agotar `POST /entrenar` no deja sin consultas al panel."""
    estados = [pedir(client_por_peticion, "POST", "/entrenar", mundo.a.headers).status_code for _ in range(4)]

    assert estados[-1] == 429
    assert pedir(client_por_peticion, "GET", "/panel", mundo.a.headers).status_code == 200

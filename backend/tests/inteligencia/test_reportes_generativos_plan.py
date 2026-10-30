"""CU-23 (E09): el plan y la suscripción. Sin `reportes_ia` (plan Básico) los tres endpoints nuevos dan 403
`plan_no_incluye_funcionalidad`; los reportes convencionales (CU-22) siguen funcionando."""

import datetime as dt

from sqlalchemy import update

from app.core.tenant import sin_filtro
from app.plataforma.models import Suscripcion
from tests.inteligencia.ayudas_reportes_generativos import API, ejecutar, interpretar


def _plan_no_incluye(respuesta) -> bool:
    return respuesta.status_code == 403 and respuesta.json().get("detail") == "plan_no_incluye_funcionalidad"


def test_el_plan_basico_recibe_403_en_los_tres_endpoints(client_por_peticion, dos_empresas):
    basico = dos_empresas.b.headers

    assert _plan_no_incluye(client_por_peticion.get(f"{API}/catalogo", headers=basico))
    assert _plan_no_incluye(interpretar(client_por_peticion, basico, texto="ventas"))
    respuesta = ejecutar(client_por_peticion, basico, texto="ventas")
    assert _plan_no_incluye(respuesta)
    assert respuesta.json()["funcionalidad"] == "reportes_ia" and respuesta.json()["plan"] == "basico"


def test_el_plan_basico_sigue_con_los_reportes_convencionales(client_por_peticion, dos_empresas):
    assert client_por_peticion.get("/api/v1/reportes/reservas", headers=dos_empresas.b.headers).status_code == 200
    assert client_por_peticion.get("/api/v1/reportes/inventario", headers=dos_empresas.b.headers).status_code == 200


def test_el_plan_profesional_pasa(client_por_peticion, dos_empresas):
    headers = dos_empresas.a.headers

    assert client_por_peticion.get(f"{API}/catalogo", headers=headers).status_code == 200
    assert interpretar(client_por_peticion, headers, solicitud={"tipo_reporte": None}).status_code == 200
    assert ejecutar(client_por_peticion, headers, solicitud={"tipo_reporte": None}).status_code == 200


def test_la_suscripcion_vencida_da_403_suscripcion_no_activa(client_por_peticion, db_session, dos_empresas):
    ayer = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(
            update(Suscripcion)
            .where(Suscripcion.empresa_id == dos_empresas.a.id)
            .values(fecha_inicio=ayer - dt.timedelta(days=30), fecha_vencimiento=ayer)
        ),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    for respuesta in (
        client_por_peticion.get(f"{API}/catalogo", headers=dos_empresas.a.headers),
        interpretar(client_por_peticion, dos_empresas.a.headers, texto="ventas"),
        ejecutar(client_por_peticion, dos_empresas.a.headers, texto="ventas"),
    ):
        assert respuesta.status_code == 403
        assert respuesta.json()["detail"] == "suscripcion_no_activa"


def test_el_catalogo_solo_lista_lo_que_el_plan_incluye(client_por_peticion, dos_empresas):
    catalogo = client_por_peticion.get(f"{API}/catalogo", headers=dos_empresas.a.headers).json()

    # La empresa A es Profesional: los 6 de reportes_ia y los 5 de analitica_ml (E12). Ver
    # test_reportes_inteligentes_cu23.py para el caso de un plan con reportes_ia pero sin analitica_ml.
    assert len(catalogo) == 11

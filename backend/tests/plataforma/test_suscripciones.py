"""E04: la suscripción de una empresa. Reglas (D08): estados y transiciones, el
estado efectivo por fecha, una sola suscripción vigente por empresa. La parte
HTTP (asignar, cambiar, renovar, suspender y el bloqueo de las empresas sin
suscripción activa) está más abajo."""

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictoError
from app.core.tenant import fijar_empresa, sin_filtro
from app.plataforma import politicas
from app.plataforma.models import Empresa, Plan, Suscripcion
from tests.conftest import crear_empresa
from tests.plataforma.ayudas_empresas import PLATAFORMA, suscripciones_de

HOY = dt.date(2026, 10, 21)
ESTADOS = ("activa", "suspendida", "vencida", "cancelada")
PERMITIDAS = {
    ("activa", "suspendida"),
    ("activa", "vencida"),
    ("activa", "cancelada"),
    ("suspendida", "activa"),
    ("suspendida", "cancelada"),
    ("vencida", "activa"),
    ("vencida", "cancelada"),
}


@pytest.mark.parametrize("origen", ESTADOS)
@pytest.mark.parametrize("destino", ESTADOS)
def test_matriz_de_transiciones(origen, destino):
    if (origen, destino) in PERMITIDAS:
        politicas.validar_transicion(origen, destino)
    else:
        with pytest.raises(ConflictoError, match="Transición de estado no permitida"):
            politicas.validar_transicion(origen, destino)


def test_cancelada_es_un_estado_final():
    for destino in ESTADOS:
        with pytest.raises(ConflictoError):
            politicas.validar_transicion("cancelada", destino)


@pytest.mark.parametrize(
    "estado, vencimiento, esperado",
    [
        ("activa", HOY + dt.timedelta(days=1), "activa"),
        ("activa", HOY, "activa"),  # vence al terminar el día de la fecha
        ("activa", HOY - dt.timedelta(days=1), "vencida"),
        ("suspendida", HOY - dt.timedelta(days=30), "suspendida"),
        ("cancelada", HOY - dt.timedelta(days=30), "cancelada"),
        ("vencida", HOY + dt.timedelta(days=10), "vencida"),
    ],
)
def test_estado_efectivo_por_fecha(estado, vencimiento, esperado):
    suscripcion = SimpleNamespace(estado=estado, fecha_vencimiento=vencimiento)
    assert politicas.estado_efectivo(suscripcion, HOY) == esperado


def test_una_empresa_nunca_tiene_dos_suscripciones_vigentes(db_session):
    empresa_id = crear_empresa(db_session, "con-una-vigente").id
    plan_id = db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    fijar_empresa(db_session, empresa_id)
    db_session.add(
        Suscripcion(
            empresa_id=empresa_id, plan_id=plan_id, estado="suspendida",
            fecha_inicio=dt.date.today(), fecha_vencimiento=dt.date.today() + dt.timedelta(days=5),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()  # ya tenía una activa: el índice parcial rechaza otra vigente
    db_session.rollback()


# ---- Parte HTTP: asignar, cambiar de plan, renovar, estado y vencimiento ----------------------
# Usan `client_por_peticion`, `dos_empresas` (A = 'tienda-a' Profesional, B = 'tienda-b'
# Básico) y `superadmin_headers` (tests/plataforma/conftest.py). El bloqueo por
# suscripción_no_activa se prueba aparte.

SUSCRIPCIONES = f"{PLATAFORMA}/suscripciones"
API = "/api/v1"
TOKEN_DE_SERVICIO = {"X-Service-Token": "token-de-pruebas"}  # TAREAS_TOKEN de tests/conftest.py


def _hoy() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _vigente(db, empresa_id: int) -> Suscripcion:
    return next(s for s in suscripciones_de(db, empresa_id) if s.estado != "cancelada")


def _fijar_fechas(db, suscripcion_id: int, inicio: dt.date, vencimiento: dt.date) -> None:
    db.execute(
        sin_filtro(
            update(Suscripcion).where(Suscripcion.id == suscripcion_id).values(fecha_inicio=inicio, fecha_vencimiento=vencimiento)
        ),
        execution_options={"synchronize_session": False},
    )
    db.commit()


def _vencer_por_fecha(db, suscripcion_id: int) -> None:
    """La deja `activa` pero con la fecha pasada: vencida SIN correr la tarea."""
    _fijar_fechas(db, suscripcion_id, _hoy() - dt.timedelta(days=40), _hoy() - dt.timedelta(days=1))


def _sucursales(client, headers, cantidad: int) -> None:
    ciudad = client.post(f"{API}/ciudades", json={"nombre": "Ciudad de prueba"}, headers=headers).json()["id"]
    for i in range(cantidad):
        creada = client.post(
            f"{API}/sucursales",
            json={"ciudad_id": ciudad, "codigo": f"S{i}", "nombre": f"S{i}", "direccion": "Calle 1"},
            headers=headers,
        )
        assert creada.status_code == 201, creada.text


def _asignar(client, headers, empresa_id: int, plan: str, **extra):
    return client.post(SUSCRIPCIONES, json={"empresa_id": empresa_id, "plan_codigo": plan, **extra}, headers=headers)


def _estado(client, headers, suscripcion_id: int, estado: str):
    return client.put(f"{SUSCRIPCIONES}/{suscripcion_id}/estado", json={"estado": estado}, headers=headers)


def test_asignar_plan_a_una_empresa_sin_suscripcion(client_por_peticion, db_session, superadmin_headers):
    empresa = Empresa(nombre="Sin Plan", codigo="sin-plan")
    db_session.add(empresa)
    db_session.commit()

    respuesta = _asignar(client_por_peticion, superadmin_headers, empresa.id, "profesional")

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["empresa_id"] == empresa.id
    assert (cuerpo["plan_codigo"], cuerpo["estado"], cuerpo["estado_efectivo"]) == ("profesional", "activa", "activa")
    assert cuerpo["fecha_inicio"] == _hoy().isoformat()
    assert cuerpo["fecha_vencimiento"] == (_hoy() + dt.timedelta(days=30)).isoformat()
    assert len(suscripciones_de(db_session, empresa.id)) == 1
    # Con fechas pedidas.
    otra = Empresa(nombre="Con Fechas", codigo="con-fechas")
    db_session.add(otra)
    db_session.commit()
    inicio, fin = _hoy() - dt.timedelta(days=3), _hoy() + dt.timedelta(days=90)
    pedida = _asignar(
        client_por_peticion, superadmin_headers, otra.id, "basico", fecha_inicio=inicio.isoformat(), fecha_vencimiento=fin.isoformat()
    )
    assert pedida.status_code == 201
    assert (pedida.json()["fecha_inicio"], pedida.json()["fecha_vencimiento"]) == (inicio.isoformat(), fin.isoformat())


def test_cambiar_de_plan_deja_dos_filas_y_una_sola_vigente(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    antes = _vigente(db_session, dos_empresas.b.id)
    assert antes.fecha_vencimiento > _hoy()  # vence en un año

    respuesta = _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "profesional")

    assert respuesta.status_code == 201
    assert respuesta.json()["plan_codigo"] == "profesional"
    assert respuesta.json()["id"] != antes.id
    filas = suscripciones_de(db_session, dos_empresas.b.id)
    assert [f.estado for f in filas] == ["cancelada", "activa"]
    cerrada, nueva = filas
    assert cerrada.id == antes.id
    assert cerrada.fecha_vencimiento == _hoy()  # recortada: constancia de cuándo terminó
    assert cerrada.fecha_inicio <= cerrada.fecha_vencimiento
    assert nueva.fecha_inicio == _hoy()
    assert len([f for f in filas if f.estado != "cancelada"]) == 1
    # El cambio rige de inmediato: Profesional ya incluye reportes_ia.
    mi = client_por_peticion.get(f"{API}/mi-empresa/suscripcion", headers=dos_empresas.b.headers).json()
    assert (mi["plan_codigo"], mi["max_sucursales"]) == ("profesional", 10)


def test_cerrar_la_vigente_respeta_el_check_de_fechas(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    # Empezó hace 10 días y vence en 5: se recorta a hoy. Si empieza mañana, el
    # vencimiento no puede quedar antes del inicio (ck_suscripcion_fechas).
    vigente = _vigente(db_session, dos_empresas.b.id)
    manana = _hoy() + dt.timedelta(days=1)
    _fijar_fechas(db_session, vigente.id, manana, manana + dt.timedelta(days=30))

    respuesta = _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "profesional")

    assert respuesta.status_code == 201, respuesta.text
    cerrada = suscripciones_de(db_session, dos_empresas.b.id)[0]
    assert cerrada.estado == "cancelada"
    assert cerrada.fecha_vencimiento == cerrada.fecha_inicio == manana

    # Una vencida conserva su fecha de vencimiento real (min(actual, hoy) = actual).
    vigente = _vigente(db_session, dos_empresas.b.id)
    pasado = _hoy() - dt.timedelta(days=4)
    _fijar_fechas(db_session, vigente.id, pasado - dt.timedelta(days=20), pasado)
    assert _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "basico").status_code == 201
    assert next(s for s in suscripciones_de(db_session, dos_empresas.b.id) if s.id == vigente.id).fecha_vencimiento == pasado


def test_asignar_el_mismo_plan_es_409(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    respuesta = _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "basico")

    assert respuesta.status_code == 409
    assert len(suscripciones_de(db_session, dos_empresas.b.id)) == 1


def test_bajar_a_un_plan_con_limite_menor_al_uso_es_409(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    _sucursales(client_por_peticion, dos_empresas.a.headers, 3)  # A (Profesional) tiene 3 activas

    respuesta = _asignar(client_por_peticion, superadmin_headers, dos_empresas.a.id, "basico")  # permite 2

    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == "limite_plan_excedido"
    assert (cuerpo["limite"], cuerpo["actual"], cuerpo["plan"], cuerpo["recurso"]) == (2, 3, "basico", "sucursales")
    assert [f.estado for f in suscripciones_de(db_session, dos_empresas.a.id)] == ["activa"]  # no cambió nada


def test_bajar_con_uso_igual_al_limite_y_subir_siempre_se_puede(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    _sucursales(client_por_peticion, dos_empresas.a.headers, 2)
    _sucursales(client_por_peticion, dos_empresas.b.headers, 2)  # B ya está al tope de su plan

    baja = _asignar(client_por_peticion, superadmin_headers, dos_empresas.a.id, "basico")  # 2 activas, límite 2
    sube = _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "profesional")

    assert baja.status_code == 201 and sube.status_code == 201
    assert _vigente(db_session, dos_empresas.a.id).plan_id != _vigente(db_session, dos_empresas.b.id).plan_id


def test_asignar_con_plan_empresa_o_fechas_invalidos(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    b = dos_empresas.b.id
    pasado = (_hoy() - dt.timedelta(days=1)).isoformat()
    futuro = (_hoy() + dt.timedelta(days=60)).isoformat()
    inicio_tardio = (_hoy() + dt.timedelta(days=90)).isoformat()

    assert _asignar(client_por_peticion, superadmin_headers, b, "no-existe").status_code == 404
    assert _asignar(client_por_peticion, superadmin_headers, 999999, "basico").status_code == 404
    assert _asignar(client_por_peticion, superadmin_headers, b, "profesional", fecha_vencimiento=pasado).status_code == 422
    incoherente = _asignar(client_por_peticion, superadmin_headers, b, "profesional", fecha_inicio=inicio_tardio, fecha_vencimiento=futuro)
    assert incoherente.status_code == 422
    assert incoherente.json() == {"detail": "La fecha de vencimiento no puede ser anterior a la de inicio"}
    assert [f.estado for f in suscripciones_de(db_session, b)] == ["activa"]  # ningún intento cambió nada


def test_asignar_un_plan_inactivo_es_409(client_por_peticion, dos_empresas, superadmin_headers):
    plan = client_por_peticion.post(
        f"{PLATAFORMA}/planes", json={"codigo": "retirado", "nombre": "Retirado", "max_sucursales": 5}, headers=superadmin_headers
    ).json()
    client_por_peticion.delete(f"{PLATAFORMA}/planes/{plan['id']}", headers=superadmin_headers)

    assert _asignar(client_por_peticion, superadmin_headers, dos_empresas.b.id, "retirado").status_code == 409


def test_renovar_una_vencida_la_deja_activa(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id)
    _vencer_por_fecha(db_session, vigente.id)  # activa en la base, vencida por fecha
    nueva_fecha = (_hoy() + dt.timedelta(days=45)).isoformat()

    respuesta = client_por_peticion.put(
        f"{SUSCRIPCIONES}/{vigente.id}/renovar", json={"fecha_vencimiento": nueva_fecha}, headers=superadmin_headers
    )

    assert respuesta.status_code == 200, respuesta.text
    assert (respuesta.json()["estado"], respuesta.json()["estado_efectivo"]) == ("activa", "activa")
    assert respuesta.json()["fecha_vencimiento"] == nueva_fecha
    assert len(suscripciones_de(db_session, dos_empresas.b.id)) == 1  # renovar no crea otra fila


def test_renovar_una_vencida_persistida_por_la_tarea_tambien_la_activa(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id)
    _vencer_por_fecha(db_session, vigente.id)
    client_por_peticion.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_DE_SERVICIO)
    assert _vigente(db_session, dos_empresas.b.id).estado == "vencida"

    respuesta = client_por_peticion.put(
        f"{SUSCRIPCIONES}/{vigente.id}/renovar",
        json={"fecha_vencimiento": (_hoy() + dt.timedelta(days=10)).isoformat()},
        headers=superadmin_headers,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "activa"


def test_renovar_con_fecha_pasada_o_de_hoy_es_422(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id)

    for fecha in (_hoy() - dt.timedelta(days=1), _hoy()):
        respuesta = client_por_peticion.put(
            f"{SUSCRIPCIONES}/{vigente.id}/renovar", json={"fecha_vencimiento": fecha.isoformat()}, headers=superadmin_headers
        )
        assert respuesta.status_code == 422, fecha
    assert _vigente(db_session, dos_empresas.b.id).fecha_vencimiento == vigente.fecha_vencimiento


def test_renovar_una_suspendida_solo_cambia_la_fecha_y_una_cancelada_no_se_renueva(
    client_por_peticion, db_session, dos_empresas, superadmin_headers
):
    vigente = _vigente(db_session, dos_empresas.b.id)
    _estado(client_por_peticion, superadmin_headers, vigente.id, "suspendida")
    fecha = (_hoy() + dt.timedelta(days=100)).isoformat()

    renovada = client_por_peticion.put(f"{SUSCRIPCIONES}/{vigente.id}/renovar", json={"fecha_vencimiento": fecha}, headers=superadmin_headers)

    assert renovada.status_code == 200
    assert (renovada.json()["estado"], renovada.json()["fecha_vencimiento"]) == ("suspendida", fecha)
    _estado(client_por_peticion, superadmin_headers, vigente.id, "cancelada")
    cancelada = client_por_peticion.put(f"{SUSCRIPCIONES}/{vigente.id}/renovar", json={"fecha_vencimiento": fecha}, headers=superadmin_headers)
    assert cancelada.status_code == 409
    assert client_por_peticion.put(f"{SUSCRIPCIONES}/999999/renovar", json={"fecha_vencimiento": fecha}, headers=superadmin_headers).status_code == 404


def test_la_tarea_persiste_la_suscripcion_vencida(client_por_peticion, db_session, dos_empresas):
    vencida_id = _vigente(db_session, dos_empresas.b.id).id
    _vencer_por_fecha(db_session, vencida_id)
    assert _vigente(db_session, dos_empresas.b.id).estado == "activa"  # aún sin persistir

    sin_token = client_por_peticion.post(f"{API}/tareas/vencer-suscripciones")
    primera = client_por_peticion.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_DE_SERVICIO)
    segunda = client_por_peticion.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_DE_SERVICIO)

    assert sin_token.status_code == 401
    assert primera.status_code == 200 and primera.json() == {"vencidas": 1}
    assert segunda.json() == {"vencidas": 0}  # idempotente
    assert _vigente(db_session, dos_empresas.b.id).estado == "vencida"
    assert _vigente(db_session, dos_empresas.a.id).estado == "activa"  # las demás empresas no cambian


def test_suspender_reactivar_y_cancelar(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id).id

    suspendida = _estado(client_por_peticion, superadmin_headers, vigente, "suspendida")
    activa = _estado(client_por_peticion, superadmin_headers, vigente, "activa")
    suspendida_otra_vez = _estado(client_por_peticion, superadmin_headers, vigente, "suspendida")
    cancelada = _estado(client_por_peticion, superadmin_headers, vigente, "cancelada")

    assert [r.status_code for r in (suspendida, activa, suspendida_otra_vez, cancelada)] == [200, 200, 200, 200]
    assert (suspendida.json()["estado"], activa.json()["estado"], cancelada.json()["estado"]) == ("suspendida", "activa", "cancelada")
    # Cancelada es final: ni reactivar ni suspender; y la empresa ya no tiene vigente.
    for destino in ("activa", "suspendida", "cancelada"):
        assert _estado(client_por_peticion, superadmin_headers, vigente, destino).status_code == 409, destino
    assert [f.estado for f in suscripciones_de(db_session, dos_empresas.b.id)] == ["cancelada"]


def test_transiciones_invalidas_son_409(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id).id

    mismo_estado = _estado(client_por_peticion, superadmin_headers, vigente, "activa")  # activa -> activa
    assert mismo_estado.status_code == 409
    assert mismo_estado.json() == {"detail": "Transición de estado no permitida"}
    # `vencida` no se pide: la fija la fecha. Un estado inexistente es 422.
    assert _estado(client_por_peticion, superadmin_headers, vigente, "vencida").status_code == 422
    assert _estado(client_por_peticion, superadmin_headers, vigente, "inventado").status_code == 422
    # Vencida por fecha: no se suspende ni se reactiva sin renovar; sí se cancela.
    _vencer_por_fecha(db_session, vigente)
    assert _estado(client_por_peticion, superadmin_headers, vigente, "suspendida").status_code == 409
    sin_renovar = _estado(client_por_peticion, superadmin_headers, vigente, "activa")
    assert sin_renovar.status_code == 409
    assert "renueve" in sin_renovar.json()["detail"].lower() or "renuévela" in sin_renovar.json()["detail"].lower()
    assert _estado(client_por_peticion, superadmin_headers, vigente, "cancelada").status_code == 200
    assert _estado(client_por_peticion, superadmin_headers, 999999, "activa").status_code == 404


def test_reactivar_una_suspendida_con_la_fecha_pasada_exige_renovar(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente = _vigente(db_session, dos_empresas.b.id).id
    _estado(client_por_peticion, superadmin_headers, vigente, "suspendida")
    _vencer_por_fecha(db_session, vigente)  # estado suspendida, fecha pasada

    sin_renovar = _estado(client_por_peticion, superadmin_headers, vigente, "activa")

    assert sin_renovar.status_code == 409
    assert _vigente(db_session, dos_empresas.b.id).estado == "suspendida"
    client_por_peticion.put(
        f"{SUSCRIPCIONES}/{vigente}/renovar",
        json={"fecha_vencimiento": (_hoy() + dt.timedelta(days=30)).isoformat()},
        headers=superadmin_headers,
    )
    assert _estado(client_por_peticion, superadmin_headers, vigente, "activa").status_code == 200


def test_listar_y_obtener_con_filtros(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    vigente_b = _vigente(db_session, dos_empresas.b.id).id
    _vencer_por_fecha(db_session, vigente_b)  # vencida por fecha, sin tarea
    _asignar(client_por_peticion, superadmin_headers, dos_empresas.a.id, "basico")  # A: una cancelada y una activa

    todas = client_por_peticion.get(SUSCRIPCIONES, headers=superadmin_headers).json()
    de_a = client_por_peticion.get(f"{SUSCRIPCIONES}?empresa_id={dos_empresas.a.id}", headers=superadmin_headers).json()
    canceladas = client_por_peticion.get(f"{SUSCRIPCIONES}?estado=cancelada", headers=superadmin_headers).json()
    vencidas = client_por_peticion.get(f"{SUSCRIPCIONES}?estado=vencida", headers=superadmin_headers).json()
    activas = client_por_peticion.get(f"{SUSCRIPCIONES}?estado=activa", headers=superadmin_headers).json()

    assert {s["empresa_id"] for s in todas} >= {dos_empresas.a.id, dos_empresas.b.id}
    assert [s["estado"] for s in de_a] == ["cancelada", "activa"]
    assert [s["plan_codigo"] for s in de_a] == ["profesional", "basico"]
    assert [s["empresa_id"] for s in canceladas] == [dos_empresas.a.id]
    assert [s["id"] for s in vencidas] == [vigente_b]  # el filtro usa el estado efectivo
    assert vencidas[0]["estado"] == "activa" and vencidas[0]["estado_efectivo"] == "vencida"
    assert vigente_b not in {s["id"] for s in activas}
    assert client_por_peticion.get(f"{SUSCRIPCIONES}?estado=inventado", headers=superadmin_headers).status_code == 422
    uno = client_por_peticion.get(f"{SUSCRIPCIONES}/{vigente_b}", headers=superadmin_headers)
    assert uno.status_code == 200 and uno.json()["id"] == vigente_b
    assert client_por_peticion.get(f"{SUSCRIPCIONES}/999999", headers=superadmin_headers).status_code == 404


def test_solo_el_superadministrador_gestiona_suscripciones(client_por_peticion, db_session, dos_empresas):
    vigente = _vigente(db_session, dos_empresas.b.id).id
    admin = dos_empresas.a.headers
    rutas = (
        ("get", SUSCRIPCIONES, None),
        ("get", f"{SUSCRIPCIONES}/{vigente}", None),
        ("post", SUSCRIPCIONES, {"empresa_id": dos_empresas.b.id, "plan_codigo": "profesional"}),
        ("put", f"{SUSCRIPCIONES}/{vigente}/renovar", {"fecha_vencimiento": "2099-01-01"}),
        ("put", f"{SUSCRIPCIONES}/{vigente}/estado", {"estado": "cancelada"}),
    )

    for metodo, ruta, cuerpo in rutas:
        assert client_por_peticion.request(metodo, ruta, json=cuerpo, headers=admin).status_code == 403, ruta
        assert client_por_peticion.request(metodo, ruta, json=cuerpo).status_code == 401, ruta
    assert _vigente(db_session, dos_empresas.b.id).estado == "activa"  # ningún intento cambió nada

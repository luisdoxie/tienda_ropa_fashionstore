"""E04: el límite de sucursales activas que fija el plan (4.7).

Cuentan TODAS las sucursales con `activo` (el depósito también). Se valida al
crear y al reactivar; el borrado lógico libera cupo; editar una sucursal ya
activa no cuenta. El límite se lee de la tabla `plan`, no del código. Con la
empresa A (Profesional, 10) y la B (Básico, 2) de la fixture `dos_empresas`,
por HTTP y con una sesión nueva por petición.

La parte "vale también por el endpoint del superadministrador" depende de
las rutas /plataforma/... y se agrega con ellas."""

import pytest
from sqlalchemy import select

from app.core.exceptions import ErrorFuncional
from app.core.tenant import en_empresa
from app.plataforma.casos_uso.cu03_gestionar_organizacion import GestionarSucursales
from app.plataforma.models import Ciudad, Plan, Suscripcion
from app.plataforma.schemas import SucursalCrear

RUTA = "/api/v1/sucursales"


def _ciudad(client, empresa) -> int:
    respuesta = client.post(
        "/api/v1/ciudades", json={"nombre": f"Ciudad {empresa.codigo}", "departamento": "Santa Cruz"}, headers=empresa.headers
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


class _Sucursales:
    """Alta de sucursales de una empresa por HTTP."""

    def __init__(self, client, empresa) -> None:
        self.client = client
        self.empresa = empresa
        self.ciudad_id = _ciudad(client, empresa)
        self._n = 0

    def crear(self, **extra):
        self._n += 1
        cuerpo = {
            "ciudad_id": self.ciudad_id,
            "codigo": f"S-{self._n}",
            "nombre": f"Sucursal {self._n}",
            "direccion": "Av. 1",
            **extra,
        }
        return self.client.post(RUTA, json=cuerpo, headers=self.empresa.headers)

    def crear_ok(self, **extra) -> int:
        respuesta = self.crear(**extra)
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()["id"]

    def desactivar(self, sucursal_id: int) -> None:
        assert self.client.delete(f"{RUTA}/{sucursal_id}", headers=self.empresa.headers).status_code == 204

    def actualizar(self, sucursal_id: int, **cambios):
        return self.client.put(f"{RUTA}/{sucursal_id}", json=cambios, headers=self.empresa.headers)


@pytest.fixture()
def basico(client_por_peticion, dos_empresas):
    return _Sucursales(client_por_peticion, dos_empresas.b)


@pytest.fixture()
def profesional(client_por_peticion, dos_empresas):
    return _Sucursales(client_por_peticion, dos_empresas.a)


def _cambiar_plan_de_la_empresa(db, empresa_id: int, codigo_plan: str) -> None:
    plan_id = db.scalar(select(Plan.id).where(Plan.codigo == codigo_plan))
    with en_empresa(db, empresa_id):
        db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada")).plan_id = plan_id
    db.commit()


def _limite_del_plan(db, codigo_plan: str, limite: int) -> None:
    db.scalar(select(Plan).where(Plan.codigo == codigo_plan)).max_sucursales = limite
    db.commit()


def test_basico_la_tercera_sucursal_activa_da_409_con_el_detalle(basico):
    basico.crear_ok()
    basico.crear_ok()

    respuesta = basico.crear()

    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == cuerpo["codigo"] == "limite_plan_excedido"
    assert cuerpo["recurso"] == "sucursales"
    assert (cuerpo["limite"], cuerpo["actual"], cuerpo["plan"]) == (2, 2, "basico")
    assert cuerpo["mensaje"]


def test_reactivar_una_sucursal_inactiva_con_el_cupo_lleno_da_409(basico):
    primera = basico.crear_ok()
    basico.crear_ok()
    basico.desactivar(primera)
    basico.crear_ok()  # ocupa el cupo que dejó la baja: 2 de 2

    respuesta = basico.actualizar(primera, activo=True)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "limite_plan_excedido"
    assert respuesta.json()["actual"] == 2


def test_desactivar_una_sucursal_y_crear_otra_es_posible(basico):
    primera = basico.crear_ok()
    basico.crear_ok()
    assert basico.crear().status_code == 409

    basico.desactivar(primera)

    assert basico.crear().status_code == 201
    assert basico.crear().status_code == 409  # vuelve a estar lleno


def test_el_deposito_cuenta_como_sucursal_activa(basico):
    basico.crear_ok()
    basico.crear_ok(es_deposito=True)

    respuesta = basico.crear()

    assert respuesta.status_code == 409
    assert respuesta.json()["actual"] == 2
    # También una segunda bodega: el tipo no exime del límite.
    assert basico.crear(es_deposito=True).status_code == 409


def test_la_baja_logica_libera_cupo_y_permite_reactivar(basico):
    primera = basico.crear_ok()
    basico.crear_ok()
    basico.desactivar(primera)

    reactivada = basico.actualizar(primera, activo=True)  # 1 de 2: hay cupo

    assert reactivada.status_code == 200, reactivada.text
    assert reactivada.json()["activo"] is True
    assert basico.crear().status_code == 409  # 2 de 2 otra vez


def test_profesional_admite_hasta_10_sucursales(profesional):
    for _ in range(10):
        profesional.crear_ok()

    respuesta = profesional.crear()

    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert (cuerpo["limite"], cuerpo["actual"], cuerpo["plan"]) == (10, 10, "profesional")


def test_el_limite_cambia_al_cambiar_de_plan(client_por_peticion, db_session, dos_empresas, basico):
    basico.crear_ok()
    basico.crear_ok()
    assert basico.crear().status_code == 409

    _cambiar_plan_de_la_empresa(db_session, dos_empresas.b.id, "profesional")
    assert basico.crear().status_code == 201  # ahora rige el límite de 10

    # Volver a Básico no desactiva nada: tiene 3 y solo se bloquean las nuevas.
    _cambiar_plan_de_la_empresa(db_session, dos_empresas.b.id, "basico")
    respuesta = basico.crear()
    assert respuesta.status_code == 409
    assert (respuesta.json()["limite"], respuesta.json()["actual"]) == (2, 3)
    activas = client_por_peticion.get(RUTA, headers=dos_empresas.b.headers).json()
    assert len([s for s in activas if s["activo"]]) == 3


def test_el_limite_es_configurable_en_la_tabla_del_plan(db_session, basico):
    basico.crear_ok()
    basico.crear_ok()
    assert basico.crear().status_code == 409

    _limite_del_plan(db_session, "basico", 3)  # sin tocar el código

    assert basico.crear().status_code == 201
    respuesta = basico.crear()
    assert respuesta.status_code == 409
    assert (respuesta.json()["limite"], respuesta.json()["actual"]) == (3, 3)


def test_editar_una_sucursal_ya_activa_no_cuenta_contra_el_limite(basico):
    primera = basico.crear_ok()
    basico.crear_ok()  # cupo lleno: 2 de 2

    assert basico.actualizar(primera, nombre="Renombrada").status_code == 200
    assert basico.actualizar(primera, activo=True).status_code == 200  # ya estaba activa
    assert basico.actualizar(primera, activo=False).status_code == 200  # desactivar nunca estorba


def test_el_limite_tambien_vale_para_el_caso_de_uso_sin_http(db_session, dos_empresas):
    with en_empresa(db_session, dos_empresas.b.id):
        ciudad = Ciudad(nombre="Ciudad de la prueba")
        db_session.add(ciudad)
        db_session.flush()
        ciudad_id = ciudad.id
        cu = GestionarSucursales()

        def alta(numero: int):
            return cu.crear(
                db_session, SucursalCrear(ciudad_id=ciudad_id, codigo=f"CU-{numero}", nombre="X", direccion="Y")
            )

        alta(1)
        alta(2)
        with pytest.raises(ErrorFuncional) as error:
            alta(3)

    assert error.value.status_code == 409
    assert error.value.codigo == "limite_plan_excedido"
    assert error.value.contexto == {"recurso": "sucursales", "limite": 2, "actual": 2, "plan": "basico"}

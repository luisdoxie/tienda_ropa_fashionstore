"""Suscripción y límite de sucursales bajo PostgreSQL real (E04).

SQLite no aplica `SELECT ... FOR UPDATE` ni hay concurrencia real: lo que
depende de eso se prueba acá.

- Dos altas simultáneas de sucursal con un solo cupo: exactamente una entra.
- El índice único parcial rechaza una segunda suscripción vigente.
- La tarea de vencimiento actúa sobre todas las empresas.

(El cambio de plan simultáneo llega con el endpoint del superadministrador.)"""

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ErrorFuncional
from app.core.tenant import sin_filtro
from app.plataforma import politicas
from app.plataforma.models import Ciudad, Empresa, Plan, Sucursal, Suscripcion
from app.plataforma.repository import SucursalRepository
from app.plataforma.schemas import SucursalCrear

from .paralelo import ejecutar_en_paralelo


def _cupo_de_uno(fabrica) -> int:
    """Deja al plan de 'fashionstore' con exactamente UN cupo libre de sucursales
    (límite = activas + 1) y devuelve el id de una ciudad para las altas."""
    with fabrica() as db:
        ciudad = Ciudad(nombre="Ciudad PG límite")
        db.add(ciudad)
        db.flush()
        activas = politicas.contar_sucursales_activas(db)
        suscripcion = politicas.obtener_suscripcion_vigente(db)
        db.get(Plan, suscripcion.plan_id).max_sucursales = activas + 1
        ciudad_id = ciudad.id
        db.commit()
    return ciudad_id


def _alta(ciudad_id: int, codigo: str):
    def operacion(db):
        return SucursalRepository().crear(
            db, SucursalCrear(ciudad_id=ciudad_id, codigo=codigo, nombre=codigo, direccion="Av. 1")
        ).id

    return operacion


def test_dos_altas_simultaneas_de_sucursal_con_un_solo_cupo_dejan_exactamente_una(fabrica_pg):
    for ronda in range(5):
        ciudad_id = _cupo_de_uno(fabrica_pg)
        with fabrica_pg() as db:
            antes = politicas.contar_sucursales_activas(db)

        resultados = ejecutar_en_paralelo(
            fabrica_pg, [_alta(ciudad_id, f"PG-{ronda}-A"), _alta(ciudad_id, f"PG-{ronda}-B")]
        )

        exitos = [r for r in resultados if r.ok]
        fallos = [r for r in resultados if not r.ok]
        assert len(exitos) == 1, [repr(r.error) for r in resultados]
        assert len(fallos) == 1
        assert isinstance(fallos[0].error, ErrorFuncional), repr(fallos[0].error)
        assert fallos[0].error.codigo == "limite_plan_excedido"
        assert fallos[0].error.status_code == 409
        with fabrica_pg() as db:
            assert politicas.contar_sucursales_activas(db) == antes + 1  # nunca por encima del límite


def test_el_indice_parcial_rechaza_una_segunda_suscripcion_vigente(fabrica_pg):
    with fabrica_pg() as db:
        plan_id = db.scalar(select(Plan.id).where(Plan.codigo == "basico"))
        empresa_id = db.scalar(select(Empresa.id).where(Empresa.codigo == "fashionstore"))
        hoy = dt.date.today()
        db.add(
            Suscripcion(
                empresa_id=empresa_id, plan_id=plan_id, estado="suspendida",
                fecha_inicio=hoy, fecha_vencimiento=hoy + dt.timedelta(days=10),
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()  # 'fashionstore' ya tiene una activa: no puede haber otra vigente
        db.rollback()

    # Una cancelada (historial) sí cabe junto a la vigente.
    with fabrica_pg() as db:
        db.add(
            Suscripcion(
                empresa_id=empresa_id, plan_id=plan_id, estado="cancelada",
                fecha_inicio=hoy - dt.timedelta(days=60), fecha_vencimiento=hoy - dt.timedelta(days=30),
            )
        )
        db.commit()
        assert db.scalar(select(func.count(Suscripcion.id)).where(Suscripcion.estado == "cancelada")) == 1


def test_dos_cambios_de_plan_simultaneos_dejan_una_sola_suscripcion_vigente(engine_pg, fabrica_pg):
    from app.core.exceptions import DomainError
    from app.core.tenant import fijar_plataforma
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarSuscripciones
    from app.plataforma.schemas import SuscripcionAsignar

    hoy = dt.date.today()
    fabrica_sin_empresa = sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)
    with fabrica_sin_empresa() as db:
        profesional = db.scalar(select(Plan.id).where(Plan.codigo == "profesional"))
        empresa = Empresa(nombre="PG cambio de plan", codigo="pg-cambio-plan")
        db.add(empresa)
        db.flush()
        empresa_id = empresa.id
        db.add(
            Suscripcion(
                empresa_id=empresa_id, plan_id=profesional, estado="activa",
                fecha_inicio=hoy, fecha_vencimiento=hoy + dt.timedelta(days=60),
            )
        )
        db.commit()

    def cambiar_a_basico(db):
        fijar_plataforma(db)  # el superadministrador: sin empresa en la sesión
        return GestionarSuscripciones().asignar_o_cambiar_plan(
            db, SuscripcionAsignar(empresa_id=empresa_id, plan_codigo="basico")
        ).id

    resultados = ejecutar_en_paralelo(fabrica_pg, [cambiar_a_basico, cambiar_a_basico])

    exitos = [r for r in resultados if r.ok]
    fallos = [r for r in resultados if not r.ok]
    assert len(exitos) == 1, [repr(r.error) for r in resultados]
    assert len(fallos) == 1 and isinstance(fallos[0].error, DomainError), repr(fallos[0].error)
    assert fallos[0].error.status_code in (404, 409)
    with fabrica_sin_empresa() as db:
        filas = list(
            db.scalars(sin_filtro(select(Suscripcion).where(Suscripcion.empresa_id == empresa_id).order_by(Suscripcion.id)))
        )
        assert [f.estado for f in filas] == ["cancelada", "activa"]  # nunca dos vigentes


def test_la_tarea_de_vencimiento_actua_sobre_todas_las_empresas(engine_pg):
    hoy = dt.date.today()
    # Sesión SIN empresa fijada (la que usa la tarea periódica): puede dar de alta
    # empresas y suscripciones ajenas con su empresa_id explícito.
    fabrica_sin_empresa = sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)
    with fabrica_sin_empresa() as db:
        plan_id = db.scalar(select(Plan.id).where(Plan.codigo == "basico"))
        creadas = {}
        for codigo, vencimiento in (("pg-vencida-1", hoy - dt.timedelta(days=3)), ("pg-vencida-2", hoy - dt.timedelta(days=1)),
                                    ("pg-vigente", hoy + dt.timedelta(days=30))):
            empresa = Empresa(nombre=codigo, codigo=codigo)
            db.add(empresa)
            db.flush()
            db.add(
                Suscripcion(
                    empresa_id=empresa.id, plan_id=plan_id, estado="activa",
                    fecha_inicio=hoy - dt.timedelta(days=40), fecha_vencimiento=vencimiento,
                )
            )
            creadas[codigo] = empresa.id
        db.commit()

        cambiadas = politicas.vencer_suscripciones(db)

        assert cambiadas == 2
        estados = dict(
            db.execute(
                sin_filtro(select(Suscripcion.empresa_id, Suscripcion.estado).where(Suscripcion.empresa_id.in_(creadas.values())))
            ).all()
        )
        assert estados == {
            creadas["pg-vencida-1"]: "vencida",
            creadas["pg-vencida-2"]: "vencida",
            creadas["pg-vigente"]: "activa",
        }
        assert politicas.vencer_suscripciones(db) == 0  # idempotente

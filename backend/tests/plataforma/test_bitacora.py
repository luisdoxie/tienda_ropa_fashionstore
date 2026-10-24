"""E06: la bitácora de auditoría. Aquí, la función `registrar_bitacora`, la
consulta paginada y la purga; los eventos enganchados están en
`test_bitacora_eventos.py` y el aislamiento entre empresas en
`test_bitacora_aislamiento.py`."""

import datetime as dt
import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.auditoria import ACCION_CREAR, ENTIDAD_USUARIO, ContextoAuditoria
from app.core.tenant import empresa_de, en_empresa, fijar_empresa, fijar_plataforma
from app.plataforma import politicas
from app.plataforma.models import Bitacora, Ciudad, Usuario
from tests.conftest import crear_empresa

API = "/api/v1"
TOKEN_DE_SERVICIO = {"X-Service-Token": "token-de-pruebas"}  # TAREAS_TOKEN de tests/conftest.py


def _filas(db) -> list[Bitacora]:
    return list(db.scalars(select(Bitacora).order_by(Bitacora.id)))


def _sembrar(db, cantidad: int, *, empresa_id: int, entidad: str = "usuario", accion: str = "crear",
             usuario_id: int | None = None, desde: dt.datetime | None = None) -> list[int]:
    """Filas de bitácora con `creado_en` controlado (una por hora hacia atrás)."""
    base = desde or dt.datetime(2026, 10, 20, 12, 0, 0)
    ids = []
    for i in range(cantidad):
        fila = Bitacora(
            empresa_id=empresa_id, usuario_id=usuario_id, entidad=entidad, entidad_id=i, accion=accion,
            creado_en=base - dt.timedelta(hours=i),
        )
        db.add(fila)
        db.flush()
        ids.append(fila.id)
    db.commit()
    return ids


# ---- registrar_bitacora ----


def test_registrar_escribe_la_fila_con_empresa_usuario_e_ip(db_session):
    empresa = empresa_de(db_session)
    fila = politicas.registrar_bitacora(
        db_session, None, ENTIDAD_USUARIO, 7, ACCION_CREAR, {"reactivado": False}, "10.0.0.5"
    )
    assert fila is not None and fila.id is not None  # ya está volcada (flush)
    assert (fila.empresa_id, fila.usuario_id, fila.entidad, fila.entidad_id, fila.accion) == (
        empresa, None, "usuario", 7, "crear",
    )
    assert fila.datos == {"reactivado": False} and fila.ip == "10.0.0.5"


def test_registrar_bitacora_de_con_contexto_y_sin_contexto(db_session):
    contexto = ContextoAuditoria(usuario_id=None, empresa_id=empresa_de(db_session), ip="1.2.3.4")
    fila = politicas.registrar_bitacora_de(db_session, contexto, "rol", 3, "crear")
    assert fila is not None and fila.ip == "1.2.3.4"
    assert politicas.registrar_bitacora_de(db_session, None, "rol", 3, "crear") is None
    assert len(_filas(db_session)) == 1


def test_el_rollback_del_llamador_se_lleva_la_fila(db_session):
    politicas.registrar_bitacora(db_session, None, "usuario", 1, "crear")
    db_session.rollback()
    assert _filas(db_session) == []


def test_la_fila_queda_en_el_mismo_commit_del_cambio_auditado(db_session):
    politicas.registrar_bitacora(db_session, None, "usuario", 1, "crear")
    db_session.commit()
    db_session.expire_all()
    assert len(_filas(db_session)) == 1


def test_no_confirma_el_trabajo_pendiente_del_llamador(db_session):
    db_session.add(Ciudad(nombre="Ciudad pendiente"))
    politicas.registrar_bitacora(db_session, None, "ciudad", None, "crear")
    db_session.rollback()  # si registrar hubiera hecho commit, la ciudad sobreviviría
    assert db_session.scalar(select(func.count()).select_from(Ciudad).where(Ciudad.nombre == "Ciudad pendiente")) == 0
    assert _filas(db_session) == []


def test_un_error_de_datos_del_llamador_se_propaga_y_no_se_traga(db_session):
    # Dos usuarios con el mismo correo en la misma empresa chocan en el flush.
    for _ in range(2):
        db_session.add(Usuario(nombre="A", apellido="B", email="repetido@example.com", password_hash="x"))
    with pytest.raises(IntegrityError):
        politicas.registrar_bitacora(db_session, None, "ciudad", None, "crear")
    db_session.rollback()


def test_si_el_insert_falla_devuelve_none_deja_el_trabajo_intacto_y_registra_el_error(
    db_session, monkeypatch, caplog
):
    def _falla(self, db, fila):
        raise RuntimeError("tabla caída")

    monkeypatch.setattr(politicas.BitacoraRepository, "crear", _falla)
    db_session.add(Ciudad(nombre="Sobrevive"))
    with caplog.at_level(logging.ERROR, logger=politicas.logger.name):
        resultado = politicas.registrar_bitacora(db_session, None, "ciudad", None, "crear")
    assert resultado is None
    assert any("No se pudo registrar en la bitácora" in r.message for r in caplog.records)
    assert any(r.exc_info for r in caplog.records)  # logger.exception: lleva la traza
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Ciudad).where(Ciudad.nombre == "Sobrevive")) == 1


def test_un_fallo_despues_de_volcar_la_fila_revierte_solo_la_fila_de_bitacora(db_session, monkeypatch):
    def _vuelca_y_falla(self, db, fila):
        db.add(fila)
        db.flush()
        raise RuntimeError("falló justo después del INSERT")

    monkeypatch.setattr(politicas.BitacoraRepository, "crear", _vuelca_y_falla)
    db_session.add(Ciudad(nombre="Se queda"))
    assert politicas.registrar_bitacora(db_session, None, "ciudad", None, "crear") is None
    db_session.commit()
    assert _filas(db_session) == []  # el SAVEPOINT se llevó la fila a medias
    assert db_session.scalar(select(func.count()).select_from(Ciudad).where(Ciudad.nombre == "Se queda")) == 1


def test_datos_no_serializables_no_tumban_la_operacion(db_session):
    fila = politicas.registrar_bitacora(db_session, None, "venta", 1, "anular_pago", {"cosa": object(), "d": {1, 2}})
    assert fila is not None
    assert isinstance(fila.datos["cosa"], str) and fila.datos["d"] == [1, 2]


def test_registrar_nunca_guarda_secretos_ni_datos_personales_aunque_el_llamador_los_pase(db_session):
    fila = politicas.registrar_bitacora(
        db_session, None, "usuario", 1, "crear",
        {"password": "claveSegura123", "email": "persona@example.com", "telefono": "70000000", "campos": ["activo"]},
    )
    assert fila.datos == {
        "password": "[omitido]", "email": "[omitido]", "telefono": "[omitido]", "campos": ["activo"],
    }


def test_la_bitacora_es_de_solo_anexar(db_session):
    fila = politicas.registrar_bitacora(db_session, None, "usuario", 1, "crear")
    db_session.commit()
    fila.accion = "otra"
    with pytest.raises(RuntimeError, match="solo anexar"):
        db_session.flush()
    db_session.rollback()
    fila = _filas(db_session)[0]
    db_session.delete(fila)
    with pytest.raises(RuntimeError, match="solo anexar"):
        db_session.flush()
    db_session.rollback()
    assert len(_filas(db_session)) == 1


def test_una_accion_de_cuarenta_letras_entra(db_session):
    accion = "a" * 40
    assert politicas.registrar_bitacora(db_session, None, "usuario", 1, accion).accion == accion


def test_en_una_sesion_de_empresa_el_argumento_empresa_id_ajeno_se_ignora(db_session):
    otra = crear_empresa(db_session, "otra-tienda")
    propia = empresa_de(db_session)
    fila = politicas.registrar_bitacora(db_session, None, "usuario", 1, "crear", empresa_id=otra.id)
    assert fila.empresa_id == propia != otra.id


def test_sin_empresa_en_la_sesion_se_usa_el_argumento_o_null(db_session):
    otra_id = crear_empresa(db_session, "otra-tienda").id
    fijar_plataforma(db_session)
    con_empresa = politicas.registrar_bitacora(db_session, None, "suscripcion", 1, "cambiar_plan", empresa_id=otra_id)
    sin_empresa = politicas.registrar_bitacora(db_session, None, "sesion", None, "login_fallido")
    assert (con_empresa.empresa_id, sin_empresa.empresa_id) == (otra_id, None)


def test_dentro_de_en_empresa_manda_la_empresa_de_ese_bloque(db_session):
    otra_id = crear_empresa(db_session, "otra-tienda").id
    fijar_plataforma(db_session)
    with en_empresa(db_session, otra_id):
        fila = politicas.registrar_bitacora(db_session, None, "usuario", 1, "crear", empresa_id=999)
    assert fila.empresa_id == otra_id


# ---- consulta ----


def test_la_consulta_pagina_ordena_y_cuenta(client, admin_headers, db_session):
    empresa = empresa_de(db_session)
    _sembrar(db_session, 45, empresa_id=empresa, entidad="paginada")  # el login de `admin_headers` deja otra fila
    desde = "2026-10-01"
    paginas = [
        client.get(
            f"{API}/bitacora?desde={desde}&hasta=2026-10-31&entidad=paginada&tamanio=20&pagina={p}", headers=admin_headers
        ).json()
        for p in (1, 2, 3)
    ]
    assert [len(p["items"]) for p in paginas] == [20, 20, 5]
    assert all(p["total"] == 45 and p["tamanio"] == 20 for p in paginas)
    fechas = [item["creado_en"] for p in paginas for item in p["items"]]
    assert fechas == sorted(fechas, reverse=True)  # más reciente primero


def test_filtros_por_entidad_accion_usuario_y_combinados(client, admin_headers, db_session):
    empresa = empresa_de(db_session)
    usuario_id = db_session.scalar(select(Usuario.id).limit(1))
    # Entidades propias de la prueba: el login de `admin_headers` ya dejó una fila de `sesion`.
    _sembrar(db_session, 3, empresa_id=empresa, entidad="e-uno", accion="crear")
    _sembrar(db_session, 2, empresa_id=empresa, entidad="e-dos", accion="crear", usuario_id=usuario_id)
    _sembrar(db_session, 4, empresa_id=empresa, entidad="e-dos", accion="actualizar")
    rango = "desde=2026-10-01&hasta=2026-10-31"

    def total(extra: str) -> int:
        return client.get(f"{API}/bitacora?{rango}&{extra}", headers=admin_headers).json()["total"]

    assert total("entidad=e-dos") == 6
    assert total("accion=actualizar") == 4
    assert total(f"usuario_id={usuario_id}&entidad=e-dos") == 2
    assert total("entidad=e-dos&accion=crear") == 2
    assert total("entidad=e-uno&accion=actualizar") == 0


def test_las_fechas_desde_y_hasta_son_inclusivas(client, admin_headers, db_session):
    empresa = empresa_de(db_session)
    for instante in (
        dt.datetime(2026, 10, 9, 23, 59, 59),
        dt.datetime(2026, 10, 10, 0, 0, 0),
        dt.datetime(2026, 10, 12, 23, 59, 59),
        dt.datetime(2026, 10, 13, 0, 0, 0),
    ):
        db_session.add(Bitacora(empresa_id=empresa, entidad="usuario", accion="crear", creado_en=instante))
    db_session.commit()
    cuerpo = client.get(f"{API}/bitacora?desde=2026-10-10&hasta=2026-10-12", headers=admin_headers).json()
    assert cuerpo["total"] == 2


def test_rango_invertido_da_400_y_tamanio_mayor_a_100_da_422(client, admin_headers):
    assert client.get(f"{API}/bitacora?desde=2026-10-20&hasta=2026-10-01", headers=admin_headers).status_code == 400
    assert client.get(f"{API}/bitacora?tamanio=101", headers=admin_headers).status_code == 422


def test_detalle_404_y_permisos(client, admin_headers, cliente_headers, db_session):
    empresa = empresa_de(db_session)
    [bitacora_id] = _sembrar(db_session, 1, empresa_id=empresa)
    assert client.get(f"{API}/bitacora/{bitacora_id}", headers=admin_headers).status_code == 200
    assert client.get(f"{API}/bitacora/999999", headers=admin_headers).status_code == 404
    assert client.get(f"{API}/bitacora", headers=cliente_headers).status_code == 403
    assert client.get(f"{API}/bitacora").status_code == 401


# ---- purga ----


def test_purgar_borra_solo_lo_anterior_al_limite_por_lotes_y_deja_constancia(db_session):
    empresa = empresa_de(db_session)
    ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for dias in (400, 380, 370, 10, 1):
        db_session.add(Bitacora(empresa_id=empresa, entidad="usuario", accion="crear", creado_en=ahora - dt.timedelta(days=dias)))
    db_session.commit()
    fijar_empresa(db_session, None)  # la tarea corre con el token de servicio: sin empresa
    borradas = politicas.purgar_bitacora(db_session, retencion_dias=365, lote=2)
    assert borradas == 3
    restantes = _filas(db_session)
    assert [f.accion for f in restantes] == ["crear", "crear", "purgar"]
    constancia = restantes[-1]
    assert (constancia.empresa_id, constancia.usuario_id, constancia.entidad) == (None, None, "bitacora")
    assert constancia.datos["filas"] == 3 and "hasta" in constancia.datos


def test_el_endpoint_de_purga_exige_el_token_de_servicio(client_por_peticion, db_session):
    assert client_por_peticion.post(f"{API}/tareas/purgar-bitacora").status_code in (401, 403)
    respuesta = client_por_peticion.post(f"{API}/tareas/purgar-bitacora", headers=TOKEN_DE_SERVICIO)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"eliminadas": 0}

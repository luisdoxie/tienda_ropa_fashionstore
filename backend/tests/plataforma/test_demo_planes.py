"""E04: la secuencia de la prueba manual guiada. Se corre con `-s` para ver lo
que imprime:

    python -m pytest -q -p no:cacheprovider -s tests/plataforma/test_demo_planes.py
"""

import datetime as dt

import pytest
from sqlalchemy import text

from app.core.rate_limit import limiter
from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.inteligencia.schemas import FiltrosReporteVoz
from tests.plataforma.ayudas_empresas import CLAVE, PLATAFORMA, registrar

MODULO_CU = "app.inteligencia.casos_uso.cu23_generar_reportes_con_ia"
API = "/api/v1"


class _InterpreteFalso:
    def parsear(self, texto):
        return FiltrosReporteVoz(tipo_reporte="reservas")


def _sucursal(client, headers, ciudad_id: int, numero: int):
    return client.post(
        f"{API}/sucursales",
        json={"ciudad_id": ciudad_id, "codigo": f"BA-{numero}", "nombre": f"Boutique {numero}", "direccion": "Av. 1"},
        headers=headers,
    )


def test_demo_planes_y_suscripciones(client_por_peticion, db_session, superadmin_headers, monkeypatch):
    cliente = client_por_peticion
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db_session.commit()
    monkeypatch.setattr(f"{MODULO_CU}.obtener_parser_reporte_voz", lambda: _InterpreteFalso())

    print("\n1. El superadministrador registra 'Boutique Andina' (plan Básico):")
    registro = registrar(cliente, superadmin_headers, "Boutique Andina", "ana@boutiqueandina.example.com")
    print("   ->", registro.status_code, {k: registro.json()[k] for k in ("codigo", "plan_codigo", "suscripcion_estado")})
    assert registro.status_code == 201
    empresa_id = registro.json()["id"]

    print("2. Su administrador entra con (nombre de empresa, correo, clave):")
    entrada = cliente.post(
        f"{API}/auth/login",
        json={"empresa": "Boutique Andina", "email": "ana@boutiqueandina.example.com", "password": CLAVE},
    )
    print("   ->", entrada.status_code)
    assert entrada.status_code == 200
    admin = {"Authorization": f"Bearer {entrada.json()['access_token']}"}

    print("3. Crea 2 sucursales y la 3.ª recibe limite_plan_excedido:")
    ciudad_id = cliente.get(f"{API}/ciudades", headers=admin).json()[0]["id"]
    assert _sucursal(cliente, admin, ciudad_id, 1).status_code == 201
    assert _sucursal(cliente, admin, ciudad_id, 2).status_code == 201
    tercera = _sucursal(cliente, admin, ciudad_id, 3)
    print("   ->", tercera.status_code, {k: tercera.json().get(k) for k in ("codigo", "limite", "actual", "plan")})
    assert tercera.status_code == 409 and tercera.json()["codigo"] == "limite_plan_excedido"

    print("4. POST /ia/reporte-voz en Básico:")
    limiter.reset()
    reporte = cliente.post(f"{API}/ia/reporte-voz", json={"texto": "reservas"}, headers=admin)
    print("   ->", reporte.status_code, reporte.json().get("codigo"))
    assert reporte.status_code == 403 and reporte.json()["codigo"] == "plan_no_incluye_funcionalidad"

    print("5. El superadministrador cambia a Profesional: ahora pasa y admite más sucursales:")
    cambio = cliente.post(
        f"{PLATAFORMA}/suscripciones",
        json={"empresa_id": empresa_id, "plan_codigo": "profesional"},
        headers=superadmin_headers,
    )
    assert cambio.status_code == 201
    reporte = cliente.post(f"{API}/ia/reporte-voz", json={"texto": "reservas"}, headers=admin)
    tercera = _sucursal(cliente, admin, ciudad_id, 3)
    print("   -> reporte", reporte.status_code, "| tercera sucursal", tercera.status_code)
    assert reporte.status_code == 200 and tercera.status_code == 201

    print("6. Lo suspende: su administrador recibe suscripcion_no_activa pero /mi-empresa responde:")
    suscripcion_id = cambio.json()["id"]
    suspendida = cliente.put(f"{PLATAFORMA}/suscripciones/{suscripcion_id}/estado", json={"estado": "suspendida"}, headers=superadmin_headers)
    assert suspendida.status_code == 200
    bloqueada = cliente.get(f"{API}/sucursales", headers=admin)
    mi_empresa = cliente.get(f"{API}/mi-empresa/suscripcion", headers=admin)
    print("   ->", bloqueada.status_code, bloqueada.json().get("codigo"), "| /mi-empresa", mi_empresa.status_code, mi_empresa.json()["estado"])
    assert bloqueada.status_code == 403 and bloqueada.json()["codigo"] == "suscripcion_no_activa"
    assert mi_empresa.status_code == 200

    print("7. Se renueva y todo vuelve:")
    nueva_fecha = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    renovada = cliente.put(f"{PLATAFORMA}/suscripciones/{suscripcion_id}/renovar", json={"fecha_vencimiento": nueva_fecha}, headers=superadmin_headers)
    reactivada = cliente.put(f"{PLATAFORMA}/suscripciones/{suscripcion_id}/estado", json={"estado": "activa"}, headers=superadmin_headers)
    vuelve = cliente.get(f"{API}/sucursales", headers=admin)
    print("   ->", renovada.status_code, reactivada.status_code, "| sucursales", vuelve.status_code)
    assert (renovada.status_code, reactivada.status_code, vuelve.status_code) == (200, 200, 200)

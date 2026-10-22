"""E04 / CU-04: las tiendas públicas (sin sesión). GET /public/tiendas lista las
empresas activas con suscripción activa, con solo cuatro campos; GET
/public/{codigo}/tienda da los mismos cuatro de una tienda. Usan
`client_por_peticion` y `dos_empresas` (A = 'tienda-a', B = 'tienda-b'; la
empresa 'fashionstore' de las semillas también cuenta)."""

import datetime as dt

from sqlalchemy import update

from app.core.tenant import sin_filtro
from app.plataforma.models import Suscripcion
from tests.plataforma.ayudas_empresas import PLATAFORMA, registrar, suscripciones_de

TIENDAS = "/api/v1/public/tiendas"
CAMPOS = {"codigo", "nombre", "logo_url", "color_acento"}


def _codigos(respuesta) -> list[str]:
    assert respuesta.status_code == 200, respuesta.text
    return [t["codigo"] for t in respuesta.json()]


def test_lista_solo_empresas_activas_con_suscripcion_activa(
    client_por_peticion, db_session, dos_empresas, superadmin_headers
):
    assert _codigos(client_por_peticion.get(TIENDAS)) == ["fashionstore", "tienda-a", "tienda-b"]
    sub_b = suscripciones_de(db_session, dos_empresas.b.id)[0].id

    # Suscripción suspendida: desaparece. Al reactivarla, vuelve.
    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_b}/estado", json={"estado": "suspendida"}, headers=superadmin_headers)
    assert _codigos(client_por_peticion.get(TIENDAS)) == ["fashionstore", "tienda-a"]
    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_b}/estado", json={"estado": "activa"}, headers=superadmin_headers)
    assert "tienda-b" in _codigos(client_por_peticion.get(TIENDAS))

    # Empresa dada de baja: desaparece.
    client_por_peticion.delete(f"{PLATAFORMA}/empresas/{dos_empresas.a.id}", headers=superadmin_headers)
    assert _codigos(client_por_peticion.get(TIENDAS)) == ["fashionstore", "tienda-b"]

    # Vencida por fecha (sin correr la tarea): desaparece.
    ayer = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(
            update(Suscripcion).where(Suscripcion.id == sub_b).values(fecha_inicio=ayer - dt.timedelta(days=5), fecha_vencimiento=ayer)
        ),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()
    assert _codigos(client_por_peticion.get(TIENDAS)) == ["fashionstore"]


def test_una_suscripcion_cancelada_saca_la_tienda_de_la_lista(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    sub_a = suscripciones_de(db_session, dos_empresas.a.id)[0].id

    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_a}/estado", json={"estado": "cancelada"}, headers=superadmin_headers)

    assert "tienda-a" not in _codigos(client_por_peticion.get(TIENDAS))


def test_la_busqueda_q_filtra_por_nombre_o_codigo_sin_distinguir_mayusculas(
    client_por_peticion, dos_empresas, superadmin_headers
):
    registrar(client_por_peticion, superadmin_headers, nombre="Boutique Andina")

    assert _codigos(client_por_peticion.get(f"{TIENDAS}?q=ANDINA")) == ["boutique-andina"]
    assert _codigos(client_por_peticion.get(f"{TIENDAS}?q=tienda-")) == ["tienda-a", "tienda-b"]
    assert _codigos(client_por_peticion.get(f"{TIENDAS}?q=fashion")) == ["fashionstore"]
    assert _codigos(client_por_peticion.get(f"{TIENDAS}?q=no-existe")) == []


def test_paginacion_con_tamanio_maximo_de_50(client_por_peticion, dos_empresas):
    primera = client_por_peticion.get(f"{TIENDAS}?tamanio=2&pagina=1")
    segunda = client_por_peticion.get(f"{TIENDAS}?tamanio=2&pagina=2")
    todas = _codigos(client_por_peticion.get(TIENDAS))

    assert _codigos(primera) + _codigos(segunda) == todas
    assert len(_codigos(primera)) == 2 and len(_codigos(segunda)) == 1
    assert client_por_peticion.get(f"{TIENDAS}?tamanio=50").status_code == 200
    assert client_por_peticion.get(f"{TIENDAS}?tamanio=51").status_code == 422
    assert client_por_peticion.get(f"{TIENDAS}?tamanio=0").status_code == 422
    assert client_por_peticion.get(f"{TIENDAS}?pagina=0").status_code == 422


def test_solo_publica_cuatro_campos_y_no_pide_sesion(client_por_peticion, dos_empresas, superadmin_headers):
    registrar(client_por_peticion, superadmin_headers, nombre="Boutique Andina", color_acento="#9A3E1F", logo_url="https://x.example.com/l.png")

    respuesta = client_por_peticion.get(f"{TIENDAS}?q=andina")

    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {"codigo": "boutique-andina", "nombre": "Boutique Andina", "logo_url": "https://x.example.com/l.png", "color_acento": "#9A3E1F"}
    ]
    for tienda in client_por_peticion.get(TIENDAS).json():
        assert set(tienda) == CAMPOS


def test_los_datos_publicos_de_una_tienda(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    respuesta = client_por_peticion.get("/api/v1/public/tienda-a/tienda")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "codigo": "tienda-a", "nombre": "tienda-a", "logo_url": None, "color_acento": None, "disponible": True,
    }
    assert client_por_peticion.get("/api/v1/public/no-existe/tienda").status_code == 404
    # Con la suscripción suspendida los datos de la tienda siguen públicos (la
    # pantalla muestra "Tienda no disponible"), pero el resto de la tienda se bloquea.
    sub_a = suscripciones_de(db_session, dos_empresas.a.id)[0].id
    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_a}/estado", json={"estado": "suspendida"}, headers=superadmin_headers)
    suspendida = client_por_peticion.get("/api/v1/public/tienda-a/tienda")
    assert suspendida.status_code == 200
    assert suspendida.json()["disponible"] is False  # la web muestra "no disponible" con esta señal
    # Reactivada, vuelve a estar disponible.
    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_a}/estado", json={"estado": "activa"}, headers=superadmin_headers)
    assert client_por_peticion.get("/api/v1/public/tienda-a/tienda").json()["disponible"] is True
    client_por_peticion.put(f"{PLATAFORMA}/suscripciones/{sub_a}/estado", json={"estado": "suspendida"}, headers=superadmin_headers)
    assert client_por_peticion.get("/api/v1/public/tienda-a/sucursales").status_code == 403
    # Una empresa dada de baja responde 404, igual que una inexistente.
    client_por_peticion.delete(f"{PLATAFORMA}/empresas/{dos_empresas.b.id}", headers=superadmin_headers)
    assert client_por_peticion.get("/api/v1/public/tienda-b/tienda").status_code == 404


def test_limite_de_trafico_de_60_por_minuto(client_por_peticion):
    for _ in range(60):
        assert client_por_peticion.get(TIENDAS).status_code == 200

    excedida = client_por_peticion.get(TIENDAS)

    assert excedida.status_code == 429
    # Las rutas de una tienda tienen su propio balde.
    assert client_por_peticion.get("/api/v1/public/fashionstore/tienda").status_code == 200

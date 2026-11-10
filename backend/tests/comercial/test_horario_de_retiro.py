"""Cuándo se puede retirar una compra: el comprador recibe dónde y a partir de qué hora, según el horario que el
administrador definió POR DÍA en la sucursal (un lunes puede abrir a las 07:00 y un martes a las 09:00; un día sin
horario no atiende). El cálculo es una función pura (`calcular_ventana_de_retiro`) y se prueba con fechas fijas; el
resto prueba que el aviso, el correo y el comprobante lo llevan solo en una compra de retiro. Brevo y FCM simulados."""

import datetime as dt
from types import SimpleNamespace

import pytest

from app.comercial.politicas import construir_correo_compra_confirmada
from app.core.tiempo import ZONA_BOLIVIA
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import calcular_ventana_de_retiro, describir_ventana_de_retiro
from tests.comercial.test_compra_confirmada import (  # noqa: F401  (el fixture `avisos` se reutiliza)
    _avisos_de_compra,
    _cliente_id,
    _cobrar_en_caja,
    _iniciar,
    _venta_digital,
    _venta_en_caja,
    _webhook,
    avisos,
)
from tests.comercial.test_pagos import contexto  # noqa: F401

# 2026-11-08 es domingo, 2026-11-09 lunes, 2026-11-10 martes.
DOMINGO, LUNES, MARTES = dt.date(2026, 11, 8), dt.date(2026, 11, 9), dt.date(2026, 11, 10)


def _a_las(dia: dt.date, hora: int, minuto: int = 0) -> dt.datetime:
    return dt.datetime.combine(dia, dt.time(hora, minuto), tzinfo=ZONA_BOLIVIA)


def _horario(dia_semana: int, apertura: str, cierre: str) -> SimpleNamespace:
    return SimpleNamespace(
        dia_semana=dia_semana, hora_apertura=dt.time.fromisoformat(apertura), hora_cierre=dt.time.fromisoformat(cierre)
    )


# Lunes 07:00 a 21:00, martes 09:00 a 19:00; el domingo no hay horario (no atiende).
HORARIOS = [_horario(1, "07:00", "21:00"), _horario(2, "09:00", "19:00")]


def _texto(ahora: dt.datetime, horarios=HORARIOS) -> str | None:
    ventana = calcular_ventana_de_retiro(horarios, ahora)
    return None if ventana is None else describir_ventana_de_retiro(ventana)


# ---- el cálculo, con el horario de cada día ----


def test_un_domingo_sin_horario_se_pasa_el_lunes_desde_que_abre():
    assert _texto(_a_las(DOMINGO, 10)) == "el lunes 09/11, desde las 07:00 hasta las 21:00"


def test_el_lunes_con_la_sucursal_abierta_se_puede_pasar_hoy_hasta_que_cierra():
    assert _texto(_a_las(LUNES, 12, 30)) == "hoy, hasta las 21:00"


def test_el_lunes_antes_de_abrir_se_pasa_hoy_a_partir_de_la_hora_de_apertura():
    assert _texto(_a_las(LUNES, 6, 15)) == "hoy, desde las 07:00 hasta las 21:00"


def test_el_lunes_despues_de_cerrar_se_pasa_el_martes_con_el_horario_del_martes():
    assert _texto(_a_las(LUNES, 21, 30)) == "el martes 10/11, desde las 09:00 hasta las 19:00"


def test_a_la_hora_exacta_de_cierre_ya_esta_cerrado():
    assert _texto(_a_las(LUNES, 21, 0)) == "el martes 10/11, desde las 09:00 hasta las 19:00"
    assert _texto(_a_las(LUNES, 20, 59)) == "hoy, hasta las 21:00"


def test_a_la_hora_exacta_de_apertura_ya_esta_abierto():
    assert _texto(_a_las(LUNES, 7, 0)) == "hoy, hasta las 21:00"


def test_si_solo_se_atiende_un_dia_y_ya_cerro_vuelve_el_mismo_dia_de_la_semana_siguiente():
    solo_lunes = [_horario(1, "07:00", "21:00")]
    assert _texto(_a_las(LUNES, 22), solo_lunes) == "el lunes 16/11, desde las 07:00 hasta las 21:00"


def test_el_martes_se_usa_el_horario_del_martes_no_el_del_lunes():
    assert _texto(_a_las(MARTES, 8)) == "hoy, desde las 09:00 hasta las 19:00"


def test_sin_ningun_horario_cargado_no_hay_ventana():
    assert calcular_ventana_de_retiro([], _a_las(LUNES, 10)) is None


def test_cambiar_el_horario_del_dia_cambia_lo_que_se_avisa():
    ampliado = [_horario(1, "06:00", "22:00"), _horario(2, "09:00", "19:00")]

    assert _texto(_a_las(DOMINGO, 10), ampliado) == "el lunes 09/11, desde las 06:00 hasta las 22:00"
    assert _texto(_a_las(LUNES, 21, 30), ampliado) == "hoy, hasta las 22:00"


# ---- la frase con la sucursal, leyendo el horario real de la base ----


def _poner_horarios(client, admin_headers, sucursal_id, horarios):
    for dia, apertura, cierre in horarios:
        respuesta = client.post(
            f"/api/v1/sucursales/{sucursal_id}/horarios",
            json={"dia_semana": dia, "hora_apertura": apertura, "hora_cierre": cierre},
            headers=admin_headers,
        )
        assert respuesta.status_code == 201, respuesta.text


def test_el_texto_dice_donde_y_usa_el_horario_que_define_el_administrador(
    client, db_session, admin_headers, contexto
):
    _poner_horarios(client, admin_headers, contexto["sucursal_id"], [(1, "07:00:00", "21:00:00"), (2, "09:00:00", "19:00:00")])
    # 2026-11-08 14:00 UTC = domingo 10:00 en Bolivia.
    domingo = dt.datetime(2026, 11, 8, 14, 0, tzinfo=dt.timezone.utc)
    lunes_noche = dt.datetime(2026, 11, 10, 1, 30, tzinfo=dt.timezone.utc)  # lunes 21:30 en Bolivia

    assert (
        plataforma_politicas.texto_de_retiro(db_session, contexto["sucursal_id"], domingo)
        == "Retira en Sucursal Pago (Av. 1): el lunes 09/11, desde las 07:00 hasta las 21:00."
    )
    assert (
        plataforma_politicas.texto_de_retiro(db_session, contexto["sucursal_id"], lunes_noche)
        == "Retira en Sucursal Pago (Av. 1): el martes 10/11, desde las 09:00 hasta las 19:00."
    )


def test_una_sucursal_sin_horarios_solo_dice_donde_retirar(client, db_session, contexto):
    assert (
        plataforma_politicas.texto_de_retiro(db_session, contexto["sucursal_id"])
        == "Retira en Sucursal Pago (Av. 1)."
    )


# ---- la compra de retiro lo lleva en el aviso, el correo y el comprobante ----


def test_una_compra_de_retiro_avisa_donde_y_cuando_pasar(client, admin_headers, cliente_headers, contexto, avisos):
    _poner_horarios(client, admin_headers, contexto["sucursal_id"], [(d, "00:00:00", "23:59:00") for d in range(1, 8)])
    venta = _venta_digital(client, contexto, cliente_headers)
    inicio = _iniciar(client, cliente_headers, venta)

    assert _webhook(client, inicio["pago"]["referencia_externa"]).status_code == 200
    avisos.fcm.correr()

    (aviso,) = _avisos_de_compra(client, cliente_headers)
    assert aviso["mensaje"].startswith(f"Tu compra {venta['codigo']} por Bs 100.00 está pagada. Retira en Sucursal Pago (Av. 1):")
    (correo,) = avisos.brevo.enviados
    assert "Retira en Sucursal Pago (Av. 1):" in correo["htmlContent"]
    assert "Retira en Sucursal Pago (Av. 1):" in correo["textContent"]


def test_el_comprobante_trae_el_retiro_mientras_la_compra_esta_pagada(
    client, admin_headers, cliente_headers, contexto, avisos
):
    _poner_horarios(client, admin_headers, contexto["sucursal_id"], [(d, "00:00:00", "23:59:00") for d in range(1, 8)])
    venta = _venta_digital(client, contexto, cliente_headers)

    antes = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()
    assert antes["retiro"] is None  # sin pagar todavía no hay nada que retirar

    _webhook(client, _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"])
    pagada = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()

    assert pagada["estado"] == "pagada"
    assert pagada["retiro"].startswith("Retira en Sucursal Pago (Av. 1):")


def test_una_venta_en_caja_no_lleva_texto_de_retiro(client, db_session, cliente_headers, contexto, avisos):
    venta = _venta_en_caja(client, contexto, cliente_id=_cliente_id(db_session))
    _cobrar_en_caja(client, contexto, venta)
    avisos.fcm.correr()

    (aviso,) = _avisos_de_compra(client, cliente_headers)
    assert "Retira" not in aviso["mensaje"]  # la persona ya se llevó las prendas
    assert "Retira" not in avisos.brevo.enviados[0]["textContent"]
    assert client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()["retiro"] is None


def test_el_correo_sin_retiro_no_agrega_el_bloque():
    correo = construir_correo_compra_confirmada(
        para_email="a@example.com",
        nombre="Ana",
        nombre_empresa="Tienda",
        codigo_empresa="tienda",
        venta_id=1,
        codigo_venta="V-1",
        fecha=dt.datetime(2026, 11, 9, 15, 0),
        sucursal="Centro",
        lineas=[("Polera", 1)],
        subtotal=100,
        descuento=0,
        costo_envio=0,
        total=100,
    )
    assert "Retira" not in correo.texto and "Retira" not in correo.html


def test_el_texto_de_retiro_del_correo_se_escapa():
    correo = construir_correo_compra_confirmada(
        para_email="a@example.com",
        nombre="Ana",
        nombre_empresa="Tienda",
        codigo_empresa="tienda",
        venta_id=1,
        codigo_venta="V-1",
        fecha=dt.datetime(2026, 11, 9, 15, 0),
        sucursal="Centro",
        lineas=[("Polera", 1)],
        subtotal=100,
        descuento=0,
        costo_envio=0,
        total=100,
        retiro="Retira en <b>Centro</b>",
    )
    assert "&lt;b&gt;Centro&lt;/b&gt;" in correo.html and "<b>Centro</b>" not in correo.html
    assert "Retira en <b>Centro</b>" in correo.texto  # el texto plano va tal cual

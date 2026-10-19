"""comercial/pasarela.py: interpretar_webhook vive en PasarelaBase (antes estaba
copiado igual en las tres pasarelas)."""

import pytest

from app.comercial.pasarela import (
    LibelulaGateway,
    PasarelaBase,
    PayPalGateway,
    QrOnlineGateway,
    ResultadoWebhook,
    obtener_pasarela,
)

PASARELAS = ["libelula", "paypal", "qr_online"]


def test_interpretar_webhook_ya_no_es_abstracto_en_la_base():
    assert "interpretar_webhook" not in PasarelaBase.__abstractmethods__
    assert "interpretar_webhook" in vars(PasarelaBase)


@pytest.mark.parametrize("clase", [LibelulaGateway, PayPalGateway, QrOnlineGateway])
def test_ninguna_pasarela_sobreescribe_interpretar_webhook(clase):
    assert "interpretar_webhook" not in vars(clase)
    assert clase.interpretar_webhook is PasarelaBase.interpretar_webhook


@pytest.mark.parametrize("codigo", PASARELAS)
def test_interpretar_webhook_devuelve_id_y_estado_del_payload(codigo):
    pasarela = obtener_pasarela(codigo)

    resultado = pasarela.interpretar_webhook({"id_transaccion": "TX-1", "estado": "aprobado"})

    assert resultado == ResultadoWebhook(id_transaccion="TX-1", estado="aprobado")


@pytest.mark.parametrize("codigo", PASARELAS)
def test_interpretar_webhook_sin_campos_lanza_key_error(codigo):
    # comportamiento actual (se conserva): el payload sin id_transaccion/estado
    # revienta con KeyError; el caso de uso lo valida antes de llamar.
    with pytest.raises(KeyError):
        obtener_pasarela(codigo).interpretar_webhook({"estado": "aprobado"})

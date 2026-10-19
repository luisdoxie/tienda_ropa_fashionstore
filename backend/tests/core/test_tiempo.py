"""core/tiempo.py: hoy_utc y ahora_utc_naive viven acá y siguen importables
desde core/deps.py (donde estaban)."""

import datetime as dt

from app.core import deps, tiempo


def test_deps_reexporta_las_mismas_funciones():
    assert deps.hoy_utc is tiempo.hoy_utc
    assert deps.ahora_utc_naive is tiempo.ahora_utc_naive


def test_hoy_utc_es_la_fecha_utc():
    antes = dt.datetime.now(dt.timezone.utc).date()
    hoy = tiempo.hoy_utc()
    despues = dt.datetime.now(dt.timezone.utc).date()

    assert isinstance(hoy, dt.date) and not isinstance(hoy, dt.datetime)
    assert antes <= hoy <= despues


def test_ahora_utc_naive_no_tiene_zona_y_esta_en_utc():
    antes = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    ahora = tiempo.ahora_utc_naive()
    despues = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    assert ahora.tzinfo is None
    assert antes <= ahora <= despues


def test_periodo_reportes_usa_el_reloj_reexportado(monkeypatch):
    # periodo_reportes toma hoy_utc del espacio de nombres de deps: los tests
    # que lo parchean ahí siguen funcionando tras mover la función.
    monkeypatch.setattr(deps, "hoy_utc", lambda: dt.date(2026, 3, 31))

    periodo = deps.periodo_reportes(desde=None, hasta=None)

    assert periodo.hasta == dt.date(2026, 3, 31)
    assert periodo.desde == dt.date(2026, 3, 1)

"""Reloj en UTC: la única forma de pedir 'hoy' o 'ahora' en el backend."""

import datetime as dt


def hoy_utc() -> dt.date:
    """La fecha de hoy en UTC, NO la local del proceso.

    Las columnas contra las que se comparan estos períodos (`venta.fecha`,
    `probador_generacion.creado_en`) se graban con `server_default=func.now()`,
    es decir en UTC. Tomar el límite con `dt.date.today()` (fecha local del
    proceso) corre la ventana de consulta respecto de los datos siempre que
    el servidor no esté en UTC: con el reloj en UTC-4, una venta cobrada
    después de las 20:00 obtiene una `fecha` del día siguiente y queda fuera
    del período "hasta hoy".

    Vive en core/tiempo.py, y no en cada caso de uso, porque la necesitan `periodo_reportes`
    (reportes), CU-23 (reporte por voz) y CU-11 (cupo diario del probador).
    """
    return dt.datetime.now(dt.timezone.utc).date()


def ahora_utc_naive() -> dt.datetime:
    """El instante actual en UTC como datetime naive (sin tzinfo).

    Para comparar contra las columnas TIMESTAMP WITHOUT TIME ZONE con
    `server_default=func.now()` (`venta.fecha`, `evento.creado_en`...): la
    base las guarda en UTC y SQLAlchemy las devuelve naive, así que restar o
    comparar contra `dt.datetime.now()` (hora local del proceso) desfasa el
    resultado el offset del servidor si no corre en UTC."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

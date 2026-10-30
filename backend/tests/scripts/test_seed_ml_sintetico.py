"""Carga del historial sintético (`scripts.seed_ml_sintetico`, E11 paso 6): se escribe como datos reales de la
empresa pedida y de NINGUNA otra, es idempotente, no toca el stock, se reconoce por prefijos y respeta la regla de
descuento del sistema. SQLite en memoria; el historial es reducido (40 semanas, 80 clientes)."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select, text

from app.catalogo.models import MovimientoInventario, ProductoVariante, Stock
from app.comercial import politicas as comercial_politicas
from app.comercial.models import Devolucion, Pago, Promocion, Venta, VentaDetalle
from app.core.deps import ParametrosPeriodo
from app.core.security import verificar_password
from app.core.tenant import en_empresa
from app.inteligencia.ml import sintetico
from app.plataforma.models import Cliente, Usuario
from scripts import seed_ml_sintetico
from scripts.seed_ml_sintetico import PREFIJO_DEVOLUCION, PREFIJO_PROMOCION, PREFIJO_VENTA, cargar_historial, correo_cliente, main
from tests.inteligencia.ml._escenario import CLIENTES, FIN, SEMANAS, cargar_historia, crear_vista_de_ventas, id_de, poblar
from tests.scripts._prendas_falsas import crear_carpeta


@pytest.fixture()
def mundo(db_session, tmp_path):
    poblar(db_session, crear_carpeta(tmp_path))
    crear_vista_de_ventas(db_session)
    return db_session


def _contar(db, empresa_id, modelo, *condiciones) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def test_dry_run_no_escribe_nada_y_cuenta_lo_que_haria(mundo, capsys, monkeypatch):
    fs = id_de(mundo, "fashionstore")
    from app.core.tenant import fijar_empresa
    from app.plataforma.models import Empresa

    monkeypatch.setattr("scripts._empresa.abrir_sesion", lambda codigo=None: (mundo, fijar_y_devolver(mundo, fs)))

    def fijar_y_devolver(db, empresa_id):
        fijar_empresa(db, empresa_id)
        return db.get(Empresa, empresa_id)

    antes = (_contar(mundo, fs, Venta), _contar(mundo, fs, Usuario), _contar(mundo, fs, Promocion))
    main(["--empresa", "fashionstore", "--clientes", "80", "--semanas", "40", "--fin", FIN.isoformat()])
    salida = capsys.readouterr().out
    assert (_contar(mundo, fs, Venta), _contar(mundo, fs, Usuario), _contar(mundo, fs, Promocion)) == antes
    assert "dry-run" in salida and "ventas" in salida
    assert "sqlite" not in salida.lower() or ":memory:" in salida  # imprime el nombre de la base, nunca la URL
    assert "://" not in salida


def test_ejecutar_inserta_en_la_empresa_pedida_y_en_ninguna_otra(mundo):
    fs, catalogo, historial, resumen = cargar_historia(mundo, "fashionstore")
    ch = id_de(mundo, "chaski-sport")

    assert not resumen.ya_existia
    assert resumen.ventas == len(historial.ventas) == _contar(mundo, fs, Venta)
    assert resumen.lineas == sum(len(v.lineas) for v in historial.ventas) == _contar(mundo, fs, VentaDetalle)
    assert resumen.clientes == len(historial.clientes) == _contar(mundo, fs, Cliente, Cliente.usuario_id.in_(
        select(Usuario.id).where(Usuario.email.like("c%@sintetico.%"))))
    assert resumen.promociones == len(historial.promociones) and resumen.devoluciones > 0
    for modelo in (Venta, VentaDetalle, Pago, Devolucion, Promocion):
        assert _contar(mundo, ch, modelo) == 0, f"{modelo.__name__} apareció en otra empresa"
    assert _contar(mundo, ch, Usuario, Usuario.email.like("%@sintetico.%")) == 0


def test_una_segunda_corrida_no_duplica_nada(mundo):
    fs, catalogo, historial, _ = cargar_historia(mundo, "fashionstore")
    antes = [_contar(mundo, fs, m) for m in (Venta, VentaDetalle, Pago, Devolucion, Promocion, Usuario, Cliente)]
    with en_empresa(mundo, fs):
        segunda = cargar_historial(mundo, historial, catalogo, "fashionstore")
    assert segunda.ya_existia and segunda.ventas == 0
    assert [_contar(mundo, fs, m) for m in (Venta, VentaDetalle, Pago, Devolucion, Promocion, Usuario, Cliente)] == antes


def test_todo_lo_sintetico_se_reconoce_por_su_prefijo_sin_columnas_nuevas(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        assert all(c.startswith(PREFIJO_VENTA) and len(c) <= 20 for c in mundo.scalars(select(Venta.codigo)))
        assert all(c.startswith(PREFIJO_DEVOLUCION) for c in mundo.scalars(select(Devolucion.codigo)))
        assert all(n.startswith(PREFIJO_PROMOCION) for n in mundo.scalars(select(Promocion.nombre)))
        correos = set(mundo.scalars(select(Usuario.email).where(Usuario.email.like("c%@sintetico.%"))))
    assert correo_cliente("fashionstore", 7) in correos and all(c.endswith("@sintetico.fashionstore.fashionstore.bo") for c in correos)


def test_el_stock_y_el_kardex_quedan_identicos(mundo):
    fs = id_de(mundo, "fashionstore")

    def foto():
        with en_empresa(mundo, fs):
            filas = mundo.execute(select(Stock.variante_id, Stock.sucursal_id, Stock.cantidad_fisica, Stock.cantidad_reservada).order_by(Stock.id)).all()
            return filas, mundo.scalar(select(func.count()).select_from(MovimientoInventario))

    antes = foto()
    cargar_historia(mundo, "fashionstore")
    assert foto() == antes


def test_el_descuento_coincide_con_la_regla_de_calcular_linea_en_una_muestra_de_25_lineas(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        con_descuento = mundo.execute(
            select(VentaDetalle, Venta.fecha)
            .join(Venta, Venta.id == VentaDetalle.venta_id)
            .where(VentaDetalle.descuento_unitario > 0)
            .order_by(VentaDetalle.id)
        ).all()
        sin_descuento = mundo.execute(
            select(VentaDetalle, Venta.fecha).join(Venta, Venta.id == VentaDetalle.venta_id).where(VentaDetalle.descuento_unitario == 0).order_by(VentaDetalle.id)
        ).all()
        assert con_descuento, "el historial debe tener líneas con promoción"
        muestra = con_descuento[:: max(1, len(con_descuento) // 15)][:15] + sin_descuento[:: max(1, len(sin_descuento) // 10)][:10]
        assert len(muestra) >= 20
        for linea, fecha in muestra:
            variante = mundo.get(ProductoVariante, linea.variante_id)
            precio, descuento_unitario, _subtotal = comercial_politicas.calcular_linea(mundo, variante, linea.cantidad, fecha.date())
            assert precio == linea.precio_unitario
            assert abs(descuento_unitario - linea.descuento_unitario) <= Decimal("0.01"), (linea.id, descuento_unitario, linea.descuento_unitario)


def test_la_serie_diaria_de_la_base_coincide_con_la_del_generador(mundo):
    fs, catalogo, historial, _ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        filas_db = comercial_politicas.reporte_ventas_serie_diaria(
            mundo, ParametrosPeriodo(FIN - dt.timedelta(weeks=SEMANAS + 2), FIN), desglose=("categoria",)
        )
    filas_generador = sintetico.filas_serie_diaria(historial, catalogo)
    clave = lambda f: (f["dia"], f["categoria_id"])  # noqa: E731
    assert {clave(f) for f in filas_db} == {clave(f) for f in filas_generador}
    db_por_clave = {clave(f): f for f in filas_db}
    for f in filas_generador:
        g = db_por_clave[clave(f)]
        assert (g["unidades"], g["transacciones"]) == (f["unidades"], f["transacciones"])
        assert g["ventas_brutas"] == f["ventas_brutas"]
        # El descuento se redondea por unidad (como el sistema real): puede diferir unos centavos por línea.
        assert abs(g["total_ventas"] - f["total_ventas"]) <= Decimal("0.01") * f["unidades"]


def test_los_clientes_sinteticos_no_pueden_iniciar_sesion(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        hashes = set(mundo.scalars(select(Usuario.password_hash).where(Usuario.email.like("c%@sintetico.%"))))
    assert len(hashes) == 1  # una sola contraseña al azar, descartada: nadie la conoce
    (hash_unico,) = hashes
    for intento in ("", "password", "claveSegura123", "c001", "fashionstore", "Sintetico123"):
        assert not verificar_password(intento, hash_unico)


def test_no_se_ejecuta_ningun_delete_y_las_devoluciones_no_pasan_de_lo_vendido(mundo):
    fs = id_de(mundo, "fashionstore")
    sentencias: list[str] = []
    motor = mundo.get_bind()

    def registrar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement.lstrip().upper())

    event.listen(motor, "before_cursor_execute", registrar)
    try:
        cargar_historia(mundo, "fashionstore")
    finally:
        event.remove(motor, "before_cursor_execute", registrar)
    assert sentencias and not [s for s in sentencias if s.startswith("DELETE")]

    with en_empresa(mundo, fs):
        devueltas = mundo.execute(text(
            "SELECT dd.cantidad, vd.cantidad FROM devolucion_detalle dd JOIN venta_detalle vd ON vd.id = dd.venta_detalle_id"
        )).all()
    assert devueltas and all(devuelto <= vendido for devuelto, vendido in devueltas)


def test_cada_venta_efectiva_tiene_su_pago_y_la_anulada_no(mundo):
    fs, catalogo, historial, resumen = cargar_historia(mundo, "fashionstore")
    efectivas = sum(1 for v in historial.ventas if v.estado != "anulada")
    assert resumen.pagos == efectivas == _contar(mundo, fs, Pago)
    with en_empresa(mundo, fs):
        # El total de cada venta es el de sus líneas (subtotal bruto - descuento).
        for venta in mundo.scalars(select(Venta).limit(40)):
            assert venta.total == venta.subtotal - venta.descuento + venta.costo_envio
        assert mundo.scalar(select(func.min(Pago.monto))) > 0


def test_el_cajero_y_la_sucursal_de_cada_venta_son_de_la_empresa(mundo):
    fs, catalogo, historial, _ = cargar_historia(mundo, "fashionstore")
    sucursales = {s.sucursal_id for s in catalogo.sucursales}
    cajeros = {s.cajero_id for s in catalogo.sucursales}
    with en_empresa(mundo, fs):
        usadas = {(v.sucursal_id, v.cajero_id, v.canal) for v in mundo.scalars(select(Venta))}
    assert {s for s, _, _ in usadas} <= sucursales
    assert all(c in cajeros for _, c, canal in usadas if canal == "presencial")
    assert all(c is None for _, c, canal in usadas if canal == "digital")  # el digital no lleva cajero
    assert resumen_clientes(mundo, fs) > 0


def resumen_clientes(db, empresa_id) -> int:
    return _contar(db, empresa_id, Cliente)


def test_los_valores_por_defecto_cargan_unas_9_mil_ventas_por_empresa_profesional():
    """650 clientes en 78 semanas es lo que se calibró (E11): con menos volumen el ruido de cada semana tapa la señal."""
    assert (seed_ml_sintetico.CLIENTES_POR_DEFECTO, seed_ml_sintetico.SEMANAS_POR_DEFECTO) == (650, 78)
    assert CLIENTES == 80 and SEMANAS == 40  # el escenario de pruebas es más chico a propósito

"""CU-24 (E11) en PostgreSQL real: lo que SQLite no puede demostrar. Corre solo con TEST_DATABASE_URL (base `_test`).

- La carga del historial sintético (`scripts.seed_ml_sintetico.cargar_historial`): cuentas, códigos únicos, sin
  DELETE, stock intacto y la vista `vw_ventas_detalle` de producción sumando lo mismo que el generador.
- El entrenamiento de punta a punta: JSONB sin NaN, BYTEA que se vuelve a cargar y predice, versiones.
- El aislamiento entre empresas con datos de verdad.
- El candado consultivo `pg_try_advisory_xact_lock` con DOS conexiones, y dos entrenamientos simultáneos en hilos.
- Los datos que `comercial.politicas` entrega al ML (serie diaria y RFM) contra lo que calcula el generador.

Cada prueba pobla dos organizaciones pequeñas (FashionStore y Chaski Sport, ambas con ML) porque `base_limpia`
vacía todo antes de cada una; el historial se carga en la prueba que lo necesita.
"""

import copy
import datetime as dt
import hashlib
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import undefer

from app.catalogo.models import MovimientoInventario, Stock
from app.comercial import politicas as comercial_politicas
from app.comercial.models import Devolucion, Pago, Promocion, Venta, VentaDetalle
from app.core.auditoria import ENTIDAD_MODELO_ML
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import ErrorFuncional
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
    EntrenarModelosAnaliticos,
)
from app.inteligencia.ml import demanda, persistencia, segmentos, sintetico
from app.inteligencia.ml.limites import ML_MAX_CLIENTES, ML_MAX_SEMANAS
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma.models import Bitacora, Cliente, Usuario
from scripts.poblar_demo import seed
from scripts.seed_ml_sintetico import cargar_historial, correo_cliente
from tests.inteligencia.ml._escenario import FIN, PASSWORD, cargar_historia, id_de, organizaciones
from tests.scripts._prendas_falsas import crear_carpeta

from .paralelo import ejecutar_en_paralelo

CU = EntrenarModelosAnaliticos()
REPO = ModeloMLRepository()
CENTAVO = Decimal("0.01")
TIPOS = (TIPO_DEMANDA, TIPO_SEGMENTOS)


@pytest.fixture()
def mundo(fabrica_pg, tmp_path) -> SimpleNamespace:
    """FashionStore (empresa 1, ya sembrada por `base_limpia`) y Chaski Sport, pobladas con catálogo, tiendas,
    cajeros y stock (sin fotos). Devuelve los ids de las dos empresas."""
    with fabrica_pg() as db:
        seed(
            db, ejecutar=True, password=PASSWORD, origen=crear_carpeta(tmp_path),
            organizaciones=organizaciones()[:2], con_fotos=False,
        )  # fmt: skip
        return SimpleNamespace(fs=id_de(db, "fashionstore"), ch=id_de(db, "chaski-sport"))


def _entrenar(fabrica_pg, empresa_id, **kwargs):
    with fabrica_pg() as db, en_empresa(db, empresa_id):
        return CU.ejecutar(db, None, hasta=FIN, **kwargs)


def _modelos(fabrica_pg, empresa_id) -> dict:
    """Todas las versiones de la empresa, SIN el artefacto, por (tipo, versión)."""
    with fabrica_pg() as db, en_empresa(db, empresa_id):
        return {(m.tipo, m.version): m for m in db.scalars(select(ModeloML))}


def _snapshot_stock(db, empresa_id) -> tuple:
    with en_empresa(db, empresa_id):
        filas = db.execute(
            select(Stock.variante_id, Stock.sucursal_id, Stock.cantidad_fisica, Stock.cantidad_reservada, Stock.cantidad_disponible)
            .order_by(Stock.variante_id, Stock.sucursal_id)
        ).all()  # fmt: skip
        movimientos = db.scalar(select(func.count()).select_from(MovimientoInventario))
    return tuple(tuple(f) for f in filas), movimientos


# ---- 1. La carga del historial ---------------------------------------------------------------------------------------------


def test_la_carga_del_historial_en_postgresql_cuadra_con_el_generador_y_no_toca_el_stock(fabrica_pg, engine_pg, mundo):
    sentencias_delete: list[str] = []

    def vigilar(conexion, cursor, sentencia, parametros, contexto, many):
        if sentencia.lstrip().upper().startswith("DELETE"):
            sentencias_delete.append(sentencia[:80])

    with fabrica_pg() as db:
        antes = _snapshot_stock(db, mundo.fs)
        assert antes[0] and antes[1] > 0  # el stock de la demo existe: la comparación no es trivial
        event.listen(engine_pg, "before_cursor_execute", vigilar)
        try:
            inicio = time.perf_counter()
            _, catalogo, historial, resumen = cargar_historia(db, "fashionstore")
            duracion = time.perf_counter() - inicio
        finally:
            event.remove(engine_pg, "before_cursor_execute", vigilar)
        despues = _snapshot_stock(db, mundo.fs)

        assert duracion < 90, f"la carga tardó {duracion:.1f} s"
        assert sentencias_delete == []  # borrado físico prohibido: la carga solo inserta
        assert despues == antes  # ni filas, ni cantidad física, ni reservada, ni disponible, ni kardex

        efectivas = [v for v in historial.ventas if v.estado != "anulada"]
        with en_empresa(db, mundo.fs):
            codigos = db.scalars(select(Venta.codigo).where(Venta.codigo.like("SIN-%"))).all()
            assert len(codigos) == len(historial.ventas) == resumen.ventas
            assert len(set(codigos)) == len(codigos)  # los códigos SIN- son únicos
            assert db.scalar(select(func.count()).select_from(VentaDetalle)) == resumen.lineas == sum(len(v.lineas) for v in historial.ventas)
            assert db.scalar(select(func.count()).select_from(Pago)) == resumen.pagos == len(efectivas)  # la anulada no deja pago
            assert db.scalar(select(func.count()).select_from(Devolucion)) == resumen.devoluciones > 0
            assert db.scalar(select(func.count()).select_from(Promocion).where(Promocion.nombre.like("[SIN] %"))) == resumen.promociones == len(historial.promociones)
            clientes = db.scalar(
                select(func.count()).select_from(Cliente).join(Usuario, Usuario.id == Cliente.usuario_id).where(Usuario.email.like("c%@sintetico.%"))
            )
            assert clientes == resumen.clientes == len(historial.clientes)

            # Repetir no inserta nada (idempotente): avisa y deja las cuentas como estaban.
            assert cargar_historial(db, historial, catalogo, "fashionstore").ya_existia is True
            assert db.scalar(select(func.count()).select_from(Venta).where(Venta.codigo.like("SIN-%"))) == resumen.ventas

            # La vista de producción (vw_ventas_detalle, V2) suma lo mismo que el generador. El subtotal de cada línea
            # redondea el descuento por unidad, el generador no: se admite un centavo por línea como máximo.
            en_la_vista = db.execute(
                text(
                    "SELECT COALESCE(SUM(v.subtotal), 0), COALESCE(SUM(v.precio_unitario * v.cantidad), 0), COUNT(*) "
                    "FROM vw_ventas_detalle v JOIN venta ve ON ve.id = v.venta_id "
                    "JOIN estado_venta ev ON ev.id = ve.estado_id "
                    "WHERE v.empresa_id = :e AND ev.codigo IN ('pagada', 'entregada')"
                ),
                {"e": mundo.fs},
            ).one()
        del_generador = sintetico.filas_serie_diaria(historial, catalogo)
        total_generador = sum((f["total_ventas"] for f in del_generador), Decimal("0"))
        bruto_generador = sum((f["ventas_brutas"] for f in del_generador), Decimal("0"))
        lineas_efectivas = sum(len(v.lineas) for v in efectivas)
        assert en_la_vista[2] == lineas_efectivas
        assert en_la_vista[1] == bruto_generador  # lo vendido a precio de lista coincide al centavo
        assert abs(en_la_vista[0] - total_generador) <= CENTAVO * lineas_efectivas


# ---- 2. El entrenamiento de punta a punta -------------------------------------------------------------------------------------


def test_entrenar_en_postgresql_guarda_jsonb_sin_nan_y_un_bytea_que_se_carga_y_predice(fabrica_pg, mundo):
    with fabrica_pg() as db:
        _, catalogo, historial, _ = cargar_historia(db, "fashionstore")

    primera = _entrenar(fabrica_pg, mundo.fs)
    assert primera.entrenados == list(TIPOS)
    assert all(r.estado == "ok" and r.version == 1 for r in primera.resultados)

    with fabrica_pg() as db, en_empresa(db, mundo.fs):
        for tipo in TIPOS:
            modelo = REPO.obtener_activo(db, tipo, con_artefacto=True)
            assert modelo.activo and modelo.version == 1 and modelo.empresa_id == mundo.fs
            # JSONB: ida y vuelta como JSON puro (la base ya rechaza NaN; el serializador estricto lo confirma).
            json.dumps([modelo.metricas, modelo.parametros], allow_nan=False)
            assert isinstance(modelo.metricas, dict) and isinstance(modelo.parametros, dict)
            assert modelo.parametros["hasta"] == FIN.isoformat()
            # BYTEA: los bytes vuelven idénticos (misma huella y mismo tamaño que se guardaron).
            assert isinstance(modelo.artefacto, bytes) and len(modelo.artefacto) == modelo.artefacto_bytes
            assert hashlib.sha256(modelo.artefacto).hexdigest() == modelo.artefacto_sha256
            assert db.scalar(text("SELECT jsonb_typeof(metricas) FROM modelo_ml WHERE id = :i"), {"i": modelo.id}) == "object"

        demanda_ml = REPO.obtener_activo(db, TIPO_DEMANDA, con_artefacto=True)
        artefacto = persistencia.deserializar(demanda_ml.artefacto, demanda_ml.artefacto_sha256)
        predicciones = demanda.predecir_demanda(artefacto, 4)
        assert len(predicciones) == 4 * len(artefacto["categorias"]) > 0
        # Y predice igual que el modelo recalculado sin pasar por la base.
        recalculado = demanda.entrenar_demanda(sintetico.filas_serie_diaria(historial, catalogo), FIN).artefacto
        assert [p.unidades for p in predicciones] == [p.unidades for p in demanda.predecir_demanda(recalculado, 4)]

        segmentos_ml = REPO.obtener_activo(db, TIPO_SEGMENTOS, con_artefacto=True)
        modelo_rfm = persistencia.deserializar(segmentos_ml.artefacto, segmentos_ml.artefacto_sha256)
        ids_segmento = {s["id"] for s in segmentos_ml.metricas["segmentos"]}
        fila = sintetico.filas_rfm(historial, FIN)[0]
        asignado = segmentos.asignar_segmento(modelo_rfm, fila["ultima_compra"], fila["frecuencia"], fila["monto_total"], FIN)
        assert asignado in ids_segmento

    segunda = _entrenar(fabrica_pg, mundo.fs)
    assert [r.version for r in segunda.resultados] == [2, 2]
    modelos = _modelos(fabrica_pg, mundo.fs)
    assert set(modelos) == {(t, v) for t in TIPOS for v in (1, 2)}
    assert all(modelos[(t, 1)].activo is False and modelos[(t, 2)].activo is True for t in TIPOS)
    with fabrica_pg() as db, en_empresa(db, mundo.fs):
        assert REPO.obtener_version(db, TIPO_DEMANDA, 1, con_artefacto=True).artefacto  # la 1 conserva su artefacto
        # Un índice parcial único deja a lo sumo UNA versión vigente por tipo.
        vigentes = db.execute(select(ModeloML.tipo, func.count()).where(ModeloML.activo.is_(True)).group_by(ModeloML.tipo)).all()
        assert sorted(vigentes) == sorted((t, 1) for t in TIPOS)


# ---- 3. Aislamiento entre empresas --------------------------------------------------------------------------------------------


def test_cada_empresa_entrena_con_lo_suyo_y_no_ve_el_modelo_ni_el_artefacto_de_la_otra(fabrica_pg, engine_pg, mundo):
    with fabrica_pg() as db:
        _, catalogo_fs, historial_fs, _ = cargar_historia(db, "fashionstore")
        _, catalogo_ch, historial_ch, _ = cargar_historia(db, "chaski-sport", perfil="B")
    assert len(historial_fs.ventas) != len(historial_ch.ventas)

    _entrenar(fabrica_pg, mundo.fs)
    _entrenar(fabrica_pg, mundo.ch)
    modelos_fs, modelos_ch = _modelos(fabrica_pg, mundo.fs), _modelos(fabrica_pg, mundo.ch)
    assert set(modelos_fs) == set(modelos_ch) == {(t, 1) for t in TIPOS}  # cada empresa numera sola
    assert {m.empresa_id for m in modelos_fs.values()} == {mundo.fs} and {m.empresa_id for m in modelos_ch.values()} == {mundo.ch}

    # Cada una usó SOLO su historial (cuentas calculadas a mano, sin pasar por la base).
    esperado_fs = demanda.entrenar_demanda(sintetico.filas_serie_diaria(historial_fs, catalogo_fs), FIN)
    esperado_ch = demanda.entrenar_demanda(sintetico.filas_serie_diaria(historial_ch, catalogo_ch), FIN)
    assert modelos_fs[(TIPO_DEMANDA, 1)].filas_entrenamiento == esperado_fs.filas_entrenamiento
    assert modelos_ch[(TIPO_DEMANDA, 1)].filas_entrenamiento == esperado_ch.filas_entrenamiento
    assert modelos_fs[(TIPO_SEGMENTOS, 1)].metricas["n_clientes"] == len(sintetico.filas_rfm(historial_fs, FIN))
    assert modelos_ch[(TIPO_SEGMENTOS, 1)].metricas["n_clientes"] == len(sintetico.filas_rfm(historial_ch, FIN))
    assert modelos_fs[(TIPO_DEMANDA, 1)].artefacto_sha256 != modelos_ch[(TIPO_DEMANDA, 1)].artefacto_sha256

    # La base tiene las cuatro filas; cada sesión solo ve las suyas, por la API del repositorio y por id.
    with engine_pg.connect() as conexion:
        assert conexion.execute(text("SELECT COUNT(*) FROM modelo_ml")).scalar() == 4
    id_fs = modelos_fs[(TIPO_DEMANDA, 1)].id
    id_ch = modelos_ch[(TIPO_DEMANDA, 1)].id
    with fabrica_pg() as db:
        for propia, id_ajeno in ((mundo.fs, id_ch), (mundo.ch, id_fs)):
            with en_empresa(db, propia):
                assert {m.empresa_id for m in db.scalars(select(ModeloML))} == {propia}
                assert [m.version for m in REPO.listar_versiones(db, TIPO_DEMANDA)] == [1]
                assert db.get(ModeloML, id_ajeno) is None
                assert db.scalars(select(ModeloML).options(undefer(ModeloML.artefacto)).where(ModeloML.id == id_ajeno)).first() is None
                assert REPO.obtener_version(db, TIPO_SEGMENTOS, 1, con_artefacto=True).empresa_id == propia


def test_inundar_de_datos_a_otra_empresa_en_postgresql_no_cambia_las_metricas_de_la_primera(fabrica_pg, mundo):
    with fabrica_pg() as db:
        cargar_historia(db, "fashionstore")
    _entrenar(fabrica_pg, mundo.fs)
    antes = _modelos(fabrica_pg, mundo.fs)
    metricas_antes = {t: copy.deepcopy(antes[(t, 1)].metricas) for t in TIPOS}
    huella_antes = antes[(TIPO_DEMANDA, 1)].artefacto_sha256

    with fabrica_pg() as db:
        cargar_historia(db, "chaski-sport", clientes=300, perfil="B")  # un volumen masivo en OTRA empresa
    _entrenar(fabrica_pg, mundo.fs)

    despues = _modelos(fabrica_pg, mundo.fs)
    for tipo in TIPOS:
        assert despues[(tipo, 2)].metricas == metricas_antes[tipo]
    assert despues[(TIPO_DEMANDA, 2)].artefacto_sha256 == huella_antes
    assert _modelos(fabrica_pg, mundo.ch) == {}  # y entrenar la primera tampoco creó nada en la otra


# ---- 4. El candado consultivo de PostgreSQL con dos conexiones ----------------------------------------------------------------


def test_el_candado_consultivo_real_bloquea_a_la_segunda_conexion_y_se_suelta_al_terminar(fabrica_pg, mundo):
    with fabrica_pg() as db1, fabrica_pg() as db2:
        # La primera toma el candado y deja la transacción abierta.
        assert EntrenarModelosAnaliticos._candado_ocupado(db1, mundo.fs, TIPO_DEMANDA) is False
        assert db1.in_transaction()

        # La segunda lo ve ocupado (y con las dos transacciones abiertas se comprueba que son conexiones distintas).
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.fs, TIPO_DEMANDA) is True
        assert db1.scalar(text("SELECT pg_backend_pid()")) != db2.scalar(text("SELECT pg_backend_pid()"))
        db2.rollback()

        # Su entrenamiento falla limpio, sin guardar nada ni dejar bitácora.
        with en_empresa(db2, mundo.fs):
            with pytest.raises(ErrorFuncional) as error:
                CU.ejecutar(db2, None, tipos=[TIPO_DEMANDA], hasta=FIN)
        assert (error.value.status_code, error.value.codigo) == (409, "entrenamiento_en_curso")
        assert error.value.contexto["tipo"] == TIPO_DEMANDA
        with fabrica_pg() as db3, en_empresa(db3, mundo.fs):
            assert db3.scalar(select(func.count()).select_from(ModeloML)) == 0
            assert db3.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.entidad == ENTIDAD_MODELO_ML)) == 0

        # Otro tipo de la misma empresa y el mismo tipo de OTRA empresa no se bloquean con el candado tomado.
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.fs, TIPO_SEGMENTOS) is False
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.ch, TIPO_DEMANDA) is False
        db2.rollback()

        # Al revertir la primera, el candado queda libre.
        db1.rollback()
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.fs, TIPO_DEMANDA) is False
        db2.rollback()

        # Y al confirmar (commit) también se suelta.
        assert EntrenarModelosAnaliticos._candado_ocupado(db1, mundo.fs, TIPO_DEMANDA) is False
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.fs, TIPO_DEMANDA) is True
        db2.rollback()
        db1.commit()
        assert EntrenarModelosAnaliticos._candado_ocupado(db2, mundo.fs, TIPO_DEMANDA) is False
        db2.rollback()


def test_con_el_candado_de_un_tipo_tomado_el_otro_tipo_si_entrena_y_al_soltarlo_tambien(fabrica_pg, mundo):
    with fabrica_pg() as db:
        cargar_historia(db, "fashionstore")
    with fabrica_pg() as db1:
        assert EntrenarModelosAnaliticos._candado_ocupado(db1, mundo.fs, TIPO_SEGMENTOS) is False  # solo el de segmentos
        # Entrenar la demanda NO espera a segmentos (otro número de candado) y guarda su versión 1.
        resumen = _entrenar(fabrica_pg, mundo.fs, tipos=[TIPO_DEMANDA])
        assert resumen.entrenados == [TIPO_DEMANDA]
        # En cambio, segmentos sí falla mientras la primera conexión lo tiene.
        with pytest.raises(ErrorFuncional) as error:
            _entrenar(fabrica_pg, mundo.fs, tipos=[TIPO_SEGMENTOS])
        assert error.value.codigo == "entrenamiento_en_curso"
        db1.rollback()
    assert _entrenar(fabrica_pg, mundo.fs, tipos=[TIPO_SEGMENTOS]).entrenados == [TIPO_SEGMENTOS]
    assert set(_modelos(fabrica_pg, mundo.fs)) == {(TIPO_DEMANDA, 1), (TIPO_SEGMENTOS, 1)}


# ---- 5. Entrenamientos concurrentes de verdad ------------------------------------------------------------------------------------


def test_dos_entrenamientos_simultaneos_nunca_dejan_dos_vigentes_ni_versiones_repetidas(fabrica_pg, engine_pg, mundo):
    with fabrica_pg() as db:
        cargar_historia(db, "fashionstore")

    def entrenar_todo(db):
        with en_empresa(db, mundo.fs):
            return CU.ejecutar(db, None, hasta=FIN)

    resultados = ejecutar_en_paralelo(fabrica_pg, [entrenar_todo, entrenar_todo])

    for resultado in resultados:  # o termina bien, o falla limpio por el candado; nada más
        if not resultado.ok:
            assert isinstance(resultado.error, ErrorFuncional), repr(resultado.error)
            assert (resultado.error.status_code, resultado.error.codigo) == (409, "entrenamiento_en_curso")
    assert any(r.ok for r in resultados)  # al menos uno entrenó

    with engine_pg.connect() as conexion:
        filas = conexion.execute(text("SELECT tipo, version, activo, empresa_id FROM modelo_ml ORDER BY tipo, version")).all()
    assert filas and {f.empresa_id for f in filas} == {mundo.fs}
    for tipo in TIPOS:
        del_tipo = [f for f in filas if f.tipo == tipo]
        versiones = [f.version for f in del_tipo]
        assert len(versiones) == len(set(versiones))  # ninguna versión repetida
        assert versiones == list(range(1, len(versiones) + 1))  # y sin huecos
        vigentes = [f.version for f in del_tipo if f.activo]
        assert vigentes == [max(versiones)]  # UNA sola vigente: la más nueva


def test_tres_entrenamientos_simultaneos_de_la_demanda_dejan_las_versiones_consistentes(fabrica_pg, engine_pg, mundo):
    with fabrica_pg() as db:
        cargar_historia(db, "fashionstore")

    def entrenar_demanda(db):
        with en_empresa(db, mundo.fs):
            return CU.ejecutar(db, None, tipos=[TIPO_DEMANDA], hasta=FIN)

    resultados = ejecutar_en_paralelo(fabrica_pg, [entrenar_demanda] * 3)
    buenos = [r for r in resultados if r.ok]
    malos = [r for r in resultados if not r.ok]
    assert buenos
    assert all(isinstance(r.error, ErrorFuncional) and r.error.codigo == "entrenamiento_en_curso" for r in malos)
    versiones_devueltas = sorted(r.valor.resultados[0].version for r in buenos)
    assert versiones_devueltas == list(range(1, len(buenos) + 1))  # cada entrenamiento que terminó tiene su propia versión

    modelos = _modelos(fabrica_pg, mundo.fs)
    assert sorted(v for (_, v) in modelos) == versiones_devueltas
    assert [v for (_, v), m in sorted(modelos.items()) if m.activo] == [len(buenos)]


# ---- 6. Lo que `comercial` entrega al ML, contra el generador ------------------------------------------------------------------------


def test_la_serie_diaria_y_el_rfm_de_comercial_en_postgresql_coinciden_con_el_generador(fabrica_pg, mundo):
    with fabrica_pg() as db:
        _, catalogo, historial, _ = cargar_historia(db, "fashionstore")
        periodo = ParametrosPeriodo(desde=FIN - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=FIN)
        with en_empresa(db, mundo.fs):
            serie = comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("categoria",))
            rfm = comercial_politicas.reporte_rfm_clientes(db, FIN, dias=365, tope=ML_MAX_CLIENTES)
            correos = {
                email: cliente_id
                for email, cliente_id in db.execute(
                    select(Usuario.email, Cliente.id).join(Cliente, Cliente.usuario_id == Usuario.id).where(Usuario.email.like("c%@sintetico.%"))
                )
            }

        # Serie diaria por categoría: mismas filas, mismos conteos y mismas ventas brutas; el total admite un centavo
        # por unidad (la base redondea el descuento por unidad al guardar la línea).
        esperada = {(f["dia"], f["categoria_id"]): f for f in sintetico.filas_serie_diaria(historial, catalogo)}
        obtenida = {(f["dia"], f["categoria_id"]): f for f in serie}
        assert esperada and obtenida.keys() == esperada.keys()
        for clave, fila in obtenida.items():
            e = esperada[clave]
            assert (fila["categoria"], fila["transacciones"], fila["unidades"]) == (e["categoria"], e["transacciones"], e["unidades"])
            assert fila["ventas_brutas"] == e["ventas_brutas"]
            assert abs(fila["total_ventas"] - e["total_ventas"]) <= CENTAVO * e["unidades"]
        assert [f["dia"] for f in serie] == sorted(f["dia"] for f in serie)  # ordenada por día

        # RFM: el generador numera a los clientes de 0 a n-1; la base les puso su propio id (el correo los une).
        cliente_de_n = {n: correos[correo_cliente("fashionstore", n)] for n in range(len(historial.clientes))}
        esperado_rfm = {cliente_de_n[f["cliente_id"]]: f for f in sintetico.filas_rfm(historial, FIN)}
        assert len(rfm) == len(esperado_rfm) > 30  # lo bastante para segmentar
        assert [f["cliente_id"] for f in rfm] == sorted(f["cliente_id"] for f in rfm)  # orden por cliente
        for fila in rfm:
            e = esperado_rfm[fila["cliente_id"]]
            assert (fila["ultima_compra"], fila["frecuencia"]) == (e["ultima_compra"], e["frecuencia"])
            # Mismo redondeo del descuento por unidad que en la serie: a lo sumo un centavo por unidad, y se admiten
            # hasta 10 unidades por venta (hoy la diferencia real es 0,00; la tolerancia solo evita una prueba frágil).
            assert abs(fila["monto_total"] - e["monto_total"]) <= CENTAVO * 10 * e["frecuencia"]

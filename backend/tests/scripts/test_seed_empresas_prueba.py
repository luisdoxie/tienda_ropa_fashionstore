"""Seed de las 2 empresas de prueba (E04): FashionStore (Profesional) y Boutique
Andina (Básico). Todo sobre SQLite en memoria (la fixture `db_session`)."""

import pytest
from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Material, Producto, ProductoVariante, Stock, Talla
from app.comercial.models import Reserva, Venta
from app.core.exceptions import ConflictoError, ErrorFuncional
from app.core.tenant import empresa_de, en_empresa, fijar_empresa, fijar_plataforma
from app.plataforma import politicas
from app.plataforma.casos_uso.cu02_gestionar_usuarios_roles_permisos import GestionarUsuarios
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
from app.plataforma.models import Ciudad, Cliente, Empleado, Empresa, Sucursal, Suscripcion, Usuario
from app.plataforma.schemas import SucursalCrear, UsuarioCrear
from scripts.seed_empresas_prueba import CODIGO_BOUTIQUE, CODIGO_FASHIONSTORE, imprimir, main, seed

PASSWORD = "claveSegura123"


def _id(db, codigo: str) -> int:
    empresa = politicas.obtener_empresa_por_codigo(db, codigo)
    assert empresa is not None, f"no existe la empresa {codigo}"
    return empresa.id


def _contar(db, empresa_id: int, modelo, *condiciones) -> int:
    """Filas de `modelo` de esa empresa (la sesión queda como estaba)."""
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def _total(resumen) -> int:
    return sum(resumen.creados.values())


def _sembrar(db, **kwargs):
    return seed(db, ejecutar=True, password=PASSWORD, **kwargs)


def test_dry_run_no_escribe(db_session):
    fashionstore = _id(db_session, CODIGO_FASHIONSTORE)

    resultados = seed(db_session, ejecutar=False, password=None)

    assert politicas.obtener_empresa_por_codigo(db_session, CODIGO_BOUTIQUE) is None
    assert db_session.scalar(select(func.count()).select_from(Empresa)) == 1
    # La empresa existente sigue como la dejó la fixture: su suscripción y nada más.
    assert _contar(db_session, fashionstore, Suscripcion) == 1
    for modelo in (Sucursal, Usuario, Empleado, Cliente, Producto, ProductoVariante, Stock, MovimientoInventario):
        assert _contar(db_session, fashionstore, modelo) == 0, modelo.__name__
    # Lo que haría sí se informa.
    assert resultados[CODIGO_BOUTIQUE].creados["empresa"] == 1
    assert resultados[CODIGO_BOUTIQUE].creados["sucursal"] == 2
    assert resultados[CODIGO_FASHIONSTORE].creados["producto"] == 10
    assert resultados[CODIGO_FASHIONSTORE].creados["sucursal"] == 3
    assert empresa_de(db_session) == fashionstore  # la sesión queda como estaba


def test_crea_las_dos_empresas_con_planes_distintos(db_session):
    resultados = _sembrar(db_session)

    assert _total(resultados[CODIGO_FASHIONSTORE]) > 0 and _total(resultados[CODIGO_BOUTIQUE]) > 0
    fashionstore, boutique = _id(db_session, CODIGO_FASHIONSTORE), _id(db_session, CODIGO_BOUTIQUE)
    for empresa_id, plan in ((fashionstore, "profesional"), (boutique, "basico")):
        with en_empresa(db_session, empresa_id):
            assert politicas.plan_de_la_empresa(db_session).codigo == plan
            assert politicas.estado_efectivo(politicas.obtener_suscripcion_vigente(db_session)) == "activa"

    # FashionStore: 2 tiendas y 1 depósito, staff, 10 productos con variantes, stock y 5 clientes.
    assert _contar(db_session, fashionstore, Sucursal, Sucursal.es_deposito.is_(False)) == 2
    assert _contar(db_session, fashionstore, Sucursal, Sucursal.es_deposito.is_(True)) == 1
    assert _contar(db_session, fashionstore, Empleado) == 5
    assert _contar(db_session, fashionstore, Producto) == 10
    assert _contar(db_session, fashionstore, ProductoVariante) == 30
    assert _contar(db_session, fashionstore, Stock) == 30 * 3
    assert _contar(db_session, fashionstore, Cliente) == 5

    # Boutique Andina: registrada con su administrador y los catálogos base.
    assert _contar(db_session, boutique, Ciudad) == 9
    assert _contar(db_session, boutique, Talla) == 6
    assert _contar(db_session, boutique, Material) == 8
    assert _contar(db_session, boutique, Sucursal, Sucursal.es_deposito.is_(False)) == 1
    assert _contar(db_session, boutique, Sucursal, Sucursal.es_deposito.is_(True)) == 1
    assert _contar(db_session, boutique, Empleado) == 3  # administrador, encargado y cajero
    assert _contar(db_session, boutique, Usuario) == 3 + 3  # staff + 3 clientes
    assert _contar(db_session, boutique, Producto) == 6
    assert _contar(db_session, boutique, ProductoVariante) == 18
    assert _contar(db_session, boutique, Stock) == 18 * 2
    assert _contar(db_session, boutique, Cliente) == 3
    assert _contar(db_session, boutique, Venta) == 2
    assert _contar(db_session, boutique, Reserva) == 1
    with en_empresa(db_session, boutique):
        correos = set(db_session.scalars(select(Usuario.email)))
    assert {"admin@boutiqueandina.bo", "encargado.centro@boutiqueandina.bo", "cajero.centro@boutiqueandina.bo"} <= correos
    assert empresa_de(db_session) == fashionstore


def test_basico_queda_con_2_sucursales_y_la_tercera_da_409(db_session):
    original = empresa_de(db_session)
    _sembrar(db_session)
    boutique = _id(db_session, CODIGO_BOUTIQUE)
    assert _contar(db_session, boutique, Sucursal, Sucursal.activo.is_(True)) == 2
    with en_empresa(db_session, boutique):
        ciudad_id = db_session.scalar(select(Ciudad.id).where(Ciudad.nombre == "La Paz"))

    fijar_plataforma(db_session)
    try:
        with pytest.raises(ErrorFuncional) as error:
            GestionarEmpresas().agregar_sucursal(
                db_session,
                boutique,
                SucursalCrear(ciudad_id=ciudad_id, codigo="LP-TERCERA", nombre="Tercera", direccion="Calle 1"),
            )
    finally:
        fijar_empresa(db_session, original)

    assert error.value.status_code == 409
    assert error.value.codigo == "limite_plan_excedido"
    assert error.value.contexto["limite"] == 2 and error.value.contexto["actual"] == 2
    assert _contar(db_session, boutique, Sucursal, Sucursal.activo.is_(True)) == 2


def test_segunda_corrida_no_cambia_nada(db_session):
    _sembrar(db_session)
    fashionstore, boutique = _id(db_session, CODIGO_FASHIONSTORE), _id(db_session, CODIGO_BOUTIQUE)
    modelos = (Sucursal, Usuario, Empleado, Cliente, Producto, ProductoVariante, Stock, MovimientoInventario, Venta, Reserva, Suscripcion)

    def foto():
        return {
            (empresa_id, modelo.__name__): _contar(db_session, empresa_id, modelo)
            for empresa_id in (fashionstore, boutique)
            for modelo in modelos
        }

    antes = foto()
    segunda = _sembrar(db_session)

    assert {codigo: _total(resumen) for codigo, resumen in segunda.items()} == {
        CODIGO_FASHIONSTORE: 0,
        CODIGO_BOUTIQUE: 0,
    }
    assert foto() == antes
    assert db_session.scalar(select(func.count()).select_from(Empresa)) == 2


def test_la_contrasena_inicial_no_se_imprime(db_session, capsys, monkeypatch):
    secreta = "Zx9-clave-secreta-unica"
    resultados = seed(db_session, ejecutar=True, password=secreta)
    imprimir(resultados, True)
    seed(db_session, ejecutar=False, password=secreta)  # el dry-run tampoco
    salida = capsys.readouterr()
    assert secreta not in salida.out and secreta not in salida.err

    # Una contraseña inválida se rechaza sin repetirla en el mensaje.
    monkeypatch.setenv("SEED_PASSWORD_INICIAL", "cl4ve")
    with pytest.raises(SystemExit) as error:
        main(["--ejecutar"])
    assert "cl4ve" not in str(error.value)
    salida = capsys.readouterr()
    assert "cl4ve" not in salida.out and "cl4ve" not in salida.err


def test_correo_repetido_en_ambas_empresas_es_valido(db_session):
    _sembrar(db_session)
    fashionstore, boutique = _id(db_session, CODIGO_FASHIONSTORE), _id(db_session, CODIGO_BOUTIQUE)

    # La semilla: mismo nombre y mismo correo local, dominios distintos.
    def usuario(empresa_id: int, local: str, dominio: str) -> tuple:
        with en_empresa(db_session, empresa_id):
            fila = db_session.scalar(select(Usuario).where(Usuario.email == f"{local}@{dominio}"))
            return fila.nombre, fila.apellido, fila.empresa_id

    for local in ("admin", "cajero.centro", "encargado.centro"):
        fs = usuario(fashionstore, local, "fashionstore.bo")
        ba = usuario(boutique, local, "boutiqueandina.bo")
        assert fs[:2] == ba[:2]
        assert (fs[2], ba[2]) == (fashionstore, boutique)

    # El MISMO correo completo en las dos empresas: el correo es único por empresa.
    nuevo = UsuarioCrear(nombre="Ana", apellido="Compartida", email="ana@correo.bo", password=PASSWORD)
    ids = {}
    for empresa_id in (fashionstore, boutique):
        with en_empresa(db_session, empresa_id):
            ids[empresa_id] = GestionarUsuarios().crear(db_session, nuevo).id
    assert ids[fashionstore] != ids[boutique]
    for empresa_id in (fashionstore, boutique):
        assert _contar(db_session, empresa_id, Usuario, Usuario.email == "ana@correo.bo") == 1

    # Dentro de una misma empresa sigue siendo único.
    with en_empresa(db_session, boutique):
        with pytest.raises(ConflictoError):
            GestionarUsuarios().crear(db_session, nuevo)
        db_session.rollback()

"""E02 (multitenant), PASO 3.7: `Cliente.empresa_id` coincide con
`Usuario.empresa_id`. Usuario y cliente se crean en la misma sesión (la
empresa la pone `before_flush`), así que coinciden por construcción; estas
pruebas lo fijan.

Un registro público (`/auth/registro`) sin empresa en la sesión responde 401
hasta la E03 (`/public/{codigo}/registro`): por eso el alta se hace con
`RegistrarCliente` desde una sesión con la empresa fijada."""

import pytest
from sqlalchemy import select, text

from app.core.exceptions import ConflictoError
from app.core.tenant import fijar_empresa
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import RegistrarCliente
from app.plataforma.models import Cliente, Usuario
from app.plataforma.repository import ClienteRepository
from app.plataforma.schemas import RegistroRequest


def _registro(email: str = "cliente@example.com", **extra) -> RegistroRequest:
    return RegistroRequest(nombre="Cli", apellido="Ente", email=email, password="claveSegura123", **extra)


def _pares_usuario_cliente(db) -> list[tuple[int, int]]:
    """(empresa del usuario, empresa del cliente) leídos SIN filtro, para
    comparar de verdad lo guardado en la base."""
    filas = db.execute(
        text("SELECT u.empresa_id, c.empresa_id FROM cliente c JOIN usuario u ON u.id = c.usuario_id")
    ).all()
    return [(fila[0], fila[1]) for fila in filas]


def test_el_cliente_registrado_queda_en_la_empresa_de_la_sesion(db_session, dos_empresas):
    for empresa in (dos_empresas.a, dos_empresas.b):
        fijar_empresa(db_session, empresa.id)
        usuario = RegistrarCliente().registrar(db_session, _registro())
        cliente = db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
        assert usuario.empresa_id == empresa.id
        assert cliente.empresa_id == usuario.empresa_id == empresa.id

    pares = _pares_usuario_cliente(db_session)
    assert sorted(pares) == sorted([(dos_empresas.a.id, dos_empresas.a.id), (dos_empresas.b.id, dos_empresas.b.id)])


def test_el_mismo_correo_se_registra_en_dos_empresas_pero_no_dos_veces_en_una(db_session, dos_empresas):
    fijar_empresa(db_session, dos_empresas.a.id)
    RegistrarCliente().registrar(db_session, _registro("mismo@example.com"))
    with pytest.raises(ConflictoError):
        RegistrarCliente().registrar(db_session, _registro("mismo@example.com"))

    fijar_empresa(db_session, dos_empresas.b.id)
    registrado_en_b = RegistrarCliente().registrar(db_session, _registro("mismo@example.com"))

    assert registrado_en_b.empresa_id == dos_empresas.b.id
    assert len(_pares_usuario_cliente(db_session)) == 2
    assert all(u == c for u, c in _pares_usuario_cliente(db_session))


def test_crear_o_actualizar_perfil_crea_el_cliente_en_la_empresa_del_usuario(db_session, dos_empresas):
    """La otra vía de alta (`ClienteRepository.crear_o_actualizar_perfil`) y el
    perfil reutilizado de un usuario reactivado respetan la misma empresa."""
    fijar_empresa(db_session, dos_empresas.b.id)
    usuario = RegistrarCliente().registrar(db_session, _registro("perfil@example.com", ci_nit="123"))
    usuario_id = usuario.id

    perfil = ClienteRepository().crear_o_actualizar_perfil(db_session, usuario_id, "456")
    assert perfil.empresa_id == dos_empresas.b.id
    assert perfil.ci_nit == "456"
    assert db_session.scalar(select(Usuario.empresa_id).where(Usuario.id == usuario_id)) == perfil.empresa_id
    assert len(_pares_usuario_cliente(db_session)) == 1

    # Desde la otra empresa ese cliente no existe.
    fijar_empresa(db_session, dos_empresas.a.id)
    assert ClienteRepository().buscar_por_usuario(db_session, usuario_id) is None

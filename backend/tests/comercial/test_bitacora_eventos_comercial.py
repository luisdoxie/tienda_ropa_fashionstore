"""E06: eventos de la bitácora enganchados en `comercial` y `catalogo`:
devolución registrada (CU-17), anulación de un pago por el personal (CU-18) y
ajustes de inventario (CU-09). Cada evento deja usuario, empresa, entidad_id e
IP correctos, nunca datos sensibles, y la fila queda en el MISMO commit que la
operación: si esta falla, no queda fila ni efecto."""

import pytest
from sqlalchemy import func, select

from app.catalogo.casos_uso.cu09_gestionar_inventario import RegistrarMovimientoInventario
from app.catalogo.models import MovimientoInventario
from app.comercial.casos_uso.cu17_gestionar_devoluciones_cambios import RegistrarDevolucion
from app.comercial.models import Devolucion
from app.comercial.schemas import DevolucionCrear, DevolucionDetalleCrear
from app.core.auditoria import ContextoAuditoria
from app.core.exceptions import ConflictoError, DomainError
from app.core.tenant import empresa_de
from app.plataforma.models import Usuario
from tests.ayudas_bitacora import exigir_datos_sin_sensibles, filas_de
from tests.conftest import crear_cajero

API = "/api/v1"
MOTIVO_LIBRE = "Cliente Juan Perez, llamar al 70012345"
OBSERVACION_LIBRE = "Conteo de Rosa Flores, revisar con ella"


@pytest.fixture()
def contexto(client, admin_headers, db_session):
    cat = client.post(f"{API}/categorias", json={"nombre": "Camisas Bitacora"}, headers=admin_headers).json()
    talla = client.post(f"{API}/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post(f"{API}/colores", json={"nombre": "Gris Bitacora"}, headers=admin_headers).json()
    producto = client.post(
        f"{API}/productos",
        json={
            "codigo": "BIT-1",
            "nombre": "Camisa bitacora",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_id = client.get(f"{API}/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]["id"]
    ciudad = client.post(
        f"{API}/ciudades", json={"nombre": "Tarija Bitacora", "departamento": "Tarija"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        f"{API}/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-BIT", "nombre": "Sucursal Bitacora", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]
    recepcion = client.post(
        f"{API}/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )
    assert recepcion.status_code == 201, recepcion.text
    return {
        "variante_id": variante_id,
        "sucursal_id": sucursal_id,
        "cajero_headers": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id),
    }


def _usuario_id(db, email: str) -> int:
    return db.scalar(select(Usuario.id).where(Usuario.email == email))


def _movimientos(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(MovimientoInventario))


def _vender_y_pagar(client, ctx, cantidad=4):
    venta = client.post(
        f"{API}/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    ).json()
    pago = client.post(
        f"{API}/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text
    return venta, pago.json()["pago"]["id"]


def _devolver(client, ctx, venta, cantidad, motivo=MOTIVO_LIBRE):
    return client.post(
        f"{API}/devoluciones",
        json={
            "venta_id": venta["id"],
            "motivo": motivo,
            "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": cantidad}],
        },
        headers=ctx["cajero_headers"],
    )


def _ajustar(client, headers, ctx, cantidad, observacion=None):
    return client.post(
        f"{API}/inventario/ajustes",
        json={
            "variante_id": ctx["variante_id"],
            "sucursal_id": ctx["sucursal_id"],
            "cantidad": cantidad,
            "observacion": observacion,
        },
        headers=headers,
    )


# ---- devolución (CU-17) ----------------------------------------------------------------------


def test_devolucion_registrada_deja_su_fila(client, contexto, db_session):
    venta, _ = _vender_y_pagar(client, contexto, cantidad=4)

    respuesta = _devolver(client, contexto, venta, 3)
    assert respuesta.status_code == 201, respuesta.text

    (fila,) = filas_de(db_session, "devolucion", "registrar")
    assert fila.entidad_id == respuesta.json()["id"]
    assert fila.usuario_id == _usuario_id(db_session, "cajero@example.com")
    assert fila.empresa_id == empresa_de(db_session)
    assert fila.ip
    assert fila.datos == {"venta_id": venta["id"], "unidades": 3}
    # La fila y la devolución quedaron confirmadas juntas.
    assert db_session.get(Devolucion, fila.entidad_id) is not None


def test_devolucion_no_copia_el_motivo_en_texto_libre(client, contexto, db_session):
    venta, _ = _vender_y_pagar(client, contexto)
    assert _devolver(client, contexto, venta, 1).status_code == 201

    (fila,) = filas_de(db_session, "devolucion", "registrar")
    exigir_datos_sin_sensibles(fila)
    assert set(fila.datos) == {"venta_id", "unidades"}
    assert "Perez" not in str(fila.datos) and "70012345" not in str(fila.datos)


def test_devolver_mas_de_lo_vendido_no_deja_fila_ni_movimiento(client, contexto, db_session):
    venta, _ = _vender_y_pagar(client, contexto, cantidad=2)
    assert _devolver(client, contexto, venta, 2).status_code == 201
    movimientos_antes = _movimientos(db_session)
    filas_antes = len(filas_de(db_session, "devolucion", "registrar"))

    segunda = _devolver(client, contexto, venta, 1)  # ya devolvió todo lo vendido

    assert segunda.status_code == 400
    assert len(filas_de(db_session, "devolucion", "registrar")) == filas_antes == 1
    assert _movimientos(db_session) == movimientos_antes


def test_devolucion_fallida_en_el_caso_de_uso_no_registra_antes_de_fallar(client, contexto, db_session):
    """Llamado directo (sin rollback del router): la fila solo se escribe al
    final, así que un fallo a mitad de camino no la deja ni siquiera pendiente."""
    venta, _ = _vender_y_pagar(client, contexto, cantidad=2)
    cajero_id = _usuario_id(db_session, "cajero@example.com")
    ctx_auditoria = ContextoAuditoria(usuario_id=cajero_id, empresa_id=empresa_de(db_session), ip="9.9.9.9")
    demasiado = DevolucionCrear(
        venta_id=venta["id"],
        motivo=None,
        detalle=[DevolucionDetalleCrear(venta_detalle_id=venta["detalle"][0]["id"], cantidad=3)],
    )

    with pytest.raises(DomainError):
        RegistrarDevolucion().ejecutar(db_session, cajero_id, demasiado, ctx_auditoria)

    assert filas_de(db_session, "devolucion") == []
    db_session.rollback()


# ---- anular el pago (CU-18) ------------------------------------------------------------------


def test_anular_pago_deja_su_fila_con_el_estado_anterior(client, admin_headers, contexto, db_session):
    venta, pago_id = _vender_y_pagar(client, contexto)

    respuesta = client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text

    (fila,) = filas_de(db_session, "venta", "anular_pago")
    assert fila.entidad_id == venta["id"]
    assert fila.usuario_id == _usuario_id(db_session, "admin@example.com")
    assert fila.empresa_id == empresa_de(db_session)
    assert fila.ip
    assert fila.datos == {"pago_id": pago_id, "estado_anterior": "pagada"}
    exigir_datos_sin_sensibles(fila)
    comprobante = client.get(f"{API}/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert comprobante["estado"] == "anulada"  # la anulación y la fila, en el mismo commit


def test_anular_un_pago_inexistente_no_deja_fila(client, admin_headers, contexto, db_session):
    respuesta = client.post(f"{API}/pagos/99999/anular", headers=admin_headers)

    assert respuesta.status_code == 404
    assert filas_de(db_session, "venta", "anular_pago") == []


def test_anular_dos_veces_deja_una_sola_fila(client, admin_headers, contexto, db_session):
    _, pago_id = _vender_y_pagar(client, contexto)
    assert client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers).status_code == 200

    segunda = client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers)

    assert segunda.status_code == 409
    assert len(filas_de(db_session, "venta", "anular_pago")) == 1


# ---- ajustes de inventario (CU-09) -----------------------------------------------------------


def test_ajuste_negativo_deja_movimiento_y_fila_en_el_mismo_commit(client, admin_headers, contexto, db_session):
    respuesta = _ajustar(client, admin_headers, contexto, -3, OBSERVACION_LIBRE)
    assert respuesta.status_code == 201, respuesta.text
    movimiento_id = respuesta.json()["id"]

    (fila,) = filas_de(db_session, "movimiento_inventario", "ajuste")
    assert fila.entidad_id == movimiento_id
    assert fila.usuario_id == _usuario_id(db_session, "admin@example.com")
    assert fila.empresa_id == empresa_de(db_session)
    assert fila.ip
    assert fila.datos == {
        "variante_id": contexto["variante_id"],
        "sucursal_id": contexto["sucursal_id"],
        "cantidad": -3,
        "tipo": "ajuste_negativo",
    }
    exigir_datos_sin_sensibles(fila)
    assert "Rosa" not in str(fila.datos)  # la observación libre queda solo en el kardex
    db_session.expire_all()
    movimiento = db_session.get(MovimientoInventario, movimiento_id)
    assert movimiento is not None and movimiento.cantidad == -3 and movimiento.saldo_post == 7


def test_ajuste_positivo_deja_movimiento_y_fila(client, admin_headers, contexto, db_session):
    respuesta = _ajustar(client, admin_headers, contexto, 5)
    assert respuesta.status_code == 201, respuesta.text

    (fila,) = filas_de(db_session, "movimiento_inventario", "ajuste")
    assert fila.entidad_id == respuesta.json()["id"]
    assert fila.datos["cantidad"] == 5 and fila.datos["tipo"] == "ajuste_positivo"
    db_session.expire_all()
    assert db_session.get(MovimientoInventario, fila.entidad_id).saldo_post == 15


def test_ajuste_por_el_endpoint_de_movimientos_tambien_se_audita(client, admin_headers, contexto, db_session):
    respuesta = client.post(
        f"{API}/inventario/movimientos",
        json={
            "variante_id": contexto["variante_id"],
            "sucursal_id": contexto["sucursal_id"],
            "tipo_movimiento_codigo": "ajuste_negativo",
            "cantidad": 2,
            "observacion": OBSERVACION_LIBRE,
        },
        headers=admin_headers,
    )
    assert respuesta.status_code == 201, respuesta.text

    (fila,) = filas_de(db_session, "movimiento_inventario", "ajuste")
    assert fila.entidad_id == respuesta.json()["id"]
    assert fila.datos["cantidad"] == -2 and fila.datos["tipo"] == "ajuste_negativo"
    assert "Rosa" not in str(fila.datos)


def test_un_movimiento_que_no_es_ajuste_no_deja_fila(client, admin_headers, contexto, db_session):
    # La recepción del fixture ya fue un movimiento normal, y tampoco dejó fila.
    assert filas_de(db_session, "movimiento_inventario") == []

    respuesta = client.post(
        f"{API}/inventario/movimientos",
        json={
            "variante_id": contexto["variante_id"],
            "sucursal_id": contexto["sucursal_id"],
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 4,
            "costo_unitario": "12.00",
        },
        headers=admin_headers,
    )

    assert respuesta.status_code == 201, respuesta.text
    assert filas_de(db_session, "movimiento_inventario") == []


def test_ajuste_negativo_por_mas_del_stock_no_deja_fila_ni_movimiento(client, admin_headers, contexto, db_session):
    movimientos_antes = _movimientos(db_session)

    respuesta = _ajustar(client, admin_headers, contexto, -11)  # hay 10

    assert respuesta.status_code == 409
    assert filas_de(db_session, "movimiento_inventario", "ajuste") == []
    assert _movimientos(db_session) == movimientos_antes


def test_ajuste_fallido_en_el_caso_de_uso_no_deja_fila_pendiente(client, admin_headers, contexto, db_session):
    """Llamado directo, sin el rollback del router: ni el movimiento ni la fila
    llegan a escribirse cuando la operación falla."""
    admin_id = _usuario_id(db_session, "admin@example.com")
    ctx_auditoria = ContextoAuditoria(usuario_id=admin_id, empresa_id=empresa_de(db_session), ip="9.9.9.9")
    movimientos_antes = _movimientos(db_session)

    with pytest.raises(ConflictoError):
        RegistrarMovimientoInventario().registrar_ajuste(
            db_session, contexto["variante_id"], contexto["sucursal_id"], -50, admin_id, None, ctx_auditoria
        )

    assert filas_de(db_session, "movimiento_inventario") == []
    assert _movimientos(db_session) == movimientos_antes
    db_session.rollback()


def test_sin_contexto_el_caso_de_uso_no_registra_nada(client, admin_headers, contexto, db_session):
    admin_id = _usuario_id(db_session, "admin@example.com")

    movimiento = RegistrarMovimientoInventario().registrar_ajuste(
        db_session, contexto["variante_id"], contexto["sucursal_id"], -1, admin_id, None
    )

    assert movimiento.id is not None and movimiento.cantidad == -1
    assert filas_de(db_session, "movimiento_inventario") == []

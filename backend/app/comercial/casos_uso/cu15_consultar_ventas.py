"""CU-15 — Consultar ventas

Absorbe los antiguos CU-26 (Consultar historial de compras) y CU-28
(Consultar ventas de la sucursal).

Actor: Cliente, Encargado de sucursal, Cajero.
Precondición: sesión iniciada. El cliente consulta su historial; el
personal (con el permiso ventas.gestionar_sucursal, solo de su sucursal
salvo alcance global, ver plataforma.politicas) consulta las ventas de su
sucursal.
Postcondición: el cliente visualiza su historial de compras y el
comprobante de la compra elegida; el personal conoce las ventas y los
ingresos de su sucursal.

Incluye ver el comprobante de una venta (antes un "extend" del catálogo, ya
no un CU aparte): es la misma consulta con más detalle."""

from sqlalchemy.orm import Session

from app.comercial.models import Venta
from app.comercial.politicas import obtener_comprobante
from app.comercial.repository import VentaRepository
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_perfil_cliente


# ---- Consultar historial de compras (antiguo CU-26) ----

class ConsultarHistorialCompras:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def obtener_comprobante(self, db: Session, venta_id: int, usuario_id: int) -> Venta:
        return obtener_comprobante(db, venta_id, usuario_id)

    def listar_mis_compras(self, db: Session, usuario_id: int) -> list[Venta]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._ventas.listar_por_cliente(db, cliente.id)


# ---- Consultar ventas de la sucursal (antiguo CU-28) ----

class ConsultarVentasSucursal:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def ejecutar(self, db: Session, sucursal_id: int, usuario_id: int) -> list[Venta]:
        plataforma_politicas.obtener_sucursal(db, sucursal_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._ventas.listar_por_sucursal(db, sucursal_id)

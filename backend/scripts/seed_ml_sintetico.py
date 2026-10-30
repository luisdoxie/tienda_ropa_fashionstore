"""Carga el historial de ventas SINTÉTICO de una empresa (E11, paso 6) como datos reales de negocio: ventas con su
detalle y su pago, devoluciones, promociones y clientes. Así los reportes convencionales, los generativos (CU-23) y
el ML (CU-24) leen lo mismo y muestran cifras coherentes. El generador es `app.inteligencia.ml.sintetico` (puro,
determinista: misma empresa y misma semilla => el mismo historial).

Por qué NO pasa por los casos de uso de venta: `registrar_venta` no acepta fecha, aparta y descuenta stock y bloquea
filas; para ~9.000 ventas históricas sería lento y dejaría el stock inconsistente (el stock es una foto ACTUAL, no un
historial). Por eso escribe con el ORM, igual que `scripts.seed_demo`. NO toca `stock`, `movimiento_inventario` ni
kardex: las ventas sintéticas no descuentan inventario (deliberado).

Lo sintético se reconoce SIN columna nueva: prefijo `SIN-` en el código de la venta, `DSN-` en el de la devolución,
`[SIN] ` en el nombre de la promoción y el dominio `@sintetico.<empresa>.fashionstore.bo` en el correo de los
clientes (sus contraseñas se generan al azar UNA vez y se descartan: nadie puede iniciar sesión con ellos).
Nunca se ejecuta en una empresa real.

Idempotente: si la empresa ya tiene ventas `SIN-%`, lo dice y no inserta (no hay modo "rehacer": borrar sería un
DELETE físico, prohibido; para repetir se usa una base nueva). Por defecto es DRY-RUN: genera el historial en memoria
y cuenta lo que crearía. Para escribir hace falta --ejecutar. Contra fashionstore_dev solo con CONFIRMO_BASE_DEV=si.

Uso (desde backend/):
    python -m scripts.seed_ml_sintetico --empresa chaski-sport
    python -m scripts.seed_ml_sintetico --empresa chaski-sport --clientes 650 --semanas 78 --perfil A --ejecutar

Requiere la empresa ya poblada (scripts.poblar_demo): catálogo, al menos una tienda con su cajero y los estados de
venta y de pago. Variables: DATABASE_URL, JWT_SECRET_KEY (la exige Settings).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import secrets
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PREFIJO_VENTA = "SIN-"
PREFIJO_DEVOLUCION = "DSN-"
PREFIJO_PROMOCION = "[SIN] "
HORA_DE_LA_VENTA = dt.time(14, 0)  # 10:00 en Bolivia: el día en UTC y en hora local coincide
LOTE = 500
DOS_DECIMALES = Decimal("0.01")
SEMANAS_POR_DEFECTO = 78
CLIENTES_POR_DEFECTO = 650  # unas 9.400 ventas en 78 semanas: con menos, el ruido de cada semana tapa la señal


def _dinero(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)


def correo_cliente(codigo_empresa: str, n: int) -> str:
    return f"c{n:03d}@sintetico.{codigo_empresa}.fashionstore.bo"


@dataclass
class ResumenCarga:
    ya_existia: bool = False
    clientes: int = 0
    promociones: int = 0
    ventas: int = 0
    lineas: int = 0
    pagos: int = 0
    devoluciones: int = 0
    total_efectivo: Decimal = Decimal("0")


# ---- El catálogo real de la empresa, en la forma que entiende el generador --------------------------------------------


def catalogo_desde_la_base(db: Session):
    """Variantes activas con su precio y costo, categorías y las TIENDAS (no depósitos) con su cajero. Dentro de la
    empresa ya fijada en la sesión. El tamaño de cada tienda sale de su stock: la que más tiene, vende más."""
    from app.catalogo.models import Categoria, Producto, ProductoVariante, Stock
    from app.inteligencia.ml.sintetico import CatalogoSintetico, CategoriaCat, SucursalCat, VarianteCat
    from app.plataforma.models import Empleado, Rol, Sucursal, usuario_rol

    costos = {
        variante_id: costo
        for variante_id, costo in db.execute(select(Stock.variante_id, func.avg(Stock.costo_promedio)).group_by(Stock.variante_id))
    }
    variantes, categorias_usadas = [], set()
    for vid, pid, cid, precio_variante, precio_base in db.execute(
        select(ProductoVariante.id, ProductoVariante.producto_id, Producto.categoria_id, ProductoVariante.precio, Producto.precio_base)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .where(Producto.activo.is_(True), ProductoVariante.activo.is_(True))
        .order_by(ProductoVariante.id)
    ):
        precio = _dinero(precio_variante if precio_variante is not None else precio_base)
        costo = _dinero(costos[vid]) if costos.get(vid) else _dinero(precio * Decimal("0.45"))
        variantes.append(VarianteCat(vid, pid, cid, precio, costo))
        categorias_usadas.add(cid)
    if not variantes:
        sys.exit("La empresa no tiene productos con variantes activas (correr antes scripts.poblar_demo)")

    categorias = [
        CategoriaCat(cid, nombre)
        for cid, nombre in db.execute(select(Categoria.id, Categoria.nombre).where(Categoria.id.in_(categorias_usadas)).order_by(Categoria.id))
    ]
    stock_por_sucursal = dict(db.execute(select(Stock.sucursal_id, func.sum(Stock.cantidad_fisica)).group_by(Stock.sucursal_id)).all())
    rol_cajero = db.scalar(select(Rol.id).where(Rol.nombre == "cajero"))
    cajeros = {}
    if rol_cajero is not None:
        for empleado_id, sucursal_id in db.execute(
            select(Empleado.id, Empleado.sucursal_id)
            .join(usuario_rol, usuario_rol.c.usuario_id == Empleado.usuario_id)
            .where(usuario_rol.c.rol_id == rol_cajero, Empleado.activo.is_(True), Empleado.sucursal_id.is_not(None))
            .order_by(Empleado.id)
        ):
            cajeros.setdefault(sucursal_id, empleado_id)  # el primer cajero de cada sucursal
    tiendas = db.execute(
        select(Sucursal.id).where(Sucursal.activo.is_(True), Sucursal.es_deposito.is_(False)).order_by(Sucursal.id)
    ).scalars().all()
    con_cajero = [sid for sid in tiendas if sid in cajeros]
    if not con_cajero:
        sys.exit("Ninguna tienda de la empresa tiene un cajero activo (correr antes scripts.poblar_demo)")
    mayor = max(float(stock_por_sucursal.get(sid) or 0) for sid in con_cajero) or 1.0
    sucursales = tuple(
        SucursalCat(sid, cajeros[sid], max(0.3, float(stock_por_sucursal.get(sid) or 0) / mayor)) for sid in con_cajero
    )
    return CatalogoSintetico(tuple(variantes), sucursales, tuple(categorias))


# ---- La carga ------------------------------------------------------------------------------------------------------------


def cargar_historial(db: Session, historial, catalogo, codigo_empresa: str) -> ResumenCarga:
    """Inserta el historial en la empresa de la sesión. Una sola transacción: si algo falla no queda nada a medias.
    Es la misma función que usan las pruebas, con un historial reducido."""
    from app.comercial.models import (
        Devolucion,
        DevolucionDetalle,
        EstadoPago,
        EstadoVenta,
        MetodoPago,
        Pago,
        Promocion,
        PromocionAlcance,
        Venta,
        VentaDetalle,
    )
    from app.core.security import hash_password
    from app.plataforma.models import Cliente, Rol, Usuario

    resumen = ResumenCarga()
    if db.scalar(select(func.count()).select_from(Venta).where(Venta.codigo.like(f"{PREFIJO_VENTA}%"))):
        resumen.ya_existia = True
        return resumen

    estados = {e.codigo: e.id for e in db.scalars(select(EstadoVenta))}
    metodos = {m.codigo: m.id for m in db.scalars(select(MetodoPago))}
    pago_aprobado = db.scalar(select(EstadoPago.id).where(EstadoPago.codigo == "aprobado"))
    rol_cliente = db.scalar(select(Rol).where(Rol.nombre == "cliente"))
    faltan = [n for n, ok in (("estados de venta", bool(estados)), ("métodos de pago", bool(metodos)), ("estado de pago 'aprobado'", pago_aprobado is not None), ("rol 'cliente'", rol_cliente is not None)) if not ok]
    if faltan:
        sys.exit("Faltan datos base: " + ", ".join(faltan) + " (correr los seeds base y scripts.seed_seguridad)")
    costo_de = {v.variante_id: v.costo for v in catalogo.variantes}

    # 1. Clientes. La contraseña se genera al azar UNA vez y se descarta: el mismo hash en todos, y nadie la conoce.
    hash_descartado = hash_password(secrets.token_urlsafe(24))
    existentes = {
        email: uid
        for email, uid in db.execute(select(Usuario.email, Usuario.id).where(Usuario.email.like("c%@sintetico.%")))
    }
    cliente_por_n: dict[int, int] = {}
    pendientes = []
    for c in historial.clientes:
        email = correo_cliente(codigo_empresa, c.n)
        if email in existentes:  # una corrida anterior se cortó después de crear los clientes
            cliente_id = db.scalar(select(Cliente.id).where(Cliente.usuario_id == existentes[email]))
            if cliente_id is not None:
                cliente_por_n[c.n] = cliente_id
                continue
        pendientes.append(
            (c.n, Usuario(nombre=f"Cliente {c.n:03d}", apellido="Sintético", email=email, password_hash=hash_descartado, activo=True, roles=[rol_cliente]))
        )
    for i in range(0, len(pendientes), LOTE):
        trozo = pendientes[i : i + LOTE]
        db.add_all([u for _, u in trozo])
        db.flush()
        perfiles = [(n, Cliente(usuario_id=u.id)) for n, u in trozo]
        db.add_all([p for _, p in perfiles])
        db.flush()
        cliente_por_n.update({n: p.id for n, p in perfiles})
        resumen.clientes += len(trozo)

    # 2. Promociones (históricas: terminan antes de hoy, así no afectan a ninguna venta real de hoy en adelante).
    for p in historial.promociones:
        promocion = Promocion(
            nombre=p.nombre[:80], tipo="porcentaje", valor=p.porcentaje, fecha_inicio=p.fecha_inicio, fecha_fin=p.fecha_fin, activo=True
        )
        promocion.alcances.append(
            PromocionAlcance(categoria_id=p.alcance_id) if p.alcance == "categoria" else PromocionAlcance(producto_id=p.alcance_id)
        )
        db.add(promocion)
        resumen.promociones += 1
    db.flush()

    # 3. Ventas con su detalle y su pago, por lotes (un flush por lote, un solo commit al final).
    ventas_por_indice: dict[int, Venta] = {}
    for i in range(0, len(historial.ventas), LOTE):
        lote = historial.ventas[i : i + LOTE]
        objetos = []
        for v in lote:
            fecha = dt.datetime.combine(v.fecha, HORA_DE_LA_VENTA)
            lineas, bruto, descuento = [], Decimal("0"), Decimal("0")
            for linea in v.lineas:
                descuento_unitario = _dinero(linea.descuento / linea.cantidad)
                subtotal_linea = _dinero((linea.precio_unitario - descuento_unitario) * linea.cantidad)
                bruto += linea.precio_unitario * linea.cantidad
                descuento += descuento_unitario * linea.cantidad
                lineas.append(
                    VentaDetalle(
                        variante_id=linea.variante_id, cantidad=linea.cantidad, precio_unitario=linea.precio_unitario,
                        descuento_unitario=descuento_unitario, costo_unitario=costo_de.get(linea.variante_id),
                        subtotal=subtotal_linea,
                    )  # fmt: skip
                )
            venta = Venta(
                codigo=f"{PREFIJO_VENTA}{v.indice:08X}", canal=v.canal,
                cliente_id=cliente_por_n.get(v.cliente_n) if v.cliente_n is not None else None,
                sucursal_id=v.sucursal_id, cajero_id=v.cajero_id, estado_id=estados[v.estado], fecha=fecha,
                subtotal=_dinero(bruto), descuento=_dinero(descuento), costo_envio=Decimal("0"),
                total=_dinero(bruto - descuento), detalle=lineas,
            )  # fmt: skip
            objetos.append((v, venta))
        db.add_all([venta for _, venta in objetos])
        db.flush()
        pagos = []
        for v, venta in objetos:
            ventas_por_indice[v.indice] = venta
            resumen.lineas += len(venta.detalle)
            if v.estado != "anulada":  # una venta anulada no deja pago
                resumen.total_efectivo += venta.total
                pagos.append(Pago(venta_id=venta.id, metodo_pago_id=metodos[v.metodo_pago], estado_id=pago_aprobado, monto=venta.total, fecha=venta.fecha))
        db.add_all(pagos)
        db.flush()
        resumen.ventas += len(objetos)
        resumen.pagos += len(pagos)

    # 4. Devoluciones aprobadas, sobre líneas que de verdad se vendieron (nunca más unidades de las vendidas).
    devueltas = []
    for n, d in enumerate(historial.devoluciones):
        venta = ventas_por_indice.get(d.venta_indice)
        if venta is None:
            continue
        detalle = []
        for variante_id, cantidad in d.lineas:
            linea = next((x for x in venta.detalle if x.variante_id == variante_id), None)
            if linea is not None:
                detalle.append(DevolucionDetalle(venta_detalle_id=linea.id, cantidad=min(cantidad, linea.cantidad)))
        if detalle:
            devueltas.append(
                Devolucion(
                    codigo=f"{PREFIJO_DEVOLUCION}{n:08X}", venta_id=venta.id, fecha=dt.datetime.combine(d.fecha, HORA_DE_LA_VENTA),
                    motivo="Devolución del historial sintético", estado="aprobada", detalle=detalle,
                )  # fmt: skip
            )
    for i in range(0, len(devueltas), LOTE):
        db.add_all(devueltas[i : i + LOTE])
        db.flush()
    resumen.devoluciones = len(devueltas)
    db.commit()
    return resumen


# ---- Entrada -----------------------------------------------------------------------------------------------------------------


def generar(db: Session, codigo_empresa: str, *, semanas: int, clientes: int, perfil: str, semilla: int, fin: dt.date):
    from app.inteligencia.ml.sintetico import ConfigSintetico, generar_historial

    catalogo = catalogo_desde_la_base(db)
    historial = generar_historial(
        catalogo, ConfigSintetico(semilla=semilla, fin=fin, semanas=semanas, n_clientes=clientes, perfil=perfil, codigo_empresa=codigo_empresa)
    )
    return catalogo, historial


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--empresa", required=True, help="Código de la empresa (por ejemplo chaski-sport)")
    parser.add_argument("--semanas", type=int, default=SEMANAS_POR_DEFECTO)
    parser.add_argument("--clientes", type=int, default=CLIENTES_POR_DEFECTO)
    parser.add_argument("--perfil", choices=("A", "B"), default="A", help="Cambia los pesos de categorías, la tendencia y la mezcla de clientes")
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--fin", type=dt.date.fromisoformat, help="Último día del historial (por defecto, ayer)")
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args(argv)

    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import engine
    from app.core.tiempo import hoy_utc
    from scripts._empresa import abrir_sesion
    from scripts.poblar_demo import exigir_base_segura

    base = engine.url.database
    print(f"Base destino: {base} ({'local' if engine.url.host in (None, '', 'localhost', '127.0.0.1') else 'remota'})")
    exigir_base_segura(base, args.ejecutar, os.environ.get("CONFIRMO_BASE_DEV"))
    fin = args.fin or hoy_utc() - dt.timedelta(days=1)

    db, empresa = abrir_sesion(args.empresa)
    try:
        catalogo, historial = generar(db, empresa.codigo, semanas=args.semanas, clientes=args.clientes, perfil=args.perfil, semilla=args.semilla, fin=fin)
        lineas = sum(len(v.lineas) for v in historial.ventas)
        print(
            f"Historial generado en memoria ({args.semanas} semanas hasta {fin}, perfil {args.perfil}, semilla {args.semilla}): "
            f"{len(historial.ventas)} ventas, {lineas} líneas, {len(historial.devoluciones)} devoluciones, "
            f"{len(historial.promociones)} promociones, {len(historial.clientes)} clientes."
        )
        print(f"Catálogo: {len(catalogo.variantes)} variantes en {len(catalogo.categorias)} categorías; tiendas: {len(catalogo.sucursales)}.")
        if not args.ejecutar:
            print("(dry-run: no se escribió nada; agregar --ejecutar)")
            return
        resumen = cargar_historial(db, historial, catalogo, empresa.codigo)
    finally:
        db.close()
    if resumen.ya_existia:
        print(f"La empresa '{empresa.codigo}' ya tiene ventas {PREFIJO_VENTA}%: no se inserta nada (para repetir, usar una base nueva).")
        return
    print(
        f"Cargado: {resumen.clientes} clientes, {resumen.promociones} promociones, {resumen.ventas} ventas, "
        f"{resumen.lineas} líneas, {resumen.pagos} pagos y {resumen.devoluciones} devoluciones "
        f"(ventas efectivas por Bs {resumen.total_efectivo:,.2f}). No se tocó el stock."
    )


if __name__ == "__main__":
    main()

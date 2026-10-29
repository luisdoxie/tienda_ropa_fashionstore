"""Pobla la plataforma con las organizaciones de demostración (`scripts.demo_organizaciones`).

Por cada organización, en este orden y por los casos de uso (nunca INSERT a mano):
  1. el plan Estándar (una sola vez, como dato: lo crea el CU-04 como lo haría el
     superadministrador);
  2. la empresa con su suscripción, su administrador y los catálogos base (CU-04), o
     la que ya existe (FashionStore la crea la migración; Boutique Andina, scripts.seed_empresas_prueba);
  3. sus sucursales (cada una en su ciudad, con coordenadas) y su personal (CU-03 y CU-02);
  4. 5 clientes de demostración;
  5. sus productos con foto y probador (scripts.seed_prendas_probador.cargar_prenda: CU-05 y CU-10);
  6. su stock inicial, DISTINTO en cada sucursal y variante, por una recepción de mercadería
     (CU-08, queda en el kardex), y sus límites de stock.

Por defecto NO escribe nada (dry-run): muestra lo que haría. Para escribir hace falta --ejecutar.
Es idempotente y reanudable: cada entidad tiene su clave natural y se omite si ya existe.
No toca el historial de ventas (eso es de scripts.seed_ml_sintetico, E11).

Uso (desde backend/):
    python -m scripts.poblar_demo --origen "<carpeta con catalogo.json, JPG y overlays/>"
    python -m scripts.poblar_demo --origen "<carpeta>" --solo chaski-sport --ejecutar
    python -m scripts.poblar_demo --origen "<carpeta>" --ejecutar --sin-fotos     (sin Cloudinary)

Variables de entorno: DATABASE_URL, JWT_SECRET_KEY (la exige Settings) y, con --ejecutar,
SEED_PASSWORD_INICIAL (contraseña inicial de todos los usuarios creados, entre 8 y 72
caracteres; o --clave-por-organizacion para que cada una use <Iniciales>.<Nombre>.2026) y, salvo
--sin-fotos, CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET.
La contraseña de SEED_PASSWORD_INICIAL no se recibe por argumento ni se imprime. Contra fashionstore_dev solo corre con
CONFIRMO_BASE_DEV=si.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts import seed_demo, seed_empresas_prueba, seed_operativo, seed_prendas_probador
from scripts.demo_organizaciones import (
    AJUSTES_PLANES,
    CLIENTES_POR_ORGANIZACION,
    LIMITE_SUCURSALES,
    ORGANIZACIONES,
    PLAN_ESTANDAR,
    TALLAS_DEMO,
    TEMPORADA_DEMO,
    OrganizacionDemo,
    SucursalDemo,
)
from scripts.seed_operativo import HORARIO_TIENDA, Resumen

BASE_DE_DESARROLLO = "fashionstore_dev"
ANIO_DE_LA_CLAVE = 2026


RUTA_ACCESOS = seed_prendas_probador.DIR_BACKUPS / "accesos_demo.txt"  # backups/ está fuera de git


def iniciales_de(org: OrganizacionDemo) -> str:
    """Las mayúsculas del nombre: FashionStore -> FS, Chaski Sport -> CS."""
    return "".join(c for c in org.nombre if c.isupper())


def clave_de_organizacion(org: OrganizacionDemo) -> str:
    """La contraseña de los usuarios de una organización con `--clave-por-organizacion`:
    `<Iniciales>.<Nombre sin espacios>.<año>` (por ejemplo `CS.ChaskiSport.2026`). Es una clave de
    demostración predecible a propósito: nunca para una empresa real, y distinta de la del
    superadministrador."""
    return f"{iniciales_de(org)}.{org.nombre.replace(' ', '')}.{ANIO_DE_LA_CLAVE}"


def texto_de_accesos(organizaciones: list[OrganizacionDemo], url_web: str = "https://tienda-ropa-ashen.vercel.app") -> str:
    """El archivo de accesos: por organización, cómo entrar, la clave y todos los correos. NO incluye la
    contraseña del superadministrador (la define quien lo crea)."""
    lineas = [
        "ACCESOS DE LA DEMOSTRACION (claves predecibles a proposito; solo para la defensa)",
        "",
        "Como entrar al personal: web /admin/login  ->  empresa (el NOMBRE de abajo), correo y clave.",
        "Como entrar un cliente:  web /t/<codigo>  ->  Iniciar sesion con el correo y la clave de su tienda.",
        "Superadministrador: se entra en /admin/login sin empresa; su clave no esta en este archivo.",
        "",
    ]
    for org in organizaciones:
        lineas += [
            "=" * 78,
            f"{org.nombre}   (plan {org.plan}, {len(org.sucursales)} sucursales)",
            f"  Empresa en el login : {org.nombre}",
            f"  Tienda publica      : {url_web}/t/{org.codigo}",
            f"  CLAVE (todos)       : {clave_de_organizacion(org)}",
            "  Personal:",
        ]
        lineas += [f"    {persona.rol:20} {persona.email}" for persona in org.personal()]
        lineas += [
            "  Clientes demo:",
            "    " + ", ".join(org.email_cliente(n) for n in range(1, CLIENTES_POR_ORGANIZACION + 1)),
            "",
        ]
    return "\n".join(lineas) + "\n"


MARCA_FIN_SUPERADMIN = "=== FIN SUPERADMINISTRADOR ==="


def _bloque_superadmin(ruta: Path) -> str:
    """Si el archivo ya trae arriba el bloque del superadministrador (lo escribe a mano quien administra
    la plataforma; este script nunca conoce esa clave), se conserva al reescribir los demás accesos."""
    if not ruta.exists():
        return ""
    texto = ruta.read_text(encoding="utf-8")
    fin = texto.find(MARCA_FIN_SUPERADMIN)
    if fin == -1 or not texto.lstrip().startswith("SUPERADMINISTRADOR"):
        return ""
    return texto[: fin + len(MARCA_FIN_SUPERADMIN)].lstrip() + "\n\n"


def escribir_accesos(organizaciones: list[OrganizacionDemo], ruta: Path = RUTA_ACCESOS) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(_bloque_superadmin(ruta) + texto_de_accesos(organizaciones), encoding="utf-8")
    return ruta

# ---- Stock -------------------------------------------------------------------------------

UNIDADES_BASE = 12
FACTOR_TALLA = {"S": 0.6, "M": 1.0, "L": 1.0, "XL": 0.7}
PROBABILIDAD_AGOTADO = 0.04  # sin línea de recepción: no hay fila de stock
PROBABILIDAD_POCO = 0.08  # 1 o 2 unidades (bajo el mínimo de la sucursal)


def cantidad_stock(org_codigo: str, sucursal: SucursalDemo, producto_codigo: str, talla: str) -> int:
    """Unidades de una variante en una sucursal. Determinista (semilla propia por
    organización, sucursal, producto y talla; nunca `hash()` ni el azar global): la
    sucursal grande tiene más, el depósito 2 a 3 veces más, la M y la L más que la S y
    la XL, y unas pocas variantes quedan en 1 o 2 unidades o sin stock."""
    clave = f"{org_codigo}|{sucursal.codigo}|{producto_codigo}|{talla}".encode()
    azar = random.Random(int.from_bytes(hashlib.sha256(clave).digest()[:8], "big"))
    suerte = azar.random()
    if suerte < PROBABILIDAD_AGOTADO:
        return 0
    if suerte < PROBABILIDAD_AGOTADO + PROBABILIDAD_POCO:
        return azar.randint(1, 2)
    base = UNIDADES_BASE * sucursal.factor * FACTOR_TALLA.get(talla, 0.8) * azar.uniform(0.6, 1.4)
    return max(3, round(base))


def unidades_previstas(org: OrganizacionDemo, planes: list, sucursales: tuple[SucursalDemo, ...] | None = None) -> int:
    return sum(
        cantidad_stock(org.codigo, s, p.codigo, talla)
        for s in (sucursales if sucursales is not None else org.sucursales)
        for p in planes
        for talla in TALLAS_DEMO
    )


# ---- Apoyo ---------------------------------------------------------------------------------


def planes_de_prendas(org: OrganizacionDemo, origen: Path) -> list:
    """Las prendas de la organización, con su precio ya ajustado, en el orden de `org.prendas`."""
    planes = seed_prendas_probador.planificar(
        origen, set(org.prendas), factor_precio=org.factor_precio, temporada=TEMPORADA_DEMO
    )
    faltan = set(org.prendas) - {p.id_dataset for p in planes}
    if faltan:
        sys.exit(f"{org.nombre}: el catalogo.json no tiene las prendas {sorted(faltan)}")
    orden = {id_dataset: i for i, id_dataset in enumerate(org.prendas)}
    return sorted(planes, key=lambda p: orden[p.id_dataset])


def exigir_base_segura(nombre_base: str | None, ejecutar: bool, confirmo_dev: str | None) -> None:
    """No se escribe en la base de desarrollo sin una confirmación explícita."""
    if ejecutar and nombre_base == BASE_DE_DESARROLLO and confirmo_dev != "si":
        sys.exit(f"La base destino es {BASE_DE_DESARROLLO}: no se escribe sin CONFIRMO_BASE_DEV=si")


def _asegurar_plan_estandar(db: Session, ejecutar: bool, resumen: Resumen) -> None:
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarPlanes
    from app.plataforma.models import Plan
    from app.plataforma.schemas import PlanCrear

    if db.scalar(select(Plan.id).where(Plan.codigo == PLAN_ESTANDAR["codigo"])) is not None:
        resumen.existente("plan")
        return
    resumen.creado("plan")
    if ejecutar:
        GestionarPlanes().crear(db, PlanCrear(**PLAN_ESTANDAR))
        print(f"  plan {PLAN_ESTANDAR['codigo']} creado")


def _ajustar_planes(db: Session, ejecutar: bool, resumen: Resumen) -> None:
    """Sube a `AJUSTES_PLANES` los valores que difieran (solo con --ajustar-planes). Es la única
    parte de este script que cambia un plan ya guardado; pasa por el CU-04 y deja bitácora."""
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarPlanes
    from app.plataforma.models import Plan
    from app.plataforma.schemas import PlanActualizar

    for codigo, deseado in AJUSTES_PLANES.items():
        plan = db.scalar(select(Plan).where(Plan.codigo == codigo))
        if plan is None:  # el Estándar todavía no existe (dry-run): nace ya con sus valores
            continue
        cambios = {campo: valor for campo, valor in deseado.items() if getattr(plan, campo) != valor}
        if not cambios:
            resumen.existente("plan_ajustado")
            continue
        resumen.creado("plan_ajustado")
        if ejecutar:
            GestionarPlanes().actualizar(db, plan.id, PlanActualizar(**cambios))
            print(f"  plan {codigo} ajustado: {cambios}")


# ---- Empresa -----------------------------------------------------------------------------------


def _asegurar_empresa(db: Session, org: OrganizacionDemo, ejecutar: bool, password: str | None, resumen: Resumen) -> int | None:
    """Devuelve el id de la empresa, o None en dry-run si todavía no existe. Modo plataforma."""
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
    from app.plataforma.politicas import obtener_empresa_por_codigo
    from app.plataforma.schemas import AdministradorRegistrar, EmpresaRegistrar

    if org.origen == "boutique":
        seed_empresas_prueba._fusionar(resumen, seed_empresas_prueba.sembrar_boutique(db, ejecutar, password))
        empresa = obtener_empresa_por_codigo(db, org.codigo)
        return empresa.id if empresa is not None else None

    empresa = obtener_empresa_por_codigo(db, org.codigo)
    if empresa is not None:
        if not empresa.activo:
            sys.exit(f"La empresa '{org.codigo}' está inactiva: reactivarla antes de seguir")
        resumen.existente("empresa")
        return empresa.id
    if org.origen == "migracion":
        sys.exit(f"No existe la empresa '{org.codigo}' (la crea la migración multitenant E01)")

    resumen.creado("empresa")
    resumen.creado("suscripcion")
    resumen.creado("catalogos_base")
    if not ejecutar:
        return None
    admin = org.personal()[0]
    respuesta = GestionarEmpresas().registrar(
        db,
        EmpresaRegistrar(
            nombre=org.nombre,
            plan_codigo=org.plan,
            color_acento=org.color_acento,
            administrador=AdministradorRegistrar(
                nombre=admin.nombre, apellido=admin.apellido, email=admin.email, telefono=admin.telefono,
                password=password,
            ),
        ),
    )
    print(f"  empresa {respuesta.codigo} registrada id={respuesta.id} (plan {respuesta.plan_codigo})")
    return respuesta.id


def _asegurar_color_acento(db: Session, org: OrganizacionDemo, empresa_id: int, ejecutar: bool, resumen: Resumen) -> None:
    """Solo si la empresa todavía no tiene color: uno que alguien cambió a mano se respeta."""
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
    from app.plataforma.politicas import obtener_empresa_por_codigo
    from app.plataforma.schemas import EmpresaActualizar

    if org.color_acento is None:
        return
    empresa = obtener_empresa_por_codigo(db, org.codigo)
    if empresa is None or empresa.color_acento is not None:
        resumen.existente("color_acento")
        return
    resumen.creado("color_acento")
    if ejecutar:
        GestionarEmpresas().actualizar(db, empresa_id, EmpresaActualizar(color_acento=org.color_acento))


# ---- Sucursales, personal y clientes (dentro de la empresa) ----------------------------------------


def _sembrar_sucursales(db: Session, org: OrganizacionDemo, ejecutar: bool, resumen: Resumen) -> dict[str, int | None]:
    """Una llamada de `seed_operativo.seed_sucursales` por ciudad (esa función recibe una sola)."""
    from app.plataforma.models import Ciudad

    por_ciudad: dict[tuple[str, str], list[SucursalDemo]] = {}
    for s in org.sucursales:
        por_ciudad.setdefault(s.ciudad, []).append(s)
    ids: dict[str, int | None] = {}
    for (nombre, departamento), grupo in por_ciudad.items():
        ciudad_id = db.scalar(select(Ciudad.id).where(Ciudad.nombre == nombre, Ciudad.departamento == departamento))
        if ciudad_id is None:
            if ejecutar:
                sys.exit(f"Falta la ciudad {nombre} en la empresa '{org.codigo}'")
            resumen.creado("sucursal", len(grupo))
            ids.update({s.codigo: None for s in grupo})
            continue
        ids.update(seed_operativo.seed_sucursales(db, ciudad_id, ejecutar, resumen, [s.como_seed() for s in grupo]))
    return ids


def _sembrar_clientes(db: Session, org: OrganizacionDemo, password: str | None, ejecutar: bool, resumen: Resumen) -> None:
    seed_empresas_prueba._sembrar_clientes(
        db, seed_demo.CLIENTES[:CLIENTES_POR_ORGANIZACION], org.email_cliente, password, ejecutar, resumen
    )


def _asegurar_proveedor(db: Session, org: OrganizacionDemo, ejecutar: bool, resumen: Resumen) -> int | None:
    from app.catalogo.casos_uso.cu08_gestionar_abastecimiento import GestionarProveedores
    from app.catalogo.models import Proveedor
    from app.catalogo.schemas import ProveedorCrear

    nombre, nit = org.proveedor
    proveedor = db.scalar(select(Proveedor).where(Proveedor.nit == nit))
    if proveedor is not None and not proveedor.activo:
        sys.exit(f"El proveedor NIT {nit} existe pero está inactivo: reactivarlo a mano")
    if proveedor is not None:
        resumen.existente("proveedor")
        return proveedor.id
    resumen.creado("proveedor")
    if not ejecutar:
        return None
    proveedor = GestionarProveedores().crear(
        db,
        ProveedorCrear(
            nombre=nombre, nit=nit, contacto="Atencion a clientes", telefono="33300000",
            email=f"ventas@{org.dominio}", direccion=f"Zona industrial, {org.sucursales[0].ciudad[0]}",
        ),
    )
    return proveedor.id


# ---- Catálogo --------------------------------------------------------------------------------------


def _sembrar_catalogo(
    db: Session,
    planes: list,
    ejecutar: bool,
    con_fotos: bool,
    manifiesto: seed_prendas_probador.Manifiesto | None,
    resumen: Resumen,
) -> None:
    from app.catalogo.models import Producto

    existentes = set(db.scalars(select(Producto.codigo).where(Producto.codigo.in_([p.codigo for p in planes]))))
    resumen.existente("producto", len(existentes))
    for plan in planes:
        if plan.codigo in existentes:
            continue
        resumen.creado("producto")
        resumen.creado("variante", len(TALLAS_DEMO))
        if con_fotos:
            resumen.creado("foto")
            if plan.admite_probador:
                resumen.creado("overlay", len(TALLAS_DEMO))
    if not ejecutar:
        return
    ctx = seed_prendas_probador.preparar_contexto(db, TALLAS_DEMO, manifiesto)
    for plan in planes:
        seed_prendas_probador.cargar_prenda(db, plan, ctx, con_fotos=con_fotos)


# ---- Stock ------------------------------------------------------------------------------------------


def _variantes_de(db: Session, planes: list) -> list[tuple[int, str, str, object]]:
    """(variante_id, código de producto, código de talla, precio) de las variantes activas
    de las prendas de la organización, en orden estable."""
    from app.catalogo.models import Producto, ProductoVariante, Talla

    filas = db.execute(
        select(ProductoVariante.id, Producto.codigo, Talla.codigo, ProductoVariante.precio, Producto.precio_base)
        .join(Producto, Producto.id == ProductoVariante.producto_id)
        .join(Talla, Talla.id == ProductoVariante.talla_id)
        .where(Producto.codigo.in_([p.codigo for p in planes]), ProductoVariante.activo.is_(True))
        .order_by(ProductoVariante.id)
    ).all()
    return [(vid, pcodigo, talla, precio if precio is not None else base) for vid, pcodigo, talla, precio, base in filas]


def _codigo_recepcion(db: Session, sucursal_codigo: str) -> str:
    from app.catalogo.models import Recepcion

    codigo, n = f"RD-{sucursal_codigo}", 1
    while db.scalar(select(Recepcion.id).where(Recepcion.codigo == codigo)) is not None:
        n += 1
        codigo = f"RD-{sucursal_codigo}-{n}"
    return codigo


def _quien_recibe(org: OrganizacionDemo, sucursal: SucursalDemo) -> str:
    """El encargado de la sucursal; en un depósito (sin personal), el administrador."""
    for persona in org.personal():
        if persona.rol == "encargado_sucursal" and persona.sucursal_codigo == sucursal.codigo:
            return persona.email
    return org.admin_email


def _sembrar_stock(
    db: Session,
    org: OrganizacionDemo,
    planes: list,
    sucursales: dict[str, int | None],
    usuarios: dict[str, int | None],
    empleados: dict[str, int | None],
    proveedor_id: int | None,
    ejecutar: bool,
    resumen: Resumen,
) -> None:
    """Una recepción por sucursal con las variantes que todavía no tienen fila de stock en
    ella. Así una corrida posterior con prendas nuevas solo recibe las nuevas."""
    from decimal import ROUND_HALF_UP, Decimal

    from app.catalogo.casos_uso.cu08_gestionar_abastecimiento import RegistrarRecepcionMercaderia
    from app.catalogo.models import Stock
    from app.catalogo.schemas import RecepcionCrear, RecepcionDetalleCrear

    variantes = _variantes_de(db, planes)
    cu_recepcion = RegistrarRecepcionMercaderia()
    for s in org.sucursales:
        sucursal_id = sucursales.get(s.codigo)
        if not variantes or sucursal_id is None:  # dry-run con el catálogo o la sucursal sin crear
            resumen.creado("recepcion")
            resumen.creado("unidades", unidades_previstas(org, planes, (s,)))
            continue
        con_stock = set(db.scalars(select(Stock.variante_id).where(Stock.sucursal_id == sucursal_id)))
        detalle = []
        for variante_id, producto_codigo, talla, precio in variantes:
            if variante_id in con_stock:
                continue
            cantidad = cantidad_stock(org.codigo, s, producto_codigo, talla)
            if cantidad > 0:
                costo = (Decimal(precio) * org.costo_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                detalle.append(RecepcionDetalleCrear(variante_id=variante_id, cantidad=cantidad, costo_unitario=costo))
        if not detalle:
            resumen.existente("recepcion")
            continue
        resumen.creado("recepcion")
        resumen.creado("unidades", sum(d.cantidad for d in detalle))
        if not ejecutar:
            continue
        quien = _quien_recibe(org, s)
        codigo = _codigo_recepcion(db, s.codigo)
        cu_recepcion.registrar(
            db,
            RecepcionCrear(
                codigo=codigo,
                proveedor_id=proveedor_id,
                sucursal_id=sucursal_id,
                observacion="Stock inicial (poblar_demo)",
                detalle=detalle,
            ),
            empleado_id=empleados.get(quien),
            creado_por=usuarios[quien],
        )
        print(f"  {codigo} recibida ({sum(d.cantidad for d in detalle)} unidades)")


def _fijar_limites_de_stock(
    db: Session, org: OrganizacionDemo, sucursales: dict[str, int | None], usuarios: dict[str, int | None],
    ejecutar: bool, resumen: Resumen,
) -> None:
    """Mínimo y máximo de cada fila de stock que todavía no los tiene."""
    from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarInventarioGlobal
    from app.catalogo.models import Stock

    cu_inventario = ConsultarInventarioGlobal()
    for s in org.sucursales:
        sucursal_id = sucursales.get(s.codigo)
        if sucursal_id is None:
            continue
        # list(): actualizar_limites hace commit, no se itera un cursor abierto.
        sin_limites = list(db.scalars(select(Stock.id).where(Stock.sucursal_id == sucursal_id, Stock.stock_maximo.is_(None))))
        resumen.creado("limites_stock", len(sin_limites))
        if ejecutar:
            for stock_id in sin_limites:
                cu_inventario.actualizar_limites(db, usuarios[org.admin_email], stock_id, s.stock_minimo, s.stock_maximo)


# ---- Una organización ---------------------------------------------------------------------------------


def _previsto(org: OrganizacionDemo, planes: list, con_fotos: bool, resumen: Resumen) -> None:
    """Dry-run con la empresa todavía inexistente: lo que se crearía dentro. En Boutique Andina
    (que crea seed_empresas_prueba) solo lo que suma esta etapa: prendas con foto y su stock."""
    if org.origen != "boutique":
        personal = org.personal()
        resumen.creado("sucursal", len(org.sucursales))
        resumen.creado("horario_sucursal", len(HORARIO_TIENDA) * len(org.tiendas))
        resumen.creado("usuario", len(personal) - 1)  # el administrador lo crea el registro de la empresa
        resumen.creado("usuario_rol", len(personal) - 1)
        resumen.creado("empleado", sum(p.sucursal_codigo is not None for p in personal))
        resumen.creado("cliente", CLIENTES_POR_ORGANIZACION)
        resumen.creado("cliente.perfil", CLIENTES_POR_ORGANIZACION)
        resumen.creado("proveedor")
    resumen.creado("categoria", len({p.categoria for p in planes}) + 1)
    resumen.creado("color", len({p.color for p in planes}))
    resumen.creado("producto", len(planes))
    resumen.creado("variante", len(planes) * len(TALLAS_DEMO))
    if con_fotos:
        resumen.creado("foto", len(planes))
        resumen.creado("overlay", sum(p.admite_probador for p in planes) * len(TALLAS_DEMO))
    resumen.creado("recepcion", len(org.sucursales))
    resumen.creado("unidades", unidades_previstas(org, planes))


def sembrar_organizacion(
    db: Session,
    org: OrganizacionDemo,
    planes: list,
    *,
    ejecutar: bool,
    password: str | None,
    con_fotos: bool,
    manifiesto: seed_prendas_probador.Manifiesto | None,
) -> Resumen:
    """Modo plataforma al entrar y al salir; cada paso interno corre dentro de la empresa."""
    from app.core.tenant import en_empresa

    resumen = Resumen()
    empresa_id = _asegurar_empresa(db, org, ejecutar, password, resumen)
    if empresa_id is None:
        _previsto(org, planes, con_fotos, resumen)
        return resumen

    estado = seed_empresas_prueba._leer_estado(db, empresa_id, org.admin_email)
    seed_empresas_prueba._asegurar_base(db, empresa_id, estado, ejecutar, resumen)
    seed_empresas_prueba._asegurar_plan(db, empresa_id, org.plan, estado, ejecutar, resumen)
    _asegurar_color_acento(db, org, empresa_id, ejecutar, resumen)

    with en_empresa(db, empresa_id):
        sucursales = _sembrar_sucursales(db, org, ejecutar, resumen)
        usuarios, empleados = seed_operativo.seed_staff(
            db, sucursales, password, ejecutar, resumen, staff=org.personal()
        )
        _sembrar_clientes(db, org, password, ejecutar, resumen)
        proveedor_id = _asegurar_proveedor(db, org, ejecutar, resumen)
        _sembrar_catalogo(db, planes, ejecutar, con_fotos, manifiesto, resumen)
        _sembrar_stock(db, org, planes, sucursales, usuarios, empleados, proveedor_id, ejecutar, resumen)
        _fijar_limites_de_stock(db, org, sucursales, usuarios, ejecutar, resumen)
    return resumen


# ---- Entrada ---------------------------------------------------------------------------------------------


def seed(
    db: Session,
    *,
    ejecutar: bool,
    password: str | None,
    origen: Path,
    organizaciones: tuple[OrganizacionDemo, ...] = ORGANIZACIONES,
    solo: set[str] | None = None,
    con_fotos: bool = True,
    manifiesto: seed_prendas_probador.Manifiesto | None = None,
    clave_por_organizacion: bool = False,
    ajustar_planes: bool = False,
) -> dict[str, Resumen]:
    """Siembra las organizaciones (o solo las de `solo`, por código). Devuelve el resumen por
    código de empresa. La sesión puede venir fijada en una empresa: se pasa a modo plataforma
    y al terminar se deja como estaba. Con `clave_por_organizacion` cada una usa
    `clave_de_organizacion` y se ignora `password`."""
    from app.core.tenant import empresa_de, en_modo_plataforma, fijar_empresa, fijar_plataforma

    desconocidas = (solo or set()) - {o.codigo for o in organizaciones}
    if desconocidas:
        sys.exit(f"No hay organizaciones con los códigos {sorted(desconocidas)}")
    elegidas = [o for o in organizaciones if not solo or o.codigo in solo]
    for org in elegidas:  # el límite del plan se respeta en los datos, no solo al crear
        limite = LIMITE_SUCURSALES.get(org.plan)
        if limite is not None and len(org.sucursales) > limite:
            sys.exit(f"{org.nombre}: {len(org.sucursales)} sucursales superan el límite {limite} del plan {org.plan}")
    planes_por_org = {org.codigo: planes_de_prendas(org, origen) for org in elegidas}

    if ejecutar:
        if clave_por_organizacion:
            for org in elegidas:
                seed_empresas_prueba._validar_password(clave_de_organizacion(org))
        else:
            seed_empresas_prueba._validar_password(password)
    anterior, era_plataforma = empresa_de(db), en_modo_plataforma(db)
    fijar_plataforma(db)
    resultados: dict[str, Resumen] = {}
    try:
        seed_empresas_prueba.verificar_precondiciones(db)
        resumen_plan = Resumen()
        _asegurar_plan_estandar(db, ejecutar, resumen_plan)
        if ajustar_planes:
            _ajustar_planes(db, ejecutar, resumen_plan)
        resultados["(plan estandar)"] = resumen_plan
        for org in elegidas:
            print(f"\n{org.nombre} ({org.plan})")
            resultados[org.codigo] = sembrar_organizacion(
                db, org, planes_por_org[org.codigo],
                ejecutar=ejecutar, password=clave_de_organizacion(org) if clave_por_organizacion else password,
                con_fotos=con_fotos, manifiesto=manifiesto,
            )  # fmt: skip
    finally:
        if era_plataforma:
            fijar_plataforma(db)
        else:
            fijar_empresa(db, anterior)
    return resultados


def imprimir(resultados: dict[str, Resumen], ejecutar: bool) -> None:
    for codigo, resumen in resultados.items():
        print(f"\n== {codigo} ==")
        resumen.imprimir(ejecutar)
    if not ejecutar:
        print("\n(dry-run: no se escribió nada; agregar --ejecutar)")


def imprimir_accesos(organizaciones: list[OrganizacionDemo], clave_por_organizacion: bool = False) -> None:
    """Cómo entrar a cada organización: el nombre de la empresa y los correos. La contraseña de
    SEED_PASSWORD_INICIAL NO se imprime; la derivada del nombre (`--clave-por-organizacion`) sí,
    porque es predecible y de demostración."""
    if clave_por_organizacion:
        print("\nAccesos (empresa, correo y contraseña de demostración derivada del nombre):")
    else:
        print("\nAccesos (empresa, correo; la contraseña es SEED_PASSWORD_INICIAL):")
    for org in organizaciones:
        clave = f"  contraseña: {clave_de_organizacion(org)}" if clave_por_organizacion else ""
        print(f"  {org.nombre} [{org.plan}]  tienda: /t/{org.codigo}{clave}")
        for persona in org.personal():
            print(f"      {persona.rol:20} {persona.email}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origen", type=Path, help="Carpeta con catalogo.json, los JPG y overlays/ (obligatorio salvo --solo-accesos)")
    parser.add_argument("--solo", nargs="*", help="Códigos de las organizaciones a sembrar (por defecto, todas)")
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    parser.add_argument("--sin-fotos", action="store_true", help="No sube fotos ni overlays (no usa Cloudinary)")
    parser.add_argument(
        "--clave-por-organizacion", action="store_true",
        help="Cada organización usa <Iniciales>.<Nombre>.2026 en vez de SEED_PASSWORD_INICIAL (solo demostración)",
    )
    parser.add_argument(
        "--ajustar-planes", action="store_true",
        help="Sube los planes Estándar y Profesional a AJUSTES_PLANES (copias y plazo de cambio crecientes)",
    )
    parser.add_argument(
        "--solo-accesos", action="store_true",
        help="Solo escribe backups/accesos_demo.txt con los correos y claves (no usa la base) y termina",
    )
    parser.add_argument(
        "--accesos-en", type=Path, default=RUTA_ACCESOS,
        help="Archivo donde se guardan los accesos (por defecto backend/backups/accesos_demo.txt, fuera de git)",
    )
    args = parser.parse_args(argv)

    if args.solo_accesos:  # no usa la base: se resuelve antes de importar la aplicación
        elegidas = [o for o in ORGANIZACIONES if not args.solo or o.codigo in args.solo]
        print(f"Accesos escritos en: {escribir_accesos(elegidas, args.accesos_en)}")
        return
    if args.origen is None:
        parser.error("--origen es obligatorio (carpeta con catalogo.json)")

    import app.main  # noqa: F401  (registra todos los modelos y configura Cloudinary)
    from app.core.database import SessionLocal, engine

    base = engine.url.database
    local = engine.url.host in (None, "", "localhost", "127.0.0.1")
    print(f"Base destino: {base} ({'local' if local else 'remota'})")
    exigir_base_segura(base, args.ejecutar, os.environ.get("CONFIRMO_BASE_DEV"))

    password = os.environ.get("SEED_PASSWORD_INICIAL")
    if args.ejecutar:
        if not args.clave_por_organizacion:
            seed_empresas_prueba._validar_password(password)
        if not args.sin_fotos:
            seed_prendas_probador.exigir_cloudinary()

    manifiesto = None
    if args.ejecutar and not args.sin_fotos:
        import datetime as dt

        marca = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        manifiesto = seed_prendas_probador.Manifiesto(
            # con el pid: dos procesos que arrancan en el mismo segundo no pisan el manifiesto del otro
            seed_prendas_probador.DIR_BACKUPS / f"manifiesto_demo_{marca}_{os.getpid()}.json",
            seed_prendas_probador.etiqueta_destino(),
        )
        print(f"Manifiesto: {manifiesto.ruta}")

    db = SessionLocal()
    try:
        resultados = seed(
            db, ejecutar=args.ejecutar, password=password, origen=args.origen,
            solo=set(args.solo) if args.solo else None, con_fotos=not args.sin_fotos, manifiesto=manifiesto,
            clave_por_organizacion=args.clave_por_organizacion, ajustar_planes=args.ajustar_planes,
        )  # fmt: skip
    finally:
        db.close()
    imprimir(resultados, args.ejecutar)
    elegidas = [o for o in ORGANIZACIONES if not args.solo or o.codigo in args.solo]
    imprimir_accesos(elegidas, args.clave_por_organizacion)
    if args.ejecutar and args.clave_por_organizacion:
        # Siempre las 8: con --solo el archivo no debe quedar con una sola organización.
        print(f"Accesos escritos en: {escribir_accesos(list(ORGANIZACIONES), args.accesos_en)}")


if __name__ == "__main__":
    main()

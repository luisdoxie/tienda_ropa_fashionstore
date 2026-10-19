# FashionStore

Plataforma de e-commerce de ropa con probador virtual con IA.
Proyecto académico de la materia Sistemas de Información II (UAGRM),
desarrollado con metodología ICONIX y modelado UML 2.5. El catálogo es de
25 casos de uso (22 implementados, 3 por construir).

FashionStore combina una tienda pública para clientes (catálogo, carrito,
checkout y reservas para probarse en sucursal), un back office administrativo
(gestión de productos, inventario, ventas, entregas, reportes) y una app móvil
con probador virtual de prendas generado con IA a partir de una foto del
cliente.

## Tecnologías

**Backend**
- Python 3.13 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic
- PostgreSQL (Railway en producción, local en desarrollo)
- Autenticación con JWT (PyJWT) y hash de contraseñas con `bcrypt`
- Límite de tasa de peticiones con `slowapi`
- Imágenes en Cloudinary
- IA con Groq (búsqueda por voz, recomendador y reporte por voz) y Vertex AI
  (probador generativo, detrás de `catalogo/generativo.py`; se agregará Decart
  como otro proveedor)
- Pagos con Libélula y PayPal (sandbox)

**Web** (back office + tienda pública)
- Angular 22 + PrimeNG
- Chatbot de Botpress (widget)

**Móvil** (cliente: catálogo, favoritos, carrito/checkout y probador virtual con IA)
- Flutter + Dart, Material 3
- Riverpod, go_router, Dio
- `image_picker` y `gal` para la foto del probador y guardar el resultado

**Despliegue**
- Backend y base de datos en Railway (sin Docker)
- Web en Vercel

## Estructura del repositorio

```
tienda_ropa/
├── backend/        API en FastAPI, monolito modular en capas
│   └── app/
│       ├── core/            infraestructura: CRUD base, seguridad JWT, permisos,
│       │                    tiempo, códigos, excepciones
│       ├── plataforma/      seguridad (usuarios, roles, permisos, autenticación),
│       │                    organización (ciudades, sucursales, empleados) y
│       │                    notificaciones
│       ├── catalogo/        catálogo, inventario, abastecimiento y probador
│       │                    virtual (modo generativo)
│       ├── comercial/       reservas, ventas, pagos (Libélula, PayPal) y entregas
│       └── inteligencia/    recomendador, búsqueda por voz, reportes e indicadores
│   └── alembic/             migraciones de base de datos
│
├── web/             Angular — back office (admin/encargado/cajero) y tienda pública
│   └── src/app/
│       ├── core/            servicios, guards, interceptores, modelos
│       ├── layout/           layout del back office
│       └── features/         una carpeta por pantalla/módulo
│
├── mobile/          Flutter — app cliente con probador virtual con IA
│   └── lib/
│       ├── core/             red, router, tema
│       └── features/         asistente, auth, catalogo, compras, favoritos, notificaciones,
│                         probador, recomendador, reservas, splash, tracking, voz
│
├── docs/            esquema de base de datos (referencia, no se ejecuta) y plan
│                    de desarrollo
└── CLAUDE.md        reglas de arquitectura y convenciones del proyecto
```

Cada paquete del backend sigue siempre la misma estructura: `models.py`,
`schemas.py`, `repository.py`, `politicas.py`, `router.py` y `casos_uso/` (un
archivo por caso de uso, `cuXX_nombre.py`). Un paquete nunca consulta
directamente las tablas de otro: llama a sus casos de uso o a sus políticas.
Orden de dependencias: `core` ← `plataforma` ← `catalogo` ← `comercial` ←
`inteligencia`.

## Casos de uso del segundo parcial

| Paquete       | Casos de uso |
|---------------|--------------|
| plataforma    | CU-01 Autenticar y registrar usuarios · CU-02 Usuarios, roles y permisos · CU-03 Organización · **CU-04 Empresas, planes y suscripciones (por construir)** |
| catalogo      | CU-05 Catálogo · CU-06 Consultar y buscar · CU-07 Favoritos · CU-08 Abastecimiento · CU-09 Inventario · CU-10 Assets del probador · CU-11 Probar prenda con IA |
| comercial     | CU-12 Reservas · CU-13 Carrito y compra digital · CU-14 Venta presencial · CU-15 Consultar ventas · CU-16 Promociones · CU-17 Devoluciones y cambios · CU-18 Pagos · CU-19 Envíos y tarifas |
| inteligencia  | CU-20 Recomendar productos · CU-21 Buscar por voz · CU-22 Reportes e indicadores · CU-23 Reportes con IA (hoy reporte por voz, se amplía) · **CU-24 Analizar con Machine Learning (por construir)** |
| sincronizacion | **CU-25 Sincronizar operaciones offline (por construir; paquete por crear)** |

## Estado y hoja de ruta (segundo parcial)

El segundo parcial pide una plataforma SaaS multitenant, con PWA y app móvil
que funcionan sin conexión, reportes con IA y analítica con Machine Learning.

Hecho:
- Se quitó el modo espejo del probador (queda solo el modo generativo) con su
  migración. Respaldo en la etiqueta `respaldo-pre-quitar-espejo` y en la rama
  `respaldo-espejo-wip`.
- Backend reestructurado en 4 paquetes más `core`, con 25 casos de uso en el
  catálogo.
- Refactorización del backend y del móvil: seguridad, integridad de stock y de
  ventas, rendimiento y pruebas de red de seguridad.
- Cimientos para multitenant y offline: unidad de trabajo (`commit=False`),
  punto único de alcance por empresa en `CRUDBase`, constantes de permisos.

Por construir, en este orden:
1. Multitenant y planes (CU-04): empresa en cada tabla, filtro automático por
   empresa, llaves únicas por empresa.
2. Sincronización offline (CU-25): idempotencia, fecha de la operación y lotes
   atómicos. PWA con IndexedDB y app Flutter con SQLite, incluido el modo
   vendedor/cajero.
3. Reportes con IA (CU-23) y Machine Learning (CU-24); proveedor Decart para el
   probador.
4. Pruebas, rendimiento y documentación ICONIX.

Pruebas: 624 en el backend (`pytest`, SQLite en memoria) y 132 en el móvil
(`flutter test`).

## Desarrolladores

| Rol        | Integrante                     |
|------------|---------------------------------|
| Full stack | Luis Miguel Aguayo Quiroz       |
| Full stack | Alexander Osinaga Blanco        |

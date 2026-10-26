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
│       ├── inteligencia/    recomendador, búsqueda por voz, reportes e indicadores
│       └── sincronizacion/  operaciones hechas sin conexión (ventas de contado y
│                            reservas): lote idempotente y consulta de su estado
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
`inteligencia` (y `sincronizacion` sobre `comercial`).

## Casos de uso del segundo parcial

| Paquete       | Casos de uso |
|---------------|--------------|
| plataforma    | CU-01 Autenticar y registrar usuarios · CU-02 Usuarios, roles y permisos · CU-03 Organización · **CU-04 Empresas, planes y suscripciones (por construir)** |
| catalogo      | CU-05 Catálogo · CU-06 Consultar y buscar · CU-07 Favoritos · CU-08 Abastecimiento · CU-09 Inventario · CU-10 Assets del probador · CU-11 Probar prenda con IA |
| comercial     | CU-12 Reservas · CU-13 Carrito y compra digital · CU-14 Venta presencial · CU-15 Consultar ventas · CU-16 Promociones · CU-17 Devoluciones y cambios · CU-18 Pagos · CU-19 Envíos y tarifas |
| inteligencia  | CU-20 Recomendar productos · CU-21 Buscar por voz · CU-22 Reportes e indicadores · CU-23 Reportes con IA (hoy reporte por voz, se amplía) · **CU-24 Analizar con Machine Learning (por construir)** |
| sincronizacion | CU-25 Sincronizar operaciones offline (backend hecho: lotes idempotentes, descarga del paquete de datos, resolución de conflictos y plazo de 24 h para cambios; falta el cliente offline de la PWA y Flutter) |

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
- Modelo multitenant (etapa E01): tablas `empresa`, `plan` y `suscripcion`,
  `empresa_id` en las 50 tablas propias de cada empresa, llaves únicas por
  empresa, rol `superadministrador` y vistas SQL conscientes de la empresa. La
  base real tiene ahora 62 tablas.
- Aislamiento automático por empresa (etapa E02): filtro en un único punto
  (`core/tenant.py`) que falla cerrado, ids del cliente validados, tareas por
  empresa y 25 rutas públicas de la tienda `/api/v1/public/{codigo}/...`.
- Login con empresa y token con empresa (etapa E03): `POST /auth/login` con
  `{empresa, email, password}`, claim `empresa_id` en los tokens, bloqueo de
  cuenta tras 5 fallos, correo en minúsculas, token de recuperación de un solo
  uso, registro de clientes por tienda (`/public/{codigo}/registro`) y
  superadministrador de la plataforma creado solo con script.
- CU-04 Empresas, planes y suscripciones (etapa E04): registro de empresas (con
  su suscripción, su administrador y sus datos base en una transacción), planes
  Básico y Profesional con límites y funcionalidades configurables, estados de la
  suscripción (activa, suspendida, vencida, cancelada), bloqueo de las empresas
  sin suscripción activa, límite de sucursales por plan y semilla de dos empresas
  de prueba (`python -m scripts.seed_empresas_prueba`).
- Tienda pública por empresa en la web (etapa E15): página de la plataforma en
  `/` con las tiendas activas, cada tienda en `/t/<codigo>` con su nombre, logo y
  color de acento, sesión, carrito y checkout atados a una sola tienda, y
  redirecciones de las rutas viejas. `GET /public/{codigo}/tienda` trae
  `disponible`. El login del personal queda pendiente hasta la E16.

Por construir, en este orden:
1. Aislamiento verificado (E05) y bitácora de auditoría (E06).
2. Sincronización offline (CU-25): idempotencia, fecha de la operación y lotes
   atómicos. PWA con IndexedDB y app Flutter con SQLite, incluido el modo
   vendedor/cajero.
3. Reportes con IA (CU-23) y Machine Learning (CU-24); proveedor Decart para el
   probador.
4. Pruebas, rendimiento y documentación ICONIX.

Pruebas: 1251 en el backend, 132 en el web (`npm test`) y 132 en el móvil (`flutter test`). Las del backend
corren con `pytest`: 1223 en SQLite en memoria y 28 en PostgreSQL real
(`backend/tests/postgres/`: esquema, bloqueos de stock, cancelar contra
expirar reservas, deadlocks y migración multitenant con datos). Estas últimas se activan con la variable
`TEST_DATABASE_URL` apuntando a una base cuyo nombre termine en `_test`; si
falta, se omiten.

## Autenticación y variables de entorno

El inicio de sesión pide la empresa: `POST /api/v1/auth/login` con
`{"empresa": "Boutique Andina", "email": "...", "password": "..."}`. El nombre se
normaliza (minúsculas, sin tildes, guiones) y se busca en el código de la empresa;
sin `empresa` solo entra un superadministrador. Los tokens llevan el `empresa_id`.
Cambiar `JWT_SECRET_KEY` cierra TODAS las sesiones (revocación de emergencia).

| Variable | Para qué |
|----------|----------|
| `JWT_SECRET_KEY` | firma de los tokens; rotarla invalida todas las sesiones |
| `LOGIN_MAX_INTENTOS` (5), `LOGIN_VENTANA_SEGUNDOS` (900) | bloqueo por cuenta tras varios fallos (en memoria; vale con un solo worker) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_EMPRESA` | `python -m scripts.crear_admin`: administrador de una empresa |
| `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` | `python -m scripts.crear_superadmin` (contraseña de 12+ caracteres) |
| `SEED_PASSWORD_INICIAL` | `python -m scripts.seed_empresas_prueba --ejecutar`: contraseña inicial de los usuarios de las dos empresas de prueba (8+ caracteres; sin `--ejecutar` solo lista lo que haría) |
| `SUSCRIPCION_DIAS_POR_DEFECTO` (30) | vigencia de una suscripción nueva si no se indica fecha de vencimiento |

El superadministrador (sin empresa) solo se crea con ese script, una vez y como
comando único del servicio; después se quitan las dos variables. Con
`--restablecer` se cambia su contraseña. Ninguna ruta HTTP crea usuarios sin empresa.

## Desarrolladores

| Rol        | Integrante                     |
|------------|---------------------------------|
| Full stack | Luis Miguel Aguayo Quiroz       |
| Full stack | Alexander Osinaga Blanco        |

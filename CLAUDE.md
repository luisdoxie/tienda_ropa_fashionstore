# FashionStore — Contexto del proyecto

Plataforma de e-commerce de ropa con probador virtual con IA.
Proyecto académico, Sistemas II, UAGRM. Primer parcial: PUDS. Segundo parcial
(SaaS multitenant, offline, reportes con IA): ICONIX. Modelado UML 2.5.

## Stack
- Backend: Python 3.13 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic
- BD: PostgreSQL en Railway
- Web: Angular + PrimeNG (back office: admin, encargado, cajero; más una
  tienda pública para clientes: catálogo, registro/login, carrito y
  checkout — sin probador virtual)
- Móvil: Flutter + Dart, Material 3 (cliente: catálogo, favoritos,
  carrito/checkout y el probador virtual, exclusivo de esta app)
- Imágenes: Cloudinary
- IA: Groq (búsqueda por voz y recomendador)
- Chatbot: Botpress (widget en la web; el mismo bot en un WebView de la app móvil). Vive en la nube de
  Botpress: sus flujos no están en el repo y el backend no tiene endpoint de chat.
- Probador: generativo, detrás de `catalogo/generativo.py` (hoy Vertex AI; se
  agregará Decart API Platform como otra implementación). El modo espejo
  (cámara en vivo + google_mlkit_pose_detection + anclajes) se eliminó.
  Respaldo en la etiqueta `respaldo-pre-quitar-espejo` y la rama
  `respaldo-espejo-wip`.
- Pagos: Libélula y PayPal, ambos en sandbox
- Despliegue: Railway sin Docker, y Vercel para el Angular

## Arquitectura
Monolito modular en capas. 4 paquetes de negocio más `core` bajo `backend/app/`
(más `sincronizacion`, pendiente de crear, para el offline del segundo parcial):
- `plataforma`: seguridad (autenticación, usuarios, roles, permisos, clientes)
  y organización (ciudades, sucursales, empleados). Aquí viven también los
  modelos de empresa, plan y suscripción (multitenant) y su gestión (CU-04).
- `catalogo`: catálogo, inventario, abastecimiento y probador virtual
  (solo modo generativo).
- `comercial`: reservas, ventas, pagos y entregas.
- `inteligencia`: recomendador, búsqueda por voz, reportes e indicadores
  (luego reportes con IA y analítica ML).
- `core`: infraestructura técnica transversal. NO es un paquete de negocio: no
  tiene casos de uso, tablas ni router. En la documentación ICONIX solo aparece
  como paquete `«infraestructura»` en el diagrama de paquetes (y en los de
  arquitectura y despliegue). No se le hacen casos de uso, diagramas de
  robustez, de secuencia propios ni de dominio; si una operación de `core`
  interviene en un flujo, se muestra como parte del caso de uso del paquete
  de negocio que la invoca.

Cada paquete tiene esta estructura (un archivo por tipo; dentro de cada
archivo los bloques de cada dominio absorbido van marcados con
`# ---- Nombre ----`, p. ej. `# ---- Inventario ----` en `catalogo`):
  models.py       modelos SQLAlchemy (compartido por todo el paquete)
  schemas.py      schemas Pydantic (Crear, Actualizar, Respuesta)
  repository.py   acceso a datos (compartido)
  politicas.py    validaciones y reglas comunes del paquete (compartido)
  router.py       endpoints FastAPI (un único `routers`)
  casos_uso/      un archivo por caso de uso del catálogo (excepto en `core`,
                  que es infraestructura y no tiene casos_uso/)

## Convención de casos de uso
- Un archivo por caso de uso del catálogo, en `<paquete>/casos_uso/`.
- Nombre del archivo: cuXX_nombre_descriptivo.py, en minúsculas y con el
  número delante, para que el listado de la carpeta salga ordenado.
- El docstring del módulo empieza con "CU-XX — Nombre del caso de uso",
  seguido de actor, precondición y postcondición, y una línea "Absorbe los
  antiguos CU-..." cuando el caso agrupa casos del primer parcial.
- Un caso de uso se realiza con una o varias CLASES DE CONTROL dentro de su
  archivo (cada clase es un controlador del diagrama de robustez de ICONIX).
  Cada clase es pública y en PascalCase.
- Un caso de uso SIMPLE (una entidad, una operación, un actor) es una sola
  clase con un único método público `ejecutar()`.
- Un caso de uso de tipo "Gestionar X" hereda de CRUDBase, no varios archivos
  separados por operación.
- Un caso de uso COMPUESTO (agrupa varias entidades u operaciones relacionadas)
  puede tener varias clases de control en el mismo archivo (una por entidad
  o por flujo), o una sola clase con varios métodos públicos. No se parte
  un caso de uso del catálogo en dos archivos.
- Prohibido duplicar lógica entre casos de uso: si dos la necesitan, baja a
  repository.py (si es acceso a datos) o a politicas.py (si es validación o
  regla de negocio).
- Las relaciones <<include>> del modelo UML se implementan como llamadas de
  un caso de uso a otro, importando su clase. Nunca copiando el código.
- Un caso de uso puede llamar a casos de uso de otro paquete. Lo que sigue
  prohibido es consultar las tablas de otro paquete.
- Una operación que ningún CU-XX del catálogo nombra como caso de uso propio
  (ej. la actualización atómica de stock, la expiración automática de
  reservas, el cálculo de una tarifa de envío) NO se convierte en un CU
  nuevo: vive en politicas.py o repository.py del paquete correspondiente.
- El router instancia el caso de uso y llama a ejecutar() (o al método
  público que corresponda en un caso de uso compuesto). El router no
  contiene lógica de negocio.

## Trazabilidad con el modelo UML
El catálogo del segundo parcial es de 25 casos de uso (el primer parcial tenía
43; la equivalencia está en `C:\Desarrollo\examen\documento\2doParcial\`):
- plataforma: CU-01 Autenticar y registrar usuarios · CU-02 Gestionar
  usuarios, roles y permisos · CU-03 Gestionar organización · CU-04 Gestionar
  empresas, planes y suscripciones (`cu04_...`, 4 clases de control).
- catalogo: CU-05 Gestionar catálogo · CU-06 Consultar y buscar catálogo ·
  CU-07 Gestionar favoritos · CU-08 Gestionar abastecimiento · CU-09 Gestionar
  inventario · CU-10 Gestionar assets del probador · CU-11 Probar prenda con IA.
- comercial: CU-12 Gestionar reservas · CU-13 Gestionar carrito y compra
  digital · CU-14 Registrar venta presencial · CU-15 Consultar ventas · CU-16
  Gestionar promociones · CU-17 Gestionar devoluciones y cambios · CU-18
  Procesar pagos · CU-19 Gestionar envíos y tarifas.
- inteligencia: CU-20 Recomendar productos · CU-21 Buscar prendas por voz ·
  CU-22 Consultar reportes e indicadores · CU-23 Generar reportes con IA
  (hoy reporte por voz; se amplía) · CU-24 Analizar con Machine Learning
  (NUEVO, sin implementar).
- sincronizacion: CU-25 Sincronizar operaciones offline (NUEVO, sin
  implementar; paquete por crear).
El antiguo CU-22 del primer parcial (modo espejo) se retiró. Una operación que no sea un caso de
uso del catálogo no crea un CU nuevo: se resuelve en politicas.py o
repository.py, o se pregunta.

Algunas tablas del esquema (`docs/fashionstore_esquema.sql`) son soporte de
un caso de uso del catálogo pero no tienen su propio CU (ej. `orden_compra`,
que CU-08 referencia de forma opcional). Se implementan con su CRUD normal.

## Reglas obligatorias
1. Sin dependencias circulares entre paquetes.
   Orden de dependencias: `core` ← `plataforma` ← `catalogo` ← `comercial` ←
   `inteligencia` (y `sincronizacion` sobre `comercial`). Una excepción
   conocida y deliberada, ninguna otra: el import diferido evita el
   ImportError circular y el acceso siempre pasa por `politicas`/`casos_uso`
   público del otro paquete, nunca por su tabla.
     - `core` ↔ `plataforma`: `core/security.py` necesita resolver permisos
       (tablas de `plataforma`) para JWT/autorización; importa
       `plataforma.politicas` de forma diferida (dentro de cada función)
       porque `plataforma.repository` importa `core.security` a nivel de
       módulo.
   Dentro de un mismo paquete también hay ciclos entre archivos que se
   resuelven con import diferido (p. ej. `catalogo/repository.py` llama
   dentro del método a `catalogo/politicas.listar_variantes_con_stock`
   para el filtro `solo_disponibles` de CU-06).
2. Un paquete NUNCA consulta las tablas de otro paquete. Llama al caso de uso
   o a la política del otro paquete. Ejemplo: comercial llama a
   catalogo.politicas.actualizar_stock_operacion(), no hace UPDATE sobre
   stock.
3. Todo caso de uso de tipo "Gestionar X" hereda de core/crud_base.py y
   ocupa un solo archivo (si agrupa varias entidades del mismo dominio, el
   archivo tiene varias clases de control, ver la convención de casos de
   uso). No repetir código CRUD ni dividir un CRUD en varios casos de uso.
4. Todo cambio de esquema va en una migración de Alembic. Nunca a mano.
5. El router no toca la base de datos ni contiene lógica de negocio: solo
   instancia el caso de uso correspondiente y llama a ejecutar() (o al
   método público que corresponda en un caso de uso compuesto). Los casos
   de uso no saben de HTTP: no reciben Request ni devuelven Response,
   trabajan con schemas de Pydantic.
6. Toda operación que afecte stock va dentro de una transacción.
7. Nombres en español, tablas en singular, snake_case.
8. Borrado lógico con el campo `activo`. Nunca DELETE físico en tablas de negocio.
9. Los secretos van en variables de entorno. Nunca en el código.
10. El hash de contraseñas usa la librería `bcrypt` directamente.
    NO usar `passlib`: está sin mantenimiento y rompe con las versiones
    actuales de bcrypt.
11. La versión de Python es 3.13, fijada con `.python-version` en la raíz
    del backend para que el entorno local y Railway coincidan.
12. Un paquete nunca fija ni cambia la empresa de la sesión fuera de
    `core/tenant.py` (`fijar_empresa`). El `empresa_id` de un registro nuevo
    lo rellena el evento `before_flush` de ese módulo; no se asigna a mano.

## Esquema de base de datos
El esquema completo y definitivo está en `docs/fashionstore_esquema.sql`
(60 tablas en el SQL, que es el del primer parcial). La base real tiene 62:
las 59 de antes (`bitacora` está en el SQL pero nunca se implementó, y
`sesion_probador` se eliminó con el modo espejo) más `empresa`, `plan` y
`suscripcion` del segundo parcial, que no están en el SQL. No inventar
tablas ni columnas nuevas sin pedirlo explícitamente.
Ese archivo es documentación de referencia: NO se ejecuta contra la base.
Las tablas las crea Alembic a partir de los modelos.

## Multitenant
Una sola base compartida con aislamiento lógico por `empresa_id` (una sucursal
NO es un tenant: una empresa tiene varias). Estado: modelo y migración (E01),
filtrado automático por empresa (E02), login con empresa y claim `empresa_id`
en el token (E03) y CU-04 con planes y suscripciones (E04) hechos. El backend NO
se despliega solo: tras la E03 el login de la web y del móvil actuales no
funciona hasta que se adapten (E15, E16, E18).
- Clasificación de las 62 tablas: 50 propias de empresa (`empresa_id` NOT NULL,
  salvo `usuario`, donde NULL = superadministrador de la plataforma), 8
  globales del sistema (`permiso`, `rol`, `rol_permiso`, `tipo_movimiento`,
  `estado_reserva`, `estado_venta`, `metodo_pago`, `estado_pago`), `plan`
  (global), `empresa` (la raíz), `usuario_rol` (hereda del usuario) y
  `suscripcion` (de la empresa, con historial).
- Toda tabla nueva de negocio hereda `EmpresaMixin` (`core/tenant.py`) y se
  clasifica en `tests/plataforma/test_modelo_multitenant.py`: una tabla sin
  clasificar hace fallar esa prueba.
- Las llaves únicas de negocio (código de producto, SKU, código de sucursal,
  número de venta, correo de usuario, etc.) son únicas POR EMPRESA. Los
  superadministradores (sin empresa) tienen su propio índice único de correo.
- Roles y permisos son globales; el aislamiento está en `usuario.empresa_id` y
  en los datos. El rol `superadministrador` tiene `plataforma.gestionar`; el
  `administrador` de cada empresa NO lo tiene y recibe `empresa.gestionar`.
- Las vistas `vw_ventas_detalle` y `vw_inventario_consolidado` están en versión
  V2 (con `empresa_id`). Las constantes V1 de los `repository.py` están
  congeladas porque las usan migraciones históricas: no editarlas.
- Las migraciones de multitenant se escriben a mano. Nunca usar autogenerate
  sobre `stock` (propone mal la columna generada `cantidad_disponible`).
- Los scripts de seeds trabajan sobre una empresa (`--empresa <codigo>`, por
  defecto `fashionstore`) mediante `scripts/_empresa.py`.

### Cómo se filtra por empresa (`core/tenant.py`)
- La empresa de la petición vive en `Session.info`, y solo `core/tenant.py` la
  escribe (`fijar_empresa`). Cada petición tiene su sesión (`get_db`).
- Un evento `do_orm_execute` agrega `empresa_id = <empresa de la sesión>` a toda
  consulta ORM (select, update, delete, count, joins, subconsultas) sobre una
  tabla de empresa. FALLA CERRADO: sin empresa en la sesión la consulta no se
  ejecuta (`EmpresaNoDefinidaError`, 401) y en modo superadministrador tampoco
  (`ModoPlataformaError`, 403). Nadie tiene que acordarse de filtrar.
- Un recurso de otra empresa responde 404, igual que uno inexistente. Nunca 403
  por pertenencia a otra empresa.
- La empresa sale SIEMPRE de una fuente confiable: el usuario autenticado
  (`get_current_user`, o el token aunque la ruta no lo exija), el código de la
  ruta `/api/v1/public/{codigo}/...` (tienda pública) o la transacción de pago
  (webhook y pantalla QR). Nunca de una cabecera, query o cuerpo.
- `sin_filtro(...)` solo vale para `Usuario` (al autenticar), `TransaccionPasarela`
  (webhook) y `Suscripcion`. Sobre cualquier otra tabla de empresa lanza error.
- SQL en texto (`text()`): solo con `condicion_empresa(db)`. Una prueba recorre
  `app/` y falla si aparece otro `text(`.
- Todo id que llega del cliente (cuerpo, query o ruta) y se guarda como FK se
  resuelve antes con una búsqueda filtrada (404 si no es de la empresa): la FK
  de la base, por sí sola, permitiría apuntar a otra empresa.
- Las tareas sin usuario (expirar reservas y ventas pendientes) corren por
  empresa con `por_cada_empresa`; el segundo plano del probador recibe la
  empresa explícita.
- Las rutas `/api/v1/public/{codigo}/...` (27) reutilizan los mismos handlers del
  catálogo, sucursales, zonas de envío y búsqueda por voz/recomendador (más el
  registro de clientes y los datos públicos de la tienda). Sin token, las rutas viejas equivalentes
  responden 401.

### Login y token (E03)
- `POST /auth/login` recibe `{empresa, email, password}`. `empresa` es el nombre
  o el código de la empresa: se normaliza (`normalizar_nombre_empresa`: sin
  tildes, minúsculas, guiones) y se busca en `empresa.codigo`, que NO cambia
  aunque cambie el nombre comercial. Sin `empresa` solo entra un
  superadministrador; un usuario de empresa nunca entra por esa vía.
- Credenciales inválidas, empresa inexistente o inactiva, correo ajeno, usuario
  inactivo: siempre el mismo 401 `Credenciales inválidas` y el mismo costo de
  bcrypt. 5 fallos en 15 minutos por cuenta (empresa + correo) → 429 con
  `Retry-After` (`LimitadorIntentos` en memoria, un solo worker); además el
  límite por IP de `slowapi`. Variables: `LOGIN_MAX_INTENTOS`,
  `LOGIN_VENTANA_SEGUNDOS`.
- Los tres tokens (access, refresh, reset) llevan el claim `empresa_id` (null =
  superadministrador). `decodificar_token` exige que exista, y `get_current_user`
  lo cruza con la fila del usuario y exige la empresa activa: ni el claim ni la
  base bastan por sí solos. Cambiar `JWT_SECRET_KEY` invalida TODAS las sesiones.
- El token de recuperación es de un solo uso (claim `ph` = huella del hash de la
  contraseña vigente). Sin empresa no se emite token de recuperación.
- El correo se guarda y se busca en minúsculas (`CorreoNormalizado`).
- Los clientes se registran por tienda: `POST /public/{codigo}/registro`
  (`/auth/registro` ya no existe). Staff y administradores los crea un
  administrador con `POST /usuarios`, dentro de su empresa.
- Superadministrador: usuario con `empresa_id` NULL y el rol global
  `superadministrador` (único rol que puede tener, y que ningún usuario de empresa
  puede recibir). Solo se crea con `scripts/crear_superadmin.py` (variables
  `SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD`, mínimo 12 caracteres); ningún
  endpoint crea usuarios sin empresa. Su token deja la sesión en modo plataforma:
  las rutas de negocio responden 403. Crear, editar o borrar roles y asignarles
  permisos exige `plataforma.gestionar` (solo el superadministrador); el
  administrador de empresa lee roles y permisos y asigna roles a sus usuarios.

### Planes y suscripciones (E04)
- Dos planes sembrados (Básico: 2 sucursales activas, sin IA/ML/copias;
  Profesional: 10, todo). Los límites y las funcionalidades se leen de la tabla
  `plan`: editar un plan cambia el comportamiento sin tocar el código.
- Una empresa tiene a lo sumo UNA suscripción vigente (no cancelada; índice
  parcial). Estados: `activa`, `suspendida`, `vencida`, `cancelada` (final). El
  estado EFECTIVO se calcula por fecha (una activa con la fecha pasada es
  vencida aunque la tarea periódica no haya corrido); la tarea
  (`vencer_suscripciones`) lo persiste. Cambiar de plan cancela la vigente (su
  vencimiento se recorta a hoy) y crea otra; bajar a un plan con menos
  sucursales de las que hay en uso se rechaza (409).
- `core/planes.py`: `verificar_suscripcion_activa` (403 `suscripcion_no_activa`)
  la ejecutan `get_current_user` y la tienda pública salvo en
  `RUTAS_SIN_SUSCRIPCION` (`/health`, `/auth/*`, `/mi-empresa*`, `/plataforma/*`,
  `/public/tiendas`, `/public/{codigo}/tienda`, webhook y QR de pagos,
  `/tareas/*`); `exigir_funcionalidad(nombre)` (403 `plan_no_incluye_funcionalidad`)
  es una dependencia que va ANTES de `require_permission` (orden de errores: 401,
  suscripción, plan, permiso, reglas de negocio). `ErrorFuncional` responde
  `{detail, codigo, mensaje, ...contexto}`.
- Límite de sucursales activas (el depósito cuenta): 409 `limite_plan_excedido`
  al crear o reactivar, con la fila de la suscripción bloqueada (FOR UPDATE en
  PostgreSQL) para que dos altas simultáneas no lo superen.
- Una empresa nueva (`POST /plataforma/empresas`) nace en una sola transacción
  con su suscripción, su administrador y sus datos base (tallas, materiales y las
  9 capitales de Bolivia) mediante `core.tenant.registrar_inicializador`; el
  superadministrador trabaja sobre una empresa ajena solo con `en_empresa`.
- Siempre queda al menos un administrador activo por empresa.
- Semilla de demostración: `python -m scripts.seed_empresas_prueba` (dry-run por
  defecto): FashionStore (Profesional) y Boutique Andina (Básico).

## Plan de desarrollo
`docs/plan_desarrollo_fashionstore.md`

## Tokens de diseño
Paleta terracota oscurecida (tienda de hombre: menos crema/pastel, base más
piedra/carbón, acento tipo cuero curtido en vez de coral). Fondo #EAE4DA
(contenido) / #FFFFFF (superficie/cards) · Texto #1C1713 / tenue #6E6156 ·
Acento #9A3E1F (hover #732E16, suave #E3D2C1) ·
Sidebar #241C18 (texto #C9BCB2, activo rgba(154,62,31,.28) / #F0DDCE) ·
Éxito #16A34A (suave #E8F6EE) · Advertencia #B45309 (suave #FDF0DD) ·
Error #DC2626 · Borde #DBD0C1 · Muted #C7BCAC.
Radio: 6px (inputs/filas/densos) · 10px (cards/stat tiles) · 18px (diálogos/hero).
Tipografía: Fraunces (serif, 500/600/700, itálica para marca y saludos) +
Public Sans (400-700, UI y datos). Números alineados en columna usan
tabular-nums. Espaciado en múltiplos de 4px.
El back office es denso (tablas compactas). El cliente móvil es amplio,
con la fotografía como protagonista.

## Alcance del probador virtual
Solo prendas superiores masculinas (poleras, camisas, chamarras).
Solo existe el modo generativo (foto del cliente + imagen de la prenda,
resuelto por un proveedor externo de IA). El modo espejo se eliminó. En el
catálogo de 25 CU, los assets del probador son CU-10 (sin anclajes) y probar
una prenda con IA es CU-11.

## Entorno local
- PostgreSQL instalado localmente. Base de desarrollo: `fashionstore_dev`,
  creada manualmente antes de la primera migración.
- pgAdmin se usa solo para consulta. Las tablas NUNCA se crean ni se
  modifican desde pgAdmin.
- Conexión por variable de entorno DATABASE_URL en `.env`:
  postgresql+psycopg://postgres:PASSWORD@localhost:5432/fashionstore_dev
- Producción: PostgreSQL en Railway, DATABASE_URL provista por el servicio.

## Flujo de cambios de esquema
1. Modificar el modelo SQLAlchemy.
2. alembic revision --autogenerate -m "descripcion"
3. Revisar a mano el archivo generado. Atención con la columna generada
   `stock.cantidad_disponible`: autogenerate suele proponerla mal.
4. alembic upgrade head en local.
5. Commit y push. Railway aplica la migración al desplegar.
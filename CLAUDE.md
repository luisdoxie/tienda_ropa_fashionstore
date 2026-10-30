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
- Exportación de reportes (E10): `openpyxl` (Excel) y `reportlab` (PDF), solo en memoria
- Machine Learning (E11): `numpy`, `scipy` y `scikit-learn` (sin pandas), con versión fija; sus
  imports van dentro de las funciones (scikit-learn tarda ~1,3 s en importarse)
- Pagos: Libélula y PayPal, ambos en sandbox
- Despliegue: Railway sin Docker, y Vercel para el Angular

## Arquitectura
Monolito modular en capas. 4 paquetes de negocio más `core` bajo `backend/app/`
(más `sincronizacion`, para el offline del segundo parcial, E07):
- `plataforma`: seguridad (autenticación, usuarios, roles, permisos, clientes)
  y organización (ciudades, sucursales, empleados). Aquí viven también los
  modelos de empresa, plan y suscripción (multitenant) y su gestión (CU-04).
- `catalogo`: catálogo, inventario, abastecimiento y probador virtual
  (solo modo generativo).
- `comercial`: reservas, ventas, pagos y entregas.
- `inteligencia`: recomendador, búsqueda por voz, reportes e indicadores,
  reportes con IA y analítica ML. El cálculo de ML vive en el subpaquete
  `inteligencia/ml/` (cálculo PURO: no importa paquetes de negocio, no recibe
  `Session` y no toca SQL; ver "Machine Learning (E11)").
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
  (reportes generativos de registro cerrado con intérprete Groq o de reglas,
  más el reporte por voz de siempre; E09) · CU-24 Analizar con Machine
  Learning (`cu24_...`, clases de control `EntrenarModelosAnaliticos` de la
  E11 y `ConsultarAnaliticaML` de la E12; las rutas `/api/v1/analitica`).
- sincronizacion: CU-25 Sincronizar operaciones offline (`cu25_...`, clases de
  control `ProcesarLote`, `ConsultarOperaciones`, `DescargarPaquete` y
  `ResolverConflicto`; las dos últimas son de la E08).
El antiguo CU-22 del primer parcial (modo espejo) se retiró. Una operación que no sea un caso de
uso del catálogo no crea un CU nuevo: se resuelve en politicas.py o
repository.py, o se pregunta.

Algunas tablas del esquema (`docs/fashionstore_esquema.sql`) son soporte de
un caso de uso del catálogo pero no tienen su propio CU (ej. `orden_compra`,
que CU-08 referencia de forma opcional). Se implementan con su CRUD normal.

## Diagramas ICONIX del segundo parcial
No hay priorización de CU ni ciclos formales como en el primer parcial (PUDS):
los CU se van agregando en cada presentación (25/10, 01/11, 08/11), pero el
documento final de la defensa es uno solo, sin esa separación por ciclos.

Mapeo fase ICONIX → artefacto (Capítulo III-V del documento):
- Requisitos → diagrama de casos de uso.
- Análisis → diagrama de robustez.
- Diseño → diagrama de secuencia + diseño de clases + diseño de arquitectura
  (diseño de despliegue + diseño de paquetes). Ya no se usa el modelo C4.
- Implementación → despliegue, paquetes, componentes.
- Pruebas → por CU, con las plantillas de la ingeniera.

El "diseño de clases" reemplaza al diagrama de comunicación como entregable
obligatorio (el de comunicación sigue siendo válido pero queda opcional): es
como un diagrama de clases que además lista, dentro de cada clase, sus
métodos/acciones. Corresponde 1:1 con el código ya existente:
- Objeto frontera → acciones de la interfaz (endpoints del router / pantalla
  del front).
- Objeto de control → la clase de control en `casos_uso/<archivo>.py`, con
  TODOS sus métodos públicos.
- Objeto entidad → modelo SQLAlchemy en `models.py`, con sus atributos y
  métodos, y las mismas relaciones y cantidad de clases que el modelo de
  dominio (3.1).
Los diagramas de secuencia derivan del diseño de clases y deben ser
coherentes entre sí, sin contradecirse.

También pueden hacer falta, dentro del diseño: diagrama de navegación
(sistema y subsistema), y diagrama de tiempo / diagrama de estado, estos dos
últimos solo si son necesarios para el caso de uso en cuestión.

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
(60 tablas en el SQL, que es el del primer parcial). La base real tiene 65:
las 59 de antes (`sesion_probador` se eliminó con el modo espejo) más
`empresa`, `plan`, `suscripcion`, `operacion_sync` (E07) y `modelo_ml` (E11) del
segundo parcial, que no están en el SQL, y `bitacora` (E06; el SQL ya trae su
bloque actualizado). No inventar tablas ni columnas nuevas sin pedirlo
explícitamente.
Ese archivo es documentación de referencia: NO se ejecuta contra la base.
Las tablas las crea Alembic a partir de los modelos.

## Multitenant
Una sola base compartida con aislamiento lógico por `empresa_id` (una sucursal
NO es un tenant: una empresa tiene varias). Estado: modelo y migración (E01),
filtrado automático por empresa (E02), login con empresa y claim `empresa_id`
en el token (E03), CU-04 con planes y suscripciones (E04), las pruebas de
aislamiento (E05), la bitácora de auditoría (E06), el paquete de
sincronización (E07) y su descarga de datos, conflictos y plazo de cambio (E08)
hechos. El backend NO
se despliega solo: tras la E03 el login de la web y del móvil actuales no
funciona hasta que se adapten (E15, E16, E18).
- Clasificación de las 65 tablas: 50 propias de empresa (`empresa_id` NOT NULL,
  salvo `usuario`, donde NULL = superadministrador de la plataforma), 8
  globales del sistema (`permiso`, `rol`, `rol_permiso`, `tipo_movimiento`,
  `estado_reserva`, `estado_venta`, `metodo_pago`, `estado_pago`), `plan`
  (global), `empresa` (la raíz), `usuario_rol` (hereda del usuario),
  `suscripcion` (de la empresa, con historial), `operacion_sync` (de la
  empresa, `EmpresaMixin`; E07), `modelo_ml` (de la empresa, `EmpresaMixin`; E11) y
  `bitacora` (`empresa_id` NULL permitido y SIN el mixin: ver "Bitácora de
  auditoría").
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
  responden 401. `GET /public/{codigo}/tienda` (exenta de la suscripción) trae
  `disponible`: falso si la suscripción de la empresa no está activa; la web
  decide con eso entre mostrar la tienda y "Tienda no disponible".

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
- Población de demostración (8 organizaciones): `python -m scripts.poblar_demo --origen <carpeta
  con catalogo.json, JPG y overlays/>` (dry-run por defecto; `--ejecutar`, `--solo <código>`,
  `--sin-fotos`). Los datos están en `scripts/demo_organizaciones.py` (3 Profesional, 3 Estándar
  y 2 Básico, 22 sucursales en 7 ciudades, 104 productos con las 24 fotos del dataset, precio por
  factor de organización y stock distinto por sucursal y variante). El plan Estándar (5 sucursales,
  IA y copias sí (guarda 6), ML no, cambio en 48 h) se crea como DATO con el CU-04, no por migración ni en
  `seed_planes.py`. Copias y plazo de cambio crecen con el plan (copias 3, 6, 10; plazo 24, 48, 72 h) y
  el Básico pasa a INCLUIR copias (cambia D07 solo en estos datos): lo aplica `poblar_demo
  --ajustar-planes` (la migración y `seed_planes.py` dejan Básico sin copias y Profesional con 5 y 24 h).
  Las prendas de mujer no admiten probador; la chamarra va como unisex. Polos y
  Camisetas deportivas cuelgan de la categoría Poleras (el backend reconoce el torso superior por
  el nombre de la categoría o sus ancestros). No toca el historial de ventas (E11) ni se corre
  contra `fashionstore_dev` sin `CONFIRMO_BASE_DEV=si`.

### Pruebas de aislamiento (E05, `backend/tests/aislamiento/`)
Demuestran en el backend (no en la interfaz) que un usuario de la empresa A no lee,
modifica ni borra datos de la B, y hacen fallar la suite si alguien agrega una ruta sin
clasificarla. Un recurso de otra empresa se ve IGUAL que uno inexistente (404, mismo cuerpo).
- `rutas_esperadas.py` (`RUTAS`): una entrada por cada (método, ruta) de la app, con
  `Ruta(clase, permiso, funcionalidad, cobertura, nota)`. Clases: POR_ID, LISTADO,
  CREA_O_ACCION, PROPIA, PUBLICA, PLATAFORMA, MI_EMPRESA, PASARELA, SERVICIO, AUTH.
  Cobertura MATRIZ (la recorre una prueba parametrizada) o EXENTA (máximo 12; la nota con
  la razón, de 20 caracteres o más, es obligatoria). Una ruta de negocio sin permiso lleva
  la nota "solo autenticado". Las guardianas (`test_registro_de_rutas.py`) fallan si una
  ruta nueva no está clasificada, si sobra una entrada, o si el permiso o la funcionalidad
  declarados no coinciden con lo que la ruta exige (se leen de `.permiso` y `.funcionalidad`
  que dejan `require_permission` y `exigir_funcionalidad`).
- Para agregar una ruta: (1) añadirla a `RUTAS` (`python -m tests.aislamiento.generar_rutas`
  imprime un borrador; nunca pisa el archivo); (2) si es POR_ID con cuerpo, su cuerpo de
  ejemplo en `plantillas.py` (`CUERPOS`) y el recurso de cada parámetro en `PARAMETROS`;
  (3) si recibe ids en el cuerpo, un caso en `casos_fk.py`; (4) si es un listado que exige
  parámetros, su consulta en `test_matriz_listados.py` (`CONSULTA_BASE`).
- `universo.py` crea dos empresas (A Profesional, B Básico) con UNA instancia de cada recurso
  por la API, con marcas `MARCA-A-…`/`MARCA-B-…` y datos solapados (mismo código de
  producto y SKU, de sucursal y correo). `conftest.py` lo arma una vez por paquete sobre un
  motor SQLite propio (fixture `mundo`). `Universo.nuevo(recurso)` da instancias desechables
  para las pruebas que borran o cambian de estado. Las pruebas que alteren plan,
  suscripción o estado de una empresa usan empresas descartables, nunca A ni B.
- Oráculo de cada intento cruzado (`oraculo.py`): O1 404; O2 mismo estado y cuerpo que con
  un id inexistente; O3 sin "MARCA-B-" en cuerpo ni cabeceras; O4 la instantánea de B
  (filas y huella de cada tabla suya) no cambia; O5 la misma petición con ids propios sí
  funciona (evita pruebas verdes por una ruta mal armada).
- Archivos: `test_matriz_por_id`, `_listados`, `_fk_en_cuerpo` (69 campos con id),
  `_relaciones`; `test_tokens_y_superadmin`; `test_publico` (tienda, pasarela);
  `test_reportes_y_vistas`; `test_planes_y_suscripcion`; `test_zz_consistencia_final` (corre
  al final: ninguna FK entre tablas de empresa apunta a otra empresa, 90 relaciones). En
  PostgreSQL: `tests/postgres/test_aislamiento_pg.py` (matriz reducida, bloqueos
  `FOR UPDATE`, concurrencia, vistas V2 y la misma consulta de consistencia).
- Correr: `python -m pytest -q -p no:cacheprovider tests/aislamiento` (≈90 s) y, con
  `TEST_DATABASE_URL` apuntando a `fashionstore_test`, `tests/postgres`. Las funcionalidades
  sin rutas aún (`analitica_ml`, `copias_seguridad`) se saltan con motivo: las etapas que
  las implementen quitan el skip y agregan sus rutas a `RUTAS` (`operacion_offline` ya lo
  hizo en la E07). Una ruta con un UUID en el path se arma con `inexistente_para(...)`.
- Hallazgos de la etapa: ninguna fuga de aislamiento. Defecto previo ajeno (CU-08):
  `PUT /ordenes-compra/{id}` con una línea de una variante que la orden ya tiene da 500.

### Bitácora de auditoría (E06)
Registro de SOLO ANEXAR de las acciones sensibles (tabla `bitacora`, modelo en
`plataforma/models.py`). Quién (`usuario_id`), qué (`entidad`, `entidad_id`, `accion`),
datos mínimos (`datos` JSONB), IP y fecha. No duplica los libros que ya existen
(kardex, `reserva_historial`, `transaccion_pasarela`): guarda la acción y la referencia.
- **Cómo auditar una acción nueva.** El caso de uso recibe `contexto: ContextoAuditoria | None = None`
  como ÚLTIMO parámetro (el router lo pasa con `Depends(obtener_contexto_auditoria)`; el login usa
  `contexto_anonimo(request)`). Hace la operación con `commit=False`, llama a
  `plataforma.politicas.registrar_bitacora_de(db, contexto, ENTIDAD_X, id, ACCION_Y, datos)` y recién
  entonces `db.commit()`: la fila queda en el MISMO commit que el cambio; si la operación falla o el
  llamador revierte, no queda fila. Con `contexto=None` no se registra nada. Los nombres de entidades y
  acciones están en `core/auditoria.py` (una sola fuente; ya reservados los de E07, E08, E21 y E22).
- **`registrar_bitacora` nunca confirma ni revierte al llamador.** Vuelca (`flush`) fuera del try (un error
  de datos del llamador se propaga) y inserta en un SAVEPOINT: si la fila falla, devuelve `None` y deja
  `logger.exception` (auditoría de mejor esfuerzo: no tumba una venta ni un login). Un evento nuevo importante
  que NO deba perderse puede cambiar eso a "fallar cerrado".
- **La empresa de la fila es la de la sesión.** El argumento `empresa_id` solo cuenta si la sesión no tiene
  empresa (superadministrador que actúa sobre la empresa 7; login con empresa inexistente → NULL).
- **`datos` pasa por `core.auditoria.sanear_datos`**: claves de secretos y de datos personales quedan en
  "[omitido]", textos con forma de JWT, hash bcrypt o correo se omiten, y hay límites de profundidad (4),
  texto (200), lista (50) y tamaño (4096 bytes). Convención: pasar IDS y CÓDIGOS, nunca nombres ni correos;
  para cambios de campos usar `diff_campos` (nombres de campo, y valores solo de los no sensibles).
- **Sin filtro automático.** `bitacora` NO hereda `EmpresaMixin`: admite NULL y el superadministrador la lee
  entera, así que `BitacoraRepository` filtra SIEMPRE de forma explícita (`empresa_id` de la sesión, o
  `plataforma=True` solo desde la ruta del superadministrador). No se agregó a `TABLAS_SIN_ALCANCE`.
- **Consulta.** `GET /bitacora` y `GET /bitacora/{id}` (permiso `bitacora.ver`, solo el administrador; el
  `empresa_id` que mande el cliente se ignora y una fila de otra empresa es 404). `GET /plataforma/bitacora`
  (superadministrador, con `empresa_id` y `sin_empresa`). Al administrador de una empresa, lo que hizo el
  superadministrador le llega como "Administrador de la plataforma" y sin IP. Paginada (máx. 100), por defecto
  los últimos 30 días, orden más reciente primero.
- **Eventos enganchados:** login (exitoso y fallido; el fallido se confirma solo y NO guarda el correo),
  recuperación de contraseña, usuarios y roles, sucursales y empleados, empresas, planes y suscripciones
  (CU-04), anular un pago, registrar una devolución y los ajustes de inventario.
- **Retención.** 365 días (`BITACORA_RETENCION_DIAS`); `POST /tareas/purgar-bitacora` (token de servicio) borra
  por lotes y deja una fila `bitacora/purgar`. No está en la tarea periódica interna: la dispara un cron.
- Pruebas: `tests/core/test_auditoria.py`, `tests/plataforma/test_bitacora*.py`,
  `tests/comercial/test_bitacora_eventos_comercial.py` y `tests/postgres/test_bitacora_postgres.py`. Las 4
  rutas están en `tests/aislamiento/rutas_esperadas.py`.

### Sincronización offline (E07, CU-25, `backend/app/sincronizacion/`)
Recibe las operaciones que la PWA y la app móvil registraron sin conexión (`venta_contado` y `reserva`),
las aplica en el servidor con las reglas de `comercial` y devuelve un resultado por operación. Es el
único paquete que se apoya en `comercial`; ningún otro importa `sincronizacion`.
- **Rutas:** `POST /api/v1/sincronizacion/lote` (permiso `sincronizacion.operar`), `GET .../operaciones` y
  `GET .../operaciones/{operacion_id}` (el UUID de la operación; plan con `operacion_offline`). Con
  `sincronizacion.supervisar` (administrador, encargado) se ven las de la empresa o de la sucursal propia, y
  el detalle incluye el `payload`; sin él, solo las propias. El contrato JSON v1 (montos en texto, fechas con
  zona, hasta 50 operaciones por lote) está en la sección 4.2 de `E07_sincronizacion_cu25.txt` y congelado por
  `tests/sincronizacion/contrato_v1.json`.
- **Idempotencia (D12).** `operacion_id` (UUID del cliente) con UNIQUE `(empresa_id, operacion_id)`. Cada
  operación reserva primero su clave: si ya existía es un reenvío y se devuelve lo guardado con
  `duplicada=true`, sin repetir nada y sumando `intentos`. Con dos lotes simultáneos, el segundo INSERT espera
  al primero (PostgreSQL) y cae en el error de unicidad.
- **Orden y aislamiento de fallos (D14).** Las operaciones se toman por `fecha_operacion` (la más antigua
  primero). Cada una corre en su SAVEPOINT y se CONFIRMA al terminar (commit por operación): una mala no tumba
  a las demás. Un fallo inesperado NO se guarda (`error_temporal`): el cliente reintenta con la misma
  `operacion_id`. Estados que se guardan: `confirmada`, `rechazada`, `en_conflicto`.
- **Reglas (D15-D18).** Sin stock suficiente la operación se deshace entera y queda `en_conflicto` con
  `faltantes`. Una venta es de contado en efectivo; se acepta el precio de la operación (D17) y, si difiere del
  actual, sale el aviso `precio_distinto`. Los rechazos llevan un `motivo` estable (`politicas.py`).
- **Suscripción y plan (D16).** El POST está en `RUTAS_SIN_SUSCRIPCION` y no usa `exigir_funcionalidad`: así
  guarda el rechazo de cada operación con su motivo (`suscripcion_no_activa`, `plan_sin_operacion_offline`).
  Ese rechazo es FINAL (reenviar la misma `operacion_id` devuelve el mismo rechazo); si se prefiere que sea
  reintentable, se cambia en `ProcesarLote` (decisión pendiente para E14 y E20).
- **Parámetros nuevos y opcionales en `comercial`:** `registrar_venta(fecha=, precios_pactados=)`,
  `cobrar_en_caja(fecha=)` y `crear_reserva(cliente_id=, creado_en=)`; y `StockInsuficienteError` (un
  `ConflictoError` 409, mismo mensaje) para distinguir "no alcanza el stock" de otros conflictos.
- **Datos:** `operacion_sync.sucursal_id` admite NULL (la sucursal pedida no existe o es de otra empresa: la
  operación se guarda rechazada y la FK no puede apuntar a una ajena). Un `tipo` desconocido se rechaza sin
  guardar (la tabla solo admite los dos tipos). La tabla no se purga.
- **Observabilidad.** Logger `app.sincronizacion`, una línea `clave=valor` por evento (`sync_lote_recibido`,
  `sync_operacion`, `sync_lote_fin`), sin payload, montos ni datos personales; y una fila de bitácora
  (`lote_sync/sincronizar_lote`) por lote.
- Pruebas: `tests/comercial/test_registrar_venta_offline.py`, `tests/sincronizacion/` (con `ayudas.py` y el
  escenario de `conftest.py`) y `tests/postgres/test_sincronizacion_concurrencia.py`. Las 3 rutas están en
  `tests/aislamiento/rutas_esperadas.py` (el lote como EXENTA, con su razón).

### Descarga, conflictos y cambios en 24 h (E08, `sincronizacion` y CU-17)
Decisiones de diseño (D15, D17, D19):
- **Cambios solo en línea (D19).** Devolver o cambiar prendas necesita la venta original y el stock
  confirmado, así que NO se ofrece sin conexión. No existe un objeto "cambio": hoy un cambio es una
  devolución más una venta nueva (D32), por eso el plazo se aplica a TODA devolución (CU-17
  `RegistrarDevolucion`, 409 `PlazoCambioVencidoError`). El plazo se cuenta desde `Venta.fecha`, la fecha
  REAL de la venta (en una venta offline, la `fecha_operacion` del dispositivo, no la de sincronización),
  con el límite inclusivo: a las 24:00:00 exactas aún se acepta. El plazo sale de `empresa.plazo_cambio_horas`
  (1 a 720, NULL = el del plan), luego `plan.plazo_cambio_horas_defecto` y, por último, el respaldo
  `plazo_cambio_horas_respaldo` de `Settings` (24). El administrador lo cambia con `PUT /mi-empresa` (`plazo_cambio_horas`;
  `null` vuelve al del plan; deja bitácora `empresa/cambiar_plazo_cambio`). `GET /ventas/{id}/plazo-cambio` dice
  cuánto queda (fecha, plazo, vencimiento, vigente). El reloj de una venta offline es el del dispositivo: un
  cajero que adelante la fecha extiende el plazo del cliente.
- **Conflicto de stock: forzar = ajuste positivo + venta, nunca stock negativo (D15).**
  `POST /sincronizacion/operaciones/{operacion_id}/resolver` con `{"accion": "forzar"|"rechazar", "motivo"}`
  (permiso `sincronizacion.resolver`: administrador y encargado; el encargado solo las de su sucursal, otra
  se ve como inexistente). `forzar` (solo ventas) significa que la prenda YA salió de la tienda: registra un
  ajuste `ajuste_positivo` por el faltante exacto (referencia `sync_forzada`, actor el encargado) y luego
  confirma la venta tal como la hizo el operador original (su fecha, sus precios, a su nombre). El disponible
  queda en 0, nunca debajo; las unidades apartadas por reservas ajenas no se tocan (el CHECK de `stock` no
  permite físico negativo). `rechazar` (ventas y reservas, motivo obligatorio) no deja efectos de stock: el
  efectivo cobrado en tienda se devuelve fuera del sistema. Las reservas en conflicto solo se rechazan.
  `confirmada` y `rechazada` son finales: repetir la MISMA acción devuelve lo guardado (idempotente), la
  contraria da 409. La fila se lee con `FOR UPDATE`. Todo (ajuste, venta, estado, aviso al operador en sus
  notificaciones y bitácora `operacion_sync/resolver_conflicto`) va en una sola transacción; si el operador
  ya no está activo o la variante se dio de baja, forzar da 409 y la operación sigue en conflicto.
- **Paquete de descarga y delta solo de stock.** `GET /sincronizacion/paquete` (manifiesto: empresa,
  sucursales autorizadas con horario, referencias, promociones vigentes y reglas) y `/paquete/catalogo`,
  `/paquete/stock`, `/paquete/clientes` (permiso `sincronizacion.operar`, plan con `operacion_offline`,
  suscripción activa: aquí SÍ se responde 403). Catálogo y clientes se paginan por clave (`desde_id`); el
  descuento de cada variante sale de UNA consulta de promociones por página con la misma regla que
  `calcular_linea` (`mejor_descuento`). El stock trae solo `cantidad_disponible` de UNA sucursal (el
  administrador debe indicarla) y es lo único con delta real: `?desde=` devuelve las filas modificadas
  desde ese instante menos un solape de 120 s que fija el servidor. Los productos o variantes dados de
  baja desaparecen: el cliente que completa una descarga borra de su copia lo que no llegó. Cada respuesta
  lleva `generado_en` (con él el cliente decide mostrar "información desactualizada" pasadas
  `sync_aviso_desactualizado_horas`), ETag (huella del cuerpo sin `generado_en`; `If-None-Match` igual da
  304) y gzip. Nunca salen costos, márgenes, límites de stock, proveedores ni datos personales (de un
  cliente solo nombre, apellido y `ci_nit`).
- Pruebas: `tests/comercial/test_plazo_cambio.py`, `tests/sincronizacion/test_resolver_conflicto.py`,
  `test_paquete*.py` y `test_plazo_cambio_offline.py`, y `tests/postgres/test_resolver_concurrencia.py`.
  Las 6 rutas nuevas están en `tests/aislamiento/rutas_esperadas.py`.

### Reportes generativos con IA (E09, CU-23, `backend/app/inteligencia/`)
Convierte una frase (escrita, o dictada y ya transcrita por el cliente) en un reporte de datos reales de
la empresa del token. La IA NUNCA ve la base ni genera SQL: solo devuelve un JSON con el tipo de reporte
y filtros, que se valida contra un registro cerrado.
- **Rutas** (plan con `reportes_ia` y permiso `reportes.ver`; 15/min por IP): `GET /api/v1/reportes-ia/catalogo`,
  `POST .../interpretar` ("entendí esto", sin ejecutar) y `POST .../ejecutar` (`{texto}` o `{solicitud}`).
  `/ia/reporte-voz` (el reporte por voz de 4 pestañas) no cambia y también exige `reportes_ia`.
- **Flujo:** intérprete (Groq con timeout de 10 s y 1 reintento; si no responde, `InterpreteReportesReglas`, de
  palabras clave, con un aviso) → `SolicitudReporte` (extra="forbid", sin ids ni empresa) → validación contra
  `registro_reportes.py` (`REGISTRO`: 6 reportes, con filtros, columnas y gráfico) → resolución de fechas con
  `core/tiempo.resolver_periodo_relativo` (la IA nunca calcula fechas) y de nombres contra la empresa de la
  sesión → ejecutor del registro (funciones de `comercial` y `catalogo`: aquí no hay SQL) → filas, resumen,
  `grafico_sugerido`, avisos y narrativa por plantilla. Una prueba guardia falla si aparece `text(`, `SELECT ` o
  `execute(` bajo `app/inteligencia`.
- **Reportes:** `ventas_por_sucursal`, `productos_mas_vendidos`, `ventas_por_periodo` (día, semana o mes, con los
  periodos sin ventas en 0), `comparacion_sucursales` (variación contra el periodo anterior),
  `productos_menor_existencia` e `ingresos_por_categoria`. Agregar uno (E12) es una entrada del registro más su
  ejecutor (`conectar_ejecutor`); el prompt de Groq y las ayudas se generan desde el registro.
- **Estados** (siempre HTTP 200; solo plan, permiso, suscripción, cuerpo mal formado y rate limit son errores):
  `ok`, `incompleta`, `ambigua` (nombre sin coincidencia: se sugieren los reales), `invalida` (periodo futuro, más
  de 366 días, límite fuera de 1..50, agrupación no admitida), `no_soportada`. Con cualquier estado distinto de `ok`
  no hay filas. Un filtro que el reporte no usa se ignora con un aviso.
- **Alcance:** quien no tiene alcance global (encargado, cajero) solo ve su sucursal; se fuerza y se avisa. El filtro
  por categoría es por id exacto (sin subcategorías). "Últimos N meses" = N-1 meses completos más lo corrido del actual.
  `hoy` es UTC (`core/tiempo.hoy_utc`). Los montos de las filas son números de 2 decimales (para mostrar, no calcular).
- **Bitácora:** cada `/ejecutar` deja una fila `reporte_ia/ejecutar` (o `rechazar`) con el tipo, el estado, el
  intérprete, los filtros ya resueltos (ids), el conteo de filas y la duración. NO guarda el texto del usuario.
- **Pendiente (opcional, E09b):** la narrativa generada por IA (extensión 8.5, apagada por defecto con
  `reportes_ia_narrativa_ia`) no se implementó; la narrativa es siempre la plantilla. Settings nuevos:
  `groq_timeout_segundos`, `groq_reintentos`, `reportes_ia_max_filas` (500).
- Pruebas: `tests/inteligencia/test_reportes_generativos*.py`, `test_registro_reportes.py`, `test_interprete_*.py`,
  `test_narrativa_reportes.py`, `tests/core/test_tiempo_periodos.py`, las consultas nuevas en `tests/comercial`,
  `tests/catalogo` y `tests/plataforma`, y `tests/postgres/test_reportes_generativos_pg.py`. Ninguna prueba llama a
  Groq (fixture autouse `sin_red_groq`). Las 3 rutas están en `tests/aislamiento/rutas_esperadas.py`.

### Exportación a Excel y PDF (E10, `backend/app/inteligencia/`)
Cualquier reporte se descarga como `.xlsx` o `.pdf` con formato de reporte formal (título, empresa,
filtros, fecha en hora de Bolivia, tabla con totales y gráfico). El constructor no sabe de dónde viene el
reporte: recibe un `DocumentoReporte` (`schemas.py`, bloque "Exportación") y devuelve los bytes.
- **Archivos.** `exportacion.py` (fachada: `construir_archivo`, `ArchivoExportado`, `MAX_FILAS`),
  `exportacion_xlsx.py` (openpyxl, gráfico nativo de Excel), `exportacion_pdf.py` (reportlab, gráfico vectorial,
  "Pagina X de Y"), `exportacion_comun.py` (colores del rediseño, topes y `datos_de_grafico`: máximo 12
  categorías, las menores en "Otros") y `exportacion_convencionales.py` (adaptadores de CU-22).
- **Rutas.** `POST /api/v1/reportes-ia/exportar` (plan con `reportes_ia`, `reportes.ver`, 10/min): cuerpo
  `{formato: xlsx|pdf, incluir_grafico, y exactamente uno de texto | solicitud | resuelta}`. `resuelta` es la
  `solicitud` que devolvió `/ejecutar`: no vuelve a interpretar, conserva el periodo ya calculado y descarta los
  ids (los nombres se resuelven otra vez contra la empresa de la sesión). Si el estado no es `ok`: 422
  `reporte_no_exportable` con `estado`, `mensaje` y `sugerencias`, sin archivo. Y
  `GET /api/v1/reportes/{ventas|inventario|reservas}/exportar?formato=` (mismos filtros que las rutas JSON, en
  los dos planes). La respuesta lleva `Content-Disposition: attachment`, `Cache-Control: no-store` y
  `X-Content-Type-Options: nosniff`; CORS expone `Content-Disposition` (`app/main.py`).
- **Reglas.** Todo en memoria, nunca en disco: openpyxl escribe archivos temporales al guardar aunque se le dé un
  `BytesIO`, así que `exportacion_xlsx.py` usa un escritor propio (depende de internos de openpyxl 3.1.5; una
  prueba avisa si cambian). Topes: 5.000 filas en Excel y 1.000 en PDF, con aviso; una tabla recortada no lleva
  totales. Texto que empieza con `= + - @` se guarda como texto en Excel; en el PDF todo texto se escapa y pasa a
  cp1252 (un emoji sale "?"). El nombre del archivo nunca usa texto del usuario:
  `reporte-<tipo>-<empresa.codigo>-AAAAMMDD-HHMM.<ext>`. Las columnas de dinero llevan "(Bs)" en el título y no se
  suman las que no tienen sentido (ticket, participación...); ver `COLUMNAS_SUMABLES` en `politicas.py`.
- **Bitácora.** `reporte_ia/exportar` y `reporte/exportar` (tipo, formato, filtros en ids, filas y bytes; nunca el
  texto del usuario).
- **Límites conocidos.** El logo de la empresa no se incluye. Fuentes estándar (solo Latin-1). Un producto en
  una `resuelta` se vuelve a buscar por texto contenido, igual que en `/ejecutar`. Las 4 rutas nuevas están en
  `tests/aislamiento/rutas_esperadas.py` como `CREA_O_ACCION` (la matriz de listados solo lee JSON); su aislamiento
  se prueba en `tests/inteligencia/test_exportar_*.py` y `tests/postgres/test_exportacion_pg.py`.
- Pruebas: `tests/inteligencia/test_exportacion_{xlsx,pdf,adaptador}.py`, `test_exportar_endpoint.py`,
  `test_exportar_convencionales.py` y `tests/postgres/test_exportacion_pg.py`.

### Machine Learning (E11, CU-24, `backend/app/inteligencia/ml/`)
Dos modelos POR EMPRESA (D22, solo plan Profesional, D23): demanda semanal por categoría (supervisado) y
segmentación de clientes por RFM con K-Means (no supervisado). Cada modelo se entrena SOLO con los datos de la
empresa de la sesión y se guarda en `modelo_ml` con su versión, métricas, huella y artefacto.
- **Capas.** `ml/` es cálculo puro (sin `Session`, sin SQL, sin imports de negocio; una prueba lo vigila):
  `sintetico.py` (generador), `preprocesamiento.py` + `demanda.py` (`entrenar_demanda`, `predecir_demanda`),
  `segmentos.py` (`segmentar_clientes`, `asignar_segmento`), `persistencia.py` (serializar con huella SHA-256,
  `CacheModelos`) y `limites.py`. El acceso a datos: `ModeloMLRepository` (`inteligencia/repository.py`),
  `comercial.politicas.reporte_ventas_serie_diaria` (con `ventas_brutas`) y `reporte_rfm_clientes`. El caso de uso
  es `EntrenarModelosAnaliticos` (`cu24_...`): exige suscripción activa y `analitica_ml` por su cuenta, toma un
  candado consultivo por (empresa, tipo) en PostgreSQL (409 `entrenamiento_en_curso`), guarda cada tipo en su
  propia transacción y deja una fila de bitácora `modelo_ml/entrenar` (solo ids y números).
- **`modelo_ml`.** UNIQUE (empresa, tipo, versión) e índice parcial único (empresa, tipo) WHERE activo: una sola
  versión vigente. `activo` aquí marca la VIGENTE (no es borrado lógico). El artefacto es BYTEA (el disco de Railway
  es efímero), tope 8 MB, `deferred` (los listados no lo traen); solo conserva el artefacto de las 3 últimas
  versiones (las viejas quedan con sus métricas). El tercer tipo, 'anomalias_ventas', se entrena desde la E12.
- **El modelo de demanda.** Predice la DIFERENCIA contra la media móvil de 4 semanas (no la demanda cruda), con un
  ciclo anual propio por categoría; candidatos Ridge, Random Forest y su promedio ("mezcla"), elegido por validación
  cruzada temporal; las últimas 12 semanas son TEST y la línea base es la media móvil. Predicción recursiva a 1..12
  semanas con un "rango estimado" (± RMSE; NO es un intervalo de confianza). Con menos de 26 semanas o 2 categorías
  devuelve `datos_insuficientes`, nunca un 500.
- **Datos sintéticos.** `scripts/seed_ml_sintetico.py` carga el historial como datos reales de la empresa (ORM, sin
  tocar stock ni kardex), por defecto 650 clientes y 78 semanas (~9.400 ventas); se reconoce por los prefijos `SIN-`,
  `DSN-`, `[SIN] ` y el dominio `@sintetico.<empresa>.fashionstore.bo`; dry-run por defecto e idempotente.
  `scripts/evaluar_ml.py` imprime la tabla de métricas para la documentación sin escribir en la base.
- **Honestidad.** Sobre datos sintéticos el modelo aprende los patrones que puso el generador: no es evidencia con
  datos reales. Con 650 clientes las tres organizaciones Profesional cumplen los umbrales (MAE <= base, R2 >= 0,50,
  mejora >= 5 %; silhouette >= 0,25; pureza >= 75 %) con la semilla por defecto, y en 6 a 7 de 8 semillas.
- **Importación diferida.** `import app.main` no carga scikit-learn ni scipy (sí numpy, que importa openpyxl).
- Pruebas: `tests/inteligencia/ml/` (generador, preprocesamiento, demanda, segmentos, persistencia, CU-24 y la
  importación diferida), `tests/comercial/test_reportes_ml.py`, `tests/scripts/test_seed_ml_sintetico.py` y
  `tests/postgres/test_ml_postgres.py` (más `test_cu24_postgres.py`). `tests/conftest.py` fuerza vacías las claves
  de Groq, Cloudinary, Vertex y PayPal: las pruebas nunca usan servicios reales aunque exista un `backend/.env`.

### Analítica ML por HTTP (E12, CU-24 y puente con CU-23, `backend/app/inteligencia/`)
Expone los modelos de la E11, solo para el plan con `analitica_ml` (el Profesional) y solo al administrador de la empresa
(alcance global: un encargado de sucursal recibe 403, D28). Sin tablas ni migraciones nuevas.
- **Rutas** `/api/v1/analitica` (permiso `reportes.ver`; 30/min en las GET y 3/min en `POST /entrenar`): `GET /estado`,
  `POST /entrenar` (cuerpo opcional `{tipos}`; sin cuerpo entrena los 3), `GET /demanda?semanas=1..12&categoria_id`,
  `GET /segmentos`, `GET /anomalias?dias=7..365`, `GET /reposicion?semanas=1..12` y `GET /panel` (todo junto con KPIs).
  Orden de errores: 401, suscripción, plan, permiso, alcance global (dependencia del router, ANTES de validar parámetros) y
  recién después las reglas. El `empresa_id` del cliente se ignora.
- **Errores:** 409 `modelo_no_entrenado`, 409 `modelo_obsoleto` (otra versión de scikit-learn, huella alterada o artefacto de
  otra empresa: el artefacto lleva su `empresa_id`), 409 `entrenamiento_en_curso`. Un modelo de más de 30 días o con datos de
  más de 4 semanas atrás se usa igual con estado `desactualizado` y un aviso. Nunca un 500. El artefacto jamás sale.
- **Clase** `ConsultarAnaliticaML` en `cu24_...py`: `estado`, `entrenar`, `demanda`, `segmentos`, `anomalias`, `reposicion`,
  `panel`. Esquemas en `schemas.py` (bloque "Analítica ML"); frases de interpretación por plantilla en `politicas.py`
  (`interpretar_*`). La variación de demanda se mide SIEMPRE contra las últimas 4 semanas reales.
- **Tercer modelo (anomalías):** `ml/anomalias.py`, Isolation Forest más una regla de desviación robusta, por (sucursal, día).
  Costo medido: ~0,2 a 1 s y <1 MB. Detecta SIEMPRE la "liquidación" inyectada por el generador (24 de 24 historiales), el
  "cierre" solo a veces (9 de 24) y no ve las devoluciones (no cambian las ventas); marca ~2,5 % de los días-sucursal. No
  es evidencia con datos reales. **Reposición:** `ml/reposicion.py`, por categoría, orientativa (no descuenta órdenes en camino).
- **Puente con CU-23:** `SolicitudReporte.horizonte_semanas` y cinco reportes nuevos en el registro (`prediccion_demanda`,
  `segmentacion_clientes`, `metricas_modelos`, `anomalias_ventas`, `reposicion_sugerida`; `funcionalidad_plan=analitica_ml`,
  `requiere_alcance_global=True`). Sin modelo entrenado: estado `no_disponible` (HTTP 200, sin filas, con sugerencia).
  El catálogo y el prompt de Groq solo muestran los tipos que el plan incluye. Las columnas decimales van como "texto".
- Pruebas: `tests/inteligencia/test_analitica_*.py`, `test_interpretacion_analitica.py`, `test_reportes_inteligentes_cu23.py`,
  `tests/inteligencia/ml/test_anomalias.py` y `test_reposicion.py`, `tests/postgres/test_analitica_pg.py`. Las 7 rutas están
  en `tests/aislamiento/rutas_esperadas.py` (LISTADO y CREA_O_ACCION, cobertura MATRIZ).

## Plan de desarrollo
`docs/plan_desarrollo_fashionstore.md`

## Tokens de diseño
Rediseño web (octubre 2026): carbón cálido sobre claro hueso, un acento lima
sobre oscuro y oliva sobre claro. Fuente de verdad: los tokens `--fs-*` de
`web/src/styles.scss`, el preset de `app.config.ts` y el canvas de Design (hoja
"Sistema de diseño"). Los componentes usan las variables, nunca hex sueltos.
- Superficies oscuras (portada, acceso, barra lateral): carbón #1B1916, más
  profundo #121110, panel #232019, borde #2F2C27, texto #F2F2F0 / tenue #B5B2AA.
  Se marcan con la clase `.fs-zona-oscura`, que remapea los tokens de texto y de
  acento para todo lo que hay dentro.
- Superficies claras: fondo #F7F5F1, cabecera de páginas interiores #E7E4DE, pie
  #DCD8D0, tarjetas #FFFFFF con borde #E4DFD6, texto #161412 / tenue #6B645C.
- Acento: lima #8FAE5B (hover #A3C26C) solo sobre oscuro; oliva #5D6B34 sobre
  claro. El botón primario sobre claro es tinta #151515, no el acento. Cada
  empresa puede definir `color_acento`: `tienda-raiz` redefine `--fs-acento*`
  (y su variante sobre oscuro, `--fs-acento-oscuro*`) solo en su elemento; si el
  color contrasta poco con blanco se usa el base.
- Estados: éxito #15803D, advertencia #A4480A, error #C62828 (cada uno con fondo
  suave). Chips y avisos: `.fs-chip--*` y `.fs-aviso--*`.
- Forma: radios 2/4/8 px, sombras mínimas (línea fina de 1px). Back office denso;
  tienda amplia con la fotografía como protagonista (en `public/imagenes/`).
- Tipografía: Archivo (ancho variable) para titulares, en mayúsculas y ancho 125%
  en la tienda (`.fs-display`) y 112% en el back office; Public Sans para UI y
  datos (14-16 px); Fraunces cursiva solo para el lema. Números alineados usan
  tabular-nums. Textos en tuteo (tú), no en voseo.
- Íconos: de trazo (`<fs-icono nombre="..." [tam]="24">`, catálogo en
  `shared/icono/iconos.ts`). Nunca menos de 20 px: etiquetas 20, botones y menú
  24, barra de la tienda 28, beneficios 36. Área tocable mínima 44 px (48 en la
  barra de la tienda). Dentro de componentes de PrimeNG se usan sus `pi pi-*`
  a 24 px. La marca de la empresa es `<fs-marca>` (logo o monograma con siglas).
- El probador virtual NO existe en la web: se menciona como "Probador virtual con
  IA en la app". No hay inicio de sesión social ni "Recordarme".

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
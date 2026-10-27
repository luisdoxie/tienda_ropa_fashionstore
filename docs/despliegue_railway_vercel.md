# Despliegue de FashionStore: Railway (base y backend) y Vercel (web)

Guía paso a paso. Orden: **1)** base y backend en Railway, **2)** datos iniciales, **3)** web en Vercel,
**4)** CORS, **5)** verificación. La app móvil todavía no entra contra este backend (su login se adapta
en la E18).

Nada de esta guía lleva valores reales: los secretos los generas y los cargas tú en Railway y Vercel.
Nunca los pegues en un chat, un commit ni un archivo del repositorio.

## 0. Lo que ya está verificado

- Las migraciones de Alembic se aplican desde una base vacía: `tests/postgres` recrea el esquema con
  `alembic upgrade head` y comprueba que queda igual a los modelos (64 tablas, una sola cabeza).
- Los planes (Básico y Profesional), la empresa `fashionstore` y el rol `superadministrador` los crean las
  migraciones. Los demás roles y permisos y los catálogos base los crea `scripts.seed_seguridad`.
- La web compila en modo producción (`npm run build`, salida en `web/dist/web/browser`).
- `backend/railway.json` (Nixpacks, healthcheck `/health`) y `backend/scripts/start.sh` (migra una sola vez y
  levanta uvicorn con un solo worker). El worker único es obligatorio: el bloqueo de intentos de login y la
  tarea periódica viven en memoria.

## 1. Railway: base de datos y backend

1. Crea un proyecto nuevo (**Empty Project**). No reutilices el servicio viejo del primer parcial: su base
   tiene otro esquema.
2. **+ New → Database → Add PostgreSQL.** Se crea el servicio `Postgres`.
3. **+ New → GitHub Repo →** este repositorio. En el servicio nuevo, **Settings → Source → Root Directory:
   `backend`**. Sin esto Railway analiza la raíz del repositorio (carpetas `backend`, `web`, `mobile`...) y falla
   con "Railpack could not determine how to build the app". Con la raíz en `backend` detecta Python solo
   (`requirements.txt` y `.python-version` 3.13); no hace falta Dockerfile.
   **Settings → Config-as-code → Railway Config File: `/backend/railway.json`** (la ruta del archivo no sigue
   a la raíz del servicio). Ese archivo fija el constructor Railpack, el comando de arranque
   `bash scripts/start.sh` y el healthcheck `/health`. Si prefieres no usarlo, pon esos dos valores a mano en
   **Settings → Deploy** (Custom Start Command y Healthcheck Path).
4. **Settings → Networking → Generate Domain.** Anota la URL (`https://<servicio>.up.railway.app`).
5. En **Variables** del servicio del backend carga lo siguiente (no definas `PORT`: Railway lo inyecta).

### Variables obligatorias

| Variable | Valor |
|---|---|
| `DATABASE_URL` | Referencia al Postgres: `${{Postgres.DATABASE_URL}}` (el nombre del servicio puede ser otro). El backend la corrige a `postgresql+psycopg://` solo. |
| `JWT_SECRET_KEY` | Aleatorio y largo. Cambiarlo invalida todas las sesiones. |
| `ENVIRONMENT` | `production`. Con `local` se confía en cabeceras falsificables y se devuelve el token de recuperación. |
| `CORS_ORIGINS` | La URL de Vercel, sin barra final (paso 4). Varias, separadas por comas. |
| `BACKEND_PUBLIC_URL` | La URL del paso 4 de esta sección (`https://<servicio>.up.railway.app`). La usan la pantalla del pago QR y los webhooks. |
| `TAREAS_TOKEN` | Aleatorio. Vacío deshabilita `/tareas/*` (por ejemplo la purga de bitácora). |

Genera cada secreto en tu PC (no se imprime en ningún servidor):

```powershell
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Variables de servicios externos (según lo que quieras mostrar)

| Variable | Para qué |
|---|---|
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Imágenes de productos. Sin ellas no se pueden subir. |
| `GROQ_API_KEY`, `GROQ_MODELO` | Búsqueda por voz y reportes con IA. Sin clave, los reportes usan el intérprete de reglas. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MODE=sandbox` | Pago con PayPal en sandbox. |
| `PAYPAL_WEBHOOK_SECRET`, `LIBELULA_WEBHOOK_SECRET` | Secretos HMAC de los webhooks. Sin valor, ese webhook se rechaza siempre. |
| `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `GOOGLE_CREDENTIALS_JSON` | Probador virtual (el contenido completo del JSON de la cuenta de servicio, en una sola variable). |

El resto de variables (`LOGIN_*`, `SYNC_*`, `BITACORA_RETENCION_DIAS`, etc.) tiene valores por defecto
correctos. **No** cambies `BCRYPT_ROUNDS` (12 en producción).

6. Railway despliega al guardar las variables. Orden recomendado: primero todo menos `BACKEND_PUBLIC_URL`,
   generas el dominio, completas `BACKEND_PUBLIC_URL` y esperas el segundo despliegue.
7. En **Deployments → Logs** debe verse `Aplicando migraciones de Alembic...` y luego `Iniciando uvicorn`.
   Abre `https://<servicio>.up.railway.app/health`: debe responder 200.

## 2. Datos iniciales (una sola vez, desde tu PC)

La base está vacía de usuarios. Los scripts se corren en tu PC contra la base de Railway. Necesitas la URL
**pública** del Postgres (servicio `Postgres` → **Variables** o **Connect** → `DATABASE_PUBLIC_URL`); la
interna solo se ve dentro de Railway. Esa URL lleva la contraseña: no la pegues en ningún chat.

**Importante:** antes de ejecutar nada, comprueba que `DATABASE_URL` apunta a Railway y no a tu
`fashionstore_dev`. Una variable de entorno gana sobre `backend\.env`, pero si te olvidas de definirla los
scripts escribirían en tu base local. Los scripts imprimen `Base destino: host:puerto/base`: léelo.

```powershell
cd C:\Desarrollo\examen\tienda_ropa\backend
$env:DATABASE_URL = "<DATABASE_PUBLIC_URL de Railway>"
$env:JWT_SECRET_KEY = "cualquier-valor-largo-solo-para-estos-scripts"

# 1) Roles, permisos y catálogos base (idempotente)
.\.venv\Scripts\python.exe -m scripts.seed_seguridad

# 2) Superadministrador de la plataforma (correo y contraseña de 12+ caracteres)
$env:SUPERADMIN_EMAIL = "<tu correo>"
$env:SUPERADMIN_PASSWORD = "<contraseña de 12+ caracteres>"
.\.venv\Scripts\python.exe -m scripts.crear_superadmin
Remove-Item Env:SUPERADMIN_EMAIL, Env:SUPERADMIN_PASSWORD

# 3) Datos de demostración: FashionStore (Profesional) y Boutique Andina (Básico)
$env:SEED_PASSWORD_INICIAL = "<contraseña inicial de los usuarios demo, 8 a 72 caracteres>"
.\.venv\Scripts\python.exe -m scripts.seed_todo              # prueba en seco: no escribe nada
.\.venv\Scripts\python.exe -m scripts.seed_todo --ejecutar   # escribe de verdad

Remove-Item Env:DATABASE_URL, Env:JWT_SECRET_KEY, Env:SEED_PASSWORD_INICIAL
```

Los scripts son idempotentes: repetirlos no duplica filas. Los usuarios demo que crean y su contraseña
(`SEED_PASSWORD_INICIAL`) son los que usarás para entrar. El superadministrador entra a la web sin indicar
empresa; los demás con el código de la empresa (`fashionstore` o `boutique-andina`).

## 3. Vercel: la web

1. Con la URL del backend (paso 1.4), edita `web/src/environments/environment.ts`: `apiUrl` debe ser
   `https://<servicio>.up.railway.app/api/v1`. Haz commit y push (pídeme que lo haga cuando me des la URL).
2. En Vercel: **Add New → Project →** este repositorio. **Root Directory: `web`**. El preset de Angular
   sirve; `web/vercel.json` ya fija `npm run build`, la salida `dist/web/browser` y el rewrite a `index.html`
   (rutas de Angular).
3. No hay variables de entorno: la URL de la API sale de `environment.ts` al compilar.
4. Despliega y anota el dominio (`https://<proyecto>.vercel.app`).

## 4. Cerrar el círculo: CORS

Vuelve a Railway y pon el dominio de Vercel en `CORS_ORIGINS` (solo el origen, sin ruta ni barra final):

```
CORS_ORIGINS=https://<proyecto>.vercel.app
```

Si usas otro dominio o los despliegues de vista previa de Vercel, agrégalos separados por comas: cada
dominio distinto necesita su entrada. Railway vuelve a desplegar al guardar.

## 5. Verificación

1. `GET https://<servicio>.up.railway.app/health` → 200.
2. Abre la web de Vercel: se ve la portada y la tienda de `fashionstore` carga el catálogo.
3. Inicia sesión como superadministrador (sin empresa): ves la gestión de empresas y planes.
4. Inicia sesión como administrador de `fashionstore`: panel, productos, inventario y ventas con datos.
5. Registra una venta presencial con el cajero demo.
6. En Reportes: ejecuta un reporte con IA y descárgalo en Excel y PDF (prueba que CORS expone
   `Content-Disposition`).
7. Entra como administrador de `boutique-andina` (plan Básico): la IA y el ML no deben estar disponibles.

## 6. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| El despliegue falla en el healthcheck | Falta `JWT_SECRET_KEY` o `DATABASE_URL`; mira los logs: `Settings` lo dice por nombre. |
| La web carga pero el login dice error de red / CORS | `CORS_ORIGINS` sin el dominio exacto de Vercel (con `https://`, sin barra final). |
| La web llama a la URL vieja | Se te olvidó actualizar `apiUrl` antes de desplegar en Vercel. |
| Login 401 con credenciales correctas | Falta el código de empresa, o el usuario es de otra empresa. Sin empresa solo entra el superadministrador. |
| Login 429 | 5 fallos en 15 minutos para esa cuenta; espera `Retry-After`. |
| 403 `suscripcion_no_activa` | La suscripción de esa empresa venció o está suspendida. |
| La exportación no descarga con nombre | CORS: revisa que el dominio de Vercel esté en `CORS_ORIGINS`. |
| Tras reiniciar se pierden los bloqueos de login | Normal: están en memoria. Es la razón del worker único. |

## 7. Cosas a tener en cuenta

- **No corras `alembic` ni scripts contra Railway por accidente**: usa siempre la variable `DATABASE_URL` de
  la sesión de PowerShell y quítala al terminar (`Remove-Item Env:DATABASE_URL`).
- **Migraciones futuras:** `start.sh` las aplica en cada despliegue antes de levantar uvicorn.
- **Purga de bitácora:** `POST /api/v1/tareas/purgar-bitacora` con el `TAREAS_TOKEN` (cabecera de servicio);
  no está en la tarea interna, la dispara un cron externo si la quieres.
- **Pagos:** PayPal y Libélula siguen en sandbox; sus webhooks necesitan la URL pública del backend.
- **Plan de Railway:** vigila las horas y el crédito de Railway antes de la defensa (martes 10/11/2026).

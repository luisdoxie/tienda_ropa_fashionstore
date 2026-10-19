"""Códigos de permiso (`permiso.codigo`) que el código consulta. Solo
constantes: no importa de ningún paquete. Los seeds (scripts/seed_seguridad.py)
siguen siendo la fuente de qué códigos existen en la base."""

# ---- plataforma ----
PERMISO_USUARIOS = "usuarios.gestionar"
PERMISO_ROLES = "roles.gestionar"
# Acceso a los endpoints de organización (ciudades, sucursales, empleados).
PERMISO_ORGANIZACION = "organizacion.gestionar"
# Quién opera todas las sucursales y no solo la suya. Hoy comparte el código
# con PERMISO_ORGANIZACION (no hace falta correr seeds), pero es otra
# decisión: con multitenant pasa a "alcance dentro de la empresa" y puede
# separarse. Por eso son dos constantes y no una.
PERMISO_ALCANCE_GLOBAL = "organizacion.gestionar"

# ---- catalogo ----
PERMISO_CATALOGO = "catalogo.gestionar"
PERMISO_CATALOGO_VER = "catalogo.ver"
PERMISO_INVENTARIO_VER = "inventario.ver"
PERMISO_INVENTARIO_GESTIONAR = "inventario.gestionar"
PERMISO_ABASTECIMIENTO = "abastecimiento.gestionar"
PERMISO_PROBADOR = "probador.gestionar"

# ---- comercial ----
PERMISO_RESERVAS_CREAR = "reservas.crear"
PERMISO_STAFF_RESERVAS = "reservas.gestionar_sucursal"
PERMISO_VENTAS_DIGITAL = "ventas.digital"
PERMISO_VENTAS_PRESENCIAL = "ventas.presencial"
PERMISO_STAFF_VENTAS = "ventas.gestionar_sucursal"
PERMISO_VENTAS_GESTIONAR = "ventas.gestionar"
PERMISO_PAGOS = "pagos.gestionar"
PERMISO_ENTREGAS = "entregas.gestionar"

# ---- inteligencia ----
PERMISO_REPORTES_VER = "reportes.ver"

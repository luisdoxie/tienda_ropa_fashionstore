"""E05, PASO 1: las dependencias de permiso y de plan dejan su dato legible para
poder auditar cada ruta por introspección."""

from app.core.planes import exigir_funcionalidad
from app.core.security import require_permission

from .introspeccion import funcionalidades_de, permisos_de, rutas_api


def test_require_permission_expone_el_permiso():
    assert require_permission("catalogo.gestionar").permiso == "catalogo.gestionar"


def test_exigir_funcionalidad_expone_la_funcionalidad():
    assert exigir_funcionalidad("reportes_ia").funcionalidad == "reportes_ia"


def test_la_introspeccion_ve_un_permiso_real_en_una_ruta():
    ruta = next(r for r in rutas_api() if r.path == "/api/v1/roles" and "POST" in r.methods)
    assert permisos_de(ruta) == ["plataforma.gestionar"]
    assert funcionalidades_de(ruta) == []


def test_la_introspeccion_ve_una_funcionalidad_real_en_una_ruta():
    con_plan = [r for r in rutas_api() if funcionalidades_de(r)]
    assert con_plan, "Ninguna ruta declara funcionalidad de plan: la introspección no la ve"

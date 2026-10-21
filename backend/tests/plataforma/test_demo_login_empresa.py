"""E03: la secuencia de la prueba manual guiada. Se corre con `-s` para ver lo
que imprime:

    python -m pytest -q -p no:cacheprovider -s tests/plataforma/test_demo_login_empresa.py
"""

import datetime as dt

import jwt

from app.catalogo.models import Categoria, Producto
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.tenant import empresa_de, fijar_empresa
from tests.conftest import crear_superadmin_de_prueba

LOGIN = "/api/v1/auth/login"
CLAVE = "claveSegura123"


def _producto(db, empresa_id: int, nombre: str) -> None:
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    categoria = Categoria(nombre=f"Cat {nombre}")
    db.add(categoria)
    db.flush()
    db.add(Producto(codigo="PROD-1", nombre=nombre, categoria_id=categoria.id, precio_base=100))
    db.commit()
    fijar_empresa(db, original)


def test_demo_login_con_empresa(client_por_peticion, db_session, dos_empresas):
    cliente = client_por_peticion
    a, b = dos_empresas.a, dos_empresas.b
    _producto(db_session, a.id, "Camisa de A")
    _producto(db_session, b.id, "Camisa de B")
    crear_superadmin_de_prueba(db_session)

    def entrar(empresa, correo, clave=CLAVE):
        cuerpo = {"email": correo, "password": clave}
        if empresa is not None:
            cuerpo["empresa"] = empresa
        return cliente.post(LOGIN, json=cuerpo)

    print("\n1. Login con 'Tienda A' (nombre, no código):")
    exito = entrar("Tienda A", f"admin@{a.codigo}.example.com")
    print("   ->", exito.status_code)
    assert exito.status_code == 200

    print("2. Empresa inexistente, clave mala y correo ajeno: los tres iguales")
    respuestas = [
        entrar("Empresa Fantasma", f"admin@{a.codigo}.example.com"),
        entrar("Tienda A", f"admin@{a.codigo}.example.com", "claveIncorrecta99"),
        entrar("Tienda A", f"admin@{b.codigo}.example.com"),
    ]
    for r in respuestas:
        print("   ->", r.status_code, r.json())
    assert {(r.status_code, str(r.json())) for r in respuestas} == {(401, str({"detail": "Credenciales inválidas"}))}

    print("3. El token de A llama a /productos y solo ve lo suyo:")
    cabeceras = {"Authorization": f"Bearer {exito.json()['access_token']}"}
    nombres = [p["nombre"] for p in cliente.get("/api/v1/productos", headers=cabeceras).json()]
    print("   ->", nombres)
    assert nombres == ["Camisa de A"]

    print("4. Un token viejo, sin el claim de empresa:")
    ahora = dt.datetime.now(dt.timezone.utc)
    ajustes = get_settings()
    viejo = jwt.encode(
        {"sub": str(a.admin_id), "tipo": "access", "iat": ahora, "exp": ahora + dt.timedelta(minutes=5)},
        ajustes.jwt_secret_key,
        algorithm=ajustes.jwt_algorithm,
    )
    sin_claim = cliente.get("/api/v1/productos", headers={"Authorization": f"Bearer {viejo}"})
    print("   ->", sin_claim.status_code)
    assert sin_claim.status_code == 401

    print("5. El superadministrador entra sin empresa y GET /productos:")
    super_login = entrar(None, "super@plataforma.example.com")
    assert super_login.status_code == 200
    productos = cliente.get(
        "/api/v1/productos", headers={"Authorization": f"Bearer {super_login.json()['access_token']}"}
    )
    print("   ->", super_login.status_code, "y luego", productos.status_code)
    assert productos.status_code == 403

    print("6. Cinco intentos malos y el sexto:")
    limiter.reset()  # los logins de arriba ya gastaron parte del límite por IP; aquí se mide el de la cuenta
    for _ in range(5):
        entrar("Tienda B", "otro@example.com", "claveIncorrecta99")
    sexto = entrar("Tienda B", "otro@example.com", "claveIncorrecta99")
    print("   ->", sexto.status_code, sexto.headers.get("Retry-After"), "segundos")
    assert sexto.status_code == 429

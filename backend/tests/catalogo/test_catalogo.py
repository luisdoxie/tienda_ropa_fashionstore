def test_get_categorias_es_publico(client):
    assert client.get("/api/v1/categorias").status_code == 200


def test_post_categorias_requiere_admin(client, cliente_headers):
    respuesta = client.post(
        "/api/v1/categorias", json={"nombre": "Camisas"}, headers=cliente_headers
    )
    assert respuesta.status_code == 403


def test_post_categorias_sin_token_rechazado(client):
    assert client.post("/api/v1/categorias", json={"nombre": "Camisas"}).status_code == 401


def test_categoria_no_puede_ser_su_propio_padre(client, admin_headers):
    creada = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()

    respuesta = client.put(
        f"/api/v1/categorias/{creada['id']}",
        json={"categoria_padre_id": creada["id"]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


def test_categoria_no_permite_ciclos(client, admin_headers):
    abuelo = client.post("/api/v1/categorias", json={"nombre": "Ropa"}, headers=admin_headers).json()
    padre = client.post(
        "/api/v1/categorias",
        json={"nombre": "Superior", "categoria_padre_id": abuelo["id"]},
        headers=admin_headers,
    ).json()
    hijo = client.post(
        "/api/v1/categorias",
        json={"nombre": "Camisas", "categoria_padre_id": padre["id"]},
        headers=admin_headers,
    ).json()

    # abuelo pasa a ser hijo de hijo -> ciclo abuelo -> padre -> hijo -> abuelo
    respuesta = client.put(
        f"/api/v1/categorias/{abuelo['id']}",
        json={"categoria_padre_id": hijo["id"]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


def test_no_permite_desactivar_categoria_con_hijos(client, admin_headers):
    padre = client.post("/api/v1/categorias", json={"nombre": "Ropa"}, headers=admin_headers).json()
    client.post(
        "/api/v1/categorias",
        json={"nombre": "Camisas", "categoria_padre_id": padre["id"]},
        headers=admin_headers,
    )

    respuesta = client.delete(f"/api/v1/categorias/{padre['id']}", headers=admin_headers)
    assert respuesta.status_code == 409


def test_categoria_padre_inexistente_falla(client, admin_headers):
    respuesta = client.post(
        "/api/v1/categorias", json={"nombre": "Camisas", "categoria_padre_id": 9999}, headers=admin_headers
    )
    assert respuesta.status_code == 404


def test_talla_codigo_unico(client, admin_headers):
    primero = client.post(
        "/api/v1/tallas", json={"codigo": "M", "descripcion": "Medium", "orden": 1}, headers=admin_headers
    )
    assert primero.status_code == 201

    duplicado = client.post(
        "/api/v1/tallas", json={"codigo": "M", "descripcion": "Otra", "orden": 2}, headers=admin_headers
    )
    assert duplicado.status_code == 409


def test_tallas_se_listan_por_orden(client, admin_headers):
    client.post("/api/v1/tallas", json={"codigo": "L", "orden": 2}, headers=admin_headers)
    client.post("/api/v1/tallas", json={"codigo": "S", "orden": 1}, headers=admin_headers)

    listado = client.get("/api/v1/tallas").json()
    assert [t["codigo"] for t in listado] == ["S", "L"]


def test_talla_sin_uso_se_puede_eliminar_fisicamente(client, admin_headers, db_session):
    """talla no tiene columna `activo`: eliminar es un DELETE físico.
    El caso "en uso" (referenciada por producto_variante) se prueba en
    P2.2, cuando exista ese paquete y su FK real hacia talla."""
    from app.catalogo.models import Talla

    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()

    respuesta = client.delete(f"/api/v1/tallas/{talla['id']}", headers=admin_headers)
    assert respuesta.status_code == 204
    assert db_session.get(Talla, talla["id"]) is None


def test_color_codigo_hex_invalido_es_rechazado(client, admin_headers):
    respuesta = client.post(
        "/api/v1/colores", json={"nombre": "Rojo", "codigo_hex": "rojo"}, headers=admin_headers
    )
    assert respuesta.status_code == 422


def test_color_codigo_hex_valido(client, admin_headers):
    respuesta = client.post(
        "/api/v1/colores", json={"nombre": "Rojo", "codigo_hex": "#FF0000"}, headers=admin_headers
    )
    assert respuesta.status_code == 201


def test_material_get_publico_post_admin(client, cliente_headers):
    assert client.get("/api/v1/materiales").status_code == 200
    assert client.post("/api/v1/materiales", json={"nombre": "Algodon"}, headers=cliente_headers).status_code == 403


def test_temporada_fecha_fin_antes_de_inicio_falla(client, admin_headers):
    respuesta = client.post(
        "/api/v1/temporadas",
        json={"nombre": "Verano", "anio": 2026, "fecha_inicio": "2026-06-01", "fecha_fin": "2026-01-01"},
        headers=admin_headers,
    )
    assert respuesta.status_code == 422


def test_temporada_actualizar_fecha_fin_antes_de_inicio_existente_falla(client, admin_headers):
    temporada = client.post(
        "/api/v1/temporadas",
        json={"nombre": "Verano", "anio": 2026, "fecha_inicio": "2026-06-01"},
        headers=admin_headers,
    ).json()

    respuesta = client.put(
        f"/api/v1/temporadas/{temporada['id']}",
        json={"fecha_fin": "2026-01-01"},
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


def test_temporada_duplicada_es_rechazada(client, admin_headers):
    client.post("/api/v1/temporadas", json={"nombre": "Verano", "anio": 2026}, headers=admin_headers)
    respuesta = client.post(
        "/api/v1/temporadas", json={"nombre": "Verano", "anio": 2026}, headers=admin_headers
    )
    assert respuesta.status_code == 409


def test_coleccion_con_temporada_inexistente_falla(client, admin_headers):
    respuesta = client.post(
        "/api/v1/colecciones", json={"nombre": "Coleccion X", "temporada_id": 9999}, headers=admin_headers
    )
    assert respuesta.status_code == 404


def test_coleccion_sin_temporada_es_valida(client, admin_headers):
    respuesta = client.post(
        "/api/v1/colecciones", json={"nombre": "Coleccion X"}, headers=admin_headers
    )
    assert respuesta.status_code == 201


def test_resolver_categoria_por_nombre_es_exacto_y_no_usa_comodines(client, admin_headers, db_session):
    from app.catalogo.politicas import resolver_categoria_por_nombre

    creada = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()

    assert resolver_categoria_por_nombre(db_session, "camisas") == creada["id"]
    assert resolver_categoria_por_nombre(db_session, " Camisas ") == creada["id"]
    assert resolver_categoria_por_nombre(db_session, "%") is None
    assert resolver_categoria_por_nombre(db_session, "Cami%") is None
    assert resolver_categoria_por_nombre(db_session, "Camisa_") is None

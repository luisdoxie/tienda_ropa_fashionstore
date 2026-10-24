"""E05, 4.8: consulta de consistencia entre empresas.

El nombre empieza por "test_zz" para que corra DESPUÉS de todas las matrices (incluidas las
pruebas de escritura y las positivas): comprueba el estado final de la base. Para CADA clave
foránea entre dos tablas que tienen empresa_id:

    SELECT count(*) FROM hijo h JOIN padre p ON p.id = h.<fk> WHERE h.empresa_id <> p.empresa_id

debe dar 0. Las FK a tablas globales (rol, permiso, estados) y las filas con FK nula no entran.
Se genera desde `Base.metadata`: una tabla o relación nueva se incluye sola. El mismo recorrido
corre en PostgreSQL en `tests/postgres/test_aislamiento_pg.py`.
"""

from sqlalchemy import func, select

from app.core.database import Base


def relaciones_entre_tablas_de_empresa():
    """(tabla hija, columna, tabla padre, columna del padre) para cada FK entre tablas con empresa_id."""
    relaciones = []
    for tabla in Base.metadata.sorted_tables:
        if "empresa_id" not in tabla.c:
            continue
        for fk in tabla.foreign_keys:
            padre = fk.column.table
            if "empresa_id" in padre.c:  # incluye la autorreferencia (categoría padre)
                relaciones.append((tabla, fk.parent.name, padre, fk.column.name))
    return relaciones


def contar_inconsistentes(conexion) -> list[str]:
    inconsistentes = []
    for hijo, columna, padre, columna_padre in relaciones_entre_tablas_de_empresa():
        h, p = hijo.alias("h"), padre.alias("p")
        consulta = (
            select(func.count())
            .select_from(h.join(p, p.c[columna_padre] == h.c[columna]))
            .where(h.c.empresa_id != p.c.empresa_id)
        )
        cantidad = conexion.execute(consulta).scalar_one()
        if cantidad:
            inconsistentes.append(f"{hijo.name}.{columna} -> {padre.name}: {cantidad} fila(s)")
    return inconsistentes


def test_ninguna_fila_apunta_a_otra_empresa(mundo):
    relaciones = relaciones_entre_tablas_de_empresa()
    with mundo.engine.connect() as conexion:
        inconsistentes = contar_inconsistentes(conexion)
    print(f"\nRelaciones revisadas entre tablas de empresa: {len(relaciones)}")
    assert len(relaciones) >= 50, f"se esperaban decenas de relaciones, hay {len(relaciones)}"
    assert inconsistentes == [], "filas que apuntan a otra empresa:\n  " + "\n  ".join(inconsistentes)


def test_la_consulta_detecta_una_fila_inconsistente(mundo):
    """Control de la propia consulta: una fila de A que apunte a un padre de B se detecta."""
    a, b = mundo.a, mundo.b
    with mundo.engine.connect() as conexion:
        conexion.exec_driver_sql(
            "UPDATE sucursal SET ciudad_id = ? WHERE id = ?", (b.ids["ciudad"], a.ids["sucursal_destino"])
        )
        try:
            assert any("sucursal.ciudad_id" in fila for fila in contar_inconsistentes(conexion))
        finally:
            conexion.rollback()
    with mundo.engine.connect() as conexion:
        assert contar_inconsistentes(conexion) == []

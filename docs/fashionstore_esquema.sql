-- =====================================================================
-- FashionStore - Esquema fisico PostgreSQL
-- Plataforma inteligente de comercio electronico para tienda de ropa
-- Sistemas II - S2-2026
-- =====================================================================
-- Organizado segun los paquetes del diagrama de paquetes.
-- Convenciones:
--   * Nombres de tabla en singular y en espanol.
--   * Toda tabla de negocio lleva creado_en y activo (borrado logico).
--   * Los estados son tablas, no ENUM, para poder ampliarlos sin migracion.
--   * Los montos son NUMERIC(12,2). Los costos NUMERIC(12,4) por el
--     promedio ponderado, que arrastra decimales.
-- =====================================================================


-- =====================================================================
-- PAQUETE 1: SEGURIDAD
-- =====================================================================

CREATE TABLE rol (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(40)  NOT NULL UNIQUE,
    descripcion     VARCHAR(200),
    activo          BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE permiso (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(60)  NOT NULL UNIQUE,
    modulo          VARCHAR(40)  NOT NULL,
    descripcion     VARCHAR(200)
);

CREATE TABLE rol_permiso (
    rol_id          INT NOT NULL REFERENCES rol(id) ON DELETE CASCADE,
    permiso_id      INT NOT NULL REFERENCES permiso(id) ON DELETE CASCADE,
    PRIMARY KEY (rol_id, permiso_id)
);

CREATE TABLE usuario (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(60)  NOT NULL,
    apellido        VARCHAR(60)  NOT NULL,
    email           VARCHAR(120) NOT NULL UNIQUE,
    telefono        VARCHAR(20),
    password_hash   VARCHAR(255) NOT NULL,
    ultimo_acceso   TIMESTAMPTZ,
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ
);

CREATE TABLE usuario_rol (
    usuario_id      INT NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    rol_id          INT NOT NULL REFERENCES rol(id),
    PRIMARY KEY (usuario_id, rol_id)
);


-- =====================================================================
-- PAQUETE 2: ORGANIZACION
-- =====================================================================

CREATE TABLE ciudad (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(60) NOT NULL,
    departamento    VARCHAR(60),
    activo          BOOLEAN     NOT NULL DEFAULT TRUE,
    UNIQUE (nombre, departamento)
);

CREATE TABLE sucursal (
    id              SERIAL PRIMARY KEY,
    ciudad_id       INT NOT NULL REFERENCES ciudad(id),
    codigo          VARCHAR(15)  NOT NULL UNIQUE,
    nombre          VARCHAR(80)  NOT NULL,
    direccion       VARCHAR(200) NOT NULL,
    telefono        VARCHAR(20),
    latitud         NUMERIC(10,7),
    longitud        NUMERIC(10,7),
    es_deposito     BOOLEAN      NOT NULL DEFAULT FALSE,
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE horario_sucursal (
    id              SERIAL PRIMARY KEY,
    sucursal_id     INT NOT NULL REFERENCES sucursal(id) ON DELETE CASCADE,
    dia_semana      SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
    hora_apertura   TIME NOT NULL,
    hora_cierre     TIME NOT NULL,
    CHECK (hora_cierre > hora_apertura),
    UNIQUE (sucursal_id, dia_semana)
);

CREATE TABLE empleado (
    id              SERIAL PRIMARY KEY,
    usuario_id      INT NOT NULL UNIQUE REFERENCES usuario(id),
    sucursal_id     INT REFERENCES sucursal(id),
    ci              VARCHAR(20),
    cargo           VARCHAR(60),
    fecha_ingreso   DATE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE cliente (
    id                  SERIAL PRIMARY KEY,
    usuario_id          INT NOT NULL UNIQUE REFERENCES usuario(id),
    ci_nit              VARCHAR(20),
    razon_social        VARCHAR(120),
    fecha_nacimiento    DATE,
    -- Datos usados por la recomendacion de talla (CU-52). Opcionales.
    estatura_cm         SMALLINT CHECK (estatura_cm BETWEEN 100 AND 250),
    preferencia_ajuste  VARCHAR(15) CHECK (preferencia_ajuste IN ('ajustado','regular','holgado')),
    acepta_datos_foto   BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- PAQUETE 3: CATALOGO
-- =====================================================================

CREATE TABLE categoria (
    id                  SERIAL PRIMARY KEY,
    categoria_padre_id  INT REFERENCES categoria(id),
    nombre              VARCHAR(60) NOT NULL,
    descripcion         VARCHAR(200),
    activo              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE talla (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(10) NOT NULL UNIQUE,
    descripcion     VARCHAR(40),
    orden           SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE color (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(40) NOT NULL UNIQUE,
    codigo_hex      CHAR(7)
);

CREATE TABLE material (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(40) NOT NULL UNIQUE,
    descripcion     VARCHAR(200)
);

CREATE TABLE temporada (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(60) NOT NULL,
    anio            SMALLINT NOT NULL,
    fecha_inicio    DATE,
    fecha_fin       DATE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (nombre, anio)
);

CREATE TABLE coleccion (
    id              SERIAL PRIMARY KEY,
    temporada_id    INT REFERENCES temporada(id),
    nombre          VARCHAR(80) NOT NULL,
    descripcion     VARCHAR(300),
    activo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE producto (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(30)  NOT NULL UNIQUE,
    nombre          VARCHAR(120) NOT NULL,
    descripcion     TEXT,
    categoria_id    INT NOT NULL REFERENCES categoria(id),
    material_id     INT REFERENCES material(id),
    temporada_id    INT REFERENCES temporada(id),
    coleccion_id    INT REFERENCES coleccion(id),
    genero          VARCHAR(15) NOT NULL DEFAULT 'unisex'
                    CHECK (genero IN ('hombre','mujer','unisex','nino')),
    precio_base     NUMERIC(12,2) NOT NULL CHECK (precio_base >= 0),
    -- Marca si la categoria admite probador virtual (torso superior).
    admite_probador BOOLEAN NOT NULL DEFAULT FALSE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por      INT REFERENCES usuario(id)
);

-- La variante es la unidad real de negocio: el stock, el precio final,
-- la reserva y la venta cuelgan de aqui, nunca del producto.
CREATE TABLE producto_variante (
    id              SERIAL PRIMARY KEY,
    producto_id     INT NOT NULL REFERENCES producto(id) ON DELETE CASCADE,
    talla_id        INT NOT NULL REFERENCES talla(id),
    color_id        INT NOT NULL REFERENCES color(id),
    sku             VARCHAR(40) NOT NULL UNIQUE,
    codigo_barras   VARCHAR(40) UNIQUE,
    precio          NUMERIC(12,2) CHECK (precio >= 0),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (producto_id, talla_id, color_id)
);

CREATE TABLE producto_imagen (
    id              SERIAL PRIMARY KEY,
    producto_id     INT NOT NULL REFERENCES producto(id) ON DELETE CASCADE,
    color_id        INT REFERENCES color(id),
    url             TEXT NOT NULL,
    orden           SMALLINT NOT NULL DEFAULT 0,
    es_principal    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Rangos corporales por talla. Base de la recomendacion de talla.
CREATE TABLE tabla_medida (
    id              SERIAL PRIMARY KEY,
    producto_id     INT REFERENCES producto(id) ON DELETE CASCADE,
    categoria_id    INT REFERENCES categoria(id),
    talla_id        INT NOT NULL REFERENCES talla(id),
    pecho_min_cm    NUMERIC(5,1),
    pecho_max_cm    NUMERIC(5,1),
    cintura_min_cm  NUMERIC(5,1),
    cintura_max_cm  NUMERIC(5,1),
    hombros_cm      NUMERIC(5,1),
    largo_cm        NUMERIC(5,1),
    CHECK (producto_id IS NOT NULL OR categoria_id IS NOT NULL)
);

CREATE TABLE favorito (
    cliente_id      INT NOT NULL REFERENCES cliente(id) ON DELETE CASCADE,
    variante_id     INT NOT NULL REFERENCES producto_variante(id) ON DELETE CASCADE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cliente_id, variante_id)
);


-- =====================================================================
-- PAQUETE 4: ABASTECIMIENTO
-- =====================================================================

CREATE TABLE proveedor (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(120) NOT NULL,
    nit             VARCHAR(20) UNIQUE,
    contacto        VARCHAR(80),
    telefono        VARCHAR(20),
    email           VARCHAR(120),
    direccion       VARCHAR(200),
    usuario_id      INT REFERENCES usuario(id),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE producto_proveedor (
    proveedor_id        INT NOT NULL REFERENCES proveedor(id) ON DELETE CASCADE,
    producto_id         INT NOT NULL REFERENCES producto(id) ON DELETE CASCADE,
    costo_referencial   NUMERIC(12,4),
    dias_entrega        SMALLINT,
    PRIMARY KEY (proveedor_id, producto_id)
);

CREATE TABLE orden_compra (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(20) NOT NULL UNIQUE,
    proveedor_id    INT NOT NULL REFERENCES proveedor(id),
    sucursal_id     INT NOT NULL REFERENCES sucursal(id),
    fecha_emision   DATE NOT NULL DEFAULT CURRENT_DATE,
    fecha_esperada  DATE,
    estado          VARCHAR(20) NOT NULL DEFAULT 'borrador'
                    CHECK (estado IN ('borrador','enviada','parcial','recibida','anulada')),
    total           NUMERIC(12,2) NOT NULL DEFAULT 0,
    creado_por      INT REFERENCES usuario(id),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orden_compra_detalle (
    id              SERIAL PRIMARY KEY,
    orden_compra_id INT NOT NULL REFERENCES orden_compra(id) ON DELETE CASCADE,
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    costo_unitario  NUMERIC(12,4) NOT NULL CHECK (costo_unitario >= 0),
    UNIQUE (orden_compra_id, variante_id)
);

-- Unica entrada de mercaderia con costo. Sin esto no hay promedio ponderado.
CREATE TABLE recepcion (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(20) NOT NULL UNIQUE,
    orden_compra_id INT REFERENCES orden_compra(id),
    proveedor_id    INT NOT NULL REFERENCES proveedor(id),
    sucursal_id     INT NOT NULL REFERENCES sucursal(id),
    empleado_id     INT REFERENCES empleado(id),
    fecha           TIMESTAMPTZ NOT NULL DEFAULT now(),
    observacion     VARCHAR(300)
);

CREATE TABLE recepcion_detalle (
    id              SERIAL PRIMARY KEY,
    recepcion_id    INT NOT NULL REFERENCES recepcion(id) ON DELETE CASCADE,
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    costo_unitario  NUMERIC(12,4) NOT NULL CHECK (costo_unitario >= 0)
);


-- =====================================================================
-- PAQUETE 5: INVENTARIO
-- =====================================================================

-- Existencia por par variante-sucursal. cantidad_disponible es calculada:
-- lo reservado sigue fisicamente en la tienda pero no se puede vender.
CREATE TABLE stock (
    id                    SERIAL PRIMARY KEY,
    variante_id           INT NOT NULL REFERENCES producto_variante(id),
    sucursal_id           INT NOT NULL REFERENCES sucursal(id),
    cantidad_fisica       INT NOT NULL DEFAULT 0 CHECK (cantidad_fisica >= 0),
    cantidad_reservada    INT NOT NULL DEFAULT 0 CHECK (cantidad_reservada >= 0),
    cantidad_disponible   INT GENERATED ALWAYS AS (cantidad_fisica - cantidad_reservada) STORED,
    stock_minimo          INT NOT NULL DEFAULT 0,
    stock_maximo          INT,
    costo_promedio        NUMERIC(12,4) NOT NULL DEFAULT 0,
    actualizado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (variante_id, sucursal_id),
    CHECK (cantidad_reservada <= cantidad_fisica)
);

CREATE TABLE tipo_movimiento (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(25) NOT NULL UNIQUE,
    nombre          VARCHAR(60) NOT NULL,
    signo           SMALLINT NOT NULL CHECK (signo IN (-1, 1)),
    afecta_costo    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Libro inmutable. Nunca se edita ni se borra: se corrige con otro movimiento.
-- El stock es la suma de sus movimientos.
CREATE TABLE movimiento_inventario (
    id                  BIGSERIAL PRIMARY KEY,
    variante_id         INT NOT NULL REFERENCES producto_variante(id),
    sucursal_id         INT NOT NULL REFERENCES sucursal(id),
    tipo_movimiento_id  INT NOT NULL REFERENCES tipo_movimiento(id),
    cantidad            INT NOT NULL CHECK (cantidad <> 0),
    costo_unitario      NUMERIC(12,4),
    costo_promedio_post NUMERIC(12,4),
    saldo_post          INT NOT NULL,
    referencia_tipo     VARCHAR(25),
    referencia_id       INT,
    usuario_id          INT REFERENCES usuario(id),
    observacion         VARCHAR(300),
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transferencia (
    id                  SERIAL PRIMARY KEY,
    codigo              VARCHAR(20) NOT NULL UNIQUE,
    sucursal_origen_id  INT NOT NULL REFERENCES sucursal(id),
    sucursal_destino_id INT NOT NULL REFERENCES sucursal(id),
    estado              VARCHAR(20) NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','en_transito','recibida','anulada')),
    fecha_envio         TIMESTAMPTZ,
    fecha_recepcion     TIMESTAMPTZ,
    usuario_id          INT REFERENCES usuario(id),
    CHECK (sucursal_origen_id <> sucursal_destino_id)
);

CREATE TABLE transferencia_detalle (
    id                  SERIAL PRIMARY KEY,
    transferencia_id    INT NOT NULL REFERENCES transferencia(id) ON DELETE CASCADE,
    variante_id         INT NOT NULL REFERENCES producto_variante(id),
    cantidad            INT NOT NULL CHECK (cantidad > 0)
);


-- =====================================================================
-- PAQUETE 6: RESERVAS
-- =====================================================================

CREATE TABLE estado_reserva (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(25) NOT NULL UNIQUE,
    nombre          VARCHAR(60) NOT NULL,
    es_final        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE reserva (
    id                  SERIAL PRIMARY KEY,
    codigo              VARCHAR(20) NOT NULL UNIQUE,
    cliente_id          INT NOT NULL REFERENCES cliente(id),
    sucursal_id         INT NOT NULL REFERENCES sucursal(id),
    estado_id           INT NOT NULL REFERENCES estado_reserva(id),
    fecha_visita        DATE NOT NULL,
    hora_visita_desde   TIME NOT NULL,
    hora_visita_hasta   TIME NOT NULL,
    fecha_expiracion    TIMESTAMPTZ NOT NULL,
    observacion         VARCHAR(300),
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (hora_visita_hasta > hora_visita_desde)
);

CREATE TABLE reserva_detalle (
    id              SERIAL PRIMARY KEY,
    reserva_id      INT NOT NULL REFERENCES reserva(id) ON DELETE CASCADE,
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    cantidad        INT NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    -- NULL = aun no probada. TRUE = el cliente la compra. FALSE = se libera al stock.
    seleccionada    BOOLEAN,
    preparada       BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (reserva_id, variante_id)
);

CREATE TABLE reserva_historial (
    id              SERIAL PRIMARY KEY,
    reserva_id      INT NOT NULL REFERENCES reserva(id) ON DELETE CASCADE,
    estado_id       INT NOT NULL REFERENCES estado_reserva(id),
    usuario_id      INT REFERENCES usuario(id),
    comentario      VARCHAR(300),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- PAQUETE 7: VENTAS
-- =====================================================================

CREATE TABLE estado_venta (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(25) NOT NULL UNIQUE,
    nombre          VARCHAR(60) NOT NULL,
    es_final        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE promocion (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(80) NOT NULL,
    tipo            VARCHAR(15) NOT NULL CHECK (tipo IN ('porcentaje','monto')),
    valor           NUMERIC(12,2) NOT NULL CHECK (valor > 0),
    fecha_inicio    DATE NOT NULL,
    fecha_fin       DATE NOT NULL,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (fecha_fin >= fecha_inicio)
);

CREATE TABLE promocion_alcance (
    id              SERIAL PRIMARY KEY,
    promocion_id    INT NOT NULL REFERENCES promocion(id) ON DELETE CASCADE,
    producto_id     INT REFERENCES producto(id),
    categoria_id    INT REFERENCES categoria(id),
    temporada_id    INT REFERENCES temporada(id),
    CHECK (num_nonnulls(producto_id, categoria_id, temporada_id) = 1)
);

-- Una sola tabla para venta digital y presencial: cambia el canal, no la entidad.
CREATE TABLE venta (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(20) NOT NULL UNIQUE,
    canal           VARCHAR(15) NOT NULL CHECK (canal IN ('digital','presencial')),
    cliente_id      INT REFERENCES cliente(id),
    sucursal_id     INT NOT NULL REFERENCES sucursal(id),
    cajero_id       INT REFERENCES empleado(id),
    reserva_id      INT REFERENCES reserva(id),
    estado_id       INT NOT NULL REFERENCES estado_venta(id),
    fecha           TIMESTAMPTZ NOT NULL DEFAULT now(),
    subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,
    descuento       NUMERIC(12,2) NOT NULL DEFAULT 0,
    costo_envio     NUMERIC(12,2) NOT NULL DEFAULT 0,
    total           NUMERIC(12,2) NOT NULL DEFAULT 0,
    -- En venta presencial el cajero es obligatorio.
    CHECK (canal <> 'presencial' OR cajero_id IS NOT NULL)
);

CREATE TABLE venta_detalle (
    id                  SERIAL PRIMARY KEY,
    venta_id            INT NOT NULL REFERENCES venta(id) ON DELETE CASCADE,
    variante_id         INT NOT NULL REFERENCES producto_variante(id),
    cantidad            INT NOT NULL CHECK (cantidad > 0),
    precio_unitario     NUMERIC(12,2) NOT NULL,
    descuento_unitario  NUMERIC(12,2) NOT NULL DEFAULT 0,
    -- Costo congelado al momento de la venta, para calcular margen real.
    costo_unitario      NUMERIC(12,4),
    subtotal            NUMERIC(12,2) NOT NULL
);

CREATE TABLE carrito (
    id              SERIAL PRIMARY KEY,
    cliente_id      INT NOT NULL REFERENCES cliente(id),
    sucursal_id     INT REFERENCES sucursal(id),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cliente_id)
);

CREATE TABLE carrito_detalle (
    id              SERIAL PRIMARY KEY,
    carrito_id      INT NOT NULL REFERENCES carrito(id) ON DELETE CASCADE,
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    UNIQUE (carrito_id, variante_id)
);

CREATE TABLE devolucion (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(20) NOT NULL UNIQUE,
    venta_id        INT NOT NULL REFERENCES venta(id),
    fecha           TIMESTAMPTZ NOT NULL DEFAULT now(),
    motivo          VARCHAR(300),
    estado          VARCHAR(20) NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente','aprobada','rechazada')),
    usuario_id      INT REFERENCES usuario(id)
);

CREATE TABLE devolucion_detalle (
    id                  SERIAL PRIMARY KEY,
    devolucion_id       INT NOT NULL REFERENCES devolucion(id) ON DELETE CASCADE,
    venta_detalle_id    INT NOT NULL REFERENCES venta_detalle(id),
    cantidad            INT NOT NULL CHECK (cantidad > 0)
);


-- =====================================================================
-- PAQUETE 8: PAGOS
-- =====================================================================

CREATE TABLE metodo_pago (
    id                  SERIAL PRIMARY KEY,
    codigo              VARCHAR(25) NOT NULL UNIQUE,
    nombre              VARCHAR(60) NOT NULL,
    requiere_pasarela   BOOLEAN NOT NULL DEFAULT FALSE,
    disponible_caja     BOOLEAN NOT NULL DEFAULT TRUE,
    disponible_online   BOOLEAN NOT NULL DEFAULT FALSE,
    activo              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE estado_pago (
    id              SERIAL PRIMARY KEY,
    codigo          VARCHAR(25) NOT NULL UNIQUE,
    nombre          VARCHAR(60) NOT NULL
);

CREATE TABLE pago (
    id                  SERIAL PRIMARY KEY,
    venta_id            INT NOT NULL REFERENCES venta(id),
    metodo_pago_id      INT NOT NULL REFERENCES metodo_pago(id),
    estado_id           INT NOT NULL REFERENCES estado_pago(id),
    monto               NUMERIC(12,2) NOT NULL CHECK (monto > 0),
    referencia_externa  VARCHAR(120),
    fecha               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transaccion_pasarela (
    id                  SERIAL PRIMARY KEY,
    pago_id             INT NOT NULL REFERENCES pago(id) ON DELETE CASCADE,
    pasarela            VARCHAR(30) NOT NULL,
    id_transaccion      VARCHAR(120),
    payload_envio       JSONB,
    payload_respuesta   JSONB,
    estado              VARCHAR(25) NOT NULL,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- PAQUETE 9: ENTREGAS
-- =====================================================================

-- Tarifa por anillo, tal como funciona el reparto en Santa Cruz.
CREATE TABLE zona_envio (
    id              SERIAL PRIMARY KEY,
    ciudad_id       INT NOT NULL REFERENCES ciudad(id),
    nombre          VARCHAR(60) NOT NULL,
    anillo_desde    SMALLINT,
    anillo_hasta    SMALLINT,
    tarifa_base     NUMERIC(12,2) NOT NULL CHECK (tarifa_base >= 0),
    activo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE regla_tarifa_envio (
    id              SERIAL PRIMARY KEY,
    zona_envio_id   INT NOT NULL REFERENCES zona_envio(id) ON DELETE CASCADE,
    peso_desde_kg   NUMERIC(6,2) NOT NULL DEFAULT 0,
    peso_hasta_kg   NUMERIC(6,2),
    recargo         NUMERIC(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE direccion_cliente (
    id              SERIAL PRIMARY KEY,
    cliente_id      INT NOT NULL REFERENCES cliente(id) ON DELETE CASCADE,
    zona_envio_id   INT REFERENCES zona_envio(id),
    alias           VARCHAR(40),
    direccion       VARCHAR(200) NOT NULL,
    referencia      VARCHAR(200),
    latitud         NUMERIC(10,7),
    longitud        NUMERIC(10,7),
    es_principal    BOOLEAN NOT NULL DEFAULT FALSE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE envio (
    id                  SERIAL PRIMARY KEY,
    venta_id            INT NOT NULL UNIQUE REFERENCES venta(id),
    direccion_id        INT NOT NULL REFERENCES direccion_cliente(id),
    zona_envio_id       INT NOT NULL REFERENCES zona_envio(id),
    costo               NUMERIC(12,2) NOT NULL,
    peso_kg             NUMERIC(6,2),
    estado              VARCHAR(20) NOT NULL DEFAULT 'programado'
                        CHECK (estado IN ('programado','en_ruta','entregado','fallido')),
    fecha_programada    TIMESTAMPTZ,
    fecha_entrega       TIMESTAMPTZ,
    repartidor          VARCHAR(80)
);


-- =====================================================================
-- PAQUETE 10: PROBADOR VIRTUAL
-- =====================================================================

CREATE TABLE activo_probador (
    id              SERIAL PRIMARY KEY,
    variante_id     INT NOT NULL REFERENCES producto_variante(id) ON DELETE CASCADE,
    tipo            VARCHAR(20) NOT NULL CHECK (tipo IN ('overlay_2d','flatlay_ia','thumb')),
    url             TEXT NOT NULL,
    ancho_px        INT,
    alto_px         INT,
    estado          VARCHAR(15) NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente','validado','rechazado')),
    creado_por      INT REFERENCES usuario(id),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_activo_variante_tipo
    ON activo_probador (variante_id, tipo) WHERE estado <> 'rechazado';

-- Cache del modo generativo: evita pagar dos veces la misma combinacion.
CREATE TABLE probador_generacion (
    id              SERIAL PRIMARY KEY,
    cliente_id      INT REFERENCES cliente(id),
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    hash_foto       CHAR(64) NOT NULL,
    url_resultado   TEXT,
    proveedor       VARCHAR(30),
    estado          VARCHAR(15) NOT NULL DEFAULT 'en_proceso'
                    CHECK (estado IN ('en_proceso','completado','fallido')),
    mensaje_error   VARCHAR(300),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_generacion_cache ON probador_generacion (hash_foto, variante_id);


-- =====================================================================
-- PAQUETE 11: INTELIGENCIA
-- =====================================================================

-- Sin esto el recomendador no tiene historial que analizar el dia de la defensa.
CREATE TABLE historial_navegacion (
    id              BIGSERIAL PRIMARY KEY,
    cliente_id      INT REFERENCES cliente(id),
    sesion_anonima  VARCHAR(64),
    producto_id     INT REFERENCES producto(id),
    variante_id     INT REFERENCES producto_variante(id),
    tipo_evento     VARCHAR(25) NOT NULL
                    CHECK (tipo_evento IN ('vista','busqueda','carrito','probador','favorito')),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_historial_cliente ON historial_navegacion (cliente_id, creado_en DESC);

CREATE TABLE consulta_voz (
    id                  SERIAL PRIMARY KEY,
    cliente_id          INT REFERENCES cliente(id),
    texto_transcrito    TEXT NOT NULL,
    filtros_json        JSONB,
    cantidad_resultados INT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE recomendacion (
    id              SERIAL PRIMARY KEY,
    cliente_id      INT NOT NULL REFERENCES cliente(id),
    variante_id     INT NOT NULL REFERENCES producto_variante(id),
    puntaje         NUMERIC(6,4),
    motivo          VARCHAR(200),
    generado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- PAQUETE 12: NUCLEO / AUDITORIA
-- =====================================================================

-- Implementada en la E06 (segundo parcial): registro de SOLO ANEXAR de las
-- acciones sensibles. Cambios respecto al primer parcial: empresa_id (NULL =
-- accion de la plataforma sin empresa), accion VARCHAR(40) (hay acciones como
-- 'contrasena_restablecida') y los tres indices de consulta. En los modelos
-- creado_en es TIMESTAMP sin zona, en UTC, como el resto de las tablas.
-- La base real tiene 63 tablas.
CREATE TABLE bitacora (
    id              BIGSERIAL PRIMARY KEY,
    empresa_id      INT REFERENCES empresa(id),
    usuario_id      INT REFERENCES usuario(id),
    entidad         VARCHAR(60) NOT NULL,
    entidad_id      BIGINT,
    accion          VARCHAR(40) NOT NULL,
    datos           JSONB,
    ip              VARCHAR(45),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bitacora_empresa_fecha   ON bitacora (empresa_id, creado_en);
CREATE INDEX ix_bitacora_empresa_entidad ON bitacora (empresa_id, entidad, entidad_id);
CREATE INDEX ix_bitacora_usuario_fecha   ON bitacora (usuario_id, creado_en);

CREATE TABLE notificacion (
    id              SERIAL PRIMARY KEY,
    usuario_id      INT NOT NULL REFERENCES usuario(id),
    titulo          VARCHAR(120) NOT NULL,
    mensaje         VARCHAR(400),
    tipo            VARCHAR(30),
    referencia_id   INT,
    leida           BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- INDICES DE CONSULTA
-- =====================================================================

CREATE INDEX ix_producto_categoria    ON producto (categoria_id) WHERE activo;
CREATE INDEX ix_producto_temporada    ON producto (temporada_id) WHERE activo;
CREATE INDEX ix_producto_genero       ON producto (genero, categoria_id) WHERE activo;
CREATE INDEX ix_variante_producto     ON producto_variante (producto_id) WHERE activo;
CREATE INDEX ix_stock_sucursal        ON stock (sucursal_id, cantidad_disponible);
CREATE INDEX ix_movimiento_variante   ON movimiento_inventario (variante_id, sucursal_id, creado_en DESC);
CREATE INDEX ix_reserva_sucursal      ON reserva (sucursal_id, fecha_visita, estado_id);
CREATE INDEX ix_reserva_cliente       ON reserva (cliente_id, creado_en DESC);
CREATE INDEX ix_venta_fecha           ON venta (fecha DESC, sucursal_id);
CREATE INDEX ix_venta_cliente         ON venta (cliente_id, fecha DESC);
CREATE INDEX ix_pago_venta            ON pago (venta_id);


-- =====================================================================
-- VISTAS DE APOYO PARA REPORTES
-- =====================================================================

CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN talla t             ON t.id = v.talla_id
JOIN color c             ON c.id = v.color_id
JOIN sucursal s          ON s.id = st.sucursal_id;

CREATE VIEW vw_ventas_detalle AS
SELECT  ve.id              AS venta_id,
        ve.codigo,
        ve.canal,
        ve.fecha,
        s.nombre           AS sucursal,
        p.nombre           AS producto,
        vd.cantidad,
        vd.precio_unitario,
        vd.subtotal,
        vd.costo_unitario,
        (vd.subtotal - (vd.cantidad * COALESCE(vd.costo_unitario, 0))) AS margen
FROM venta_detalle vd
JOIN venta ve            ON ve.id = vd.venta_id
JOIN sucursal s          ON s.id = ve.sucursal_id
JOIN producto_variante v ON v.id = vd.variante_id
JOIN producto p          ON p.id = v.producto_id;


-- =====================================================================
-- DATOS BASE
-- =====================================================================

INSERT INTO rol (nombre, descripcion) VALUES
 ('administrador',       'Acceso total al sistema'),
 ('encargado_sucursal',  'Gestiona reservas e inventario de su sucursal'),
 ('cajero',              'Registra ventas presenciales y cobros'),
 ('proveedor',           'Registra informacion de sus productos'),
 ('cliente',             'Compra, reserva y usa el probador virtual');

INSERT INTO estado_reserva (codigo, nombre, es_final) VALUES
 ('pendiente',   'Pendiente de preparacion', FALSE),
 ('preparada',   'Prendas preparadas',       FALSE),
 ('en_prueba',   'Cliente en sucursal',      FALSE),
 ('completada',  'Completada',               TRUE),
 ('cancelada',   'Cancelada por el cliente', TRUE),
 ('expirada',    'Expirada por tiempo',      TRUE);

INSERT INTO estado_venta (codigo, nombre, es_final) VALUES
 ('pendiente_pago', 'Pendiente de pago', FALSE),
 ('pagada',         'Pagada',            FALSE),
 ('entregada',      'Entregada',         TRUE),
 ('anulada',        'Anulada',           TRUE);

INSERT INTO estado_pago (codigo, nombre) VALUES
 ('iniciado',  'Iniciado'),
 ('aprobado',  'Aprobado'),
 ('rechazado', 'Rechazado'),
 ('reembolsado','Reembolsado');

INSERT INTO tipo_movimiento (codigo, nombre, signo, afecta_costo) VALUES
 ('recepcion',        'Recepcion de mercaderia',   1,  TRUE),
 ('venta',            'Salida por venta',         -1,  FALSE),
 ('devolucion',       'Ingreso por devolucion',    1,  FALSE),
 ('transferencia_in', 'Ingreso por transferencia', 1,  TRUE),
 ('transferencia_out','Salida por transferencia', -1,  FALSE),
 ('ajuste_positivo',  'Ajuste por sobrante',       1,  FALSE),
 ('ajuste_negativo',  'Ajuste por faltante',      -1,  FALSE);

INSERT INTO metodo_pago (codigo, nombre, requiere_pasarela, disponible_caja, disponible_online) VALUES
 ('efectivo',      'Efectivo',              FALSE, TRUE,  FALSE),
 ('qr',            'Codigo QR',             FALSE, TRUE,  TRUE),
 ('tarjeta',       'Tarjeta debito/credito',FALSE, TRUE,  FALSE),
 ('transferencia', 'Transferencia bancaria',FALSE, TRUE,  FALSE),
 ('libelula',      'Pasarela Libelula',     TRUE,  FALSE, TRUE),
 ('paypal',        'PayPal',                TRUE,  FALSE, TRUE);

INSERT INTO talla (codigo, descripcion, orden) VALUES
 ('XS','Extra small',1),('S','Small',2),('M','Medium',3),
 ('L','Large',4),('XL','Extra large',5),('XXL','Doble extra large',6);

INSERT INTO material (nombre) VALUES
 ('Algodon'),('Hilo'),('Poliester'),('Lino'),('Mezclilla'),
 ('Lana'),('Seda'),('Cuero sintetico');

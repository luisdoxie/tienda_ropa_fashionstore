"""Límites de tiempo, tamaño y semilla del ML (E11, paso 9). Solo constantes: este módulo NO importa
numpy ni scikit-learn, así que puede importarse al arrancar la aplicación.

Con los datos sintéticos por defecto (104 semanas x 30 categorías = 3.120 filas de entrenamiento
de demanda; hasta 50.000 filas x 3 columnas de RFM) todo cabe en unos pocos MB de RAM y entrena en
segundos. Si hay más datos se recortan por recencia con un aviso.
"""

ML_MIN_SEMANAS = 26  # menos semanas con ventas -> resultado "datos_insuficientes", nunca un 500
ML_MAX_SEMANAS = 104
ML_MAX_CATEGORIAS = 30
ML_MIN_CATEGORIAS = 2  # con menos de 2 categorías con ventas no hay modelo de demanda
ML_MIN_CLIENTES = 30  # clientes con compras para segmentar
ML_MAX_CLIENTES = 50_000

ML_MAX_ARTEFACTO_BYTES = 8 * 1024 * 1024  # tope duro del modelo serializado (BYTEA en modelo_ml)
ML_VERSIONES_CON_ARTEFACTO = 3  # versiones que conservan el artefacto; las viejas quedan solo con métricas
ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG = 20  # si se supera, warning y el tiempo queda en `parametros`

ML_DIAS_VIGENCIA = 30  # un modelo con más días se sigue usando, pero se avisa que está desactualizado
ML_SEMANAS_NUEVAS_MAX = 4  # lo mismo si hay más de tantas semanas de ventas posteriores a sus datos
ML_PUNTOS_DISPERSION = 300  # muestra máxima (sin identificadores) del gráfico de dispersión de segmentos

ML_SEMILLA_POR_DEFECTO = 42
ML_N_JOBS = 1  # siempre: el contenedor de Railway es chico y evita hilos descontrolados
ML_MAX_MODELOS_EN_CACHE = 8  # modelos deserializados que el proceso conserva (empresa, tipo, versión)

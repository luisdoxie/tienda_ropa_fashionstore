"""Cálculo puro de Machine Learning (CU-24, E11): datos sintéticos, preprocesamiento, modelos,
evaluación y serialización.

Reglas de este subpaquete (una prueba las vigila):
- NO importa `app.comercial`, `app.catalogo` ni `app.plataforma`, no recibe `Session` y no toca
  SQL: recibe datos planos (listas, dataclasses, arreglos) y devuelve resultados planos. Así se
  prueba sin base de datos y no puede mezclar empresas. El acceso a datos vive en
  `politicas.py`, `repository.py` y `casos_uso/` del paquete `inteligencia`.
- Los imports de numpy, scipy y scikit-learn van DENTRO de las funciones, nunca a nivel de
  módulo: importar scikit-learn cuesta ~1,3 s y no debe alargar el arranque ni `/health`.
- Nada se guarda en disco: el artefacto de un modelo es un BYTEA en la tabla `modelo_ml`.
"""

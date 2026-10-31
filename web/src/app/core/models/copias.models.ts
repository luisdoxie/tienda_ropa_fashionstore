/**
 * Contrato real de `/api/v1/copias-seguridad` (E22). Refleja `plataforma/schemas.py` (bloque "Copias de seguridad").
 * La copia es un ZIP que se descarga UNA vez en la misma respuesta que la crea: el servidor solo guarda sus metadatos.
 */

export type EstadoCopia = 'en_proceso' | 'completada' | 'fallida';

/** Códigos estables de `motivo_fallo` (nunca el detalle técnico). */
export type MotivoFalloCopia =
  | 'copia_demasiado_grande'
  | 'copia_tiempo_agotado'
  | 'servidor_ocupado'
  | 'abandonada'
  | 'error_interno';

/** Una fila del historial. */
export interface Copia {
  id: number;
  estado: EstadoCopia | string;
  usuario_id: number;
  usuario_nombre: string | null;
  tamano_bytes: number | null;
  total_filas: number | null;
  /** Tabla -> cantidad de filas. */
  tablas_incluidas: Record<string, number> | null;
  version_esquema: string | null;
  /** SHA-256 del ZIP en hexadecimal: sirve para comprobar un archivo ya descargado. */
  checksum: string | null;
  /** Código estable (`MotivoFalloCopia`) cuando la copia falló. */
  motivo_fallo: MotivoFalloCopia | string | null;
  /** UTC, ISO y sin zona. */
  creado_en: string;
  terminado_en: string | null;
}

export interface CopiaPagina {
  total: number;
  pagina: number;
  tamanio: number;
  items: Copia[];
}

export interface TablaExcluida {
  tabla: string;
  motivo: string;
}

/** `GET /copias-seguridad/tablas`: qué incluye la copia y qué no. */
export interface CopiaTablas {
  incluidas: string[];
  referencias: string[];
  excluidas: TablaExcluida[];
  /** Tabla -> columnas que no salen en la copia (contraseñas, secretos...). */
  columnas_excluidas: Record<string, string[]>;
}

/** Lo que devuelve `POST /copias-seguridad`: el ZIP y lo que el servidor dice de él en las cabeceras. */
export interface CopiaDescargada {
  blob: Blob;
  nombre: string;
  /** `X-Copia-Id`; null si no vino. */
  copiaId: number | null;
  /** `X-Checksum-SHA256` (64 caracteres hexadecimales); null si no vino. */
  checksum: string | null;
}

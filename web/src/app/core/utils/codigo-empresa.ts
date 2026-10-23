/** Longitud máxima de `empresa.codigo` (`_LONGITUD_CODIGO_EMPRESA` en plataforma/politicas.py). */
export const LONGITUD_CODIGO_EMPRESA = 60;

/**
 * Vista previa del código de una empresa. Replica `normalizar_nombre_empresa`
 * del backend: sin tildes ni la tilde de la ñ (NFKD), en minúsculas, toda
 * secuencia que no sea a-z0-9 pasa a un solo guion, sin guiones en los
 * extremos y como máximo 60 caracteres.
 * 'Moda Ñandú & Hijos' -> 'moda-nandu-hijos'.
 *
 * Es solo orientativa: el código real lo genera y confirma el backend.
 */
export function codigoEmpresa(nombre: string | null | undefined): string {
  if (typeof nombre !== 'string') return '';
  const sinMarcas = nombre.normalize('NFKD').replace(/\p{M}/gu, '');
  const guionado = sinMarcas
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return guionado.slice(0, LONGITUD_CODIGO_EMPRESA).replace(/^-+|-+$/g, '');
}

import { LONGITUD_CODIGO_EMPRESA, codigoEmpresa } from './codigo-empresa';

describe('codigoEmpresa', () => {
  it('quita tildes y la tilde de la ñ, pasa a minúsculas y une con guiones', () => {
    expect(codigoEmpresa('Moda Ñandú & Hijos')).toBe('moda-nandu-hijos');
    expect(codigoEmpresa('Boutique Andina')).toBe('boutique-andina');
    expect(codigoEmpresa('CAFÉ Ñoño')).toBe('cafe-nono');
  });

  it('colapsa cualquier secuencia de símbolos o espacios en un solo guion', () => {
    expect(codigoEmpresa('A   &&&   B')).toBe('a-b');
    expect(codigoEmpresa('uno___dos...tres')).toBe('uno-dos-tres');
  });

  it('no deja guiones en los extremos', () => {
    expect(codigoEmpresa('  --Hola--  ')).toBe('hola');
    expect(codigoEmpresa('¡Oferta!')).toBe('oferta');
  });

  it('conserva los dígitos', () => {
    expect(codigoEmpresa('Tienda 24 Horas')).toBe('tienda-24-horas');
  });

  it('devuelve vacío si no queda ninguna letra ni número', () => {
    expect(codigoEmpresa('')).toBe('');
    expect(codigoEmpresa('   ')).toBe('');
    expect(codigoEmpresa('---&&&')).toBe('');
    expect(codigoEmpresa('日本')).toBe('');
    expect(codigoEmpresa(null)).toBe('');
    expect(codigoEmpresa(undefined)).toBe('');
  });

  it('corta en 60 caracteres y no termina en guion', () => {
    const largo = codigoEmpresa('a'.repeat(59) + ' ' + 'b'.repeat(20));
    expect(largo.length).toBeLessThanOrEqual(LONGITUD_CODIGO_EMPRESA);
    expect(largo.endsWith('-')).toBe(false);
    expect(codigoEmpresa('x'.repeat(100))).toHaveLength(LONGITUD_CODIGO_EMPRESA);
  });
});

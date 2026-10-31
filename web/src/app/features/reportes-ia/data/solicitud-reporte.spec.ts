import { SolicitudResuelta } from '../../../core/models/reportes-ia.models';
import { fechaParcialDesdeIso, periodoDeRango, solicitudDesdeResuelta } from './solicitud-reporte';

const base: SolicitudResuelta = {
  tipo_reporte: 'ventas_por_sucursal',
  periodo: { desde: '2026-09-01', hasta: '2026-09-30', etiqueta: 'septiembre de 2026' },
  sucursales: [],
  categorias: [],
  productos: [],
  canal: null,
  agrupacion: null,
  orden: null,
  limite: null,
  horizonte_semanas: null,
};

describe('solicitud-reporte', () => {
  it('fechaParcialDesdeIso separa día, mes y año', () => {
    expect(fechaParcialDesdeIso('2026-09-05')).toEqual({ dia: 5, mes: 9, anio: 2026 });
    expect(fechaParcialDesdeIso('2026-12-31T23:59:00Z')).toEqual({ dia: 31, mes: 12, anio: 2026 });
    expect(() => fechaParcialDesdeIso('ayer')).toThrow();
  });

  it('periodoDeRango arma un rango de fechas', () => {
    expect(periodoDeRango('2026-09-01', '2026-09-30')).toEqual({
      tipo: 'rango_fechas',
      desde: { dia: 1, mes: 9, anio: 2026 },
      hasta: { dia: 30, mes: 9, anio: 2026 },
    });
  });

  describe('solicitudDesdeResuelta', () => {
    it('convierte el periodo a rango y no manda filtros vacíos', () => {
      const s = solicitudDesdeResuelta(base);
      expect(s).toEqual({ tipo_reporte: 'ventas_por_sucursal', periodo: periodoDeRango('2026-09-01', '2026-09-30') });
    });

    it('manda nombres, nunca ids', () => {
      const s = solicitudDesdeResuelta({
        ...base,
        sucursales: [{ id: 3, nombre: 'Centro' }],
        categorias: [{ id: 7, nombre: 'Poleras' }],
        productos: [{ id: 9, nombre: 'Polera básica' }],
        canal: 'presencial',
        agrupacion: 'semana',
        orden: 'menor_a_mayor',
        limite: 5,
      });
      expect(s.sucursales).toEqual(['Centro']);
      expect(s.categorias).toEqual(['Poleras']);
      expect(s.productos).toEqual(['Polera básica']);
      expect(s).toMatchObject({ canal: 'presencial', agrupacion: 'semana', orden: 'menor_a_mayor', limite: 5 });
      expect(JSON.stringify(s)).not.toMatch(/"id"|empresa/);
    });

    it('un reporte sin periodo (existencias) no manda periodo; el horizonte se conserva', () => {
      const s = solicitudDesdeResuelta({ ...base, tipo_reporte: 'reposicion_sugerida', periodo: null, horizonte_semanas: 8 });
      expect(s.periodo).toBeUndefined();
      expect(s.horizonte_semanas).toBe(8);
    });
  });
});

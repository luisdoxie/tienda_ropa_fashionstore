import { FiltroCatalogo, ReporteCatalogo, SolicitudResuelta } from '../../core/models/reportes-ia.models';
import {
  EJEMPLOS_RESPALDO,
  MAX_ATAJOS,
  camposDeCatalogo,
  chipsDeSolicitud,
  ejemplosDelCatalogo,
  errorDeFormulario,
  etiquetaDeValor,
  fechaHoraLocal,
  formularioDesdeResuelta,
  solicitudDesdeFormulario,
  textoFiltrosAplicados,
} from './reportes-ia.util';

function filtro(tipo: FiltroCatalogo['tipo'], extra: Partial<FiltroCatalogo> = {}): FiltroCatalogo {
  return { tipo, descripcion: '', obligatorio: false, defecto: null, minimo: null, maximo: null, valores: [], ...extra };
}

const FILTROS: Record<string, FiltroCatalogo> = {
  periodo: filtro('periodo', { obligatorio: true }),
  sucursales: filtro('lista_nombres'),
  categorias: filtro('lista_nombres'),
  canal: filtro('enum', { valores: ['digital', 'presencial'] }),
  limite: filtro('entero', { minimo: 1, maximo: 50 }),
};

function resuelta(extra: Partial<SolicitudResuelta> = {}): SolicitudResuelta {
  return {
    tipo_reporte: 'ventas_por_sucursal',
    periodo: { desde: '2026-09-01', hasta: '2026-09-30', etiqueta: 'septiembre de 2026' },
    sucursales: [{ id: 3, nombre: 'Sucursal Centro' }],
    categorias: [],
    productos: [],
    canal: null,
    agrupacion: null,
    orden: null,
    limite: null,
    horizonte_semanas: null,
    ...extra,
  };
}

function reporteCatalogo(codigo: string, ejemplos: string[]): ReporteCatalogo {
  return {
    codigo,
    titulo: codigo,
    descripcion: '',
    ejemplos,
    filtros: {},
    columnas: [],
    grafico: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null },
  };
}

describe('ejemplosDelCatalogo', () => {
  it('toma el primer ejemplo de cada reporte, en el orden del servidor, hasta 6', () => {
    const catalogo = Array.from({ length: 9 }, (_, i) => reporteCatalogo(`r${i}`, [`ejemplo ${i}a`, `ejemplo ${i}b`]));
    const atajos = ejemplosDelCatalogo(catalogo);
    expect(atajos).toHaveLength(MAX_ATAJOS);
    expect(atajos[0]).toBe('ejemplo 0a');
    expect(atajos[5]).toBe('ejemplo 5a');
  });

  it('salta los reportes sin ejemplos y los repetidos', () => {
    const atajos = ejemplosDelCatalogo([
      reporteCatalogo('a', []),
      reporteCatalogo('b', ['uno']),
      reporteCatalogo('c', ['uno']),
      reporteCatalogo('d', ['dos']),
    ]);
    expect(atajos).toEqual(['uno', 'dos']);
  });

  it('sin catálogo usa los 6 de respaldo', () => {
    expect(ejemplosDelCatalogo([])).toEqual([...EJEMPLOS_RESPALDO]);
    expect(EJEMPLOS_RESPALDO).toHaveLength(6);
  });
});

describe('fechaHoraLocal', () => {
  it('muestra el instante UTC en la hora local del navegador', () => {
    const local = new Date(2026, 9, 30, 9, 5);
    expect(fechaHoraLocal(local.toISOString())).toBe('30/10/2026 09:05');
  });

  it('un valor ilegible se devuelve tal cual', () => {
    expect(fechaHoraLocal('no es fecha')).toBe('no es fecha');
  });
});

describe('chipsDeSolicitud y textoFiltrosAplicados', () => {
  it('solo muestra los filtros que traen valor', () => {
    const chips = chipsDeSolicitud(resuelta({ canal: 'digital', limite: 10, agrupacion: 'semana', horizonte_semanas: 1 }));
    expect(chips.map((c) => c.clave)).toEqual(['periodo', 'sucursales', 'canal', 'agrupacion', 'limite', 'horizonte_semanas']);
    expect(chips[0].texto).toBe('Periodo: septiembre de 2026 (01/09/2026 al 30/09/2026)');
    expect(chips[1].texto).toBe('Sucursales: Sucursal Centro');
    expect(chips[2].texto).toBe('Canal: Digital');
    expect(chips[3].texto).toBe('Agrupación: Por semana');
    expect(chips[5].texto).toBe('Horizonte: 1 semana');
  });

  it('el texto de filtros aplicados los une, y sin ninguno lo dice', () => {
    expect(textoFiltrosAplicados(resuelta())).toBe('Periodo: septiembre de 2026 (01/09/2026 al 30/09/2026) · Sucursales: Sucursal Centro');
    expect(textoFiltrosAplicados(resuelta({ periodo: null, sucursales: [] }))).toBe('Sin filtros adicionales');
    expect(textoFiltrosAplicados(null)).toBe('Sin filtros');
  });

  it('un valor nuevo del servidor se muestra tal cual', () => {
    expect(etiquetaDeValor('canal', 'mayorista')).toBe('mayorista');
    expect(etiquetaDeValor('orden', 'mayor_a_menor')).toBe('De mayor a menor');
  });
});

describe('formulario de filtros', () => {
  it('camposDeCatalogo respeta un orden estable e ignora claves que la solicitud no conoce', () => {
    const campos = camposDeCatalogo({ limite: filtro('entero'), color_favorito: filtro('enum'), periodo: filtro('periodo') });
    expect(campos.map((c) => c.clave)).toEqual(['periodo', 'limite']);
  });

  it('formularioDesdeResuelta toma el periodo, los nombres y los valores del "entendí esto"', () => {
    const f = formularioDesdeResuelta(resuelta({ limite: 5 }));
    expect(f.desde).toEqual(new Date(2026, 8, 1));
    expect(f.hasta).toEqual(new Date(2026, 8, 30));
    expect(f.sucursales).toEqual(['Sucursal Centro']);
    expect(f.limite).toBe(5);
    expect(f.canal).toBeNull();
  });

  it('solicitudDesdeFormulario manda NOMBRES y un rango de fechas, sin ids', () => {
    const f = formularioDesdeResuelta(resuelta({ canal: 'digital', limite: 5 }));
    const s = solicitudDesdeFormulario('ventas_por_sucursal', f, FILTROS);
    expect(s).toEqual({
      tipo_reporte: 'ventas_por_sucursal',
      periodo: { tipo: 'rango_fechas', desde: { dia: 1, mes: 9, anio: 2026 }, hasta: { dia: 30, mes: 9, anio: 2026 } },
      sucursales: ['Sucursal Centro'],
      canal: 'digital',
      limite: 5,
    });
    expect(JSON.stringify(s)).not.toContain('"id"');
  });

  it('solo manda los filtros que el catálogo declara', () => {
    const f = formularioDesdeResuelta(resuelta({ canal: 'digital', limite: 5 }));
    const s = solicitudDesdeFormulario('ventas_por_sucursal', f, { periodo: filtro('periodo') });
    expect(Object.keys(s).sort()).toEqual(['periodo', 'tipo_reporte']);
  });

  it('un filtro vaciado ya no se manda', () => {
    const f = { ...formularioDesdeResuelta(resuelta()), sucursales: [], desde: null, hasta: null };
    const s = solicitudDesdeFormulario('ventas_por_sucursal', f, { ...FILTROS, periodo: filtro('periodo') });
    expect(s).toEqual({ tipo_reporte: 'ventas_por_sucursal' });
  });

  it('errorDeFormulario valida fechas y rangos numéricos con textos en tuteo', () => {
    const base = formularioDesdeResuelta(resuelta());
    expect(errorDeFormulario(base, FILTROS)).toBeNull();
    expect(errorDeFormulario({ ...base, hasta: null }, FILTROS)).toBe('Elige las dos fechas del periodo: Desde y Hasta.');
    expect(errorDeFormulario({ ...base, desde: null, hasta: null }, FILTROS)).toBe('Elige el periodo del reporte.');
    expect(errorDeFormulario({ ...base, desde: new Date(2026, 9, 1) }, FILTROS)).toBe('La fecha Desde no puede ser posterior a Hasta.');
    expect(errorDeFormulario({ ...base, limite: 80 }, FILTROS)).toBe('Límite de filas: el máximo es 50.');
    expect(errorDeFormulario({ ...base, limite: 0 }, FILTROS)).toBe('Límite de filas: el mínimo es 1.');
  });
});

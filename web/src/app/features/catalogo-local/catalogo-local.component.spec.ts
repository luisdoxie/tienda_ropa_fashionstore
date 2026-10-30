import 'fake-indexeddb/auto';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import { BaseOffline } from '../../core/offline/db-offline';
import type { PaqueteLocal } from '../../core/offline/offline.models';
import {
  ErrorDescargaOffline,
  EstadoDatosOffline,
  PaqueteOfflineService,
} from '../../core/offline/paquete-offline.service';
import { RepositorioLocal } from '../../core/offline/repositorio-local';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
import { CatalogoLocalComponent, textoHace } from './catalogo-local.component';

let contador = 0;
const HORA = 3_600_000;

/** dd/mm/aaaa HH:mm en la hora local, igual que la pantalla. */
function fechaLocal(iso: string): string {
  const d = new Date(iso);
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}
const horaLocal = (iso: string) => fechaLocal(iso).slice(-5);
const haceHoras = (horas: number) => new Date(Date.now() - horas * HORA).toISOString();

/** Un paquete pequeño pero completo. `marca` distingue a una empresa de otra. */
function paquete(marca: string, extra: Partial<PaqueteLocal> = {}): PaqueteLocal {
  const generadoEn = '2026-10-30T10:00:00Z';
  return {
    empresa: { id: 1, codigo: marca.toLowerCase(), nombre: marca },
    generadoEn,
    avisoDesactualizadoHoras: 12,
    sucursales: [
      { id: 10, codigo: 'SC-CENTRO', nombre: 'Sucursal Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] },
      { id: 11, codigo: 'SC-DEPOSITO', nombre: 'Depósito Norte', direccion: 'Calle 2', es_deposito: true, horarios: [] },
    ],
    categorias: [
      { id: 1, nombre: 'Poleras', categoria_padre_id: null },
      { id: 2, nombre: 'Chamarras', categoria_padre_id: null },
    ],
    tallas: [
      { id: 1, codigo: 'M', orden: 2 },
      { id: 2, codigo: 'L', orden: 3 },
    ],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
    productos: [
      {
        id: 100,
        codigo: 'FS-10005',
        nombre: `Polera ${marca} Estampada`,
        categoria_id: 1,
        genero: 'hombre',
        temporada_id: null,
        imagen_principal: null,
        variantes: [
          { id: 1000, talla_id: 1, color_id: 1, sku: `${marca}-POL-M`, codigo_barras: '7770001', precio: '149.00', descuento_unitario: '0.00' },
          { id: 1001, talla_id: 2, color_id: 1, sku: `${marca}-POL-L`, codigo_barras: null, precio: '149.00', descuento_unitario: '0.00' },
        ],
      },
      {
        id: 101,
        codigo: 'FS-20001',
        nombre: `Chamarra ${marca}`,
        categoria_id: 2,
        genero: 'unisex',
        temporada_id: null,
        imagen_principal: null,
        variantes: [{ id: 1100, talla_id: 1, color_id: 1, sku: `${marca}-CHA-M`, codigo_barras: '7770002', precio: '1234.50', descuento_unitario: '0.00' }],
      },
    ],
    stock: [
      {
        sucursalId: 10,
        generadoEn,
        items: [
          { variante_id: 1000, cantidad_disponible: 5, actualizado_en: generadoEn },
          { variante_id: 1001, cantidad_disponible: 0, actualizado_en: generadoEn },
        ],
      },
      { sucursalId: 11, generadoEn, items: [{ variante_id: 1000, cantidad_disponible: 30, actualizado_en: generadoEn }] },
    ],
    clientes: [],
    reglas: {
      metodos_pago_offline: ['efectivo'],
      max_operaciones_por_lote: 50,
      plazo_cambio_horas: 24,
      cambios_y_devoluciones: 'solo_en_linea',
      reservas_offline: 'permitidas',
    },
    ...extra,
  };
}

describe('CatalogoLocalComponent', () => {
  let db: BaseOffline;
  let fallaLaLectura: boolean;
  let liberarEstado: (() => void) | null;
  let esperarEstado: boolean;

  // El doble de la descarga (otro agente lo implementa): solo lo que la pantalla usa.
  const ultimaDescarga = signal<string | null>(null);
  const estadoDatos = signal<EstadoDatosOffline>('sin_datos');
  const descargando = signal(false);
  const errorDescarga = signal<ErrorDescargaOffline | null>(null);
  const descargar = vi.fn<() => Promise<boolean>>();
  const cargarEstado = vi.fn<() => Promise<void>>();
  const conexion = signal<EstadoConexion>('en_linea');

  const repoDe = (empresaId: number) => new RepositorioLocal(db, { empresaId, usuarioId: 7 });

  beforeEach(async () => {
    db = new BaseOffline(`prueba_pantalla_catalogo_local_${++contador}_${Date.now()}`);
    fallaLaLectura = false;
    esperarEstado = false;
    liberarEstado = null;
    ultimaDescarga.set(null);
    estadoDatos.set('sin_datos');
    descargando.set(false);
    errorDescarga.set(null);
    conexion.set('en_linea');
    descargar.mockReset();
    descargar.mockResolvedValue(true);
    cargarEstado.mockReset();
    cargarEstado.mockImplementation(() => (esperarEstado ? new Promise<void>((r) => (liberarEstado = r)) : Promise.resolve()));

    TestBed.configureTestingModule({
      imports: [CatalogoLocalComponent],
      providers: [
        {
          provide: PaqueteOfflineService,
          useValue: { ultimaDescarga, estadoDatos, descargando, errorDescarga, descargar, cargarEstado },
        },
        { provide: ConectividadService, useValue: { estado: conexion } },
        {
          provide: SesionOfflineService,
          useValue: {
            repositorio: () => {
              if (fallaLaLectura) throw new Error('La base no se pudo abrir');
              return repoDe(1);
            },
          },
        },
      ],
    });
  });

  afterEach(() => db.close());

  /** Datos descargados hace `horas`, con el catálogo de la empresa 1 (y otro de la empresa 2 que NO debe verse). */
  async function conDatos(horas: number, estado: EstadoDatosOffline = 'vigentes'): Promise<string> {
    await repoDe(1).reemplazarReferencia(paquete('Alfa'));
    await repoDe(2).reemplazarReferencia(paquete('Beta'));
    const iso = haceHoras(horas);
    ultimaDescarga.set(iso);
    estadoDatos.set(estado);
    return iso;
  }

  async function abrir(): Promise<{ fixture: ComponentFixture<CatalogoLocalComponent>; el: HTMLElement }> {
    const fixture = TestBed.createComponent(CatalogoLocalComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(el.querySelector('[data-estado="cargando"]')).toBeNull();
    });
    return { fixture, el };
  }

  const filas = (el: HTMLElement) => Array.from(el.querySelectorAll('tbody tr'));
  const textoDe = (nodo: Element | null | undefined) => (nodo?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const botonPorTexto = (el: HTMLElement, texto: string) =>
    Array.from(el.querySelectorAll('button')).find((b) => (b.textContent ?? '').includes(texto)) as HTMLButtonElement | undefined;

  describe('con datos descargados', () => {
    it('muestra la franja con la fecha y el "hace N h", y NO la de desactualizado', async () => {
      const iso = await conDatos(3);
      const { el } = await abrir();

      const franja = el.querySelector('.franja') as HTMLElement;
      expect(franja.getAttribute('data-estado')).toBe('vigentes');
      expect(textoDe(franja)).toContain(`Datos descargados el ${fechaLocal(iso)} (hace 3 h)`);
      expect(textoDe(franja)).not.toContain('Información desactualizada');
      expect(franja.classList).toContain('franja--vigente');
      expect(cargarEstado).toHaveBeenCalledTimes(1);
    });

    it('lista los productos de la empresa con categoría, precio, tallas y colores con stock y stock por sucursal', async () => {
      const iso = await conDatos(1);
      const { el } = await abrir();

      const f = filas(el);
      expect(f.length).toBe(2);
      // Orden por nombre: Chamarra antes que Polera.
      const chamarra = Array.from(f[0].querySelectorAll('td'));
      expect(textoDe(chamarra[0])).toContain('Chamarra Alfa');
      expect(textoDe(chamarra[0])).toContain('FS-20001');
      expect(textoDe(chamarra[1])).toBe('Chamarras');
      expect(textoDe(chamarra[2])).toBe('Bs 1.234,50');
      // Sin stock conocido: no hay tallas ni colores disponibles y la sucursal sale con raya.
      expect(textoDe(chamarra[3])).toBe('Sin stock');
      expect(textoDe(chamarra[4])).toBe('Sin stock');
      expect(Array.from(chamarra[5].querySelectorAll('.stock-linea')).map((l) => textoDe(l))).toEqual([
        'Sucursal Centro —',
        'Depósito Norte —',
      ]);

      const polera = Array.from(f[1].querySelectorAll('td'));
      expect(textoDe(polera[0])).toContain('Polera Alfa Estampada');
      expect(textoDe(polera[1])).toBe('Poleras');
      expect(textoDe(polera[2])).toBe('Bs 149,00');
      // La talla L tiene 0 unidades: solo la M está disponible.
      expect(Array.from(polera[3].querySelectorAll('p-tag')).map((t) => textoDe(t))).toEqual(['M']);
      expect(Array.from(polera[4].querySelectorAll('p-tag')).map((t) => textoDe(t))).toEqual(['Negro']);
      expect(Array.from(polera[5].querySelectorAll('.stock-linea')).map((l) => textoDe(l))).toEqual([
        'Sucursal Centro 5',
        'Depósito Norte 30',
      ]);

      expect(textoDe(el.querySelector('.conteo'))).toBe('2 productos');
      // La nota del stock lleva la hora de la descarga.
      expect(textoDe(el.querySelector('.nota-stock'))).toBe(`Conocido a las ${horaLocal(iso)}, no garantizado`);
    });

    it('no muestra nada de otra empresa', async () => {
      await conDatos(1);
      const { el } = await abrir();

      expect(el.textContent).not.toContain('Beta');
    });

    it('con varios precios en un producto muestra "Desde" el menor', async () => {
      await repoDe(1).reemplazarReferencia(
        paquete('Alfa', {
          productos: [
            {
              id: 100,
              codigo: 'FS-1',
              nombre: 'Polera Doble Precio',
              categoria_id: 1,
              genero: 'hombre',
              temporada_id: null,
              imagen_principal: null,
              variantes: [
                { id: 1, talla_id: 1, color_id: 1, sku: 'A-1', codigo_barras: null, precio: '120.00', descuento_unitario: '0.00' },
                { id: 2, talla_id: 2, color_id: 1, sku: 'A-2', codigo_barras: null, precio: '99.90', descuento_unitario: '0.00' },
              ],
            },
          ],
          stock: [],
        }),
      );
      ultimaDescarga.set(haceHoras(1));
      estadoDatos.set('vigentes');
      const { el } = await abrir();

      expect(textoDe(filas(el)[0].querySelectorAll('td')[2])).toBe('Desde Bs 99,90');
      // Sin stock descargado en ninguna sucursal, la columna lo dice.
      expect(textoDe(filas(el)[0].querySelectorAll('td')[5])).toBe('Sin dato de stock');
    });
  });

  describe('datos desactualizados', () => {
    it('la franja es de advertencia con el aviso y el botón [Actualizar datos] a la vista', async () => {
      const iso = await conDatos(30, 'desactualizados');
      const { el } = await abrir();

      const franja = el.querySelector('.franja') as HTMLElement;
      expect(franja.getAttribute('data-estado')).toBe('desactualizados');
      expect(franja.classList).not.toContain('franja--vigente');
      expect(textoDe(franja)).toContain('Información desactualizada: conéctate para actualizar');
      expect(textoDe(franja)).toContain(`Datos descargados el ${fechaLocal(iso)} (hace 30 h)`);
      const boton = botonPorTexto(el, 'Actualizar datos')!;
      expect(boton).toBeDefined();
      expect(boton.disabled).toBe(false);
    });

    it('[Actualizar datos] descarga y la lista se vuelve a leer con lo nuevo', async () => {
      await conDatos(30, 'desactualizados');
      const nuevoIso = haceHoras(0);
      descargar.mockImplementation(async () => {
        await repoDe(1).reemplazarReferencia(
          paquete('Alfa', {
            productos: [
              {
                id: 500,
                codigo: 'FS-NUEVO',
                nombre: 'Sombrero Recién Llegado',
                categoria_id: 1,
                genero: 'unisex',
                temporada_id: null,
                imagen_principal: null,
                variantes: [{ id: 5000, talla_id: 1, color_id: 1, sku: 'SOM-M', codigo_barras: null, precio: '50.00', descuento_unitario: '0.00' }],
              },
            ],
            stock: [],
          }),
        );
        ultimaDescarga.set(nuevoIso);
        estadoDatos.set('vigentes');
        return true;
      });
      const { fixture, el } = await abrir();
      expect(el.textContent).not.toContain('Sombrero Recién Llegado');

      botonPorTexto(el, 'Actualizar datos')!.click();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(el.textContent).toContain('Sombrero Recién Llegado');
      });

      expect(descargar).toHaveBeenCalledTimes(1);
      expect(el.querySelector('.franja')?.getAttribute('data-estado')).toBe('vigentes');
      expect(el.textContent).not.toContain('Polera Alfa');
      expect(textoDe(el.querySelector('.franja'))).toContain(`Datos descargados el ${fechaLocal(nuevoIso)}`);
    });

    it('sin conexión el aviso sigue y el botón queda a la vista pero deshabilitado', async () => {
      await conDatos(30, 'desactualizados');
      conexion.set('sin_conexion');
      const { el } = await abrir();

      expect(textoDe(el.querySelector('.franja'))).toContain('Información desactualizada: conéctate para actualizar');
      const boton = botonPorTexto(el, 'Actualizar datos')!;
      expect(boton.disabled).toBe(true);
      expect(boton.getAttribute('title')).toBe('Conéctate a Internet para actualizar');
      boton.click();
      expect(descargar).not.toHaveBeenCalled();
      // Y la lista de lo ya descargado se puede seguir usando.
      expect(filas(el).length).toBe(2);
    });

    it('mientras descarga el botón dice "Actualizando…" y no permite otro clic', async () => {
      await conDatos(30, 'desactualizados');
      descargando.set(true);
      const { el } = await abrir();

      const boton = botonPorTexto(el, 'Actualizando')!;
      expect(boton.disabled).toBe(true);
    });
  });

  describe('sin datos descargados', () => {
    it('con conexión explica y ofrece [Descargar datos], que descarga', async () => {
      const { fixture, el } = await abrir();

      expect(el.querySelector('[data-estado="sin-datos"]')).not.toBeNull();
      expect(textoDe(el)).toContain('Todavía no hay datos descargados en este equipo.');
      expect(el.querySelector('.franja')).toBeNull();
      expect(el.querySelector('table')).toBeNull();

      botonPorTexto(el, 'Descargar datos')!.click();
      fixture.detectChanges();
      expect(descargar).toHaveBeenCalledTimes(1);
    });

    it('sin conexión no hay botón y pide conectarse', async () => {
      conexion.set('sin_conexion');
      const { el } = await abrir();

      expect(botonPorTexto(el, 'Descargar datos')).toBeUndefined();
      expect(textoDe(el)).toContain('Conéctate a Internet para descargarlos.');
    });
  });

  describe('búsqueda y filtro de categoría', () => {
    it('buscar por nombre sin tildes filtra la lista; un texto sin coincidencias muestra "sin resultados"', async () => {
      await conDatos(1);
      const { fixture, el } = await abrir();
      const entrada = el.querySelector('.buscador input') as HTMLInputElement;

      entrada.value = 'POLERA';
      entrada.dispatchEvent(new Event('input'));
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(filas(el).length).toBe(1);
      });
      expect(textoDe(filas(el)[0])).toContain('Polera Alfa Estampada');
      expect(textoDe(el.querySelector('.conteo'))).toBe('1 producto');

      entrada.value = 'sombrero';
      entrada.dispatchEvent(new Event('input'));
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(el.querySelector('[data-estado="sin-resultados"]')).not.toBeNull();
      });
      expect(textoDe(el.querySelector('[data-estado="sin-resultados"]'))).toContain('No encontramos productos con esos datos');
    });

    it('buscar por SKU y por código de barras', async () => {
      await conDatos(1);
      const { fixture, el } = await abrir();
      const entrada = el.querySelector('.buscador input') as HTMLInputElement;

      for (const [texto, producto] of [
        ['alfa-cha-m', 'Chamarra Alfa'],
        ['7770001', 'Polera Alfa Estampada'],
      ]) {
        entrada.value = texto;
        entrada.dispatchEvent(new Event('input'));
        await vi.waitFor(() => {
          fixture.detectChanges();
          expect(filas(el).length).toBe(1);
          expect(textoDe(filas(el)[0])).toContain(producto);
        });
      }
    });

    it('el filtro de categoría deja solo los productos de esa categoría y se puede quitar', async () => {
      await conDatos(1);
      const { fixture, el } = await abrir();
      const pantalla = fixture.componentInstance as unknown as { cambiarCategoria(id: number | null): void };

      pantalla.cambiarCategoria(2);
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(filas(el).length).toBe(1);
      });
      expect(textoDe(filas(el)[0])).toContain('Chamarra Alfa');

      pantalla.cambiarCategoria(null);
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(filas(el).length).toBe(2);
      });
    });

    it('no tiene un select de categorías vacío: lista las categorías de la empresa ordenadas', async () => {
      await conDatos(1);
      const { fixture } = await abrir();
      const pantalla = fixture.componentInstance as unknown as { categoriasOrdenadas(): { nombre: string }[] };

      expect(pantalla.categoriasOrdenadas().map((c) => c.nombre)).toEqual(['Chamarras', 'Poleras']);
    });
  });

  describe('errores', () => {
    const casos: [ErrorDescargaOffline, string][] = [
      ['sin_conexion', 'No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'],
      ['plan_sin_offline', 'Tu plan no incluye la operación sin conexión.'],
      ['suscripcion', 'La suscripción de tu empresa no está activa'],
      ['error', 'No pudimos descargar los datos. Inténtalo de nuevo en unos minutos.'],
    ];

    for (const [tipo, mensaje] of casos) {
      it(`un error de descarga "${tipo}" muestra un mensaje claro y propio`, async () => {
        errorDescarga.set(tipo);
        const { el } = await abrir();

        const aviso = el.querySelector('[data-estado="error-descarga"]');
        expect(aviso?.getAttribute('role')).toBe('alert');
        expect(textoDe(aviso)).toContain(mensaje);
      });
    }

    it('con plan o suscripción que no permiten descargar no ofrece el botón de descarga', async () => {
      for (const tipo of ['plan_sin_offline', 'suscripcion'] as const) {
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
          imports: [CatalogoLocalComponent],
          providers: [
            {
              provide: PaqueteOfflineService,
              useValue: { ultimaDescarga, estadoDatos, descargando, errorDescarga, descargar, cargarEstado },
            },
            { provide: ConectividadService, useValue: { estado: conexion } },
            { provide: SesionOfflineService, useValue: { repositorio: () => repoDe(1) } },
          ],
        });
        errorDescarga.set(tipo);
        const { el } = await abrir();

        expect(botonPorTexto(el, 'Descargar datos')).toBeUndefined();
        expect(textoDe(el)).toContain('No podemos descargarlos por ahora');
      }
    });

    it('un error de descarga con datos viejos mantiene la lista a la vista', async () => {
      await conDatos(30, 'desactualizados');
      errorDescarga.set('sin_conexion');
      const { el } = await abrir();

      expect(el.querySelector('[data-estado="error-descarga"]')).not.toBeNull();
      expect(filas(el).length).toBe(2);
    });

    it('si la base de este equipo no se puede leer lo dice y [Reintentar] vuelve a leer', async () => {
      await conDatos(1);
      fallaLaLectura = true;
      const { fixture, el } = await abrir();

      expect(el.querySelector('[data-estado="error-lectura"]')).not.toBeNull();
      expect(textoDe(el)).toContain('No pudimos leer los datos guardados en este equipo.');
      expect(el.querySelector('table')).toBeNull();

      fallaLaLectura = false;
      botonPorTexto(el, 'Reintentar')!.click();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(filas(el).length).toBe(2);
      });
      expect(el.querySelector('[data-estado="error-lectura"]')).toBeNull();
    });
  });

  describe('estado cargando', () => {
    it('mientras se lee el estado de la descarga muestra "Cargando" (sin tabla ni "sin datos") y luego la lista', async () => {
      await conDatos(1);
      esperarEstado = true;
      const fixture = TestBed.createComponent(CatalogoLocalComponent);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;

      expect(el.querySelector('[data-estado="cargando"]')).not.toBeNull();
      expect(el.querySelector('[data-estado="sin-datos"]')).toBeNull();
      expect(el.querySelector('table')).toBeNull();

      liberarEstado!();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(filas(el).length).toBe(2);
      });
      expect(el.querySelector('[data-estado="cargando"]')).toBeNull();
    });
  });
});

describe('textoHace', () => {
  it('describe el tiempo en segundos, minutos, horas y días', () => {
    expect(textoHace(5_000)).toBe('hace unos segundos');
    expect(textoHace(-1_000)).toBe('hace unos segundos');
    expect(textoHace(12 * 60_000)).toBe('hace 12 min');
    expect(textoHace(59 * 60_000)).toBe('hace 59 min');
    expect(textoHace(60 * 60_000)).toBe('hace 1 h');
    expect(textoHace(3 * HORA + 59 * 60_000)).toBe('hace 3 h');
    expect(textoHace(47 * HORA)).toBe('hace 47 h');
    expect(textoHace(72 * HORA)).toBe('hace 3 días');
    expect(textoHace(Number.NaN)).toBe('hace unos segundos');
  });
});

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MarcaDemo, PlanEscena, TiendaEscena } from './contrato';
import { CARGAR_ESCENA, EscenaTiendaComponent, type CargadorEscena } from './escena-tienda.component';
import type { OpcionesEscena } from './escena-tienda';

const doble = vi.hoisted(() => ({
  fallarImport: false,
  fallarCrear: false,
  opciones: undefined as unknown,
  escena: undefined as unknown,
}));

/** Sustituye la carga del motor: la escena de mentira solo anota lo que le piden. */
const cargadorFalso: CargadorEscena = async () => {
  if (doble.fallarImport) throw new Error('no se pudo cargar el fragmento');
  return {
    EscenaTienda: {
      crear: (opciones: unknown) => {
        if (doble.fallarCrear) throw new Error('sin WebGL');
        doble.opciones = opciones;
        doble.escena = {
          fijarDatos: vi.fn(),
          fijarMarca: vi.fn(),
          redimensionar: vi.fn(),
          destruir: vi.fn(),
        };
        return doble.escena;
      },
    },
  } as unknown as Awaited<ReturnType<CargadorEscena>>;
};

interface EscenaFalsa {
  fijarDatos: ReturnType<typeof vi.fn>;
  fijarMarca: ReturnType<typeof vi.fn>;
  redimensionar: ReturnType<typeof vi.fn>;
  destruir: ReturnType<typeof vi.fn>;
}

const PLANES: PlanEscena[] = [{ codigo: 'basico', nombre: 'Básico', sucursales: 2 }];
const TIENDAS: TiendaEscena[] = [{ codigo: 'fashionstore', nombre: 'FashionStore', acento: '#8fae5b' }];
const MARCA: MarcaDemo = { nombre: 'Chaski', tela: '#9a3e1f', acento: '#e27b55' };

describe('EscenaTiendaComponent', () => {
  let fixture: ComponentFixture<EscenaTiendaComponent>;
  let errores: ReturnType<typeof vi.spyOn>;

  const escena = () => doble.escena as EscenaFalsa;
  const opciones = () => doble.opciones as OpcionesEscena;

  function montar(): void {
    fixture = TestBed.createComponent(EscenaTiendaComponent);
    fixture.componentRef.setInput('planes', PLANES);
    fixture.componentRef.setInput('tiendas', TIENDAS);
    fixture.componentRef.setInput('marca', MARCA);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [{ provide: CARGAR_ESCENA, useValue: cargadorFalso }] });
    doble.fallarImport = false;
    doble.fallarCrear = false;
    doble.opciones = undefined;
    doble.escena = undefined;
    errores = vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => errores.mockRestore());

  it('muestra un lienzo oculto a los lectores de pantalla', () => {
    montar();
    const lienzo = (fixture.nativeElement as HTMLElement).querySelector('canvas')!;
    expect(lienzo).not.toBeNull();
    expect(lienzo.getAttribute('aria-hidden')).toBe('true');
  });

  it('crea la escena tras renderizar con el lienzo y le empuja los datos y la marca', async () => {
    montar();
    await vi.waitFor(() => expect(doble.escena).toBeDefined());
    expect(opciones().canvas).toBe((fixture.nativeElement as HTMLElement).querySelector('canvas'));
    expect(opciones().reducirMovimiento).toBe(false);
    expect(escena().fijarDatos).toHaveBeenCalledWith({ planes: PLANES, tiendas: TIENDAS });
    expect(escena().fijarMarca).toHaveBeenCalledWith(MARCA);
  });

  it('empuja de nuevo cuando cambian los datos o la marca', async () => {
    montar();
    await vi.waitFor(() => expect(doble.escena).toBeDefined());
    const otras: TiendaEscena[] = [...TIENDAS, { codigo: 'casa-lino', nombre: 'Casa Lino', acento: null }];
    const otraMarca: MarcaDemo = { nombre: 'Otra', tela: '#1f5f73', acento: '#58b0cc' };
    fixture.componentRef.setInput('tiendas', otras);
    fixture.componentRef.setInput('marca', otraMarca);
    fixture.detectChanges();
    expect(escena().fijarDatos).toHaveBeenLastCalledWith({ planes: PLANES, tiendas: otras });
    expect(escena().fijarMarca).toHaveBeenLastCalledWith(otraMarca);
  });

  it('emite tiendaElegida cuando la escena avisa que se eligió un local', async () => {
    montar();
    await vi.waitFor(() => expect(doble.escena).toBeDefined());
    const elegidas: string[] = [];
    fixture.componentInstance.tiendaElegida.subscribe((codigo) => elegidas.push(codigo));
    opciones().alElegirTienda('casa-lino');
    expect(elegidas).toEqual(['casa-lino']);
  });

  it('emite sinEscena (y registra el error) si el fragmento no carga', async () => {
    doble.fallarImport = true;
    const avisos: number[] = [];
    fixture = TestBed.createComponent(EscenaTiendaComponent);
    fixture.componentInstance.sinEscena.subscribe(() => avisos.push(1));
    fixture.componentRef.setInput('planes', PLANES);
    fixture.componentRef.setInput('tiendas', TIENDAS);
    fixture.componentRef.setInput('marca', MARCA);
    fixture.detectChanges();
    await vi.waitFor(() => expect(avisos).toEqual([1]));
    expect(errores).toHaveBeenCalled();
    expect(doble.escena).toBeUndefined();
  });

  it('emite sinEscena si la creación de la escena falla', async () => {
    doble.fallarCrear = true;
    const avisos: number[] = [];
    fixture = TestBed.createComponent(EscenaTiendaComponent);
    fixture.componentInstance.sinEscena.subscribe(() => avisos.push(1));
    fixture.componentRef.setInput('planes', PLANES);
    fixture.componentRef.setInput('tiendas', TIENDAS);
    fixture.componentRef.setInput('marca', MARCA);
    fixture.detectChanges();
    await vi.waitFor(() => expect(avisos).toEqual([1]));
    expect(errores).toHaveBeenCalled();
  });

  it('destruye la escena al destruirse el componente', async () => {
    montar();
    await vi.waitFor(() => expect(doble.escena).toBeDefined());
    const actual = escena();
    fixture.destroy();
    expect(actual.destruir).toHaveBeenCalledTimes(1);
  });

  it('si se destruye antes de que cargue el fragmento, no crea la escena', async () => {
    montar();
    fixture.destroy();
    await new Promise((r) => setTimeout(r, 20));
    expect(doble.escena).toBeUndefined();
  });
});

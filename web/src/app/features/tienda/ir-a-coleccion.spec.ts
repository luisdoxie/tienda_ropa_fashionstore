import { irAColeccion } from './ir-a-coleccion';

describe('irAColeccion', () => {
  let seccion: HTMLElement;
  let buscador: HTMLInputElement;
  let scroll: ReturnType<typeof vi.fn>;

  function simularMovimientoReducido(reducido: boolean): void {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((consulta: string) => ({
        matches: consulta.includes('prefers-reduced-motion') ? reducido : false,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      })),
    );
  }

  beforeEach(() => {
    seccion = document.createElement('section');
    seccion.id = 'catalogo';
    scroll = vi.fn();
    seccion.scrollIntoView = scroll as unknown as typeof seccion.scrollIntoView;
    buscador = document.createElement('input');
    buscador.id = 'catalogo-buscar';
    document.body.append(seccion, buscador);
    simularMovimientoReducido(false);
  });

  afterEach(() => {
    seccion.remove();
    buscador.remove();
    vi.unstubAllGlobals();
  });

  it('cancela el enlace y baja a la sección con scroll suave', () => {
    const evento = new Event('click', { cancelable: true });

    irAColeccion(evento);

    expect(evento.defaultPrevented).toBe(true);
    expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    expect(document.activeElement).not.toBe(buscador);
  });

  it('con prefers-reduced-motion baja sin animación', () => {
    simularMovimientoReducido(true);

    irAColeccion(new Event('click', { cancelable: true }));

    expect(scroll).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' });
  });

  it('con enfocarBuscador deja el cursor en el buscador', () => {
    irAColeccion(new Event('click', { cancelable: true }), true);

    expect(document.activeElement).toBe(buscador);
  });

  it('no falla si la sección no está en pantalla', () => {
    seccion.remove();
    buscador.remove();

    expect(() => irAColeccion(new Event('click', { cancelable: true }), true)).not.toThrow();
  });
});

import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { SinConexionComponent } from './sin-conexion.component';

describe('SinConexionComponent', () => {
  afterEach(() => {
    delete (navigator as { onLine?: boolean }).onLine;
    vi.unstubAllGlobals();
  });

  function crear(returnTo: string | null) {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap(returnTo === null ? {} : { returnTo }) } },
        },
      ],
    });
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(SinConexionComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const reintentar = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Reintentar')) as HTMLButtonElement;
    const esperar = async () => {
      await fixture.whenStable();
      fixture.detectChanges();
    };
    return { fixture, el, navegar, reintentar, esperar };
  }

  it('muestra el título, el texto en tuteo y las dos acciones', () => {
    const { el } = crear(null);

    expect(el.querySelector('h1')?.textContent).toContain('Sin conexión');
    expect(el.textContent).toContain('Esta pantalla necesita conexión a Internet. Lo que ya guardaste en este equipo sigue disponible.');
    expect(el.textContent).toContain('Reintentar');
    const inicio = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Ir al inicio'));
    expect(inicio?.getAttribute('href')).toBe('/');
  });

  it('Reintentar con el servidor respondiendo vuelve a la pantalla que se quería abrir', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true } as Response)));
    const { navegar, reintentar, esperar } = crear('/t/acme/carrito');

    reintentar.click();
    await esperar();

    expect(navegar).toHaveBeenCalledTimes(1);
    expect(navegar).toHaveBeenCalledWith('/t/acme/carrito');
  });

  it('Reintentar sin red no navega y avisa que todavía no hay conexión', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
    const { el, navegar, reintentar, esperar } = crear('/t/acme/carrito');

    reintentar.click();
    await esperar();

    expect(navegar).not.toHaveBeenCalled();
    const aviso = el.querySelector('[role="status"]') as HTMLElement;
    expect(aviso.textContent).toContain('Todavía no hay conexión');
    expect(aviso.getAttribute('aria-live')).toBe('polite');
  });

  it('un returnTo que apunta a otro sitio se ignora y se vuelve al inicio', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true } as Response)));
    const { navegar, reintentar, esperar } = crear('//malo.example/robo');

    reintentar.click();
    await esperar();

    expect(navegar).toHaveBeenCalledWith('/');
  });

  it('sin returnTo vuelve al inicio', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true } as Response)));
    const { navegar, reintentar, esperar } = crear(null);

    reintentar.click();
    await esperar();

    expect(navegar).toHaveBeenCalledWith('/');
  });
});

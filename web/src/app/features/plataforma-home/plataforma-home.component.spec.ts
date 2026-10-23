import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { ResumenTienda } from '../../core/models/empresa.models';
import { CLAVE_ULTIMA_TIENDA } from '../tienda/state/tienda-actual.service';
import { PlataformaHomeComponent, RUTA_ACCESO_PERSONAL, TAMANIO_PAGINA_TIENDAS } from './plataforma-home.component';

const URL_TIENDAS = `${environment.apiUrl}/public/tiendas`;

function tienda(codigo: string, nombre = codigo, extra: Partial<ResumenTienda> = {}): ResumenTienda {
  return { codigo, nombre, logo_url: null, color_acento: null, ...extra };
}

function filas(cantidad: number, desde = 0): ResumenTienda[] {
  return Array.from({ length: cantidad }, (_, i) => tienda(`t${desde + i}`, `Tienda ${desde + i}`));
}

describe('PlataformaHomeComponent', () => {
  let controller: HttpTestingController;
  let fixture: ComponentFixture<PlataformaHomeComponent>;

  function crear(): void {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    controller = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PlataformaHomeComponent);
    fixture.detectChanges();
  }

  function pedidoTiendas(pagina: number, q = '') {
    return controller.expectOne(
      (r) =>
        r.url === URL_TIENDAS &&
        r.params.get('pagina') === String(pagina) &&
        r.params.get('q') === q &&
        r.params.get('tamanio') === String(TAMANIO_PAGINA_TIENDAS),
    );
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  afterEach(() => {
    vi.useRealTimers();
    try {
      localStorage.clear();
    } catch {
      // sin localStorage
    }
  });

  it('fija el título de la plataforma y muestra el acceso del personal', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    expect(TestBed.inject(Title).getTitle()).toBe('FashionStore | Tiendas de ropa');
    const acceso = html().querySelector<HTMLAnchorElement>('.home-acceso');
    expect(acceso?.textContent).toContain('Acceso del personal');
    expect(acceso?.getAttribute('href')).toBe(RUTA_ACCESO_PERSONAL);
    expect(html().textContent).toContain('Visita una tienda');
    expect(html().textContent).toContain('FashionStore · Plataforma para tiendas de ropa');
  });

  it('presenta servicios y los dos planes, sin precio ni cifras de relleno', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    const texto = html().textContent ?? '';
    expect(html().querySelectorAll('.home-servicio').length).toBe(6);
    expect(Array.from(html().querySelectorAll('.home-plan__nombre')).map((n) => n.textContent?.trim())).toEqual([
      'Básico',
      'Profesional',
    ]);
    expect(texto).not.toMatch(/\[(N|precio)\]/);
    expect(texto).not.toContain('Bs [');
    // Sin endpoint de alta: la franja final lleva al acceso del personal, no a un formulario.
    expect(html().querySelector('form')).toBeNull();
    expect(html().querySelector('.home-cta__enlace')?.getAttribute('href')).toBe(RUTA_ACCESO_PERSONAL);
  });

  it('el plan Profesional marca como próximamente lo que aún no existe', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    const profesional = html().querySelectorAll('.home-plan')[1].textContent ?? '';
    expect(profesional).toContain('Reportes con IA');
    expect(profesional).toContain('Analítica con aprendizaje automático (próximamente)');
    expect(profesional).toContain('Trabajo sin conexión (próximamente)');
    expect(profesional).not.toContain('Funciones de IA y analítica');
  });

  it('muestra esqueletos mientras carga y luego una tarjeta por tienda, con enlace a /t/<codigo>', () => {
    crear();
    expect(html().querySelectorAll('.tarjeta--esqueleto').length).toBe(6);

    pedidoTiendas(1).flush([tienda('acme', 'Acme', { color_acento: '#9a3e1f' }), tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelectorAll('.tarjeta--esqueleto').length).toBe(0);
    const enlaces = Array.from(html().querySelectorAll<HTMLAnchorElement>('a.tarjeta'));
    expect(enlaces.map((a) => a.getAttribute('href'))).toEqual(['/t/acme', '/t/andina']);
    expect(enlaces[0].textContent).toContain('Acme');
    // Sin logo: las siglas de la marca.
    expect(enlaces[0].querySelector('.marca__monograma')?.textContent?.trim()).toBe('AC');
    expect(enlaces[0].style.getPropertyValue('--tarjeta-acento')).toBe('#9a3e1f');
    // Sin color propio: queda el acento base de la app.
    expect(enlaces[1].style.getPropertyValue('--tarjeta-acento')).toBe('');
  });

  it('solo usa logos http/https; otro esquema muestra las siglas', () => {
    crear();
    pedidoTiendas(1).flush([
      tienda('con', 'Con logo', { logo_url: 'https://cdn.example.com/logo.png' }),
      tienda('mala', 'Mala', { logo_url: 'javascript:alert(1)' }),
    ]);
    fixture.detectChanges();

    const tarjetas = html().querySelectorAll('a.tarjeta');
    expect(tarjetas[0].querySelector('img')?.getAttribute('src')).toBe('https://cdn.example.com/logo.png');
    expect(tarjetas[1].querySelector('img')).toBeNull();
    expect(tarjetas[1].querySelector('.marca__monograma')?.textContent?.trim()).toBe('MA');
  });

  it('si el logo no carga, muestra las siglas', () => {
    crear();
    pedidoTiendas(1).flush([tienda('rota', 'Rota', { logo_url: 'https://cdn.example.com/rota.png' })]);
    fixture.detectChanges();

    html().querySelector('img')?.dispatchEvent(new Event('error'));
    fixture.detectChanges();

    expect(html().querySelector('img')).toBeNull();
    expect(html().querySelector('a.tarjeta .marca__monograma')?.textContent?.trim()).toBe('RO');
  });

  it('el buscador espera 350 ms y pide con ?q=', () => {
    vi.useFakeTimers();
    crear();
    pedidoTiendas(1).flush(filas(2));
    fixture.detectChanges();

    const input = html().querySelector<HTMLInputElement>('input')!;
    input.value = 'bout';
    input.dispatchEvent(new Event('input'));

    vi.advanceTimersByTime(349);
    controller.expectNone((r) => r.url === URL_TIENDAS);

    vi.advanceTimersByTime(1);
    pedidoTiendas(1, 'bout').flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
    controller.verify();
  });

  it('sin resultados muestra el mensaje de vacío', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    expect(html().textContent).toContain('No encontramos tiendas con ese nombre.');
    expect(html().querySelectorAll('a.tarjeta').length).toBe(0);
  });

  it('con error muestra el mensaje y Reintentar vuelve a pedir', () => {
    crear();
    pedidoTiendas(1).flush('boom', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(html().textContent).toContain('No pudimos cargar las tiendas');
    const boton = Array.from(html().querySelectorAll('button')).find((b) => b.textContent?.includes('Reintentar'));
    expect(boton).toBeDefined();

    boton!.click();
    pedidoTiendas(1).flush([tienda('acme', 'Acme')]);
    fixture.detectChanges();

    expect(html().textContent).not.toContain('No pudimos cargar las tiendas');
    expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
  });

  it('"Ver más" aparece si la página vino completa, pide la siguiente y se oculta con una página corta', () => {
    crear();
    pedidoTiendas(1).flush(filas(TAMANIO_PAGINA_TIENDAS));
    fixture.detectChanges();

    const verMas = () => Array.from(html().querySelectorAll('button')).find((b) => b.textContent?.includes('Ver más'));
    expect(verMas()).toBeDefined();

    verMas()!.click();
    pedidoTiendas(2).flush(filas(3, TAMANIO_PAGINA_TIENDAS));
    fixture.detectChanges();

    expect(html().querySelectorAll('a.tarjeta').length).toBe(TAMANIO_PAGINA_TIENDAS + 3);
    expect(verMas()).toBeUndefined();
    controller.verify();
  });

  it('sin tienda anterior no pide ni muestra "Volver a"', () => {
    crear();
    pedidoTiendas(1).flush([]);
    controller.expectNone((r) => r.url.endsWith('/tienda'));
    expect(html().textContent).not.toContain('Volver a');
  });

  it('muestra "Volver a <nombre>" arriba de la lista con la última tienda', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
    crear();
    controller.expectOne(`${environment.apiUrl}/public/acme/tienda`).flush(tienda('acme', 'Acme Ropa'));
    pedidoTiendas(1).flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    const volver = html().querySelector<HTMLAnchorElement>('.tarjeta--volver');
    expect(volver?.textContent).toContain('Volver a');
    expect(volver?.textContent).toContain('Acme Ropa');
    expect(volver?.getAttribute('href')).toBe('/t/acme');
    // Se agrega: la lista sigue completa.
    expect(html().querySelectorAll('a.tarjeta:not(.tarjeta--volver)').length).toBe(1);
  });

  it('si la última tienda ya no existe, no muestra "Volver a"', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'vieja');
    crear();
    controller.expectOne(`${environment.apiUrl}/public/vieja/tienda`).flush('no', { status: 404, statusText: 'Not Found' });
    pedidoTiendas(1).flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelector('.tarjeta--volver')).toBeNull();
  });
});

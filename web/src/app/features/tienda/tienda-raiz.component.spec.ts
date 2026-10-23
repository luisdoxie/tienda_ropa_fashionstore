import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { EmpresaPublica } from '../../core/models/empresa.models';
import { TiendaActualService } from './state/tienda-actual.service';
import { TiendaRaizComponent } from './tienda-raiz.component';

const empresa = (color: string | null): EmpresaPublica => ({
  codigo: 'acme',
  nombre: 'Acme',
  logo_url: null,
  color_acento: color,
});

describe('TiendaRaizComponent', () => {
  let fixture: ComponentFixture<TiendaRaizComponent>;
  let servicio: TiendaActualService;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [TiendaRaizComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    servicio = TestBed.inject(TiendaActualService);
    fixture = TestBed.createComponent(TiendaRaizComponent);
  });

  afterEach(() => {
    fixture?.destroy();
    document.documentElement.style.removeProperty('--fs-acento');
    localStorage.clear();
    vi.restoreAllMocks();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function mostrar(): void {
    fixture.detectChanges();
  }

  it('"lista" muestra el router-outlet y ninguna pantalla de estado', () => {
    servicio.fijar('acme', 'lista', empresa(null));
    mostrar();
    expect(el().querySelector('router-outlet')).not.toBeNull();
    expect(el().querySelector('app-tienda-no-disponible')).toBeNull();
    expect(el().querySelector('.raiz-estado')).toBeNull();
  });

  it('"cargando" muestra el esqueleto', () => {
    servicio.fijar('acme', 'cargando');
    mostrar();
    const seccion = el().querySelector('.raiz-estado');
    expect(seccion).not.toBeNull();
    expect(seccion?.getAttribute('aria-busy')).toBe('true');
    expect(el().querySelector('router-outlet')).toBeNull();
  });

  it('"sin_tienda" muestra el esqueleto de carga', () => {
    servicio.fijar(null, 'sin_tienda');
    mostrar();
    expect(el().querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(el().querySelector('router-outlet')).toBeNull();
  });

  it('"no_encontrada" muestra la pantalla de tienda no encontrada', () => {
    servicio.fijar('acme', 'no_encontrada');
    mostrar();
    expect(el().querySelector('app-tienda-no-disponible')).not.toBeNull();
    expect(el().textContent).toContain('Tienda no encontrada');
    expect(el().textContent).toContain('Revisa el enlace o busca otra.');
    expect(el().querySelector('router-outlet')).toBeNull();
  });

  it('"no_disponible" muestra la pantalla de tienda no disponible', () => {
    servicio.fijar('acme', 'no_disponible');
    mostrar();
    expect(el().querySelector('app-tienda-no-disponible')).not.toBeNull();
    expect(el().textContent).toContain('Tienda no disponible');
    expect(el().querySelector('router-outlet')).toBeNull();
  });

  it('"error" muestra el mensaje y el botón Reintentar vuelve a cargar', () => {
    servicio.fijar('acme', 'error');
    const cargar = vi.spyOn(servicio, 'cargar').mockReturnValue(of('lista'));
    mostrar();
    expect(el().textContent).toContain('No pudimos cargar la tienda');
    expect(el().textContent).toContain('Revisa tu conexión e inténtalo de nuevo.');
    expect(el().querySelector('[role="alert"]')).not.toBeNull();
    const boton = el().querySelector<HTMLButtonElement>('button.fs-btn');
    expect(boton).not.toBeNull();
    expect(boton?.textContent?.trim()).toBe('Reintentar');

    boton!.click();

    expect(cargar).toHaveBeenCalledTimes(1);
    expect(cargar).toHaveBeenCalledWith('acme');
  });

  describe('marca (color de acento)', () => {
    it('con "lista" y color válido fija --fs-acento solo en el host, no en :root', () => {
      servicio.fijar('acme', 'lista', empresa('#2563eb'));
      mostrar();
      expect(el().style.getPropertyValue('--fs-acento')).toBe('#2563eb');
      expect(el().style.getPropertyValue('--fs-acento-hover')).not.toBe('');
      expect(el().style.getPropertyValue('--fs-acento-suave')).not.toBe('');
      // La variante sobre superficies oscuras y el texto de un botón relleno con ella.
      expect(el().style.getPropertyValue('--fs-acento-oscuro')).not.toBe('');
      expect(el().style.getPropertyValue('--fs-acento-oscuro-hover')).not.toBe('');
      expect(el().style.getPropertyValue('--fs-sobre-acento-oscuro')).not.toBe('');
      // Los controles siguen siendo tinta: la marca no toca el primario de PrimeNG.
      expect(el().style.getPropertyValue('--p-primary-color')).toBe('');
      expect(document.documentElement.style.getPropertyValue('--fs-acento')).toBe('');
      expect(getComputedStyle(document.documentElement).getPropertyValue('--fs-acento').trim()).not.toBe('#2563eb');
    });

    it('un color con mal contraste no fija la variable', () => {
      servicio.fijar('acme', 'lista', empresa('#ffee88'));
      mostrar();
      expect(el().style.getPropertyValue('--fs-acento')).toBe('');
    });

    it('un color inválido o ausente no fija la variable', () => {
      servicio.fijar('acme', 'lista', empresa('nada'));
      mostrar();
      expect(el().style.getPropertyValue('--fs-acento')).toBe('');

      servicio.fijar('acme', 'lista', empresa(null));
      fixture.detectChanges();
      expect(el().style.getPropertyValue('--fs-acento')).toBe('');
    });

    it('si el estado no es "lista" no aplica la marca aunque haya empresa', () => {
      servicio.fijar('acme', 'no_disponible', empresa('#2563eb'));
      mostrar();
      expect(el().style.getPropertyValue('--fs-acento')).toBe('');
    });
  });

  it('al destruirse sale de la tienda', () => {
    servicio.fijar('acme', 'lista', empresa(null));
    mostrar();
    fixture.destroy();
    expect(servicio.estado()).toBe('sin_tienda');
    expect(servicio.codigo()).toBeNull();
  });
});

import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EmpresaPublica } from '../../core/models/empresa.models';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { AccesoPantallaComponent } from './acceso-pantalla.component';

@Component({
  standalone: true,
  imports: [AccesoPantallaComponent],
  template: `
    <app-acceso-pantalla [modo]="modo()" [foto]="foto()" altFoto="Foto de prueba">
      <p class="lema" panelImagen>Más que ropa</p>
      <form class="formulario-proyectado"><h1>Título</h1></form>
    </app-acceso-pantalla>
  `,
})
class AnfitrionComponent {
  readonly modo = signal<'personal' | 'cliente'>('cliente');
  readonly foto = signal<'acceso' | 'portada'>('acceso');
}

function tienda(extra: Partial<EmpresaPublica> = {}): EmpresaPublica {
  return { codigo: 'acme', nombre: 'Acme Ropa', logo_url: null, color_acento: null, ...extra };
}

describe('AccesoPantallaComponent', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [AnfitrionComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
  });

  afterEach(() => localStorage.clear());

  function crear(modo: 'personal' | 'cliente' = 'cliente', foto: 'acceso' | 'portada' = 'acceso') {
    const fixture = TestBed.createComponent(AnfitrionComponent);
    fixture.componentInstance.modo.set(modo);
    fixture.componentInstance.foto.set(foto);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  describe('modo cliente (claro)', () => {
    it('tiene cabecera, pie y proyecta el formulario y el panel de la imagen', () => {
      const { el } = crear('cliente');

      expect(el.querySelector('.acceso--personal')).toBeNull();
      expect(el.querySelector('.fs-zona-oscura')).toBeNull();
      expect(el.querySelector('header.acceso__cabecera')).not.toBeNull();
      expect(el.querySelector('footer')?.textContent).toContain('Con la tecnología de FashionStore');
      expect(el.querySelector('.acceso__panel .formulario-proyectado')).not.toBeNull();
      expect(el.querySelector('.acceso__foto .lema')?.textContent).toContain('Más que ropa');
    });

    it('sin tienda: marca FashionStore y "Ir al inicio" hacia la plataforma', () => {
      const { el } = crear('cliente');

      expect(el.querySelector('header fs-marca')?.getAttribute('aria-label')).toBe('FashionStore');
      const volver = el.querySelector<HTMLAnchorElement>('.acceso__volver')!;
      expect(volver.textContent).toContain('Ir al inicio');
      expect(volver.getAttribute('href')).toBe('/');
    });

    it('con tienda: su nombre, "Volver a la tienda" y el monograma de sus siglas', () => {
      TestBed.inject(TiendaActualService).fijar('acme', 'lista', tienda());
      const { el } = crear('cliente');

      expect(el.querySelector('header fs-marca')?.getAttribute('aria-label')).toBe('Acme Ropa');
      expect(el.querySelector('header .marca__monograma')?.textContent?.trim()).toBe('AR');
      expect(el.querySelector('header img')).toBeNull();
      const volver = el.querySelector<HTMLAnchorElement>('.acceso__volver')!;
      expect(volver.textContent).toContain('Volver a la tienda');
      expect(volver.getAttribute('href')).toBe('/t/acme');
    });

    it('con logo http(s) muestra el logo; con otro esquema vuelve al monograma', () => {
      TestBed.inject(TiendaActualService).fijar('acme', 'lista', tienda({ logo_url: 'https://cdn.example.com/l.png' }));
      const con = crear('cliente');
      expect(con.el.querySelector('header img')?.getAttribute('src')).toBe('https://cdn.example.com/l.png');
      con.fixture.destroy();

      TestBed.inject(TiendaActualService).fijar('acme', 'lista', tienda({ logo_url: 'javascript:alert(1)' }));
      const sin = crear('cliente');
      expect(sin.el.querySelector('header img')).toBeNull();
      expect(sin.el.querySelector('header .marca__monograma')).not.toBeNull();
    });
  });

  describe('modo personal (oscuro)', () => {
    it('es zona oscura, sin cabecera ni pie, con la marca sobre la foto', () => {
      const { el } = crear('personal');

      expect(el.querySelector('.acceso.acceso--personal.fs-zona-oscura')).not.toBeNull();
      expect(el.querySelector('header')).toBeNull();
      expect(el.querySelector('footer')).toBeNull();
      expect(el.querySelector('.acceso__foto-marca fs-marca')?.getAttribute('aria-label')).toBe('FashionStore');
      expect(el.querySelector('.acceso__panel .formulario-proyectado')).not.toBeNull();
    });

    it('el titular de la foto es decorativo (aria-hidden) y no compite con el h1 del formulario', () => {
      const { el } = crear('personal');

      expect(el.querySelector('.acceso-foto-titular')?.getAttribute('aria-hidden')).toBe('true');
      expect(el.querySelector('.acceso__foto h1, .acceso__foto h2')).toBeNull();
      expect(el.querySelectorAll('h1').length).toBe(1);
      // El panel proyectado del modo cliente no se usa en el personal.
      expect(el.querySelector('.lema')).toBeNull();
    });
  });

  it('usa la foto de acceso o la de portada, con su texto alternativo', () => {
    const acceso = crear('cliente', 'acceso');
    const imgAcceso = acceso.el.querySelector<HTMLImageElement>('.acceso__foto-img')!;
    expect(imgAcceso.getAttribute('src')).toBe('/imagenes/acceso.png');
    expect(imgAcceso.alt).toBe('Foto de prueba');
    acceso.fixture.destroy();

    const portada = crear('cliente', 'portada');
    expect(portada.el.querySelector('.acceso__foto-img')?.getAttribute('src')).toBe('/imagenes/portada-tienda.png');
  });
});

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { SolicitarRecuperacionComponent } from './solicitar-recuperacion.component';

const API = environment.apiUrl;

describe('SolicitarRecuperacionComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [SolicitarRecuperacionComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  function crear() {
    const fixture = TestBed.createComponent(SolicitarRecuperacionComponent);
    fixture.detectChanges();
    return { fixture, comp: fixture.componentInstance as any, el: fixture.nativeElement as HTMLElement };
  }

  it('tras enviar muestra "Revisa tu correo" con el mismo mensaje, exista o no el correo', () => {
    const { fixture, comp, el } = crear();
    comp.formulario.patchValue({ empresa: 'acme', email: 'a@b.com' });
    comp.enviar();
    http.expectOne(`${API}/auth/recuperar`).flush({ detail: 'ok' });
    fixture.detectChanges();

    expect(el.querySelector('h1')?.textContent).toContain('Revisa tu correo');
    expect(el.querySelector('[role="status"]')?.textContent).toContain(
      'Si el correo está registrado, se enviarán instrucciones de recuperación.',
    );
    expect(el.querySelector('form')).toBeNull();
    expect(el.querySelector('a.acceso-enlace')?.getAttribute('href')).toBe('/admin/login');
  });

  it('dentro de una tienda manda el código de la tienda y no pide la empresa', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const { comp, el } = crear();
    expect(el.querySelector('#empresa')).toBeNull();

    comp.formulario.patchValue({ email: 'a@b.com' });
    comp.enviar();
    expect(http.expectOne(`${API}/auth/recuperar`).request.body).toEqual({ email: 'a@b.com', empresa: 'acme' });
  });

  it('el personal (sin tienda) escribe su empresa y se manda con el correo', () => {
    const { comp, el } = crear();
    expect(el.querySelector('#empresa')).not.toBeNull();
    expect(el.querySelector('a.acceso-enlace')?.getAttribute('href')).toBe('/admin/login');

    comp.formulario.patchValue({ empresa: ' Boutique Andina ', email: 'a@b.com' });
    comp.enviar();
    expect(http.expectOne(`${API}/auth/recuperar`).request.body).toEqual({
      email: 'a@b.com',
      empresa: 'Boutique Andina',
    });
  });

  it('el personal sin empresa no envía nada y se lo avisa en pantalla', () => {
    const { fixture, comp, el } = crear();
    comp.formulario.patchValue({ email: 'a@b.com' });
    comp.enviar();
    fixture.detectChanges();

    http.expectNone(`${API}/auth/recuperar`);
    const campo = el.querySelector('#empresa')!;
    expect(campo.getAttribute('aria-invalid')).toBe('true');
    expect(campo.getAttribute('aria-describedby')).toBe('error-empresa');
    const error = el.querySelector('#error-empresa');
    expect(error?.getAttribute('role')).toBe('alert');
    expect(error?.textContent).toContain('Escribe el nombre o el código de tu empresa.');
  });

  it('una empresa de solo espacios también cuenta como vacía', () => {
    const { comp } = crear();
    comp.formulario.patchValue({ empresa: '   ', email: 'a@b.com' });
    comp.enviar();
    http.expectNone(`${API}/auth/recuperar`);
  });

  it('un correo inválido muestra su mensaje ligado al campo', () => {
    const { fixture, comp, el } = crear();
    comp.formulario.patchValue({ empresa: 'acme', email: 'no-es-correo' });
    comp.enviar();
    fixture.detectChanges();

    http.expectNone(`${API}/auth/recuperar`);
    expect(el.querySelector('#email')?.getAttribute('aria-describedby')).toBe('error-email');
    expect(el.querySelector('#error-email')?.textContent).toContain('correo válido');
  });

  it('sin tienda (personal) usa la pantalla oscura del acceso del personal, con la foto de acceso', () => {
    const { el } = crear();

    expect(el.querySelector('.acceso--personal.fs-zona-oscura')).not.toBeNull();
    expect(el.querySelector('header.acceso__cabecera')).toBeNull();
    expect(el.querySelector('.acceso__foto-img')?.getAttribute('src')).toBe('/imagenes/acceso.png');
    expect(el.querySelector('button[type="submit"]')?.classList.contains('fs-btn--acento')).toBe(true);
  });

  it('con tienda (cliente) sigue en la pantalla clara con la cabecera de la tienda', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const { el } = crear();

    expect(el.querySelector('.acceso--personal')).toBeNull();
    expect(el.querySelector('header.acceso__cabecera')).not.toBeNull();
    expect(el.querySelector('button[type="submit"]')?.classList.contains('fs-btn--primario')).toBe(true);
  });
});

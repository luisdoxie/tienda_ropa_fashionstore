import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { TiendaActualService } from '../state/tienda-actual.service';
import { MisComprasComponent } from './mis-compras.component';
import { MisReservasComponent } from './mis-reservas.component';

const API = environment.apiUrl;

describe('listas de la cuenta del cliente', () => {
  let http: HttpTestingController;

  function preparar(): void {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
  }

  afterEach(() => localStorage.clear());

  describe('MisComprasComponent', () => {
    const URL = `${API}/ventas/mis-compras`;

    function montar() {
      preparar();
      const fixture = TestBed.createComponent(MisComprasComponent);
      fixture.detectChanges();
      return { fixture, el: fixture.nativeElement as HTMLElement };
    }

    it('lista las compras con chip de estado, total en Bs y enlace al detalle', () => {
      const { fixture, el } = montar();
      http.expectOne(URL).flush([
        { id: 1, codigo: 'V-1', estado: 'pagada', fecha: '2026-10-22T10:42:00', total: 409.2 },
        { id: 2, codigo: 'V-2', estado: 'pendiente_pago', fecha: '2026-10-18T16:05:00', total: 689 },
        { id: 3, codigo: 'V-3', estado: 'anulada', fecha: '2026-10-02T11:30:00', total: 149 },
      ]);
      fixture.detectChanges();

      const filas = Array.from(el.querySelectorAll('a.fila'));
      expect(filas.length).toBe(3);
      expect(filas[0].getAttribute('href')).toBe('/t/acme/mis-compras/1');
      expect(filas[0].textContent).toContain('V-1');
      expect(filas[0].textContent).toContain('Bs 409.20');
      expect(filas[0].querySelector('.fs-chip')?.classList).toContain('fs-chip--exito');
      expect(filas[0].querySelector('.fs-chip')?.textContent).toContain('Pagada');
      expect(filas[1].querySelector('.fs-chip')?.classList).toContain('fs-chip--advertencia');
      expect(filas[2].querySelector('.fs-chip')?.classList).toContain('fs-chip--error');
      expect(el.querySelector('.fs-tab--activa')?.textContent).toContain('Compras');
    });

    it('sin compras muestra el vacío en tuteo, no un error', () => {
      const { fixture, el } = montar();
      http.expectOne(URL).flush([]);
      fixture.detectChanges();

      expect(el.querySelector('.vacio')?.textContent).toContain('Todavía no has hecho ninguna compra.');
      expect(el.querySelector('.estado-error')).toBeNull();
    });

    it('si la API falla muestra el error con "Reintentar" (no el vacío) y reintenta', () => {
      const { fixture, el } = montar();
      http.expectOne(URL).flush('x', { status: 500, statusText: 'Error' });
      fixture.detectChanges();

      expect(el.querySelector('.estado-error')?.textContent).toContain('No se pudieron cargar tus compras.');
      expect(el.querySelector('.vacio')).toBeNull();

      (el.querySelector('.estado-error button') as HTMLButtonElement).click();
      http.expectOne(URL).flush([]);
      fixture.detectChanges();

      expect(el.querySelector('.estado-error')).toBeNull();
      expect(el.querySelector('.vacio')).not.toBeNull();
    });
  });

  describe('MisReservasComponent', () => {
    function montar() {
      preparar();
      const fixture = TestBed.createComponent(MisReservasComponent);
      fixture.detectChanges();
      return { fixture, el: fixture.nativeElement as HTMLElement };
    }

    const reserva = (id: number, estado: string) => ({
      id,
      codigo: `R-${id}`,
      estado,
      fecha_visita: '2026-10-25',
      hora_visita_desde: '10:00:00',
      hora_visita_hasta: '11:00:00',
    });

    it('lista las reservas con su horario y chip de estado', () => {
      const { fixture, el } = montar();
      http
        .expectOne((r) => r.url.includes('/reservas'))
        .flush([reserva(1, 'preparada'), reserva(2, 'pendiente'), reserva(3, 'cancelada')]);
      fixture.detectChanges();

      const filas = Array.from(el.querySelectorAll('a.fila'));
      expect(filas.length).toBe(3);
      expect(filas[0].getAttribute('href')).toBe('/t/acme/mis-reservas/1');
      expect(filas[0].textContent).toContain('10:00 - 11:00');
      expect(filas[0].querySelector('.fs-chip')?.classList).toContain('fs-chip--exito');
      expect(filas[1].querySelector('.fs-chip')?.classList).toContain('fs-chip--advertencia');
      expect(filas[2].querySelector('.fs-chip')?.classList).toContain('fs-chip--error');
      expect(el.querySelector('.fs-tab--activa')?.textContent).toContain('Reservas');
    });

    it('sin reservas muestra el vacío, y si falla la API muestra el error con "Reintentar"', () => {
      const { fixture, el } = montar();
      http.expectOne((r) => r.url.includes('/reservas')).flush([]);
      fixture.detectChanges();
      expect(el.querySelector('.vacio')?.textContent).toContain('Todavía no has hecho ninguna reserva.');

      TestBed.resetTestingModule();
      const otra = montar();
      http.expectOne((r) => r.url.includes('/reservas')).flush('x', { status: 500, statusText: 'Error' });
      otra.fixture.detectChanges();

      expect(otra.el.querySelector('.estado-error')?.textContent).toContain('No se pudieron cargar tus reservas.');
      expect(otra.el.querySelector('.vacio')).toBeNull();

      (otra.el.querySelector('.estado-error button') as HTMLButtonElement).click();
      http.expectOne((r) => r.url.includes('/reservas')).flush([]);
      otra.fixture.detectChanges();
      expect(otra.el.querySelector('.vacio')).not.toBeNull();
    });
  });
});

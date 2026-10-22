import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { TiendaActualService } from '../state/tienda-actual.service';
import { DisponibilidadService } from './disponibilidad.service';

describe('DisponibilidadService', () => {
  let servicio: DisponibilidadService;
  let controller: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    servicio = TestBed.inject(DisponibilidadService);
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    controller.verify();
    localStorage.clear();
  });

  it('pide la disponibilidad por la API pública de la tienda', () => {
    servicio.porVariante(7).subscribe();
    const req = controller.expectOne((r) => r.url === `${environment.apiUrl}/public/acme/inventario/disponibilidad`);
    expect(req.request.params.get('variante_id')).toBe('7');
    req.flush([]);
  });

  it('pide las sucursales por la API pública de la tienda', () => {
    servicio.sucursales().subscribe();
    const req = controller.expectOne((r) => r.url === `${environment.apiUrl}/public/acme/sucursales`);
    expect(req.request.params.get('tamanio')).toBe('100');
    req.flush([]);
  });
});

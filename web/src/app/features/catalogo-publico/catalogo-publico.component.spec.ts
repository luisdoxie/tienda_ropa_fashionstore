import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { CatalogoPublicoComponent } from './catalogo-publico.component';

describe('CatalogoPublicoComponent', () => {
  afterEach(() => localStorage.clear());

  it('carga catálogo y referencias desde /public/<codigo>/...', () => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const controller = TestBed.inject(HttpTestingController);

    const fixture = TestBed.createComponent(CatalogoPublicoComponent);
    fixture.detectChanges();

    const base = `${environment.apiUrl}/public/acme`;
    controller.expectOne((r) => r.url.startsWith(`${base}/catalogo?`) && !r.url.includes('/buscar')).flush([]);
    for (const lista of ['categorias', 'tallas', 'colores', 'materiales', 'temporadas']) {
      controller.expectOne((r) => r.url.startsWith(`${base}/${lista}?`)).flush([]);
    }
    controller.verify();
  });
});

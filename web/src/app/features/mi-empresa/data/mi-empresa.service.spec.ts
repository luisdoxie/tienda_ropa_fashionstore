import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { MiEmpresa } from '../../../core/models/plan.models';
import { MiEmpresaService } from './mi-empresa.service';

const URL_EMPRESA = `${environment.apiUrl}/mi-empresa`;

const EMPRESA: MiEmpresa = { id: 1, codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: '#9a3e1f', activo: true };

describe('MiEmpresaService', () => {
  let servicio: MiEmpresaService;
  let controller: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(MiEmpresaService);
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => controller.verify());

  it('obtener pide GET /mi-empresa sin toast de error', () => {
    let recibida: MiEmpresa | undefined;
    servicio.obtener().subscribe((empresa) => (recibida = empresa));

    const peticion = controller.expectOne(URL_EMPRESA);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush(EMPRESA);

    expect(recibida).toEqual(EMPRESA);
  });

  it('actualizar manda PUT /mi-empresa con la identidad y sin toast de error', () => {
    const cuerpo = { nombre: 'Acme 2', logo_url: null, color_acento: '#112233' };
    let recibida: MiEmpresa | undefined;
    servicio.actualizar(cuerpo).subscribe((empresa) => (recibida = empresa));

    const peticion = controller.expectOne(URL_EMPRESA);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual(cuerpo);
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({ ...EMPRESA, ...cuerpo });

    expect(recibida?.nombre).toBe('Acme 2');
  });
});

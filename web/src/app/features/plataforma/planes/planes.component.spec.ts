import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { PlanPlataforma } from '../../../core/models/plataforma.models';
import { PlanesComponent } from './planes.component';

const URL_PLANES = `${environment.apiUrl}/plataforma/planes`;

function plan(sobrescribir: Partial<PlanPlataforma> = {}): PlanPlataforma {
  return {
    id: 1,
    codigo: 'basico',
    nombre: 'Básico',
    max_sucursales: 2,
    max_copias_historial: 0,
    plazo_cambio_horas_defecto: 24,
    reportes_convencionales: true,
    reportes_ia: false,
    operacion_offline: false,
    analitica_ml: false,
    copias_seguridad: false,
    gestion_productos: true,
    gestion_ventas: true,
    reservas: true,
    activo: true,
    ...sobrescribir,
  };
}

interface Interno {
  formulario: {
    invalid: boolean;
    controls: Record<string, { setValue(v: unknown): void; valid: boolean }>;
  };
  abrirEditar(p: PlanPlataforma): void;
  guardar(): void;
  cambios(): Record<string, unknown>;
  dialogoVisible(): boolean;
}

describe('PlanesComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlanesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function crear(planes: PlanPlataforma[] = [plan(), plan({ id: 2, codigo: 'profesional', nombre: 'Profesional', max_sucursales: 10, reportes_ia: true })]) {
    const fixture = TestBed.createComponent(PlanesComponent);
    fixture.detectChanges();
    const lista = http.expectOne((r) => r.url === URL_PLANES);
    expect(lista.request.params.get('pagina')).toBe('1');
    lista.flush(planes);
    fixture.detectChanges();
    return { fixture, comp: fixture.componentInstance as unknown as Interno };
  }

  it('lista los planes con sus datos', () => {
    const { fixture } = crear();
    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texto).toContain('Básico');
    expect(texto).toContain('Profesional');
    expect(texto).toContain('Reportes con IA');
  });

  it('acepta los límites en los bordes del rango y rechaza lo que está fuera', () => {
    const { comp } = crear();
    comp.abrirEditar(plan());
    const c = comp.formulario.controls;

    for (const [campo, valor, valido] of [
      ['max_sucursales', 1, true],
      ['max_sucursales', 1000, true],
      ['max_sucursales', 0, false],
      ['max_sucursales', 1001, false],
      ['max_sucursales', null, false],
      ['max_sucursales', 2.5, false],
      ['max_copias_historial', 0, true],
      ['max_copias_historial', 1000, true],
      ['max_copias_historial', -1, false],
      ['max_copias_historial', 1001, false],
      ['plazo_cambio_horas_defecto', 0, true],
      ['plazo_cambio_horas_defecto', 8760, true],
      ['plazo_cambio_horas_defecto', 8761, false],
      ['plazo_cambio_horas_defecto', -5, false],
    ] as [string, number | null, boolean][]) {
      c[campo].setValue(valor);
      expect(c[campo].valid, `${campo}=${valor}`).toBe(valido);
      c[campo].setValue(campo === 'max_sucursales' ? 2 : campo === 'plazo_cambio_horas_defecto' ? 24 : 0);
    }
  });

  it('con un valor inválido no llama a la API', () => {
    const { comp } = crear();
    comp.abrirEditar(plan());
    comp.formulario.controls['max_sucursales'].setValue(0);
    comp.guardar();
    http.expectNone(`${URL_PLANES}/1`);
    expect(comp.formulario.invalid).toBe(true);
    expect(comp.dialogoVisible()).toBe(true);
  });

  it('manda en el PUT solo los campos que cambiaron (límites y banderas)', () => {
    const { comp } = crear();
    comp.abrirEditar(plan());
    comp.formulario.controls['max_sucursales'].setValue(5);
    comp.formulario.controls['reportes_ia'].setValue(true);
    comp.formulario.controls['reservas'].setValue(false);
    expect(comp.cambios()).toEqual({ max_sucursales: 5, reportes_ia: true, reservas: false });

    comp.guardar();
    const put = http.expectOne(`${URL_PLANES}/1`);
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ max_sucursales: 5, reportes_ia: true, reservas: false });
    put.flush(plan({ max_sucursales: 5 }));

    // Tras guardar se recarga la lista.
    http.expectOne((r) => r.url === URL_PLANES).flush([plan({ max_sucursales: 5 })]);
    expect(comp.dialogoVisible()).toBe(false);
  });

  it('sin cambios cierra el diálogo y no llama a la API', () => {
    const { comp } = crear();
    comp.abrirEditar(plan());
    comp.guardar();
    http.expectNone(`${URL_PLANES}/1`);
    expect(comp.dialogoVisible()).toBe(false);
  });

  it('el aviso explica lo que realmente hace el backend al bajar un límite', () => {
    const { fixture, comp } = crear();
    comp.abrirEditar(plan());
    fixture.detectChanges();
    const texto = document.body.textContent ?? '';
    expect(texto).toContain('no desactiva las que una empresa ya tiene');
  });
});

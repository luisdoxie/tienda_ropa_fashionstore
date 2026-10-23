import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { ReservasComponent } from './reservas.component';

const API = environment.apiUrl;

const reserva = (id: number, estado: string) => ({
  id,
  codigo: 'R-' + id,
  estado,
  fecha_visita: '2026-10-22',
  hora_visita_desde: '10:00',
  hora_visita_hasta: '11:00',
  observacion: null,
  detalle: [{ id: 1, variante_id: 9, cantidad: 2, seleccionada: null, preparada: false }],
  historial: [],
});

type Comp = {
  filtroSucursal: { set(v: number): void };
  filtroEstado: { set(v: string | null): void };
  buscarReservas(): void;
  marcarPreparada(varianteId: number, marcado: boolean): void;
  elegirCompra(varianteId: number, comprada: boolean): void;
};

describe('ReservasComponent', () => {
  let http: HttpTestingController;

  function abrir() {
    TestBed.configureTestingModule({
      imports: [ReservasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ReservasComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/sucursales?pagina=1&tamanio=100`).flush([{ id: 1, nombre: 'Central' }]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, comp: fixture.componentInstance as unknown as Comp };
  }

  type Pantalla = ReturnType<typeof abrir>;

  function cargar({ fixture, comp }: Pantalla): void {
    comp.filtroSucursal.set(1);
    comp.buscarReservas();
    http
      .expectOne(`${API}/reservas/sucursal/1`)
      .flush([reserva(1, 'pendiente'), reserva(2, 'preparada'), reserva(3, 'completada'), reserva(4, 'cancelada')]);
    fixture.detectChanges();
  }

  function abrirDetalle({ fixture, el }: Pantalla, indice: number): void {
    (el.querySelectorAll('tbody [aria-label="Ver detalle"]')[indice] as HTMLButtonElement).click();
    fixture.detectChanges();
  }

  const boton = (texto: string) =>
    Array.from(document.body.querySelectorAll('.p-dialog button')).find((b) =>
      b.textContent?.includes(texto),
    ) as HTMLButtonElement | undefined;

  afterEach(() => http.match(() => true));

  it('no consulta nada hasta elegir una sucursal y la pide con un mensaje en tuteo', () => {
    const { el } = abrir();

    http.expectNone((r) => r.url.startsWith(`${API}/reservas`));
    expect(el.querySelector('.vacio')?.textContent).toContain('Elige una sucursal.');
  });

  it('lista las reservas de la sucursal y el filtro de estado deja solo las que coinciden', () => {
    const pantalla = abrir();
    cargar(pantalla);
    const { fixture, el, comp } = pantalla;

    const chips = () => Array.from(el.querySelectorAll('tbody .fs-chip')).map((c) => c.textContent?.trim());
    expect(chips()).toEqual(['Pendiente', 'Preparada', 'Completada', 'Cancelada']);
    expect(el.querySelector('tbody .fs-chip--exito')?.textContent).toBe('Completada');

    comp.filtroEstado.set('preparada');
    fixture.detectChanges();
    expect(chips()).toEqual(['Preparada']);
    expect(el.querySelector('.conteo')?.textContent).toContain('1 reservas');
  });

  it('preparar: la reserva pendiente exige marcar cada prenda y pasa a preparada', () => {
    const pantalla = abrir();
    cargar(pantalla);
    const { fixture, el, comp } = pantalla;
    abrirDetalle(pantalla, 0);

    expect(document.body.textContent).toContain('Marca cada prenda al prepararla');
    expect(boton('Confirmar preparación')?.disabled).toBe(true);

    comp.marcarPreparada(9, true);
    fixture.detectChanges();
    expect(boton('Confirmar preparación')?.disabled).toBe(false);

    boton('Confirmar preparación')!.click();
    http.expectOne((r) => r.method === 'PUT' && r.url === `${API}/reservas/1/preparar`).flush(reserva(1, 'preparada'));
    fixture.detectChanges();

    expect(el.querySelector('tbody tr .fs-chip')?.textContent).toBe('Preparada');
    expect(boton('Confirmar llegada del cliente')).toBeDefined();
  });

  it('entregar: confirma la llegada, registra qué compró el cliente y completa la reserva', () => {
    const pantalla = abrir();
    cargar(pantalla);
    const { fixture, el, comp } = pantalla;
    abrirDetalle(pantalla, 1);

    boton('Confirmar llegada del cliente')!.click();
    http
      .expectOne((r) => r.method === 'PUT' && r.url === `${API}/reservas/2/confirmar-llegada`)
      .flush(reserva(2, 'en_prueba'));
    fixture.detectChanges();
    expect(document.body.textContent).toContain('¿Qué se llevó el cliente?');
    expect(boton('Confirmar selección')?.disabled).toBe(true);

    comp.elegirCompra(9, true);
    fixture.detectChanges();
    boton('Confirmar selección')!.click();
    const seleccion = http.expectOne((r) => r.method === 'PUT' && r.url === `${API}/reservas/2/seleccion`);
    expect(seleccion.request.body).toEqual({ lineas: [{ variante_id: 9, seleccionada: true }] });
    seleccion.flush({ ...reserva(2, 'completada'), detalle: [{ id: 1, variante_id: 9, cantidad: 2, seleccionada: true, preparada: true }] });
    fixture.detectChanges();

    expect(el.querySelectorAll('tbody tr .fs-chip')[1].textContent).toBe('Completada');
    expect(document.body.querySelector('.p-dialog .fs-chip--exito')?.textContent).toBeDefined();
    expect(document.body.textContent).toContain('Comprada');
  });
});

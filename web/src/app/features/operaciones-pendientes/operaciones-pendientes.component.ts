import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { AuthService } from '../../core/auth.service';
import { ConectividadService } from '../../core/conectividad.service';
import { CatalogoLocalService } from '../../core/offline/catalogo-local.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import type {
  EstadoOperacion,
  FilaSucursal,
  FiltroOperaciones,
  OperacionOffline,
  ResultadoSync,
  TipoOperacion,
} from '../../core/offline/offline.models';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import {
  ETIQUETA_TIPO,
  VISTA_ESTADO,
  VistaEstado,
  formatoBs,
  htmlComprobante,
  iconoEstadoCola,
  motivoClaro,
  plural,
  textoEstadoCola,
  textoIntento,
  ultimoResultado,
} from './textos-operacion';

/** Operaciones por página (la tabla es compacta). */
const FILAS_POR_PAGINA = 20;

const OPCIONES_ESTADO: { label: string; value: EstadoOperacion | null }[] = [
  { label: 'Todos los estados', value: null },
  { label: VISTA_ESTADO.registrada.texto, value: 'registrada' },
  { label: VISTA_ESTADO.enviada.texto, value: 'enviada' },
  { label: VISTA_ESTADO.confirmada.texto, value: 'confirmada' },
  { label: VISTA_ESTADO.rechazada.texto, value: 'rechazada' },
  { label: 'En conflicto', value: 'en_conflicto' },
];

const OPCIONES_TIPO: { label: string; value: TipoOperacion | null }[] = [
  { label: 'Ventas y reservas', value: null },
  { label: 'Ventas', value: 'venta_contado' },
  { label: 'Reservas', value: 'reserva' },
];

/**
 * "Pendientes de envío" (E14b, plan 4.9): todo lo que se registró en ESTE equipo con tu usuario y en qué va cada cosa.
 * Solo se lee: ninguna acción borra ni descarta una operación. Se vuelve a leer cuando cambian los conteos de la cola.
 */
@Component({
  selector: 'app-operaciones-pendientes',
  standalone: true,
  imports: [DatePipe, FormsModule, DatePickerModule, DialogModule, SelectModule, TableModule, TagModule, IconoComponent],
  templateUrl: './operaciones-pendientes.component.html',
  styleUrl: './operaciones-pendientes.component.scss',
})
export class OperacionesPendientesComponent implements OnInit, OnDestroy {
  private readonly sesion = inject(SesionOfflineService);
  private readonly catalogo = inject(CatalogoLocalService);
  private readonly conectividad = inject(ConectividadService);
  private readonly auth = inject(AuthService);
  protected readonly cola = inject(ColaSincronizacionService);

  protected readonly opcionesEstado = OPCIONES_ESTADO;
  protected readonly opcionesTipo = OPCIONES_TIPO;
  protected readonly filasPorPagina = FILAS_POR_PAGINA;
  protected readonly vistaEstado = (estado: EstadoOperacion): VistaEstado => VISTA_ESTADO[estado];
  protected readonly etiquetaTipo = (tipo: TipoOperacion): string => ETIQUETA_TIPO[tipo];
  protected readonly bs = formatoBs;
  protected readonly motivoClaro = motivoClaro;
  protected readonly ultimoResultado = ultimoResultado;
  protected readonly textoIntento = textoIntento;

  // ---- Filtros ------------------------------------------------------------------------------------------------------
  protected readonly filtroEstado = signal<EstadoOperacion | null>(null);
  protected readonly filtroTipo = signal<TipoOperacion | null>(null);
  protected readonly filtroSucursal = signal<number | null>(null);
  protected readonly filtroRango = signal<(Date | null)[] | null>(null);
  protected readonly filtroTexto = signal('');

  protected readonly sucursales = signal<FilaSucursal[]>([]);
  protected readonly hayFiltros = computed(
    () =>
      this.filtroEstado() !== null ||
      this.filtroTipo() !== null ||
      this.filtroSucursal() !== null ||
      this.filtroRango() !== null ||
      this.filtroTexto().trim() !== '',
  );

  // ---- Lista ----------------------------------------------------------------------------------------------------------
  protected readonly operaciones = signal<OperacionOffline[]>([]);
  protected readonly cargando = signal(true);
  protected readonly errorLectura = signal(false);

  // ---- Estado de la cola ------------------------------------------------------------------------------------------------
  protected readonly enviando = signal(false);
  private readonly ahora = signal(Date.now());
  protected readonly hayRed = computed(() => this.conectividad.estado() === 'en_linea');
  protected readonly segundosParaReintento = computed(() => {
    const proximo = this.cola.proximoIntentoEn();
    if (proximo === null) return null;
    const instante = Date.parse(proximo);
    return Number.isNaN(instante) ? null : Math.max(0, Math.ceil((instante - this.ahora()) / 1000));
  });
  protected readonly textoCola = computed(() =>
    textoEstadoCola(this.cola.estadoCola(), this.cola.pendientes(), this.segundosParaReintento()),
  );
  protected readonly iconoCola = computed(() => iconoEstadoCola(this.cola.estadoCola()));
  protected readonly puedeEnviar = computed(
    () => this.hayRed() && this.cola.pendientes() > 0 && this.cola.estadoCola() !== 'sincronizando' && !this.enviando(),
  );
  protected readonly ayudaEnviar = computed(() => {
    if (!this.hayRed()) return 'Conéctate a Internet para enviar.';
    if (this.cola.pendientes() === 0) return 'No hay nada pendiente de enviar.';
    return null;
  });
  protected readonly resumen = computed(() => [
    { clave: 'pendientes', icono: 'reloj' as const, texto: plural(this.cola.pendientes(), 'pendiente', 'pendientes') },
    { clave: 'en_conflicto', icono: 'advertencia' as const, texto: `${this.cola.enConflicto()} en conflicto` },
    { clave: 'rechazadas', icono: 'cerrar' as const, texto: plural(this.cola.rechazadas(), 'rechazada', 'rechazadas') },
    { clave: 'confirmadas', icono: 'check' as const, texto: plural(this.cola.confirmadas(), 'sincronizada', 'sincronizadas') },
  ]);

  // ---- Detalle ----------------------------------------------------------------------------------------------------------
  protected readonly detalleVisible = signal(false);
  protected readonly detalle = signal<OperacionOffline | null>(null);
  protected readonly intentos = signal<ResultadoSync[]>([]);
  protected readonly errorIntentos = signal(false);
  protected readonly avisoImpresion = signal<string | null>(null);

  private secuencia = 0;
  private reloj: ReturnType<typeof setInterval> | undefined;

  constructor() {
    // Se vuelve a leer cuando cambia un filtro o cuando la cola reporta otros conteos o estado (sin pedir nada a la red).
    effect(() => {
      this.filtroEstado();
      this.filtroTipo();
      this.filtroSucursal();
      this.filtroRango();
      this.filtroTexto();
      this.cola.pendientes();
      this.cola.enConflicto();
      this.cola.rechazadas();
      this.cola.confirmadas();
      this.cola.estadoCola();
      untracked(() => void this.cargar());
    });
  }

  async ngOnInit(): Promise<void> {
    this.reloj = setInterval(() => this.ahora.set(Date.now()), 1000);
    try {
      this.sucursales.set(await this.catalogo.sucursales());
    } catch {
      this.sucursales.set([]);
    }
  }

  ngOnDestroy(): void {
    clearInterval(this.reloj);
  }

  protected reintentarLectura(): void {
    this.cargando.set(true);
    void this.cargar();
  }

  protected limpiarFiltros(): void {
    this.filtroEstado.set(null);
    this.filtroTipo.set(null);
    this.filtroSucursal.set(null);
    this.filtroRango.set(null);
    this.filtroTexto.set('');
  }

  protected async enviarAhora(): Promise<void> {
    if (!this.puedeEnviar()) return;
    this.enviando.set(true);
    try {
      await this.cola.enviarAhora();
    } finally {
      this.enviando.set(false);
    }
    await this.cargar();
  }

  protected nombreSucursal(id: number): string {
    return this.sucursales().find((s) => s.id === id)?.nombre ?? `Sucursal ${id}`;
  }

  protected nombreFaltante(varianteId: number, operacion: OperacionOffline): string {
    const linea = operacion.lineas.find((l) => l.variante_id === varianteId);
    if (!linea) return `Prenda ${varianteId}`;
    const detalle = [linea.talla, linea.color].filter(Boolean).join(' · ');
    return detalle ? `${linea.producto_nombre} (${detalle})` : linea.producto_nombre;
  }

  protected async abrirDetalle(operacion: OperacionOffline): Promise<void> {
    this.avisoImpresion.set(null);
    this.errorIntentos.set(false);
    this.detalle.set(operacion);
    this.intentos.set([]);
    this.detalleVisible.set(true);
    const repositorio = this.sesion.repositorio();
    if (repositorio === null) return;
    try {
      const [fresca, intentos] = await Promise.all([
        repositorio.operacion(operacion.operacion_id),
        repositorio.intentosDe(operacion.operacion_id),
      ]);
      if (this.detalle()?.operacion_id !== operacion.operacion_id) return;
      if (fresca) this.detalle.set(fresca);
      this.intentos.set(intentos);
    } catch {
      this.errorIntentos.set(true);
    }
  }

  /** Abre el comprobante de una venta en otra ventana para imprimirlo. Todo el texto va escapado. */
  protected imprimirComprobante(): void {
    const operacion = this.detalle();
    if (operacion === null || operacion.tipo !== 'venta_contado') return;
    const empresa = this.auth.usuario()?.empresa_nombre ?? 'FashionStore';
    const fecha = new DatePipe('en-US').transform(operacion.fecha_operacion, 'dd/MM/yyyy HH:mm') ?? operacion.fecha_operacion;
    const ventana = window.open('', '_blank', 'width=420,height=640');
    if (!ventana) {
      this.avisoImpresion.set('Tu navegador bloqueó la ventana de impresión. Permite las ventanas emergentes e inténtalo de nuevo.');
      return;
    }
    this.avisoImpresion.set(null);
    ventana.document.write(htmlComprobante(operacion, this.nombreSucursal(operacion.sucursal_id), empresa, fecha));
    ventana.document.close();
    ventana.focus();
    ventana.print();
  }

  private filtroActual(): FiltroOperaciones {
    const rango = this.filtroRango();
    const desde = rango?.[0] ?? null;
    const hasta = rango?.[1] ?? desde;
    return {
      estado: this.filtroEstado(),
      tipo: this.filtroTipo(),
      sucursalId: this.filtroSucursal(),
      desde: desde ? aFechaIso(desde) : null,
      hasta: hasta ? aFechaIso(hasta) : null,
      texto: this.filtroTexto().trim() || null,
    };
  }

  private async cargar(): Promise<void> {
    const miSecuencia = ++this.secuencia;
    try {
      const repositorio = this.sesion.repositorio();
      const filas = repositorio === null ? [] : await repositorio.misOperaciones(this.filtroActual());
      if (miSecuencia !== this.secuencia) return;
      this.operaciones.set(filas);
      this.errorLectura.set(false);
    } catch {
      if (miSecuencia !== this.secuencia) return;
      this.operaciones.set([]);
      this.errorLectura.set(true);
    } finally {
      if (miSecuencia === this.secuencia) this.cargando.set(false);
    }
  }
}

function aFechaIso(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

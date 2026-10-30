import { DatePipe } from '@angular/common';
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DatePickerModule } from 'primeng/datepicker';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { fechaLocalIso } from '../../core/date-utils';
import {
  ACCIONES_AUDITORIA,
  ENTIDADES_AUDITORIA,
  OpcionAuditoria,
  RegistroBitacora,
  etiquetaAccion,
  etiquetaEntidad,
  fechaDeBitacora,
  resumenDeDatos,
} from '../../core/models/auditoria.models';
import { EmpresaPlataforma } from '../../core/models/plataforma.models';
import { IconoComponent } from '../../shared/icono/icono.component';
import { PlataformaService } from '../plataforma/data/plataforma.service';
import { BitacoraService, TAMANIO_PAGINA_BITACORA } from './data/bitacora.service';

/** Días hacia atrás del rango inicial (igual que el backend cuando no llega `desde`). */
export const DIAS_RANGO_INICIAL = 30;

/** Valor del filtro de empresa para "solo lo que no tiene empresa". */
export const SIN_EMPRESA = 'sin';
type FiltroEmpresa = number | typeof SIN_EMPRESA | null;

export interface FilaBitacora {
  registro: RegistroBitacora;
  fecha: Date;
  usuario: string;
  empresa: string;
  accion: string;
  entidad: string;
  resumen: string;
  ip: string;
  /** `datos` formateado como TEXTO para el <pre>. Nunca se inserta como HTML. */
  datosTexto: string;
}

const SIN_DATOS = 'Sin datos adicionales.';

function ordenadas(opciones: readonly OpcionAuditoria[]): OpcionAuditoria[] {
  return [...opciones].sort((a, b) => a.label.localeCompare(b.label, 'es'));
}

/**
 * Bitácora de auditoría (E06 en el backend), de solo lectura. La misma pantalla
 * sirve al administrador de una empresa (ruta `/auditoria`) y al
 * superadministrador (`/plataforma/auditoria`, dato de ruta `plataforma`), que
 * además filtra por empresa y ve la columna Empresa. Lo que se ve y lo que se
 * oculta lo decide el backend: la web no filtra nada.
 */
@Component({
  selector: 'app-bitacora',
  standalone: true,
  imports: [DatePipe, FormsModule, ButtonModule, DatePickerModule, SelectModule, TableModule, IconoComponent],
  templateUrl: './bitacora.component.html',
  styleUrl: './bitacora.component.scss',
})
export class BitacoraComponent implements OnInit {
  private readonly servicio = inject(BitacoraService);
  private readonly plataforma = inject(PlataformaService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  /** Verdadero en la ruta del superadministrador: filtro y columna de empresa. */
  protected readonly esPlataforma = inject(ActivatedRoute).snapshot.data['plataforma'] === true;
  protected readonly tamanioPagina = TAMANIO_PAGINA_BITACORA;
  protected readonly hoy = new Date();

  // ---- Filtros ----
  protected readonly desde = signal<Date | null>(this.diasAtras(DIAS_RANGO_INICIAL));
  protected readonly hasta = signal<Date | null>(new Date());
  protected readonly filtroEntidad = signal<string | null>(null);
  protected readonly filtroAccion = signal<string | null>(null);
  protected readonly filtroUsuario = signal<number | null>(null);
  protected readonly filtroEmpresa = signal<FiltroEmpresa>(null);

  // ---- Datos ----
  protected readonly registros = signal<RegistroBitacora[]>([]);
  protected readonly total = signal(0);
  protected readonly pagina = signal(1);
  protected readonly cargando = signal(false);
  protected readonly error = signal(false);
  protected readonly empresas = signal<EmpresaPlataforma[]>([]);
  protected readonly personal = signal<{ id: number; nombre: string }[]>([]);
  protected readonly expandidas = signal<ReadonlySet<number>>(new Set());

  protected readonly opcionesEntidad = computed(() => [
    { label: 'Todas las entidades', value: null as string | null },
    ...ordenadas(ENTIDADES_AUDITORIA).map((o) => ({ label: o.label, value: o.value as string | null })),
  ]);
  protected readonly opcionesAccion = computed(() => [
    { label: 'Todas las acciones', value: null as string | null },
    ...ordenadas(ACCIONES_AUDITORIA).map((o) => ({ label: o.label, value: o.value as string | null })),
  ]);
  protected readonly opcionesUsuario = computed(() => [
    { label: 'Todos los usuarios', value: null as number | null },
    ...this.personal().map((u) => ({ label: u.nombre, value: u.id as number | null })),
  ]);
  protected readonly opcionesEmpresa = computed(() => [
    { label: 'Todas las empresas', value: null as FiltroEmpresa },
    { label: 'Sin empresa', value: SIN_EMPRESA as FiltroEmpresa },
    ...this.empresas().map((e) => ({ label: e.nombre, value: e.id as FiltroEmpresa })),
  ]);

  private readonly nombresEmpresa = computed(() => new Map(this.empresas().map((e) => [e.id, e.nombre])));

  /** Mensaje de rango inválido, o null si se puede consultar. */
  protected readonly errorRango = computed(() => {
    const desde = this.desde();
    const hasta = this.hasta();
    if (desde === null || hasta === null) return 'Elige la fecha inicial y la final.';
    if (fechaLocalIso(desde) > fechaLocalIso(hasta)) return 'La fecha inicial no puede ser posterior a la final.';
    return null;
  });

  protected readonly filas = computed<FilaBitacora[]>(() =>
    this.registros().map((registro) => ({
      registro,
      fecha: fechaDeBitacora(registro.creado_en),
      usuario: registro.usuario_nombre ?? (registro.usuario_id !== null ? `Usuario #${registro.usuario_id}` : 'Sin usuario identificado'),
      empresa: this.nombreEmpresa(registro.empresa_id),
      accion: etiquetaAccion(registro.accion),
      entidad: etiquetaEntidad(registro.entidad),
      resumen: resumenDeDatos(registro.datos),
      ip: registro.ip ?? '—',
      datosTexto: this.textoDeDatos(registro.datos),
    })),
  );

  protected readonly columnas = computed(() => (this.esPlataforma ? 8 : 7));
  protected readonly totalPaginas = computed(() => Math.max(1, Math.ceil(this.total() / this.tamanioPagina)));

  private peticion?: Subscription;

  constructor() {
    this.destroyRef.onDestroy(() => this.peticion?.unsubscribe());
  }

  ngOnInit(): void {
    if (this.esPlataforma) {
      this.plataforma.listarTodasEmpresas().subscribe({ next: (e) => this.empresas.set(e), error: () => undefined });
    } else if (this.auth.tienePermiso('usuarios.gestionar')) {
      // Sin ese permiso `/usuarios` respondería 403: el filtro simplemente no se ofrece.
      this.servicio.listarPersonal().subscribe({
        next: (usuarios) =>
          this.personal.set(usuarios.map((u) => ({ id: u.id, nombre: `${u.nombre} ${u.apellido}`.trim() }))),
        error: () => undefined,
      });
    }
    this.cargar();
  }

  // ---- Consulta ----

  protected cargar(): void {
    this.peticion?.unsubscribe();
    if (this.errorRango() !== null) {
      this.cargando.set(false);
      return;
    }
    this.cargando.set(true);
    this.error.set(false);

    const base = {
      desde: fechaLocalIso(this.desde()!),
      hasta: fechaLocalIso(this.hasta()!),
      entidad: this.filtroEntidad(),
      accion: this.filtroAccion(),
      pagina: this.pagina(),
      tamanio: this.tamanioPagina,
    };
    const empresa = this.filtroEmpresa();
    const consulta$ = this.esPlataforma
      ? this.servicio.listarPlataforma({
          ...base,
          empresa_id: typeof empresa === 'number' ? empresa : null,
          sin_empresa: empresa === SIN_EMPRESA,
        })
      : this.servicio.listar({ ...base, usuario_id: this.filtroUsuario() });

    this.peticion = consulta$.subscribe({
      next: (pagina) => {
        this.registros.set(pagina.items);
        this.total.set(pagina.total);
        this.expandidas.set(new Set());
        this.cargando.set(false);
      },
      error: () => {
        this.registros.set([]);
        this.total.set(0);
        this.error.set(true);
        this.cargando.set(false);
      },
    });
  }

  private volverALaPrimera(): void {
    this.pagina.set(1);
    this.cargar();
  }

  protected cambiarDesde(fecha: Date | null): void {
    this.desde.set(fecha);
    this.volverALaPrimera();
  }

  protected cambiarHasta(fecha: Date | null): void {
    this.hasta.set(fecha);
    this.volverALaPrimera();
  }

  protected cambiarEntidad(entidad: string | null): void {
    this.filtroEntidad.set(entidad);
    this.volverALaPrimera();
  }

  protected cambiarAccion(accion: string | null): void {
    this.filtroAccion.set(accion);
    this.volverALaPrimera();
  }

  protected cambiarUsuario(id: number | null): void {
    this.filtroUsuario.set(id);
    this.volverALaPrimera();
  }

  protected cambiarEmpresa(valor: FiltroEmpresa): void {
    this.filtroEmpresa.set(valor);
    this.volverALaPrimera();
  }

  protected irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.update((p) => p - 1);
      this.cargar();
    }
  }

  protected irAPaginaSiguiente(): void {
    if (this.pagina() < this.totalPaginas()) {
      this.pagina.update((p) => p + 1);
      this.cargar();
    }
  }

  // ---- Fila expandible ----

  protected estaExpandida(id: number): boolean {
    return this.expandidas().has(id);
  }

  protected alternar(id: number): void {
    this.expandidas.update((actuales) => {
      const nuevas = new Set(actuales);
      if (nuevas.has(id)) nuevas.delete(id);
      else nuevas.add(id);
      return nuevas;
    });
  }

  // ---- Texto ----

  private nombreEmpresa(id: number | null): string {
    if (id === null) return 'Sin empresa';
    return this.nombresEmpresa().get(id) ?? `Empresa #${id}`;
  }

  private textoDeDatos(datos: Record<string, unknown> | null): string {
    if (datos === null || Object.keys(datos).length === 0) return SIN_DATOS;
    return JSON.stringify(datos, null, 2);
  }

  private diasAtras(dias: number): Date {
    const fecha = new Date();
    fecha.setDate(fecha.getDate() - dias);
    return fecha;
  }
}

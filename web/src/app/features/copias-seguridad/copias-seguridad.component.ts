import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { Subscription } from 'rxjs';
import { ConectividadService } from '../../core/conectividad.service';
import { Copia, CopiaTablas } from '../../core/models/copias.models';
import { PlanService } from '../../core/plan.service';
import { descargarArchivo } from '../../core/utils/descargar-archivo';
import { leerErrorBlob } from '../../core/utils/http-blob';
import { formatearEntero } from '../../shared/graficos/formato-reporte';
import { IconoComponent } from '../../shared/icono/icono.component';
import { CopiasSeguridadService } from './data/copias-seguridad.service';
import {
  ClaseErrorCopia,
  ErrorCopia,
  checksumCorto,
  clasificarErrorCopia,
  copiarAlPortapapeles,
  fechaDeUtc,
  formatearTamano,
  limiteBytesDeError,
  nombreLegible,
  textoMotivoFallo,
  vistaEstadoCopia,
} from './vistas-copias';

export const TAMANIO_PAGINA = 20;
export const MENSAJE_SIN_CONEXION_BOTON = 'Necesitas conexión a Internet';
export const NOMBRE_EJEMPLO = 'fashionstore-copia.zip';
/** Cuánto tiempo dice "Copiado" el botón antes de volver a "Copiar". */
export const MS_AVISO_COPIADO = 2_000;

/** Lo que se sabe de la última copia descargada en esta visita (solo en memoria). */
export interface CopiaRecienDescargada {
  nombre: string;
  tamanoBytes: number;
  checksum: string | null;
  copiaId: number | null;
}

type BloqueoCopias = 'plan' | 'suscripcion' | 'rol';
const CLASES_BLOQUEO: ClaseErrorCopia[] = ['plan', 'suscripcion', 'rol'];

/**
 * Copias de seguridad (E22): el administrador descarga una copia de los datos de su empresa. La copia se entrega en la misma
 * respuesta que la crea y no se guarda en el servidor; aquí solo se descarga, se muestra su checksum y se lista el historial.
 * Cada bloque (historial y "Qué incluye") pide lo suyo y explica su propio fallo. Nada se guarda en el navegador.
 */
@Component({
  selector: 'app-copias-seguridad',
  standalone: true,
  imports: [DatePipe, RouterLink, TableModule, IconoComponent],
  templateUrl: './copias-seguridad.component.html',
  styleUrl: './copias-seguridad.component.scss',
})
export class CopiasSeguridadComponent {
  private readonly servicio = inject(CopiasSeguridadService);
  private readonly plan = inject(PlanService);
  private readonly conectividad = inject(ConectividadService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly tamanioPagina = TAMANIO_PAGINA;
  protected readonly textoSinConexion = MENSAJE_SIN_CONEXION_BOTON;
  protected readonly vistaEstado = vistaEstadoCopia;
  protected readonly textoMotivo = textoMotivoFallo;
  protected readonly tamano = formatearTamano;
  protected readonly checksumCorto = checksumCorto;
  protected readonly nombreLegible = nombreLegible;
  protected readonly entero = formatearEntero;
  protected readonly fechaDe = fechaDeUtc;

  // ---- Crear ------------------------------------------------------------------------------------------------------
  protected readonly creando = signal(false);
  protected readonly errorCrear = signal<ErrorCopia | null>(null);
  protected readonly descargada = signal<CopiaRecienDescargada | null>(null);

  // ---- Bloqueos ---------------------------------------------------------------------------------------------------
  /** El servidor dijo que el plan, la suscripción o el rol no permiten las copias (respaldo de lo que el plan ya sabe). */
  private readonly bloqueoServidor = signal<BloqueoCopias | null>(null);
  protected readonly bloqueo = computed<BloqueoCopias | null>(() =>
    !this.plan.incluye('copias_seguridad') ? 'plan' : this.bloqueoServidor(),
  );
  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  /** Falso = no se llama a nada y los controles se ven apagados. */
  protected readonly activo = computed(() => this.bloqueo() === null && !this.sinConexion());
  protected readonly puedeCrear = computed(() => this.activo() && !this.creando());

  // ---- Historial --------------------------------------------------------------------------------------------------
  protected readonly copias = signal<Copia[]>([]);
  protected readonly total = signal(0);
  protected readonly pagina = signal(1);
  protected readonly primero = computed(() => (this.pagina() - 1) * TAMANIO_PAGINA);
  protected readonly cargandoHistorial = signal(false);
  protected readonly errorHistorial = signal<string | null>(null);
  /** Falso hasta la primera respuesta: así "Aún no hay copias" no parpadea antes de saber. */
  protected readonly historialListo = signal(false);

  // ---- Qué incluye ------------------------------------------------------------------------------------------------
  protected readonly tablas = signal<CopiaTablas | null>(null);
  protected readonly cargandoTablas = signal(false);
  protected readonly errorTablas = signal<string | null>(null);
  protected readonly panelAbierto = signal(false);
  protected readonly columnasExcluidas = computed(() =>
    Object.entries(this.tablas()?.columnas_excluidas ?? {}).map(([tabla, columnas]) => ({ tabla, columnas })),
  );

  // ---- Verificar y copiar -----------------------------------------------------------------------------------------
  protected readonly verificacionAbierta = signal(false);
  protected readonly nombreParaVerificar = computed(() => this.descargada()?.nombre ?? NOMBRE_EJEMPLO);
  protected readonly comandoPowerShell = computed(() => `Get-FileHash .\\${this.nombreParaVerificar()} -Algorithm SHA256`);
  protected readonly comandoLinux = computed(() => `sha256sum ${this.nombreParaVerificar()}`);
  /** Qué botón "Copiar" dice "Copiado" ahora (`resultado` o `fila-<id>`). */
  protected readonly copiado = signal<string | null>(null);
  protected readonly errorCopiar = signal(false);

  private suscripcionCrear: Subscription | null = null;
  private suscripcionHistorial: Subscription | null = null;
  private suscripcionTablas: Subscription | null = null;
  private temporizadorCopiado: ReturnType<typeof setTimeout> | null = null;
  private destruido = false;

  constructor() {
    this.plan.cargar();
    this.destroyRef.onDestroy(() => {
      this.destruido = true;
      this.suscripcionCrear?.unsubscribe();
      this.suscripcionHistorial?.unsubscribe();
      this.suscripcionTablas?.unsubscribe();
      if (this.temporizadorCopiado !== null) clearTimeout(this.temporizadorCopiado);
    });
    // Al abrir (y al volver la conexión) se leen el historial y lo que incluye la copia; sin plan, rol o conexión no se
    // llama a nada.
    effect(() => {
      const activo = this.activo();
      untracked(() => (activo ? this.cargarTodo() : this.detenerLecturas()));
    });
  }

  protected cargarTodo(): void {
    this.cargarHistorial();
    this.cargarTablas();
  }

  private detenerLecturas(): void {
    this.suscripcionHistorial?.unsubscribe();
    this.suscripcionTablas?.unsubscribe();
    this.cargandoHistorial.set(false);
    this.cargandoTablas.set(false);
  }

  // ---- Crear y descargar -------------------------------------------------------------------------------------------

  protected crear(): void {
    if (!this.puedeCrear()) return;
    this.creando.set(true);
    this.errorCrear.set(null);
    this.descargada.set(null);
    this.suscripcionCrear?.unsubscribe();
    this.suscripcionCrear = this.servicio.crear().subscribe({
      next: (copia) => {
        descargarArchivo({ blob: copia.blob, nombre: copia.nombre });
        this.descargada.set({
          nombre: copia.nombre,
          tamanoBytes: copia.blob.size,
          checksum: copia.checksum,
          copiaId: copia.copiaId,
        });
        this.creando.set(false);
        // La copia nueva aparece arriba del historial.
        this.pagina.set(1);
        this.cargarHistorial();
      },
      error: (error: unknown) => void this.alFallarCrear(error),
    });
  }

  private async alFallarCrear(error: unknown): Promise<void> {
    const clasificado = await this.clasificar(error);
    if (this.destruido) return;
    this.creando.set(false);
    if (this.aplicarBloqueo(clasificado)) return;
    this.errorCrear.set(clasificado);
  }

  /** Lee el error (que en la descarga llega como Blob) y lo clasifica; pasa el límite del 413 y el estado de la suscripción. */
  private async clasificar(error: unknown): Promise<ErrorCopia> {
    const leido = await leerErrorBlob(error);
    const limite = leido.status === 413 ? await limiteBytesDeError(error) : null;
    return clasificarErrorCopia(leido, limite, leido.estado);
  }

  /** Un 403 apaga la pantalla entera; devuelve verdadero si lo aplicó. */
  private aplicarBloqueo(error: ErrorCopia): boolean {
    if (!CLASES_BLOQUEO.includes(error.clase)) return false;
    if (error.clase === 'suscripcion') this.plan.marcarBloqueada(error.estadoSuscripcion);
    this.bloqueoServidor.set(error.clase as BloqueoCopias);
    return true;
  }

  // ---- Historial ----------------------------------------------------------------------------------------------------

  protected cargarHistorial(): void {
    this.suscripcionHistorial?.unsubscribe();
    this.cargandoHistorial.set(true);
    this.errorHistorial.set(null);
    this.suscripcionHistorial = this.servicio.listar(this.pagina(), TAMANIO_PAGINA).subscribe({
      next: (respuesta) => {
        this.copias.set(respuesta.items);
        this.total.set(respuesta.total);
        this.cargandoHistorial.set(false);
        this.historialListo.set(true);
      },
      error: (error: unknown) => void this.alFallarLectura(error, this.errorHistorial, this.cargandoHistorial),
    });
  }

  protected alPaginar(evento: TableLazyLoadEvent): void {
    const filas = evento.rows ?? TAMANIO_PAGINA;
    const pagina = Math.floor((evento.first ?? 0) / filas) + 1;
    if (pagina === this.pagina()) return;
    this.pagina.set(pagina);
    this.cargarHistorial();
  }

  // ---- Qué incluye --------------------------------------------------------------------------------------------------

  protected cargarTablas(): void {
    this.suscripcionTablas?.unsubscribe();
    this.cargandoTablas.set(true);
    this.errorTablas.set(null);
    this.suscripcionTablas = this.servicio.tablas().subscribe({
      next: (respuesta) => {
        this.tablas.set(respuesta);
        this.cargandoTablas.set(false);
      },
      error: (error: unknown) => void this.alFallarLectura(error, this.errorTablas, this.cargandoTablas),
    });
  }

  protected alternarPanel(): void {
    this.panelAbierto.update((abierto) => !abierto);
  }

  protected alternarVerificacion(): void {
    this.verificacionAbierta.update((abierta) => !abierta);
  }

  /** Un fallo de lectura se explica en su bloque; solo un 403 apaga toda la pantalla. */
  private async alFallarLectura(
    error: unknown,
    destino: { set(valor: string | null): void },
    cargando: { set(valor: boolean): void },
  ): Promise<void> {
    const clasificado = await this.clasificar(error);
    if (this.destruido) return;
    cargando.set(false);
    if (this.aplicarBloqueo(clasificado)) return;
    destino.set(clasificado.mensaje);
  }

  // ---- Copiar ---------------------------------------------------------------------------------------------------------

  protected async copiar(texto: string | null, clave: string): Promise<void> {
    if (!texto) return;
    const copiado = await copiarAlPortapapeles(texto);
    if (this.destruido) return;
    this.errorCopiar.set(!copiado);
    this.copiado.set(copiado ? clave : null);
    if (this.temporizadorCopiado !== null) clearTimeout(this.temporizadorCopiado);
    if (copiado) {
      this.temporizadorCopiado = setTimeout(() => {
        this.copiado.set(null);
        this.temporizadorCopiado = null;
      }, MS_AVISO_COPIADO);
    }
  }

  /** Nombre de la persona que pidió la copia, o un texto neutro si ya no hay nombre. */
  protected solicitante(copia: Copia): string {
    return copia.usuario_nombre?.trim() || 'Usuario sin nombre';
  }
}

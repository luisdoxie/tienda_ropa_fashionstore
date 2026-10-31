import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnDestroy, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { InputTextModule } from 'primeng/inputtext';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../../core/conectividad.service';
import { codigoFuncional } from '../../core/errores-funcionales';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import { mensajeFuncional } from '../../core/mensajes-error-funcional';
import { Categoria } from '../../core/models/catalogo.models';
import { Empleado, Sucursal } from '../../core/models/organizacion.models';
import {
  EntradaEjecutarReporte,
  FormatoExportacion,
  InterpreteUsado,
  OrigenSolicitud,
  ReporteCatalogo,
  ReporteEjecutado,
  ReporteGenerativoRespuesta,
  SolicitudReporte,
  SolicitudResuelta,
} from '../../core/models/reportes-ia.models';
import { PlanService } from '../../core/plan.service';
import { descargarArchivo } from '../../core/utils/descargar-archivo';
import { ErrorLeido, leerErrorBlob } from '../../core/utils/http-blob';
import { VozService } from '../../core/voz.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ReportesIaService } from './data/reportes-ia.service';
import { solicitudDesdeResuelta } from './data/solicitud-reporte';
import { FiltrosReporteComponent } from './filtros-reporte.component';
import { ResultadoReporteComponent } from './resultado-reporte.component';
import { MAX_TEXTO_PEDIDO, camposDeCatalogo, chipsDeSolicitud, ejemplosDelCatalogo } from './reportes-ia.util';

/** Cuánto se bloquea "Generar" tras un 429 (el límite del servidor es por minuto, esto solo evita insistir). */
export const ESPERA_LIMITE_MS = 10_000;

type Ocupado = 'generar' | 'actualizar' | null;
type ModoEjecucion = 'generar' | 'actualizar' | 'restablecer';

/** Lo que se muestra cuando una llamada falla: no es lo mismo una falla real que un límite o un permiso. */
interface Problema {
  tipo: 'red' | 'servidor' | 'limite' | 'permiso';
  mensaje: string;
  reintentar: boolean;
}

/** La última respuesta `ok`: de aquí salen "entendí esto", los filtros editables, el resultado y la exportación. */
interface ResultadoOk {
  solicitud: SolicitudResuelta;
  reporte: ReporteEjecutado;
  narrativa: string | null;
  avisos: string[];
}

const MENSAJE_RED = 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.';
const MENSAJE_SERVIDOR = 'Algo salió mal al preparar el reporte. Inténtalo de nuevo.';
const MENSAJE_LIMITE = 'Hiciste demasiadas consultas seguidas. Espera unos segundos e inténtalo de nuevo.';
const MENSAJE_PERMISO =
  'Tu usuario no puede ver este reporte. Los de análisis avanzado son para quien consulta todas las sucursales.';
const MENSAJE_LIMITE_EXPORTAR = 'Pediste demasiadas exportaciones seguidas. Espera un momento e inténtalo de nuevo.';
const MENSAJE_SIN_RESPUESTA = 'No pude preparar ese reporte. Prueba con otro pedido.';

const ETIQUETA_INTERPRETE: Record<InterpreteUsado, string> = {
  groq: 'Interpretado con IA',
  reglas: 'Interpretado con reglas: la IA no respondió',
};

const SIN_TOAST = () => ({ context: new HttpContext().set(SIN_TOAST_ERROR, true) });

/** El texto que mandó el servidor en un error (`mensaje` o un `detail` legible), o null. */
function mensajeDelCuerpo(error: HttpErrorResponse): string | null {
  const cuerpo = error.error;
  if (cuerpo === null || typeof cuerpo !== 'object') return null;
  if (typeof cuerpo.mensaje === 'string' && cuerpo.mensaje.trim() !== '') return cuerpo.mensaje;
  if (typeof cuerpo.detail === 'string' && /\s/.test(cuerpo.detail)) return cuerpo.detail;
  return null;
}

/**
 * Reportes con IA (CU-23, E17a): se pide un reporte escribiendo o dictando, el servidor lo interpreta y lo ejecuta, y aquí
 * se muestra "entendí esto", los filtros editables, el resultado en tabla o gráfico y la exportación a Excel o PDF.
 * El web nunca arma consultas: solo envía una frase o una solicitud y muestra lo que devuelve el servidor. Nada se guarda
 * en el navegador.
 */
@Component({
  selector: 'app-reportes-ia',
  standalone: true,
  imports: [FormsModule, RouterLink, InputTextModule, IconoComponent, FiltrosReporteComponent, ResultadoReporteComponent],
  templateUrl: './reportes-ia.component.html',
  styleUrl: './reportes-ia.component.scss',
})
export class ReportesIaComponent implements OnInit, OnDestroy {
  private readonly servicio = inject(ReportesIaService);
  private readonly voz = inject(VozService);
  private readonly plan = inject(PlanService);
  private readonly conectividad = inject(ConectividadService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly maxTexto = MAX_TEXTO_PEDIDO;
  protected readonly vozDisponible = this.voz.disponible;
  protected readonly etiquetaInterprete = ETIQUETA_INTERPRETE;

  // ---- Plan y conexión ----------------------------------------------------------------------------------------------
  /** El servidor respondió 403 `plan_no_incluye_funcionalidad` (quien no es administrador no conoce su plan). */
  private readonly planNegado = signal(false);
  protected readonly sinPlan = computed(() => this.planNegado() || !this.plan.incluye('reportes_ia'));
  protected readonly sinConexion = computed(() => !this.conectividad.enLinea());
  protected readonly habilitado = computed(() => !this.sinPlan() && !this.sinConexion());

  // ---- Pedido -------------------------------------------------------------------------------------------------------
  protected readonly texto = signal('');
  protected readonly escuchando = signal(false);
  protected readonly errorVoz = signal<string | null>(null);

  // ---- Catálogo y listas de apoyo -----------------------------------------------------------------------------------
  protected readonly catalogo = signal<ReporteCatalogo[]>([]);
  protected readonly atajos = computed(() => ejemplosDelCatalogo(this.catalogo()));
  protected readonly sucursales = signal<string[] | null>(null);
  protected readonly categorias = signal<string[] | null>(null);
  protected readonly sucursalFija = signal(false);
  private datosIniciados = false;

  // ---- Estado de la consulta ----------------------------------------------------------------------------------------
  protected readonly ocupado = signal<Ocupado>(null);
  protected readonly bloqueoLimite = signal(false);
  protected readonly problema = signal<Problema | null>(null);
  /** Respuesta con estado distinto de `ok`: incompleta, ambigua, inválida, no soportada o no disponible. */
  protected readonly respuestaNegocio = signal<ReporteGenerativoRespuesta | null>(null);
  protected readonly ultimaOk = signal<ResultadoOk | null>(null);
  /** El "entendí esto" de la primera respuesta del pedido (a lo que vuelve Restablecer). */
  protected readonly inicial = signal<SolicitudResuelta | null>(null);
  protected readonly interprete = signal<InterpreteUsado | null>(null);

  protected readonly tipoActual = computed(() => {
    const ok = this.ultimaOk();
    return ok === null ? null : (this.catalogo().find((c) => c.codigo === ok.solicitud.tipo_reporte) ?? null);
  });
  protected readonly tituloTipo = computed(() => {
    const ok = this.ultimaOk();
    return ok === null ? '' : (this.tipoActual()?.titulo ?? ok.solicitud.tipo_reporte);
  });
  protected readonly chips = computed(() => {
    const ok = this.ultimaOk();
    return ok === null ? [] : chipsDeSolicitud(ok.solicitud);
  });
  /** Los filtros editables del reporte actual: null si el catálogo no lo trae. */
  protected readonly filtrosDelTipo = computed(() => this.tipoActual()?.filtros ?? null);
  protected readonly hayFiltrosEditables = computed(() => {
    const filtros = this.filtrosDelTipo();
    return filtros !== null && camposDeCatalogo(filtros).length > 0;
  });

  protected readonly puedeLanzar = computed(
    () => this.habilitado() && this.ocupado() === null && !this.bloqueoLimite() && !this.escuchando(),
  );
  protected readonly generarDeshabilitado = computed(() => !this.puedeLanzar() || this.texto().trim() === '');

  // ---- Exportación --------------------------------------------------------------------------------------------------
  protected readonly exportando = signal<FormatoExportacion | null>(null);
  protected readonly errorExportacion = signal<ErrorLeido | null>(null);

  private secuencia = 0;
  private reintento: (() => void) | null = null;
  private temporizadorLimite: ReturnType<typeof setTimeout> | null = null;
  private destruido = false;

  constructor() {
    // El catálogo y las listas se piden cuando el plan y la conexión lo permiten (no antes, para no llamar a /reportes-ia/*
    // en un plan que no lo incluye).
    effect(() => {
      const listo = this.habilitado() && !this.plan.cargando();
      if (listo) untracked(() => this.cargarDatosDeApoyo());
    });
  }

  ngOnInit(): void {
    // Quien no es administrador no puede leer su plan: el 403 del servidor lo avisa.
    this.plan.cargar();
  }

  ngOnDestroy(): void {
    this.destruido = true;
    if (this.temporizadorLimite !== null) clearTimeout(this.temporizadorLimite);
  }

  // ---- Datos de apoyo -----------------------------------------------------------------------------------------------

  private cargarDatosDeApoyo(): void {
    if (this.datosIniciados) return;
    this.datosIniciados = true;

    this.servicio
      .catalogo()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (catalogo) => this.catalogo.set(catalogo),
        error: (error: HttpErrorResponse) => {
          if (this.esPlanNegado(error)) this.planNegado.set(true);
          else this.datosIniciados = false; // se vuelve a intentar al recuperar la conexión
        },
      });

    this.http
      .get<Sucursal[]>(`${environment.apiUrl}/sucursales?pagina=1&tamanio=100`, SIN_TOAST())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => this.sucursales.set(lista.filter((s) => s.activo !== false).map((s) => s.nombre)),
        error: () => this.sucursales.set(null),
      });
    this.http
      .get<Categoria[]>(`${environment.apiUrl}/categorias?pagina=1&tamanio=100`, SIN_TOAST())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => this.categorias.set(lista.filter((c) => c.activo !== false).map((c) => c.nombre)),
        error: () => this.categorias.set(null),
      });
    // Quien tiene sucursal asignada ve solo esa: el servidor la fuerza y trae un aviso.
    this.http
      .get<Empleado>(`${environment.apiUrl}/empleados/yo`, SIN_TOAST())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (empleado) => this.sucursalFija.set(empleado.sucursal_id !== null),
        error: () => this.sucursalFija.set(false),
      });
  }

  // ---- Pedir --------------------------------------------------------------------------------------------------------

  protected dictar(): void {
    if (this.escuchando() || !this.puedeLanzar()) return;
    this.errorVoz.set(null);
    this.escuchando.set(true);
    let hayTexto = false;
    this.voz
      .escuchar()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (dictado) => {
          hayTexto = true;
          this.escuchando.set(false);
          this.texto.set(dictado.slice(0, MAX_TEXTO_PEDIDO));
          this.generar('voz'); // un comando de voz se envía solo; el texto queda visible
        },
        error: (error: Error) => {
          this.escuchando.set(false);
          this.errorVoz.set(error.message);
        },
        complete: () => {
          this.escuchando.set(false);
          if (!hayTexto) this.errorVoz.set('No se escuchó nada. Inténtalo de nuevo.');
        },
      });
  }

  protected generar(origen: OrigenSolicitud = 'texto'): void {
    const pedido = this.texto().trim();
    if (pedido === '' || !this.puedeLanzar()) return;
    this.lanzar({ texto: pedido, origen }, 'generar');
  }

  /** Un clic en un ejemplo o en una sugerencia llena el campo y genera. */
  protected usarEjemplo(ejemplo: string): void {
    if (!this.puedeLanzar()) return;
    this.texto.set(ejemplo.slice(0, MAX_TEXTO_PEDIDO));
    this.generar('texto');
  }

  protected actualizar(solicitud: SolicitudReporte): void {
    if (!this.puedeLanzar()) return;
    this.lanzar({ solicitud }, 'actualizar');
  }

  protected restablecer(): void {
    const inicial = this.inicial();
    if (inicial === null || !this.puedeLanzar()) return;
    this.lanzar({ solicitud: solicitudDesdeResuelta(inicial) }, 'restablecer');
  }

  protected reintentar(): void {
    this.reintento?.();
  }

  // ---- Ejecutar -----------------------------------------------------------------------------------------------------

  private lanzar(entrada: EntradaEjecutarReporte, modo: ModoEjecucion): void {
    const mia = ++this.secuencia;
    this.reintento = () => {
      if (this.puedeLanzar()) this.lanzar(entrada, modo);
    };
    this.ocupado.set(modo === 'generar' ? 'generar' : 'actualizar');
    this.problema.set(null);
    this.respuestaNegocio.set(null);
    this.errorExportacion.set(null);

    this.servicio
      .ejecutar(entrada)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (respuesta) => {
          if (mia !== this.secuencia) return;
          this.ocupado.set(null);
          this.recibir(respuesta, modo);
        },
        error: (error: HttpErrorResponse) => {
          if (mia !== this.secuencia) return;
          this.ocupado.set(null);
          this.fallar(error);
        },
      });
  }

  private recibir(respuesta: ReporteGenerativoRespuesta, modo: ModoEjecucion): void {
    if (modo === 'generar' || respuesta.interprete !== null) this.interprete.set(respuesta.interprete);

    if (respuesta.estado === 'ok' && respuesta.solicitud !== null && respuesta.reporte !== null) {
      this.ultimaOk.set({
        solicitud: respuesta.solicitud,
        reporte: respuesta.reporte,
        narrativa: respuesta.narrativa?.trim() ? respuesta.narrativa : null,
        avisos: respuesta.avisos,
      });
      if (modo === 'generar') this.inicial.set(respuesta.solicitud);
      return;
    }

    // Una actualización que no se pudo (p. ej. fechas inválidas) deja a la vista el reporte anterior para corregirla.
    this.respuestaNegocio.set({ ...respuesta, mensaje: respuesta.mensaje?.trim() ? respuesta.mensaje : MENSAJE_SIN_RESPUESTA });
    if (modo === 'generar') {
      this.ultimaOk.set(null);
      this.inicial.set(null);
    }
  }

  private esPlanNegado(error: HttpErrorResponse): boolean {
    return error.status === 403 && codigoFuncional(error) === 'plan_no_incluye_funcionalidad';
  }

  private fallar(error: HttpErrorResponse): void {
    if (this.esPlanNegado(error)) {
      this.planNegado.set(true);
      return;
    }
    if (error.status === 429) {
      this.bloquearGenerar();
      this.problema.set({ tipo: 'limite', mensaje: MENSAJE_LIMITE, reintentar: false });
      return;
    }
    if (error.status === 403) {
      const funcional = mensajeFuncional(codigoFuncional(error), error.error, null);
      this.problema.set({
        tipo: 'permiso',
        mensaje: funcional?.detalle ?? mensajeDelCuerpo(error) ?? MENSAJE_PERMISO,
        reintentar: false,
      });
      return;
    }
    if (error.status === 0) {
      this.problema.set({ tipo: 'red', mensaje: MENSAJE_RED, reintentar: true });
      return;
    }
    this.problema.set({ tipo: 'servidor', mensaje: MENSAJE_SERVIDOR, reintentar: true });
  }

  private bloquearGenerar(): void {
    this.bloqueoLimite.set(true);
    if (this.temporizadorLimite !== null) clearTimeout(this.temporizadorLimite);
    this.temporizadorLimite = setTimeout(() => {
      this.temporizadorLimite = null;
      if (!this.destruido) this.bloqueoLimite.set(false);
    }, ESPERA_LIMITE_MS);
  }

  // ---- Exportar -----------------------------------------------------------------------------------------------------

  /** Exporta lo que se ve: la solicitud de la ÚLTIMA respuesta `ok` (con los filtros actuales), sin llamar a la IA. */
  protected exportar(formato: FormatoExportacion): void {
    const ok = this.ultimaOk();
    if (ok === null || this.exportando() !== null || !this.habilitado()) return;
    this.errorExportacion.set(null);
    this.exportando.set(formato);
    this.servicio
      .exportar({ formato, resuelta: ok.solicitud, incluir_grafico: true })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (archivo) => {
          this.exportando.set(null);
          descargarArchivo(archivo);
        },
        error: (error: unknown) => {
          void leerErrorBlob(error).then((leido) => {
            if (this.destruido) return;
            this.exportando.set(null);
            if (leido.status === 403 && leido.codigo === 'plan_no_incluye_funcionalidad') {
              this.planNegado.set(true);
              return;
            }
            this.errorExportacion.set(leido.status === 429 ? { ...leido, mensaje: MENSAJE_LIMITE_EXPORTAR } : leido);
          });
        },
      });
  }
}

import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, Injectable, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom, timeout } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../conectividad.service';
import { codigoFuncional } from '../errores-funcionales';
import { SIN_TOAST_ERROR } from '../http-contexts';
import { PlanService } from '../plan.service';
import {
  BACKOFF_BASE_MS,
  BACKOFF_TOPE_MS,
  HUERFANA_ENVIADA_MS,
  INTENTOS_AUTOMATICOS_MAX,
  INTERVALO_COLA_MS,
  INTERVALO_CONSULTA_CONFLICTOS_MS,
  META_REGLAS,
  TAM_LOTE,
  TIMEOUT_LOTE_MS,
} from './offline.config';
import type { AlcanceOffline, OperacionOffline, ResultadoServidor } from './offline.models';
import type { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';

/** En qué está la cola de envío de operaciones hechas sin conexión. */
export type EstadoCola =
  | 'inactiva'
  | 'sincronizando'
  | 'esperando_reintento'
  | 'pausada_sesion'
  | 'pausada_plan'
  | 'sin_conexion'
  | 'detenida_por_fallos';

/** Versión del contrato de `POST /sincronizacion/lote`. */
export const VERSION_CONTRATO_LOTE = '1.0';
/** Nombre del candado entre pestañas (Web Locks). */
export const NOMBRE_CANDADO_SYNC = 'fs-sync';
export const MOTIVO_DETENIDA = 'No se pudo enviar. Reintenta manualmente.';
export const MENSAJE_ERROR_FORMATO = 'No se pudo enviar por un error de formato. Avisa a soporte.';

const MAX_RETRY_AFTER_MS = 3_600_000;
/** Cuántas operaciones en conflicto se consultan por ciclo (las demás, en el siguiente). */
const MAX_CONSULTAS_CONFLICTO = 20;
const CODIGOS_PAUSA_PLAN = ['plan_no_incluye_funcionalidad', 'suscripcion_no_activa'];

interface ResultadoLote extends ResultadoServidor {
  operacion_id: string;
}

interface RespuestaLote {
  version_contrato?: string;
  procesado_en?: string;
  resumen?: unknown;
  resultados: ResultadoLote[];
}

interface RespuestaConsultaOperacion {
  operacion_id: string;
  estado: string;
  motivo?: string | null;
  mensaje?: string | null;
  recurso?: ResultadoServidor['recurso'];
  cambio?: string | null;
  avisos?: ResultadoServidor['avisos'];
  faltantes?: ResultadoServidor['faltantes'];
  resolucion?: { accion?: string; motivo?: string | null } | null;
}

interface OpcionesProcesar {
  /** Botón "Enviar ahora": ignora la espera de los reintentos y levanta una pausa o una detención. */
  manual?: boolean;
  /** Volvió la red: levanta una pausa o una detención, pero respeta la espera de cada operación. */
  reanudar?: boolean;
}

/** Cuánto esperar tras el fallo número `n` (1 = el primero): 5 s, 10 s, 20 s... con tope y ±20 % de variación. */
export function esperaBackoffMs(n: number, aleatorio: () => number = Math.random): number {
  const exponente = Math.min(Math.max(n, 1) - 1, 20);
  const base = Math.min(BACKOFF_BASE_MS * 2 ** exponente, BACKOFF_TOPE_MS);
  const factor = 0.8 + 0.4 * aleatorio();
  return Math.min(Math.round(base * factor), BACKOFF_TOPE_MS);
}

/** `Retry-After` (segundos o fecha HTTP) en milisegundos, entre 1 s y 1 h; null si no viene o no se entiende. */
export function leerRetryAfterMs(valor: string | null | undefined, ahora: number = Date.now()): number | null {
  if (!valor) return null;
  const segundos = Number(valor);
  let ms: number;
  if (Number.isFinite(segundos)) {
    ms = segundos * 1000;
  } else {
    const fecha = Date.parse(valor);
    if (Number.isNaN(fecha)) return null;
    ms = fecha - ahora;
  }
  return Math.min(Math.max(ms, 1000), MAX_RETRY_AFTER_MS);
}

function claveAlcance(alcance: AlcanceOffline | null): string | null {
  return alcance === null ? null : `${alcance.empresaId}:${alcance.usuarioId}`;
}

const ahoraIso = (): string => new Date().toISOString();

/** La operación local con la forma del contrato v1, o null si le falta algo que el servidor exige (no se puede enviar). */
function aOperacionEntrada(op: OperacionOffline): Record<string, unknown> | null {
  let payload: Record<string, unknown>;
  if (op.tipo === 'venta_contado') {
    if (op.pago === null || op.pago === undefined || op.lineas.length === 0) return null;
    payload = {
      cliente_id: op.cliente_id,
      lineas: op.lineas.map((l) => ({
        variante_id: l.variante_id,
        cantidad: l.cantidad,
        precio_unitario: l.precio_unitario,
        descuento_unitario: l.descuento_unitario,
      })),
      total: op.total,
      pago: { metodo: op.pago.metodo, monto_recibido: op.pago.monto_recibido },
    };
  } else if (op.tipo === 'reserva') {
    if (op.reserva === null || op.reserva === undefined || op.cliente_id === null || op.lineas.length === 0) return null;
    payload = {
      cliente_id: op.cliente_id,
      fecha_visita: op.reserva.fecha_visita,
      hora_visita_desde: op.reserva.hora_visita_desde,
      hora_visita_hasta: op.reserva.hora_visita_hasta,
      observacion: op.reserva.observacion,
      lineas: op.lineas.map((l) => ({ variante_id: l.variante_id, cantidad: l.cantidad })),
    };
  } else {
    return null;
  }
  return {
    operacion_id: op.operacion_id,
    tipo: op.tipo,
    sucursal_id: op.sucursal_id,
    fecha_operacion: op.fecha_operacion,
    payload,
  };
}

/** Posiciones (dentro del lote) de las operaciones que el 422 señala, o null si no se puede saber cuáles son. */
function posicionesInvalidas(error: HttpErrorResponse, total: number): number[] | null {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detalle) || detalle.length === 0) return null;
  const posiciones = new Set<number>();
  for (const d of detalle) {
    const loc = (d as { loc?: unknown } | null)?.loc;
    if (!Array.isArray(loc)) return null;
    const i = loc.indexOf('operaciones');
    const posicion = i >= 0 ? loc[i + 1] : undefined;
    if (typeof posicion !== 'number' || !Number.isInteger(posicion) || posicion < 0 || posicion >= total) return null;
    posiciones.add(posicion);
  }
  return [...posiciones];
}

/**
 * Envía al servidor las operaciones hechas sin conexión (E14b, plan 4.8).
 *
 * Reglas que no se rompen:
 *  - NUNCA se borra ni se descarta una operación por intentar enviarla: solo cambia de estado. Cualquier fallo la deja
 *    en `registrada` (con su espera) o `bloqueada`, y el reenvío usa el mismo `operacion_id` (idempotencia del servidor).
 *  - Solo se envían las operaciones de MI usuario y de la empresa de la sesión (el repositorio lo garantiza).
 *  - Un solo ciclo a la vez (candado `fs-sync` entre pestañas y una promesa compartida dentro de la pestaña).
 *
 * Disparadores: volver la red, iniciar con sesión, volver a la pestaña con pendientes, un temporizador de 60 s,
 * registrar una operación nueva y el botón "Enviar ahora".
 */
@Injectable({ providedIn: 'root' })
export class ColaSincronizacionService {
  private readonly http = inject(HttpClient);
  private readonly sesion = inject(SesionOfflineService);
  private readonly conectividad = inject(ConectividadService);
  private readonly plan = inject(PlanService);

  readonly estadoCola = signal<EstadoCola>('inactiva');
  /** Operaciones mías sin enviar o enviándose (registrada + enviada). */
  readonly pendientes = signal(0);
  readonly enConflicto = signal(0);
  readonly rechazadas = signal(0);
  readonly confirmadas = signal(0);
  /** Cuándo (ISO) se reintentará sola; null si no hay un reintento programado. */
  readonly proximoIntentoEn = signal<string | null>(null);
  /** Texto para el usuario cuando la cola está pausada o detenida (null si no). */
  readonly motivoPausa = signal<string | null>(null);
  /** Operaciones sin enviar de OTROS usuarios de este equipo: no se envían desde esta sesión. */
  readonly pendientesDeOtros = signal(0);

  private cicloEnCurso: Promise<void> | null = null;
  private nuevaDuranteCiclo = false;
  private fallosSeguidos = 0;
  private temporizadorReintento: ReturnType<typeof setTimeout> | null = null;
  /** `undefined` = todavía no se observó la sesión. */
  private claveActual: string | null | undefined = undefined;
  /** El usuario cuya sesión venció: solo él reanuda la cola al volver a iniciar sesión (4.10). */
  private clavePausadaPorSesion: string | null = null;
  /** La pausa por plan salió de `PlanService` (no de un 403 del servidor): se levanta sola al cambiar el plan. */
  private pausaPlanLocal = false;
  private ultimaConsultaConflictos = 0;

  constructor() {
    const destroyRef = inject(DestroyRef);

    this.conectividad.volvioConexion$?.pipe(takeUntilDestroyed(destroyRef)).subscribe(() => {
      this.fallosSeguidos = 0;
      void this.procesar({ reanudar: true });
    });

    // Cambia la sesión (iniciar, cerrar, otro usuario): arranca o se reinicia la cola de esa persona.
    effect(() => {
      const alcance = this.sesion.alcance();
      untracked(() => this.alCambiarAlcance(alcance));
    });

    if (typeof setInterval === 'function') {
      const intervalo = setInterval(() => {
        if (this.conectividad.enLinea()) void this.procesar();
      }, INTERVALO_COLA_MS);
      destroyRef.onDestroy(() => clearInterval(intervalo));
    }

    if (typeof document !== 'undefined') {
      const alVolverALaPestana = () => {
        if (document.visibilityState === 'visible' && this.pendientes() > 0) void this.procesar();
      };
      document.addEventListener('visibilitychange', alVolverALaPestana);
      destroyRef.onDestroy(() => document.removeEventListener('visibilitychange', alVolverALaPestana));
    }

    destroyRef.onDestroy(() => this.cancelarReintento());
  }

  // ---- Interfaz pública ----------------------------------------------------------------------------------------------------

  /** Vuelve a contar los estados desde la base local (se llama después de registrar o de cambiar una operación). Nunca lanza. */
  async refrescarConteos(): Promise<void> {
    const repo = this.sesion.repositorio();
    if (repo === null) return;
    const clave = claveAlcance(this.sesion.alcance());
    try {
      const [conteo, deOtros] = await Promise.all([repo.contarPorEstado(), repo.pendientesDeOtrosUsuarios()]);
      // Si mientras se contaba cambió la sesión, estos números ya no son de quien mira.
      if (clave !== claveAlcance(this.sesion.alcance())) return;
      this.pendientes.set(conteo.registrada + conteo.enviada);
      this.enConflicto.set(conteo.en_conflicto);
      this.rechazadas.set(conteo.rechazada);
      this.confirmadas.set(conteo.confirmada);
      this.pendientesDeOtros.set(deOtros);
    } catch (error) {
      console.warn('No se pudieron contar las operaciones locales.', error);
    }
  }

  /** Avisa que se registró una operación nueva: si hay red y todo está en orden, la cola intenta enviarla enseguida. */
  notificarNuevaOperacion(): void {
    void this.refrescarConteos();
    if (this.cicloEnCurso !== null) {
      // La operación se guardó después de que el ciclo leyó su lista: al terminar, el ciclo vuelve a mirar.
      this.nuevaDuranteCiclo = true;
      return;
    }
    // Con un reintento ya programado (el servidor falló hace poco) no se martilla: la nueva sale con el siguiente intento.
    if (this.estadoCola() === 'esperando_reintento') return;
    void this.procesar();
  }

  /** Envía ahora, ignorando la espera de los reintentos (botón "Enviar ahora"). Nunca lanza. */
  async enviarAhora(): Promise<void> {
    await this.procesar({ manual: true });
  }

  // ---- Sesión --------------------------------------------------------------------------------------------------------------

  private alCambiarAlcance(alcance: AlcanceOffline | null): void {
    const clave = claveAlcance(alcance);
    if (clave === this.claveActual) return;
    this.claveActual = clave;

    if (clave === null) {
      // Sin sesión: no queda nada que mostrar ni que enviar. Lo guardado en el equipo NO se toca.
      this.cancelarReintento();
      this.proximoIntentoEn.set(null);
      this.pendientes.set(0);
      this.enConflicto.set(0);
      this.rechazadas.set(0);
      this.confirmadas.set(0);
      this.pendientesDeOtros.set(0);
      if (this.estadoCola() !== 'pausada_sesion') this.reiniciarEstado();
      return;
    }

    if (this.estadoCola() === 'pausada_sesion' && this.clavePausadaPorSesion === clave) {
      // El mismo usuario volvió a iniciar sesión: sus operaciones siguen guardadas y se reanuda.
      this.limpiarPausa();
      this.fallosSeguidos = 0;
    } else {
      this.reiniciarEstado();
    }
    void this.refrescarConteos().then(() => {
      // Si todavía corre el ciclo de la persona anterior, el de esta empieza cuando aquel termine (no comparte su envío).
      if (this.cicloEnCurso !== null) this.nuevaDuranteCiclo = true;
      else void this.procesar();
    });
  }

  private reiniciarEstado(): void {
    this.cancelarReintento();
    this.limpiarPausa();
    this.fallosSeguidos = 0;
    this.estadoCola.set('inactiva');
    this.proximoIntentoEn.set(null);
  }

  private limpiarPausa(): void {
    this.estadoCola.set('inactiva');
    this.motivoPausa.set(null);
    this.pausaPlanLocal = false;
    this.clavePausadaPorSesion = null;
  }

  /** 'igual' | 'sin_sesion' (cerró sesión) | 'otro' (entró otra persona): con 'otro' el ciclo no toca nada de la pantalla. */
  private compararAlcance(capturado: AlcanceOffline): 'igual' | 'sin_sesion' | 'otro' {
    const actual = claveAlcance(this.sesion.alcance());
    if (actual === null) return 'sin_sesion';
    return actual === claveAlcance(capturado) ? 'igual' : 'otro';
  }

  // ---- Ciclo ---------------------------------------------------------------------------------------------------------------

  /** Un solo ciclo a la vez: un segundo disparo comparte el que está en curso (no hay segundo envío). */
  private procesar(opciones: OpcionesProcesar = {}): Promise<void> {
    if (this.cicloEnCurso !== null) return this.cicloEnCurso;
    this.cicloEnCurso = this.conCandado(() => this.ciclo(opciones))
      .catch((error: unknown) => console.warn('La cola de sincronización falló; las operaciones siguen guardadas.', error))
      .finally(() => {
        this.cicloEnCurso = null;
        if (this.nuevaDuranteCiclo) {
          this.nuevaDuranteCiclo = false;
          void this.procesar();
        }
      });
    return this.cicloEnCurso;
  }

  /** Con Web Locks, dos pestañas no envían a la vez; sin ellos, solo la bandera de esta pestaña (el servidor es idempotente). */
  private conCandado(trabajo: () => Promise<void>): Promise<void> {
    const locks = typeof navigator !== 'undefined' ? (navigator as Navigator & { locks?: LockManager }).locks : undefined;
    if (!locks || typeof locks.request !== 'function') return trabajo();
    return locks.request(NOMBRE_CANDADO_SYNC, { ifAvailable: true }, async (candado) => {
      if (candado === null) return; // otra pestaña está enviando
      await trabajo();
    }) as Promise<void>;
  }

  private async ciclo(opciones: OpcionesProcesar): Promise<void> {
    const alcance = this.sesion.alcance();
    const repo = this.sesion.repositorio();
    if (alcance === null || repo === null) return;

    const forzado = opciones.manual === true || opciones.reanudar === true;

    if (!this.conectividad.enLinea()) {
      await this.marcarSinConexion();
      return;
    }

    if (!(await this.planPermiteEnviar(repo))) return;

    const estado = this.estadoCola();
    const detenida = estado === 'pausada_sesion' || estado === 'pausada_plan' || estado === 'detenida_por_fallos';
    if (detenida && !forzado) return;
    if (detenida) this.limpiarPausa();
    if (forzado) this.fallosSeguidos = 0;
    this.cancelarReintento();

    const tamLote = await this.tamanoLote(repo);
    const intentadas = new Set<string>();
    let envio = false;
    let mal = false;

    while (this.compararAlcance(alcance) !== 'otro') {
      const elegibles = (
        await repo.operacionesParaEnviar({
          max: tamLote + intentadas.size,
          ahora: ahoraIso(),
          ignorarEspera: opciones.manual === true,
          huerfanasMs: HUERFANA_ENVIADA_MS,
        })
      )
        .filter((o) => !intentadas.has(o.operacion_id))
        .slice(0, tamLote);
      if (elegibles.length === 0) break;

      envio = true;
      this.estadoCola.set('sincronizando');
      this.motivoPausa.set(null);
      this.proximoIntentoEn.set(null);
      for (const o of elegibles) intentadas.add(o.operacion_id);

      const resultado = await this.enviarLote(repo, alcance, elegibles, intentadas);
      if (resultado === 'mal') {
        mal = true;
        break;
      }
    }

    if (this.compararAlcance(alcance) === 'otro') return;

    await this.refrescarConteos();
    if (!mal) {
      await this.consultarConflictos(repo, alcance, envio || opciones.manual === true);
      await this.fijarEstadoTrasCiclo(repo);
    }
  }

  /** Sin red no se intenta: las operaciones esperan (sin gastar intentos) y `volvioConexion$` reanuda. */
  private async marcarSinConexion(): Promise<void> {
    await this.refrescarConteos();
    const estado = this.estadoCola();
    if (this.pendientes() > 0 && estado !== 'pausada_sesion' && estado !== 'pausada_plan' && estado !== 'detenida_por_fallos') {
      this.cancelarReintento();
      this.proximoIntentoEn.set(null);
      this.estadoCola.set('sin_conexion');
    }
  }

  /** Si `PlanService` ya sabe que el plan no incluye operar sin conexión (o la suscripción no está activa), no se envía. */
  private async planPermiteEnviar(repo: RepositorioLocal): Promise<boolean> {
    const incluye = this.plan.incluye('operacion_offline');
    const activo = this.plan.estadoActivo();
    if (incluye && activo) {
      if (this.pausaPlanLocal) this.limpiarPausa();
      return true;
    }
    const cuantas = await this.contarPendientes(repo);
    this.pausaPlanLocal = true;
    this.cancelarReintento();
    this.proximoIntentoEn.set(null);
    this.estadoCola.set('pausada_plan');
    this.motivoPausa.set(
      !incluye
        ? `Tu plan no incluye operar sin conexión. ${this.textoGuardadas(cuantas)}`
        : `La suscripción de tu empresa no está activa. ${this.textoGuardadas(cuantas)}`,
    );
    return false;
  }

  private textoGuardadas(cuantas: number): string {
    return cuantas === 1 ? 'Tu operación pendiente sigue guardada.' : `Tus ${cuantas} operaciones pendientes siguen guardadas.`;
  }

  private async contarPendientes(repo: RepositorioLocal): Promise<number> {
    try {
      const conteo = await repo.contarPorEstado();
      return conteo.registrada + conteo.enviada;
    } catch {
      return this.pendientes();
    }
  }

  private async tamanoLote(repo: RepositorioLocal): Promise<number> {
    try {
      const reglas = await repo.leerMeta<{ max_operaciones_por_lote?: number }>(META_REGLAS);
      const maximo = reglas?.max_operaciones_por_lote;
      if (typeof maximo === 'number' && Number.isInteger(maximo) && maximo > 0) return Math.min(TAM_LOTE, maximo);
    } catch {
      // Sin reglas guardadas se usa el tamaño por defecto.
    }
    return TAM_LOTE;
  }

  // ---- Un lote -------------------------------------------------------------------------------------------------------------

  /** 'continuar': se puede mirar si quedan más; 'mal': el ciclo termina aquí (el estado de la cola ya quedó fijado). */
  private async enviarLote(
    repo: RepositorioLocal,
    alcance: AlcanceOffline,
    lote: OperacionOffline[],
    intentadas: Set<string>,
  ): Promise<'continuar' | 'mal'> {
    // Una operación local a la que le falta algo que el servidor exige no se envía ni se descarta: queda bloqueada.
    const validas: { op: OperacionOffline; entrada: Record<string, unknown> }[] = [];
    for (const op of lote) {
      const entrada = aOperacionEntrada(op);
      if (entrada === null) {
        await this.cambiar(repo, op.operacion_id, {
          estado: 'registrada',
          bloqueada: true,
          ultimo_error: 'operacion_invalida',
          mensaje: MENSAJE_ERROR_FORMATO,
        });
      } else {
        validas.push({ op, entrada });
      }
    }
    if (validas.length === 0) return 'continuar';

    const ids = validas.map((v) => v.op.operacion_id);
    await repo.marcarEnviadas(ids, ahoraIso());

    const cuerpo = {
      version_contrato: VERSION_CONTRATO_LOTE,
      dispositivo: this.sesion.dispositivoId(),
      operaciones: validas.map((v) => v.entrada),
    };

    let respuesta: RespuestaLote;
    try {
      respuesta = await firstValueFrom(
        this.http
          .post<RespuestaLote>(`${environment.apiUrl}/sincronizacion/lote`, cuerpo, { context: new HttpContext().set(SIN_TOAST_ERROR, true) })
          .pipe(timeout({ first: TIMEOUT_LOTE_MS })),
      );
    } catch (error) {
      return this.alFallarElLote(repo, alcance, validas, error, intentadas);
    }

    if (!respuesta || !Array.isArray(respuesta.resultados)) {
      // Un 200 que no es lo que manda este servidor (un proxy, una página de error): se trata como un fallo.
      return this.devolverPorFallo(repo, validas, 'respuesta_invalida', 200);
    }
    return this.aplicarResultados(repo, validas, respuesta);
  }

  private async aplicarResultados(
    repo: RepositorioLocal,
    validas: { op: OperacionOffline }[],
    respuesta: RespuestaLote,
  ): Promise<'continuar' | 'mal'> {
    const porId = new Map<string, ResultadoLote>();
    for (const r of respuesta.resultados) {
      if (typeof r?.operacion_id === 'string') porId.set(r.operacion_id.toLowerCase(), r);
    }

    let progreso = false;
    let esperaMinima: number | null = null;
    for (const { op } of validas) {
      const resultado = porId.get(op.operacion_id.toLowerCase());
      // Lo guardado en la base ya tiene el intento sumado por `marcarEnviadas`.
      const intentos = op.intentos + 1;
      if (resultado === undefined) {
        const espera = esperaBackoffMs(intentos);
        await this.volverARegistrada(repo, op.operacion_id, 'sin_respuesta', espera);
        await this.anotar(repo, op.operacion_id, 200, 'sin_respuesta', null);
        esperaMinima = Math.min(esperaMinima ?? espera, espera);
      } else if (resultado.estado === 'confirmada' || resultado.estado === 'rechazada' || resultado.estado === 'en_conflicto') {
        // `duplicada: true` es un reenvío seguro: el servidor devolvió lo ya guardado y se trata como cualquier otra respuesta.
        await this.cambiar(repo, op.operacion_id, {
          estado: resultado.estado,
          motivo: resultado.motivo ?? null,
          mensaje: resultado.mensaje ?? null,
          resultado,
          ultimo_error: null,
          proximo_intento_en: null,
          bloqueada: false,
        });
        await this.anotar(repo, op.operacion_id, 200, resultado.motivo ?? null, resultado);
        progreso = true;
      } else {
        // `error_temporal` (o un estado que esta versión no conoce): NO se guardó en el servidor, se reintenta.
        const motivo = resultado.estado === 'error_temporal' ? (resultado.motivo ?? 'error_temporal') : 'estado_desconocido';
        const espera = esperaBackoffMs(intentos);
        await this.volverARegistrada(repo, op.operacion_id, motivo, espera);
        await this.anotar(repo, op.operacion_id, 200, motivo, resultado);
        esperaMinima = Math.min(esperaMinima ?? espera, espera);
      }
    }

    if (progreso) {
      this.fallosSeguidos = 0;
      return 'continuar';
    }
    // El servidor contestó pero no dejó nada en firme: cuenta como un fallo (si no, se reenviaría sin parar).
    this.registrarFallo(esperaMinima ?? esperaBackoffMs(this.fallosSeguidos + 1));
    return 'mal';
  }

  private async alFallarElLote(
    repo: RepositorioLocal,
    alcance: AlcanceOffline,
    validas: { op: OperacionOffline }[],
    error: unknown,
    intentadas: Set<string>,
  ): Promise<'continuar' | 'mal'> {
    if (!(error instanceof HttpErrorResponse)) {
      const motivo = (error as { name?: string } | null)?.name === 'TimeoutError' ? 'timeout' : 'error_red';
      return this.devolverPorFallo(repo, validas, motivo, null);
    }

    switch (error.status) {
      case 401: {
        // El interceptor ya intentó renovar la sesión: si llegó aquí, venció. Las operaciones siguen guardadas.
        for (const { op } of validas) {
          await this.volverARegistrada(repo, op.operacion_id, 'sesion_vencida', null);
          await this.anotar(repo, op.operacion_id, 401, 'sesion_vencida', null);
        }
        const cuantas = await this.contarPendientes(repo);
        this.cancelarReintento();
        this.proximoIntentoEn.set(null);
        if (this.compararAlcance(alcance) !== 'otro') {
          this.clavePausadaPorSesion = claveAlcance(alcance);
          this.estadoCola.set('pausada_sesion');
          this.motivoPausa.set(
            cuantas === 1
              ? 'Inicia sesión para enviar tu operación pendiente. Sigue guardada.'
              : `Inicia sesión para enviar tus ${cuantas} operaciones pendientes. Siguen guardadas.`,
          );
        }
        return 'mal';
      }
      case 403: {
        const codigo = codigoFuncional(error);
        if (codigo !== null && CODIGOS_PAUSA_PLAN.includes(codigo)) {
          // El servidor rechazó el lote completo por el plan o la suscripción: no se marca nada como rechazado.
          for (const { op } of validas) {
            await this.volverARegistrada(repo, op.operacion_id, codigo, null);
            await this.anotar(repo, op.operacion_id, 403, codigo, error.error);
          }
          const cuantas = await this.contarPendientes(repo);
          this.cancelarReintento();
          this.proximoIntentoEn.set(null);
          if (this.compararAlcance(alcance) !== 'otro') {
            this.pausaPlanLocal = false;
            this.estadoCola.set('pausada_plan');
            this.motivoPausa.set(
              codigo === 'plan_no_incluye_funcionalidad'
                ? `Tu plan no incluye operar sin conexión. ${this.textoGuardadas(cuantas)}`
                : `La suscripción de tu empresa no está activa. ${this.textoGuardadas(cuantas)}`,
            );
          }
          return 'mal';
        }
        return this.devolverPorFallo(repo, validas, 'http_403', 403, error.error);
      }
      case 400:
      case 422:
        return this.bloquearPorFormato(repo, validas, error, intentadas);
      case 429:
        return this.devolverPorFallo(repo, validas, 'http_429', 429, error.error, leerRetryAfterMs(error.headers?.get('Retry-After')));
      case 0:
        if (!this.conectividad.enLinea()) {
          // Se fue la red a mitad del envío: no es un fallo del servidor. Esperan sin gastar intentos hasta volver la conexión.
          for (const { op } of validas) {
            await this.volverARegistrada(repo, op.operacion_id, 'sin_conexion', null);
            await this.anotar(repo, op.operacion_id, 0, 'sin_conexion', null);
          }
          this.cancelarReintento();
          this.proximoIntentoEn.set(null);
          if (this.compararAlcance(alcance) !== 'otro') this.estadoCola.set('sin_conexion');
          return 'mal';
        }
        return this.devolverPorFallo(repo, validas, 'sin_conexion', 0);
      default:
        return this.devolverPorFallo(repo, validas, `http_${error.status}`, error.status, error.error);
    }
  }

  /** Error de formato del lote completo: no se reintenta solo. Si el servidor señala cuáles, solo esas quedan bloqueadas. */
  private async bloquearPorFormato(
    repo: RepositorioLocal,
    validas: { op: OperacionOffline }[],
    error: HttpErrorResponse,
    intentadas: Set<string>,
  ): Promise<'continuar' | 'mal'> {
    const culpables = error.status === 422 ? posicionesInvalidas(error, validas.length) : null;
    for (let i = 0; i < validas.length; i++) {
      const { op } = validas[i];
      const bloquear = culpables === null || culpables.includes(i);
      await this.cambiar(repo, op.operacion_id, {
        estado: 'registrada',
        bloqueada: bloquear,
        ultimo_error: bloquear ? 'error_formato' : 'lote_con_error_de_formato',
        mensaje: bloquear ? MENSAJE_ERROR_FORMATO : null,
        proximo_intento_en: null,
      });
      await this.anotar(repo, op.operacion_id, error.status, bloquear ? 'error_formato' : 'lote_con_error_de_formato', error.error);
      // Las que no tienen la culpa vuelven a entrar al siguiente lote del mismo ciclo.
      if (!bloquear) intentadas.delete(op.operacion_id);
    }
    return 'continuar';
  }

  /** Red, tiempo agotado, 5xx, 429...: todas vuelven a `registrada` con espera y el ciclo termina. */
  private async devolverPorFallo(
    repo: RepositorioLocal,
    validas: { op: OperacionOffline }[],
    motivo: string,
    status: number | null,
    cuerpo: unknown = null,
    esperaFija: number | null = null,
  ): Promise<'mal'> {
    const espera = esperaFija ?? esperaBackoffMs(this.fallosSeguidos + 1);
    for (const { op } of validas) {
      await this.volverARegistrada(repo, op.operacion_id, motivo, espera);
      await this.anotar(repo, op.operacion_id, status, motivo, cuerpo);
    }
    this.registrarFallo(espera);
    return 'mal';
  }

  /** Suma un fallo seguido: reintenta sola con espera creciente y, pasado el tope, se detiene (siguen guardadas). */
  private registrarFallo(esperaMs: number): void {
    this.fallosSeguidos += 1;
    if (this.fallosSeguidos >= INTENTOS_AUTOMATICOS_MAX) {
      this.cancelarReintento();
      this.proximoIntentoEn.set(null);
      this.estadoCola.set('detenida_por_fallos');
      this.motivoPausa.set(MOTIVO_DETENIDA);
      return;
    }
    this.estadoCola.set('esperando_reintento');
    this.motivoPausa.set(null);
    this.programarReintento(esperaMs);
  }

  // ---- Reintentos ----------------------------------------------------------------------------------------------------------

  private programarReintento(esperaMs: number): void {
    this.cancelarReintento();
    this.proximoIntentoEn.set(new Date(Date.now() + esperaMs).toISOString());
    // Unos milisegundos de margen: al despertar, la espera de la operación ya tiene que haber pasado.
    this.temporizadorReintento = setTimeout(() => {
      this.temporizadorReintento = null;
      void this.procesar();
    }, esperaMs + 25);
  }

  private cancelarReintento(): void {
    if (this.temporizadorReintento !== null) {
      clearTimeout(this.temporizadorReintento);
      this.temporizadorReintento = null;
    }
  }

  /** Terminado un ciclo sin fallos: si alguna operación sigue esperando su turno, se programa; si no, la cola descansa. */
  private async fijarEstadoTrasCiclo(repo: RepositorioLocal): Promise<void> {
    const estado = this.estadoCola();
    if (estado === 'pausada_sesion' || estado === 'pausada_plan' || estado === 'detenida_por_fallos') return;
    let proxima: number | null = null;
    try {
      const ahora = Date.now();
      const esperando = (await repo.misOperaciones({ estado: 'registrada' })).filter(
        (o) => !o.bloqueada && o.proximo_intento_en !== null && Date.parse(o.proximo_intento_en) > ahora,
      );
      if (esperando.length > 0) proxima = Math.min(...esperando.map((o) => Date.parse(o.proximo_intento_en as string)));
    } catch {
      proxima = null;
    }
    if (proxima !== null) {
      this.estadoCola.set('esperando_reintento');
      this.motivoPausa.set(null);
      this.programarReintento(Math.max(proxima - Date.now(), 0));
      return;
    }
    this.cancelarReintento();
    this.proximoIntentoEn.set(null);
    this.motivoPausa.set(null);
    this.estadoCola.set('inactiva');
  }

  // ---- Conflictos ----------------------------------------------------------------------------------------------------------

  /**
   * Un encargado puede resolver una operación `en_conflicto`: se pregunta al servidor por cada una y, si ya quedó
   * `confirmada` o `rechazada`, se actualiza la copia local. Un error en la consulta se ignora (se vuelve a intentar luego).
   */
  private async consultarConflictos(repo: RepositorioLocal, alcance: AlcanceOffline, forzar: boolean): Promise<void> {
    if (!forzar && Date.now() - this.ultimaConsultaConflictos < INTERVALO_CONSULTA_CONFLICTOS_MS) return;
    let enConflicto: OperacionOffline[];
    try {
      enConflicto = await repo.misOperaciones({ estado: 'en_conflicto' });
    } catch {
      return;
    }
    if (enConflicto.length === 0) return;
    this.ultimaConsultaConflictos = Date.now();

    let cambio = false;
    for (const op of enConflicto.slice(0, MAX_CONSULTAS_CONFLICTO)) {
      if (this.compararAlcance(alcance) === 'otro') return;
      try {
        const remota = await firstValueFrom(
          this.http.get<RespuestaConsultaOperacion>(
            `${environment.apiUrl}/sincronizacion/operaciones/${encodeURIComponent(op.operacion_id)}`,
            { context: new HttpContext().set(SIN_TOAST_ERROR, true) },
          ),
        );
        if (remota?.estado !== 'confirmada' && remota?.estado !== 'rechazada') continue;
        const resultado = {
          estado: remota.estado,
          motivo: remota.motivo ?? null,
          mensaje: remota.mensaje ?? null,
          recurso: remota.recurso ?? null,
          cambio: remota.cambio ?? null,
          avisos: remota.avisos ?? [],
          faltantes: remota.faltantes ?? [],
          resolucion: remota.resolucion ?? null,
        } as ResultadoServidor;
        const guardado = await this.cambiar(repo, op.operacion_id, {
          estado: remota.estado,
          motivo: remota.motivo ?? remota.resolucion?.motivo ?? null,
          mensaje: remota.mensaje ?? null,
          resultado,
          ultimo_error: null,
        });
        cambio = cambio || guardado;
      } catch {
        // Sin respuesta o sin permiso: se deja como está y se pregunta en el próximo ciclo.
      }
    }
    if (cambio) await this.refrescarConteos();
  }

  // ---- Escrituras seguras --------------------------------------------------------------------------------------------------

  /** Devuelve una operación a la cola (`registrada`) con el motivo y, si hay, la hora antes de la cual no se reintenta. */
  private async volverARegistrada(repo: RepositorioLocal, operacionId: string, motivo: string, esperaMs: number | null): Promise<void> {
    await this.cambiar(repo, operacionId, {
      estado: 'registrada',
      ultimo_error: motivo,
      proximo_intento_en: esperaMs === null ? null : new Date(Date.now() + esperaMs).toISOString(),
    });
  }

  /** Cambia una operación sin lanzar: si no se puede (ya era final, falló IndexedDB) queda como estaba y se recupera después. */
  private async cambiar(repo: RepositorioLocal, operacionId: string, cambios: Parameters<RepositorioLocal['actualizarOperacion']>[1]): Promise<boolean> {
    try {
      await repo.actualizarOperacion(operacionId, cambios);
      return true;
    } catch (error) {
      console.warn('No se pudo actualizar una operación local.', error);
      return false;
    }
  }

  private async anotar(repo: RepositorioLocal, operacionId: string, status: number | null, motivo: string | null, respuesta: unknown): Promise<void> {
    try {
      await repo.registrarIntento({ operacion_id: operacionId, fecha: ahoraIso(), http_status: status, motivo, respuesta });
    } catch (error) {
      console.warn('No se pudo anotar el intento de envío.', error);
    }
  }
}

import { DOCUMENT } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  InjectionToken,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { SwUpdate, VersionEvent, VersionReadyEvent } from '@angular/service-worker';
import { Subscription, filter } from 'rxjs';
import { IconoComponent } from '../icono/icono.component';

/** Clave de localStorage: fecha (ISO) en la que el usuario dijo "Ahora no" a instalar. */
export const CLAVE_INSTALAR_DESCARTADO = 'fs_pwa_instalar_descartado';
/** Clave de localStorage: la guÃ­a de iOS ya se mostrÃ³ (se muestra una sola vez). */
export const CLAVE_GUIA_IOS_VISTA = 'fs_pwa_guia_ios_vista';
/** DÃ­as sin volver a ofrecer la instalaciÃ³n despuÃ©s de "Ahora no". */
export const DIAS_SIN_OFRECER_INSTALAR = 14;
/** Cada cuÃ¡nto se busca una versiÃ³n nueva con la aplicaciÃ³n abierta. */
export const INTERVALO_REVISION_VERSION_MS = 6 * 60 * 60 * 1000;

const MS_POR_DIA = 24 * 60 * 60 * 1000;

/** Evento no estÃ¡ndar de Chromium: permite mostrar el diÃ¡logo de instalaciÃ³n cuando uno quiere. */
export interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform?: string }>;
}

/**
 * Recarga la pÃ¡gina. Es un token para que las pruebas lo reemplacen: `location.reload`
 * no se puede simular directamente en el navegador.
 */
export const RECARGAR_PAGINA = new InjectionToken<() => void>('RECARGAR_PAGINA', {
  providedIn: 'root',
  factory: () => {
    const documento = inject(DOCUMENT);
    return () => documento.location.reload();
  },
});

/**
 * Avisos de la PWA (E13), fijos abajo a la derecha (en celular, abajo a todo el ancho):
 * - instalar la aplicaciÃ³n (`beforeinstallprompt`); "Ahora no" la oculta 14 dÃ­as;
 * - guÃ­a de iOS Safari (no dispara `beforeinstallprompt`), una sola vez;
 * - nueva versiÃ³n lista: la aplicaciÃ³n NUNCA se recarga sola (puede haber una venta a medio armar);
 * - estado irrecuperable del Service Worker: hay que recargar.
 * Funciona sin `SwUpdate` (sin `provideServiceWorker`) y con el Service Worker apagado (`ng serve`).
 */
@Component({
  selector: 'app-aviso-pwa',
  standalone: true,
  imports: [IconoComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './aviso-pwa.component.html',
  styleUrl: './aviso-pwa.component.scss',
})
export class AvisoPwaComponent implements OnDestroy {
  private readonly documento = inject(DOCUMENT);
  private readonly ventana = this.documento.defaultView;
  private readonly swUpdate = inject(SwUpdate, { optional: true });
  private readonly recargarPagina = inject(RECARGAR_PAGINA);

  private readonly eventoInstalar = signal<BeforeInstallPromptEvent | null>(null);
  protected readonly mostrarInstalar = computed(() => this.eventoInstalar() !== null);
  protected readonly mostrarGuiaIos = signal(false);
  protected readonly hayVersionNueva = signal(false);
  protected readonly requiereRecarga = signal(false);
  protected readonly hayAviso = computed(
    () => this.mostrarInstalar() || this.mostrarGuiaIos() || this.hayVersionNueva() || this.requiereRecarga(),
  );

  private readonly suscripciones = new Subscription();
  private temporizador: ReturnType<typeof setInterval> | null = null;

  private readonly alOfrecerInstalar = (evento: Event): void => {
    // Evita el mini aviso del navegador y guarda el evento para usarlo con el botÃ³n.
    evento.preventDefault();
    if (this.yaEstaInstalada() || this.descartadoRecientemente()) {
      return;
    }
    this.eventoInstalar.set(evento as BeforeInstallPromptEvent);
  };

  private readonly alInstalarse = (): void => this.eventoInstalar.set(null);

  private readonly alCambiarVisibilidad = (): void => {
    if (this.documento.visibilityState === 'visible') {
      this.buscarVersionNueva();
    }
  };

  constructor() {
    if (this.ventana) {
      if (!this.yaEstaInstalada()) {
        this.ventana.addEventListener('beforeinstallprompt', this.alOfrecerInstalar);
        this.ventana.addEventListener('appinstalled', this.alInstalarse);
        this.evaluarGuiaIos();
      }
    }
    this.vigilarVersiones();
  }

  ngOnDestroy(): void {
    this.ventana?.removeEventListener('beforeinstallprompt', this.alOfrecerInstalar);
    this.ventana?.removeEventListener('appinstalled', this.alInstalarse);
    this.documento.removeEventListener('visibilitychange', this.alCambiarVisibilidad);
    if (this.temporizador !== null) {
      clearInterval(this.temporizador);
      this.temporizador = null;
    }
    this.suscripciones.unsubscribe();
  }

  // ---- Instalar ----

  protected async instalar(): Promise<void> {
    const evento = this.eventoInstalar();
    if (!evento) {
      return;
    }
    // El evento solo sirve una vez: la tarjeta se retira haga lo que haga el usuario.
    this.eventoInstalar.set(null);
    try {
      await evento.prompt();
      const eleccion = await evento.userChoice;
      if (eleccion.outcome === 'dismissed') {
        this.guardarDescarte();
      }
    } catch {
      // El navegador rechazÃ³ mostrar el diÃ¡logo: no hay nada mÃ¡s que hacer.
    }
  }

  protected ahoraNo(): void {
    this.guardarDescarte();
    this.eventoInstalar.set(null);
  }

  protected cerrarGuiaIos(): void {
    this.mostrarGuiaIos.set(false);
  }

  // ---- Nueva versiÃ³n ----

  protected actualizar(): void {
    if (!this.swUpdate) {
      this.recargarPagina();
      return;
    }
    this.swUpdate
      .activateUpdate()
      .catch(() => undefined)
      .then(() => this.recargarPagina());
  }

  protected despues(): void {
    this.hayVersionNueva.set(false);
  }

  protected recargar(): void {
    this.recargarPagina();
  }

  // ---- Internos ----

  private vigilarVersiones(): void {
    const swUpdate = this.swUpdate;
    if (!swUpdate || !swUpdate.isEnabled) {
      return;
    }
    this.suscripciones.add(
      swUpdate.versionUpdates
        .pipe(filter((evento: VersionEvent): evento is VersionReadyEvent => evento.type === 'VERSION_READY'))
        .subscribe(() => this.hayVersionNueva.set(true)),
    );
    this.suscripciones.add(swUpdate.unrecoverable.subscribe(() => this.requiereRecarga.set(true)));
    this.documento.addEventListener('visibilitychange', this.alCambiarVisibilidad);
    this.temporizador = setInterval(() => this.buscarVersionNueva(), INTERVALO_REVISION_VERSION_MS);
  }

  private buscarVersionNueva(): void {
    if (!this.swUpdate?.isEnabled) {
      return;
    }
    // Sin red o con el SW en un estado raro la revisiÃ³n falla: se reintenta en la prÃ³xima ocasiÃ³n.
    this.swUpdate.checkForUpdate().catch(() => undefined);
  }

  private yaEstaInstalada(): boolean {
    const ventana = this.ventana;
    if (!ventana) {
      return false;
    }
    const navegador = ventana.navigator as Navigator & { standalone?: boolean };
    if (navegador.standalone === true) {
      return true;
    }
    return typeof ventana.matchMedia === 'function' && ventana.matchMedia('(display-mode: standalone)').matches;
  }

  private descartadoRecientemente(): boolean {
    try {
      const guardado = this.ventana?.localStorage.getItem(CLAVE_INSTALAR_DESCARTADO);
      if (!guardado) {
        return false;
      }
      const fecha = Date.parse(guardado);
      return !Number.isNaN(fecha) && Date.now() - fecha < DIAS_SIN_OFRECER_INSTALAR * MS_POR_DIA;
    } catch {
      return false;
    }
  }

  private guardarDescarte(): void {
    try {
      this.ventana?.localStorage.setItem(CLAVE_INSTALAR_DESCARTADO, new Date().toISOString());
    } catch {
      // Sin almacenamiento (modo privado o bloqueado): la tarjeta volverÃ¡ en la prÃ³xima visita.
    }
  }

  /** Safari de iPhone/iPad no ofrece `beforeinstallprompt`: se explica una sola vez cÃ³mo instalarla a mano. */
  private evaluarGuiaIos(): void {
    const navegador = this.ventana?.navigator;
    if (!navegador || !this.esSafariIos(navegador)) {
      return;
    }
    try {
      if (this.ventana?.localStorage.getItem(CLAVE_GUIA_IOS_VISTA)) {
        return;
      }
      this.ventana?.localStorage.setItem(CLAVE_GUIA_IOS_VISTA, new Date().toISOString());
    } catch {
      // Sin almacenamiento no se puede garantizar "una sola vez": mejor no molestar.
      return;
    }
    this.mostrarGuiaIos.set(true);
  }

  private esSafariIos(navegador: Navigator): boolean {
    const agente = navegador.userAgent;
    // iPadOS 13+ se identifica como Mac: se distingue por la pantalla tÃ¡ctil.
    const esIos = /iPhone|iPad|iPod/.test(agente) || (/Macintosh/.test(agente) && navegador.maxTouchPoints > 1);
    const esOtroNavegador = /CriOS|FxiOS|EdgiOS|OPiOS/.test(agente);
    return esIos && !esOtroNavegador;
  }
}

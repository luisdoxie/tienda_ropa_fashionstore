import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SwUpdate, UnrecoverableStateEvent, VersionEvent } from '@angular/service-worker';
import { Subject } from 'rxjs';
import {
  AvisoPwaComponent,
  CLAVE_GUIA_IOS_VISTA,
  CLAVE_INSTALAR_DESCARTADO,
  INTERVALO_REVISION_VERSION_MS,
  RECARGAR_PAGINA,
} from './aviso-pwa.component';

const DIA_MS = 24 * 60 * 60 * 1000;

/** SwUpdate falso: solo lo que usa el componente. */
class SwUpdateFalso {
  isEnabled = true;
  readonly versionUpdates = new Subject<VersionEvent>();
  readonly unrecoverable = new Subject<UnrecoverableStateEvent>();
  readonly activateUpdate = vi.fn(() => Promise.resolve(true));
  readonly checkForUpdate = vi.fn(() => Promise.resolve(false));
}

function versionLista(): VersionEvent {
  return { type: 'VERSION_READY', currentVersion: { hash: 'a' }, latestVersion: { hash: 'b' } };
}

/** Un `beforeinstallprompt` falso con `prompt()` y `userChoice`. */
function eventoInstalacion(outcome: 'accepted' | 'dismissed' = 'accepted') {
  const prompt = vi.fn(() => Promise.resolve());
  const evento = new Event('beforeinstallprompt', { cancelable: true });
  Object.assign(evento, { prompt, userChoice: Promise.resolve({ outcome }) });
  return { evento, prompt };
}

describe('AvisoPwaComponent', () => {
  let recargar: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<AvisoPwaComponent>;
  let matchMediaOriginal: PropertyDescriptor | undefined;
  let standalone: boolean;

  beforeEach(() => {
    recargar = vi.fn();
    standalone = false;
    window.localStorage.clear();
    matchMediaOriginal = Object.getOwnPropertyDescriptor(window, 'matchMedia');
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (consulta: string) => ({
        matches: consulta === '(display-mode: standalone)' && standalone,
        media: consulta,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    window.localStorage.clear();
    if (matchMediaOriginal) {
      Object.defineProperty(window, 'matchMedia', matchMediaOriginal);
    } else {
      Reflect.deleteProperty(window, 'matchMedia');
    }
    Reflect.deleteProperty(document, 'visibilityState');
  });

  function configurar(sw: SwUpdateFalso | null = null): void {
    TestBed.configureTestingModule({
      providers: [
        { provide: RECARGAR_PAGINA, useValue: recargar },
        ...(sw ? [{ provide: SwUpdate, useValue: sw }] : []),
      ],
    });
  }

  function crear(): ComponentFixture<AvisoPwaComponent> {
    fixture = TestBed.createComponent(AvisoPwaComponent);
    fixture.detectChanges();
    return fixture;
  }

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function boton(etiqueta: string): HTMLButtonElement | undefined {
    const botones = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'));
    return botones.find((b) => b.textContent?.trim() === etiqueta);
  }

  function ofrecerInstalacion(outcome: 'accepted' | 'dismissed' = 'accepted') {
    const falso = eventoInstalacion(outcome);
    window.dispatchEvent(falso.evento);
    fixture.detectChanges();
    return falso;
  }

  // ---- Instalar ----

  it('con beforeinstallprompt muestra [Instalar]; el clic llama a prompt() y retira la tarjeta', () => {
    configurar();
    crear();
    expect(boton('Instalar')).toBeUndefined();

    const { evento, prompt } = ofrecerInstalacion();

    expect(evento.defaultPrevented).toBe(true);
    expect(texto()).toContain('Instala FashionStore en este equipo para abrirla como una app');
    expect(boton('Ahora no')).toBeDefined();

    boton('Instalar')?.click();
    expect(prompt).toHaveBeenCalledTimes(1);
    fixture.detectChanges();
    expect(boton('Instalar')).toBeUndefined();
  });

  it('si el usuario cierra el diálogo del navegador, cuenta como "Ahora no"', async () => {
    configurar();
    crear();
    ofrecerInstalacion('dismissed');

    boton('Instalar')?.click();

    await vi.waitFor(() => expect(window.localStorage.getItem(CLAVE_INSTALAR_DESCARTADO)).not.toBeNull());
  });

  it('"Ahora no" guarda la fecha y un nuevo montaje no muestra la tarjeta', () => {
    configurar();
    crear();
    ofrecerInstalacion();

    boton('Ahora no')?.click();
    fixture.detectChanges();

    const guardado = window.localStorage.getItem(CLAVE_INSTALAR_DESCARTADO);
    expect(guardado).not.toBeNull();
    expect(Number.isNaN(Date.parse(guardado ?? ''))).toBe(false);
    expect(boton('Instalar')).toBeUndefined();

    fixture.destroy();
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeUndefined();
  });

  it('pasados 14 días vuelve a mostrar la tarjeta (a los 13 todavía no)', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-01T10:00:00Z'));
    configurar();
    crear();
    ofrecerInstalacion();
    boton('Ahora no')?.click();
    fixture.destroy();

    vi.setSystemTime(new Date('2026-10-01T10:00:00Z').getTime() + 13 * DIA_MS);
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeUndefined();
    fixture.destroy();

    vi.setSystemTime(new Date('2026-10-01T10:00:00Z').getTime() + 14 * DIA_MS + 1000);
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeDefined();
  });

  it('una fecha guardada inválida no bloquea la tarjeta', () => {
    window.localStorage.setItem(CLAVE_INSTALAR_DESCARTADO, 'no-es-una-fecha');
    configurar();
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeDefined();
  });

  it('con localStorage roto sigue funcionando (todo acceso va en try/catch)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado');
    });
    configurar();
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeDefined();

    expect(() => boton('Ahora no')?.click()).not.toThrow();
    fixture.detectChanges();
    expect(boton('Instalar')).toBeUndefined();
  });

  it('"appinstalled" oculta la tarjeta', () => {
    configurar();
    crear();
    ofrecerInstalacion();
    expect(boton('Instalar')).toBeDefined();

    window.dispatchEvent(new Event('appinstalled'));
    fixture.detectChanges();

    expect(boton('Instalar')).toBeUndefined();
  });

  it('en modo standalone (ya instalada) no muestra la tarjeta de instalar', () => {
    standalone = true;
    configurar();
    crear();

    const { evento } = ofrecerInstalacion();

    expect(boton('Instalar')).toBeUndefined();
    expect(texto().trim()).toBe('');
    // No se escuchó el evento: el navegador conserva su comportamiento normal.
    expect(evento.defaultPrevented).toBe(false);
  });

  // ---- iOS ----

  it('en Safari de iPhone muestra la guía una sola vez', () => {
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    );
    configurar();
    crear();

    expect(texto()).toContain('Toca Compartir y luego Agregar a pantalla de inicio');
    expect(window.localStorage.getItem(CLAVE_GUIA_IOS_VISTA)).not.toBeNull();

    fixture.destroy();
    crear();
    expect(texto()).not.toContain('Agregar a pantalla de inicio');
  });

  it('en Chrome de iPhone (CriOS) y en escritorio no muestra la guía de iOS', () => {
    configurar();
    crear();
    expect(texto()).not.toContain('Agregar a pantalla de inicio');
    fixture.destroy();

    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0 Mobile/15E148 Safari/604.1',
    );
    crear();
    expect(texto()).not.toContain('Agregar a pantalla de inicio');
  });

  // ---- Nueva versión ----

  it('con VERSION_READY aparece "Actualizar ahora"; el clic activa y recarga, no antes', async () => {
    const sw = new SwUpdateFalso();
    configurar(sw);
    crear();
    expect(boton('Actualizar ahora')).toBeUndefined();

    sw.versionUpdates.next({ type: 'VERSION_DETECTED', version: { hash: 'b' } });
    fixture.detectChanges();
    expect(boton('Actualizar ahora')).toBeUndefined();

    sw.versionUpdates.next(versionLista());
    fixture.detectChanges();
    expect(texto()).toContain('Hay una versión nueva de FashionStore');
    // Nunca recarga sola: hay una venta que puede estar a medio armar.
    expect(recargar).not.toHaveBeenCalled();
    expect(sw.activateUpdate).not.toHaveBeenCalled();

    boton('Actualizar ahora')?.click();
    expect(sw.activateUpdate).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(recargar).toHaveBeenCalledTimes(1));
  });

  it('[Después] oculta la tarjeta sin activar ni recargar', () => {
    const sw = new SwUpdateFalso();
    configurar(sw);
    crear();
    sw.versionUpdates.next(versionLista());
    fixture.detectChanges();

    boton('Después')?.click();
    fixture.detectChanges();

    expect(boton('Actualizar ahora')).toBeUndefined();
    expect(sw.activateUpdate).not.toHaveBeenCalled();
    expect(recargar).not.toHaveBeenCalled();
  });

  it('estado irrecuperable: avisa que hay que recargar la página y el botón recarga', () => {
    const sw = new SwUpdateFalso();
    configurar(sw);
    crear();

    sw.unrecoverable.next({ type: 'UNRECOVERABLE_STATE', reason: 'hash roto' });
    fixture.detectChanges();

    expect(texto()).toContain('Hay que recargar la página');
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')).not.toBeNull();
    boton('Recargar')?.click();
    expect(recargar).toHaveBeenCalledTimes(1);
  });

  it('sin SwUpdate (null) el componente no falla y no muestra avisos de versión', () => {
    configurar(null);
    expect(() => crear()).not.toThrow();
    expect(texto().trim()).toBe('');
    expect(() => fixture.destroy()).not.toThrow();
  });

  it('con SwUpdate apagado (ng serve) no se suscribe ni consulta versiones', () => {
    const sw = new SwUpdateFalso();
    sw.isEnabled = false;
    configurar(sw);
    crear();

    expect(sw.versionUpdates.observed).toBe(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sw.checkForUpdate).not.toHaveBeenCalled();
  });

  // ---- Revisión de versiones y limpieza ----

  it('revisa versiones al volver la pestaña a visible, no si queda oculta', () => {
    const sw = new SwUpdateFalso();
    configurar(sw);
    crear();
    let estado: DocumentVisibilityState = 'hidden';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => estado });

    document.dispatchEvent(new Event('visibilitychange'));
    expect(sw.checkForUpdate).not.toHaveBeenCalled();

    estado = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sw.checkForUpdate).toHaveBeenCalledTimes(1);
  });

  it('un fallo de checkForUpdate no provoca errores sin capturar', async () => {
    const sw = new SwUpdateFalso();
    sw.checkForUpdate.mockImplementation(() => Promise.reject(new Error('sin red')));
    configurar(sw);
    crear();
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });

    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();

    expect(sw.checkForUpdate).toHaveBeenCalledTimes(1);
  });

  it('revisa cada 6 h y, al destruir, limpia el intervalo y todos los listeners', () => {
    vi.useFakeTimers();
    const sw = new SwUpdateFalso();
    configurar(sw);
    crear();
    expect(vi.getTimerCount()).toBe(1);

    vi.advanceTimersByTime(INTERVALO_REVISION_VERSION_MS - 1);
    expect(sw.checkForUpdate).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(sw.checkForUpdate).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(INTERVALO_REVISION_VERSION_MS);
    expect(sw.checkForUpdate).toHaveBeenCalledTimes(2);

    fixture.destroy();

    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(INTERVALO_REVISION_VERSION_MS * 3);
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sw.checkForUpdate).toHaveBeenCalledTimes(2);

    // Los listeners de ventana también se quitan: el navegador conserva su aviso propio.
    const { evento } = eventoInstalacion();
    window.dispatchEvent(evento);
    expect(evento.defaultPrevented).toBe(false);

    // Y las suscripciones al Service Worker.
    expect(sw.versionUpdates.observed).toBe(false);
    expect(sw.unrecoverable.observed).toBe(false);
  });
});

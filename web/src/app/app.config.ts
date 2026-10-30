import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideRouter, withNavigationErrorHandler } from '@angular/router';
import { provideServiceWorker } from '@angular/service-worker';
import { definePreset } from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';
import { MessageService } from 'primeng/api';
import { providePrimeNG } from 'primeng/config';
import { of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { routes } from './app.routes';
import { AuthService } from './core/auth.service';
import { authInterceptor } from './core/auth.interceptor';
import { errorInterceptor } from './core/error.interceptor';
import { alFallarLaNavegacion } from './core/navegacion-sin-conexion';
import { environment } from '../environments/environment';

// Preset de PrimeNG alineado con styles.scss (CLAUDE.md, tokens de diseño).
// Sobre fondo claro el "primario" es la tinta (#151515), igual que el botón
// primario propio (.fs-btn--primario): el color de acento (lima u oliva) no
// pinta controles, solo detalles. Grises cálidos, esquinas casi rectas y
// áreas tocables de 44-48 px.
const FashionStorePreset = definePreset(Aura, {
  primitive: {
    borderRadius: { none: '0', xs: '2px', sm: '2px', md: '4px', lg: '6px', xl: '8px' },
  },
  semantic: {
    primary: {
      50: '#f7f5f1',
      100: '#efebe4',
      200: '#e4dfd6',
      300: '#c9c2b6',
      400: '#a39b8f',
      500: '#6b645c',
      600: '#3d3a35',
      700: '#2a2723',
      800: '#1f1d19',
      900: '#151515',
      950: '#0d0c0b',
    },
    formField: {
      paddingX: '0.875rem',
      paddingY: '0.8rem',
      borderRadius: '{border.radius.md}',
    },
    overlay: {
      modal: { borderRadius: '{border.radius.xl}', padding: '1.5rem', shadow: '0 20px 48px rgba(22, 20, 18, 0.3)' },
    },
    colorScheme: {
      light: {
        surface: {
          0: '#ffffff',
          50: '#f7f5f1',
          100: '#efebe4',
          200: '#e4dfd6',
          300: '#c9c2b6',
          400: '#a39b8f',
          500: '#6b645c',
          600: '#544e48',
          700: '#3d3935',
          800: '#272421',
          900: '#1b1916',
          950: '#0f0d0b',
        },
        primary: {
          color: '{primary.900}',
          contrastColor: '#f5f4f0',
          hoverColor: '{primary.700}',
          activeColor: '{primary.600}',
        },
        highlight: {
          background: '{primary.900}',
          focusBackground: '{primary.700}',
          color: '#f5f4f0',
          focusColor: '#f5f4f0',
        },
      },
    },
  },
  components: {
    button: {
      root: {
        paddingX: '1.25rem',
        paddingY: '0.85rem',
        label: { fontWeight: '600' },
      },
    },
    datatable: {
      headerCell: { background: 'transparent', color: '{text.muted.color}' },
      bodyCell: { padding: '0.5rem 0.75rem' },
    },
    dialog: {
      title: { fontSize: '1.25rem', fontWeight: '800' },
    },
  },
});

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withNavigationErrorHandler(alFallarLaNavegacion)),
    provideHttpClient(withInterceptors([errorInterceptor, authInterceptor])),
    provideAnimationsAsync(),
    providePrimeNG({
      theme: { preset: FashionStorePreset, options: { darkModeSelector: '.fs-oscuro' } },
      license: environment.primeuiLicense,
    }),
    MessageService,
    // PWA (E13): el Service Worker solo existe en las compilaciones optimizadas (`ng serve` no lo registra).
    // Precachea la aplicación y NUNCA respuestas autenticadas: ver ngsw-config.json.
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
    // Restaura la sesión (si hay tokens guardados) antes de renderizar,
    // para que las guardas de ruta ya tengan roles/permisos disponibles.
    provideAppInitializer(() => {
      const authService = inject(AuthService);
      const restauracion = authService.restaurarSesion();
      if (!restauracion) {
        return of(null);
      }
      return restauracion.pipe(catchError(() => of(null)));
    }),
  ],
};

import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, finalize, shareReplay, tap } from 'rxjs';
import { environment } from '../../environments/environment';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { RecuperarRespuesta, RegistroRequest, TokenRespuesta, Usuario, UsuarioYo } from './models/seguridad.models';

const CLAVE_ACCESS_TOKEN = 'fs_access_token';
const CLAVE_REFRESH_TOKEN = 'fs_refresh_token';

/** Rol global del superadministrador de la plataforma (`core/permisos.py`). */
export const ROL_SUPERADMINISTRADOR = 'superadministrador';

/** Entrada del personal (administrador, encargado, cajero y superadministrador). */
export const RUTA_LOGIN_PERSONAL = '/admin/login';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly usuarioActual = signal<UsuarioYo | null>(null);
  private refrescoEnCurso$: Observable<TokenRespuesta> | null = null;

  readonly usuario = this.usuarioActual.asReadonly();
  readonly estaAutenticado = computed(() => this.usuarioActual() !== null);
  readonly permisos = computed(() => this.usuarioActual()?.permisos ?? []);
  readonly roles = computed(() => this.usuarioActual()?.roles ?? []);
  /** Empresa de la sesión (null = sin sesión o superadministrador de la plataforma). */
  readonly empresaId = computed(() => this.usuarioActual()?.empresa_id ?? null);
  /** Código de la empresa de la sesión: lo que se compara con la tienda actual (/t/:codigo). */
  readonly empresaCodigo = computed(() => this.usuarioActual()?.empresa_codigo ?? null);
  /** Superadministrador de la plataforma: rol propio o sesión sin empresa. */
  readonly esSuperadmin = computed(() => {
    const usuario = this.usuarioActual();
    return usuario !== null && (usuario.roles.includes(ROL_SUPERADMINISTRADOR) || usuario.empresa_id === null);
  });
  /** Cuenta de comprador: su único rol es "cliente" (no entra al back office). */
  readonly esSoloCliente = computed(() => {
    const roles = this.roles();
    return roles.length > 0 && roles.every((rol) => rol === 'cliente');
  });

  private readonly tienda = inject(TiendaActualService);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  tienePermiso(codigo: string): boolean {
    return this.permisos().includes(codigo);
  }

  /** `empresa` (código de la tienda) solo se envía cuando viene; sin ella solo entra un superadministrador. */
  login(email: string, password: string, empresa?: string | null): Observable<TokenRespuesta> {
    const cuerpo = empresa ? { empresa, email, password } : { email, password };
    return this.http
      .post<TokenRespuesta>(`${environment.apiUrl}/auth/login`, cuerpo)
      .pipe(
        tap((tokens) => {
          this.guardarTokens(tokens);
        }),
      );
  }

  /** Recarga el usuario (roles y permisos reales) desde /auth/yo. */
  cargarUsuarioActual(): Observable<UsuarioYo> {
    return this.http
      .get<UsuarioYo>(`${environment.apiUrl}/auth/yo`)
      .pipe(tap((usuario) => this.usuarioActual.set(usuario)));
  }

  /** Se llama al iniciar la app: si hay tokens guardados, restaura la sesión. */
  restaurarSesion(): Observable<UsuarioYo> | null {
    if (!this.getAccessToken()) {
      return null;
    }
    return this.cargarUsuarioActual();
  }

  /** Los clientes se registran por tienda: POST /public/{codigo}/registro. */
  registrar(datos: RegistroRequest, codigoTienda: string): Observable<Usuario> {
    return this.http.post<Usuario>(
      `${environment.apiUrl}/public/${encodeURIComponent(codigoTienda)}/registro`,
      datos,
    );
  }

  solicitarRecuperacion(email: string, empresa?: string | null): Observable<RecuperarRespuesta> {
    const cuerpo = empresa ? { email, empresa } : { email };
    return this.http.post<RecuperarRespuesta>(`${environment.apiUrl}/auth/recuperar`, cuerpo);
  }

  confirmarRecuperacion(token: string, password: string): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(`${environment.apiUrl}/auth/recuperar/confirmar`, {
      token,
      password,
    });
  }

  /** Borra tokens y usuario, sin navegar a ningún lado. */
  limpiarSesion(): void {
    localStorage.removeItem(CLAVE_ACCESS_TOKEN);
    localStorage.removeItem(CLAVE_REFRESH_TOKEN);
    this.usuarioActual.set(null);
  }

  logout(): void {
    this.limpiarSesion();
    // Dentro de una tienda se vuelve a su login; fuera, al login del personal.
    if (this.tienda.codigo()) {
      this.router.navigate(this.tienda.ruta('login'));
    } else {
      this.router.navigate([RUTA_LOGIN_PERSONAL]);
    }
  }

  private refrescarTokens(): Observable<TokenRespuesta> {
    const refreshToken = this.getRefreshToken();
    return this.http
      .post<TokenRespuesta>(`${environment.apiUrl}/auth/refresh`, { refresh_token: refreshToken })
      .pipe(tap((tokens) => this.guardarTokens(tokens)));
  }

  /**
   * Igual que refrescarTokens(), pero deduplicada: si varias requests
   * reciben 401 casi al mismo tiempo (p. ej. varios GET en paralelo de un
   * dashboard), todas comparten esta misma llamada en vez de disparar cada
   * una su propio POST /auth/refresh. Sin esto, si el backend rota el
   * refresh token, la segunda llamada en paralelo usa un refresh token ya
   * invalidado por la primera y falla, cerrando la sesión de un usuario
   * cuyo access token en realidad sí se pudo renovar (ver W-1, auditoría).
   */
  refrescarTokensCompartido(): Observable<TokenRespuesta> {
    if (!this.refrescoEnCurso$) {
      this.refrescoEnCurso$ = this.refrescarTokens().pipe(
        finalize(() => (this.refrescoEnCurso$ = null)),
        shareReplay(1),
      );
    }
    return this.refrescoEnCurso$;
  }

  guardarTokens(tokens: TokenRespuesta): void {
    localStorage.setItem(CLAVE_ACCESS_TOKEN, tokens.access_token);
    localStorage.setItem(CLAVE_REFRESH_TOKEN, tokens.refresh_token);
  }

  getAccessToken(): string | null {
    return localStorage.getItem(CLAVE_ACCESS_TOKEN);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(CLAVE_REFRESH_TOKEN);
  }
}

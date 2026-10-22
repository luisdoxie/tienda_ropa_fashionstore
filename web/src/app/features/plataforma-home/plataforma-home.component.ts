import { NgTemplateOutlet } from '@angular/common';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputTextModule } from 'primeng/inputtext';
import { Subscription } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import { EmpresaPublica, ResumenTienda } from '../../core/models/empresa.models';
import { SeoService, esUrlHttp } from '../../core/seo.service';
import { calcularPaletaAcento } from '../../core/utils/color';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

/** Acceso del personal (back office). E16 lo cambia a '/admin/login'. */
export const RUTA_ACCESO_PERSONAL = '/login';

// Misma demora que el buscador de catalogo-publico (allá la constante no se exporta).
const DEMORA_BUSQUEDA_MS = 350;

/** Tiendas por página. */
export const TAMANIO_PAGINA_TIENDAS = 12;

/** Lo que pinta una tarjeta: ya validado y con los colores resueltos. */
interface TarjetaTienda {
  codigo: string;
  nombre: string;
  logo: string | null;
  inicial: string;
  /** Color de la franja y del fondo de la inicial; null = acento base de la app. */
  acento: string | null;
  /** Color del texto sobre el acento; null = blanco. */
  textoSobreAcento: string | null;
}

function aTarjeta(tienda: ResumenTienda): TarjetaTienda {
  const paleta = calcularPaletaAcento(tienda.color_acento);
  return {
    codigo: tienda.codigo,
    nombre: tienda.nombre,
    logo: esUrlHttp(tienda.logo_url) ? tienda.logo_url.trim() : null,
    inicial: (tienda.nombre.trim().charAt(0) || '?').toLocaleUpperCase('es'),
    acento: paleta?.acento ?? null,
    textoSobreAcento: paleta?.textoSobreAcento ?? null,
  };
}

/**
 * Página de la plataforma ("/"): el comprador elige una tienda. No hereda el
 * color de ninguna tienda (TiendaRaiz lo limita a su propio elemento).
 */
@Component({
  selector: 'app-plataforma-home',
  standalone: true,
  imports: [NgTemplateOutlet, RouterLink, IconFieldModule, InputIconModule, InputTextModule],
  templateUrl: './plataforma-home.component.html',
  styleUrl: './plataforma-home.component.scss',
})
export class PlataformaHomeComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly tiendaActual = inject(TiendaActualService);
  private readonly seo = inject(SeoService);

  protected readonly rutaAccesoPersonal = RUTA_ACCESO_PERSONAL;
  protected readonly esqueletos = [1, 2, 3, 4, 5, 6];

  protected readonly tiendas = signal<TarjetaTienda[]>([]);
  protected readonly cargando = signal(true);
  protected readonly cargandoMas = signal(false);
  protected readonly error = signal(false);
  protected readonly hayMas = signal(false);
  /** "Volver a <nombre>": la última tienda visitada, si todavía carga bien. */
  protected readonly ultima = signal<TarjetaTienda | null>(null);
  /** Códigos cuyo logo no cargó: se muestra la inicial. */
  protected readonly logosFallidos = signal<ReadonlySet<string>>(new Set());

  private texto = '';
  private pagina = 1;
  private temporizador?: ReturnType<typeof setTimeout>;
  private peticion?: Subscription;

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      clearTimeout(this.temporizador);
      this.peticion?.unsubscribe();
    });
  }

  ngOnInit(): void {
    this.seo.fijarPlataforma();
    this.cargarUltimaTienda();
    this.cargar();
  }

  protected onBuscar(valor: string): void {
    this.texto = valor;
    clearTimeout(this.temporizador);
    this.temporizador = setTimeout(() => this.cargar(), DEMORA_BUSQUEDA_MS);
  }

  /** Primera página: reemplaza la grilla. */
  protected cargar(): void {
    this.peticion?.unsubscribe();
    this.pagina = 1;
    this.cargando.set(true);
    this.cargandoMas.set(false);
    this.error.set(false);
    // Sin toast: el error se muestra en la propia pantalla, con "Reintentar".
    this.peticion = this.pedirPagina(1, true).subscribe({
      next: (filas) => {
        this.tiendas.set(filas.map(aTarjeta));
        this.hayMas.set(filas.length === TAMANIO_PAGINA_TIENDAS);
        this.cargando.set(false);
      },
      error: () => {
        this.tiendas.set([]);
        this.hayMas.set(false);
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  /** Página siguiente: se suma a lo que ya está en pantalla. */
  protected verMas(): void {
    if (this.cargando() || this.cargandoMas() || !this.hayMas()) return;
    this.cargandoMas.set(true);
    const siguiente = this.pagina + 1;
    this.peticion = this.pedirPagina(siguiente, false).subscribe({
      next: (filas) => {
        this.pagina = siguiente;
        this.tiendas.update((actuales) => [...actuales, ...filas.map(aTarjeta)]);
        this.hayMas.set(filas.length === TAMANIO_PAGINA_TIENDAS);
        this.cargandoMas.set(false);
      },
      // Falló "una página más": la grilla que ya se veía queda y el botón sirve para reintentar.
      error: () => this.cargandoMas.set(false),
    });
  }

  protected mostrarLogo(tarjeta: TarjetaTienda): boolean {
    return tarjeta.logo !== null && !this.logosFallidos().has(tarjeta.codigo);
  }

  protected logoFallo(codigo: string): void {
    this.logosFallidos.update((actuales) => new Set(actuales).add(codigo));
  }

  private pedirPagina(pagina: number, sinToast: boolean) {
    const params = new HttpParams()
      .set('q', this.texto.trim())
      .set('pagina', pagina)
      .set('tamanio', TAMANIO_PAGINA_TIENDAS);
    const context = new HttpContext().set(SIN_TOAST_ERROR, sinToast);
    return this.http.get<ResumenTienda[]>(`${environment.apiUrl}/public/tiendas`, { params, context });
  }

  private cargarUltimaTienda(): void {
    const codigo = this.tiendaActual.ultimaTienda();
    if (codigo === null || codigo === '') return;
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    this.http
      .get<EmpresaPublica>(`${environment.apiUrl}/public/${encodeURIComponent(codigo)}/tienda`, { context })
      .subscribe({
        next: (empresa) => {
          if (empresa.disponible !== false) this.ultima.set(aTarjeta(empresa));
        },
        // Si falla (tienda dada de baja, sin red) simplemente no se ofrece.
        error: () => this.ultima.set(null),
      });
  }
}

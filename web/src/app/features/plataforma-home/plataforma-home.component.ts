import { NgTemplateOutlet } from '@angular/common';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { environment } from '../../../environments/environment';
import { RUTA_LOGIN_PERSONAL } from '../../core/auth.service';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import { EmpresaPublica, ResumenTienda } from '../../core/models/empresa.models';
import { SeoService, esUrlHttp } from '../../core/seo.service';
import { calcularPaletaAcento } from '../../core/utils/color';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';
import { MarcaComponent } from '../../shared/marca/marca.component';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

/** Acceso del personal (back office). */
export const RUTA_ACCESO_PERSONAL = RUTA_LOGIN_PERSONAL;

// Misma demora que el buscador de catalogo-publico (allá la constante no se exporta).
const DEMORA_BUSQUEDA_MS = 350;

/** Tiendas por página. */
export const TAMANIO_PAGINA_TIENDAS = 12;

/** Lo que pinta una tarjeta: ya validado y con los colores resueltos. */
interface TarjetaTienda {
  codigo: string;
  nombre: string;
  logo: string | null;
  /** Color de la franja y de las siglas; null = acento base de la app. */
  acento: string | null;
}

/** Un bloque de texto con ícono de la página (banda de confianza, servicios). */
interface ContenidoPlataforma {
  icono: NombreIcono;
  titulo: string;
  texto: string;
}

function aTarjeta(tienda: ResumenTienda): TarjetaTienda {
  const paleta = calcularPaletaAcento(tienda.color_acento);
  return {
    codigo: tienda.codigo,
    nombre: tienda.nombre,
    logo: esUrlHttp(tienda.logo_url) ? tienda.logo_url.trim() : null,
    acento: paleta?.acento ?? null,
  };
}

/**
 * Página de la plataforma ("/"): presenta la plataforma y deja elegir una tienda. No hereda el
 * color de ninguna tienda (TiendaRaiz lo limita a su propio elemento).
 */
@Component({
  selector: 'app-plataforma-home',
  standalone: true,
  imports: [NgTemplateOutlet, RouterLink, IconoComponent, MarcaComponent],
  templateUrl: './plataforma-home.component.html',
  styleUrl: './plataforma-home.component.scss',
})
export class PlataformaHomeComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly tiendaActual = inject(TiendaActualService);
  private readonly seo = inject(SeoService);

  protected readonly rutaAccesoPersonal = RUTA_ACCESO_PERSONAL;
  protected readonly esqueletos = [1, 2, 3, 4, 5, 6];

  protected readonly confianza: readonly ContenidoPlataforma[] = [
    { icono: 'tienda', titulo: 'Una tienda por empresa', texto: 'Cada una con su propia dirección' },
    { icono: 'inventario', titulo: 'Stock por sucursal', texto: 'Siempre al día' },
    { icono: 'tarjeta', titulo: 'Pagos en línea', texto: 'Con QR o PayPal' },
    { icono: 'destellos', titulo: 'Funciones con IA', texto: 'Probador, voz y reportes' },
  ];

  protected readonly servicios: readonly ContenidoPlataforma[] = [
    {
      icono: 'tienda',
      titulo: 'Tienda en línea propia',
      texto:
        'Catálogo, carrito, reservas y compras de tus clientes en la dirección de tu empresa, con tu logo y tu nombre.',
    },
    {
      icono: 'telefono',
      titulo: 'Probador virtual con IA',
      texto: 'Tus clientes suben una foto desde la app y ven cómo les queda la prenda antes de decidir.',
    },
    {
      icono: 'inventario',
      titulo: 'Inventario por sucursal',
      texto: 'Existencias, entradas y salidas por sucursal, con alertas de stock bajo.',
    },
    {
      icono: 'dinero',
      titulo: 'Caja y ventas',
      texto: 'Registra ventas presenciales, controla devoluciones y emite el comprobante.',
    },
    {
      icono: 'grafico',
      titulo: 'Reportes con IA',
      texto: 'Consulta indicadores y pide reportes hablando, sin armar tablas a mano.',
    },
    {
      icono: 'tarjeta',
      titulo: 'Pagos en línea',
      texto: 'Cobra con QR o PayPal y concilia cada pago con su venta.',
    },
  ];

  protected readonly pasos: readonly { numero: string; titulo: string; texto: string }[] = [
    { numero: '01', titulo: 'Te damos de alta', texto: 'Creamos tu empresa, tu plan y tu primer administrador.' },
    {
      numero: '02',
      titulo: 'Cargas tu catálogo',
      texto: 'Productos, tallas, colores, fotos y existencias por sucursal.',
    },
    {
      numero: '03',
      titulo: 'Empiezas a vender',
      texto: 'Tu tienda queda visible en línea y tu equipo trabaja desde el panel.',
    },
  ];

  /** Los dos planes sembrados (sin precio: la plataforma no lo maneja). */
  protected readonly planes: readonly { nombre: string; oscuro: boolean; items: readonly string[] }[] = [
    {
      nombre: 'Básico',
      oscuro: false,
      items: [
        'Hasta 2 sucursales activas',
        'Tienda en línea, inventario y reservas',
        'Caja y ventas',
        'Sin funciones de IA, analítica ni copias de seguridad',
      ],
    },
    {
      nombre: 'Profesional',
      oscuro: true,
      items: [
        'Hasta 10 sucursales activas',
        'Todo lo del plan Básico',
        'Reportes con IA',
        'Analítica con aprendizaje automático (próximamente)',
        'Trabajo sin conexión (próximamente)',
        'Copias de seguridad (próximamente)',
      ],
    },
  ];

  protected readonly tiendas = signal<TarjetaTienda[]>([]);
  protected readonly cargando = signal(true);
  protected readonly cargandoMas = signal(false);
  protected readonly error = signal(false);
  protected readonly hayMas = signal(false);
  /** "Volver a <nombre>": la última tienda visitada, si todavía carga bien. */
  protected readonly ultima = signal<TarjetaTienda | null>(null);

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

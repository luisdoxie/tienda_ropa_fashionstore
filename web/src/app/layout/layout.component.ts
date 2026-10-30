import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Injector,
  OnDestroy,
  OnInit,
  ViewChild,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { PopoverModule } from 'primeng/popover';
import { filter } from 'rxjs';
import { AuthService, ROL_SUPERADMINISTRADOR } from '../core/auth.service';
import { ConectividadService } from '../core/conectividad.service';
import { FuncionPlan } from '../core/models/plan.models';
import { NotificacionesService } from '../core/notificaciones.service';
import { PlanService } from '../core/plan.service';
import { MiEmpresaService } from '../features/mi-empresa/data/mi-empresa.service';
import { AvisoSuscripcionComponent } from '../shared/aviso-suscripcion/aviso-suscripcion.component';
import { IconoComponent } from '../shared/icono/icono.component';
import { NombreIcono } from '../shared/icono/iconos';
import { IndicadorConexionComponent } from '../shared/indicador-conexion/indicador-conexion.component';
import { MarcaComponent } from '../shared/marca/marca.component';

const INTERVALO_NOTIFICACIONES_MS = 20_000;

/** Debajo de este ancho el menú lateral pasa a ser un cajón (igual que en layout.component.scss). */
const CONSULTA_CAJON = '(max-width: 899px)';

/** A dónde lleva un ítem del menú cuyo plan no incluye la funcionalidad. */
export const RUTA_EXPLICACION_PLAN = '/mi-empresa';
export const PARAMS_EXPLICACION_PLAN = { ver: 'funcionalidades' };

export interface ItemMenu {
  etiqueta: string;
  /** Nombre de un `fs-icono` (24 px en el menú). */
  icono: NombreIcono;
  ruta: string;
  permiso?: string;
  /** Solo lo ve ese rol; sin `rol` lo ve el personal de una empresa, nunca el superadministrador. */
  rol?: typeof ROL_SUPERADMINISTRADOR;
  /** Si el plan no la incluye, el ítem sigue en su lugar pero deshabilitado y con candado. */
  funcion?: FuncionPlan;
}

export interface GrupoMenu {
  id: string;
  etiqueta: string;
  items: ItemMenu[];
}

/** Rótulo del menú tal como lo dibuja el canvas: agrupa ítems de las listas de abajo por su ruta. */
interface SeccionDef {
  id: string;
  etiqueta: string;
  /** Las secciones plegables arrancan cerradas, salvo la de la ruta activa. */
  plegable: boolean;
  rutas: string[];
}

interface SeccionVista {
  id: string;
  etiqueta: string;
  plegable: boolean;
  items: ItemVista[];
}

interface ItemVista extends ItemMenu {
  deshabilitado: boolean;
}

interface GrupoVista extends Omit<GrupoMenu, 'items'> {
  items: ItemVista[];
}

export const ITEMS_INICIO: ItemMenu[] = [
  { etiqueta: 'Dashboard', icono: 'dashboard', ruta: '/dashboard' },
  { etiqueta: 'Reportes', icono: 'grafico', ruta: '/reportes', permiso: 'reportes.ver' },
];

export const GRUPOS_MENU: GrupoMenu[] = [
  {
    id: 'organizacion',
    etiqueta: 'Organización',
    items: [
      { etiqueta: 'Usuarios', icono: 'usuarios', ruta: '/usuarios', permiso: 'usuarios.gestionar' },
      { etiqueta: 'Roles', icono: 'escudo', ruta: '/roles', permiso: 'roles.gestionar' },
      { etiqueta: 'Empleados', icono: 'carnet', ruta: '/empleados', permiso: 'organizacion.gestionar' },
      { etiqueta: 'Ciudades', icono: 'ubicacion', ruta: '/ciudades', permiso: 'organizacion.gestionar' },
      { etiqueta: 'Sucursales', icono: 'tienda', ruta: '/sucursales', permiso: 'organizacion.gestionar' },
    ],
  },
  {
    id: 'catalogo',
    etiqueta: 'Catálogo',
    items: [
      { etiqueta: 'Productos', icono: 'camisa', ruta: '/productos', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Categorías', icono: 'categorias', ruta: '/categorias', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Tallas', icono: 'etiqueta', ruta: '/tallas', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Colores', icono: 'paleta', ruta: '/colores', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Temporadas', icono: 'sol', ruta: '/temporadas', permiso: 'catalogo.gestionar' },
      { etiqueta: 'Colecciones', icono: 'imagen', ruta: '/colecciones', permiso: 'catalogo.gestionar' },
    ],
  },
  {
    id: 'ventas',
    etiqueta: 'Ventas',
    items: [
      { etiqueta: 'Caja', icono: 'dinero', ruta: '/caja', permiso: 'ventas.presencial' },
      { etiqueta: 'Promociones', icono: 'promociones', ruta: '/promociones', permiso: 'ventas.gestionar' },
      {
        etiqueta: 'Reservas',
        icono: 'calendario',
        ruta: '/reservas',
        permiso: 'reservas.gestionar_sucursal',
      },
    ],
  },
  {
    // Lo único que ve el superadministrador.
    id: 'plataforma',
    etiqueta: 'Plataforma',
    items: [
      { etiqueta: 'Empresas', icono: 'edificio', ruta: '/plataforma/empresas', rol: ROL_SUPERADMINISTRADOR },
      { etiqueta: 'Planes', icono: 'estrella', ruta: '/plataforma/planes', rol: ROL_SUPERADMINISTRADOR },
      {
        etiqueta: 'Suscripciones',
        icono: 'calendario',
        ruta: '/plataforma/suscripciones',
        rol: ROL_SUPERADMINISTRADOR,
      },
    ],
  },
];

export const ITEMS_FIN: ItemMenu[] = [
  { etiqueta: 'Inventario', icono: 'inventario', ruta: '/inventario', permiso: 'inventario.ver' },
  { etiqueta: 'Proveedores', icono: 'camion', ruta: '/proveedores', permiso: 'abastecimiento.gestionar' },
  { etiqueta: 'Envíos', icono: 'envios', ruta: '/envios', permiso: 'entregas.gestionar' },
  { etiqueta: 'Zonas de envío', icono: 'mapa', ruta: '/zonas-envio', permiso: 'entregas.gestionar' },
  { etiqueta: 'Assets del probador', icono: 'imagen', ruta: '/probador', permiso: 'probador.gestionar' },
  { etiqueta: 'Mi empresa', icono: 'edificio', ruta: '/mi-empresa', permiso: 'empresa.gestionar' },
];

/**
 * Cómo se agrupan los ítems en el menú (canvas Dashboard/Crud). Es solo
 * presentación: qué ítems ve cada persona lo deciden `permiso`, `rol` y
 * `funcion` de las listas de arriba. Un ítem que no esté en ninguna sección
 * (uno nuevo) se agrega al final de Organización.
 */
const SECCIONES_MENU: SeccionDef[] = [
  { id: 'general', etiqueta: 'General', plegable: false, rutas: ['/dashboard', '/caja'] },
  {
    id: 'catalogo',
    etiqueta: 'Catálogo',
    plegable: true,
    rutas: [
      '/productos',
      '/inventario',
      '/categorias',
      '/tallas',
      '/colores',
      '/temporadas',
      '/colecciones',
      '/proveedores',
      '/probador',
    ],
  },
  { id: 'comercial', etiqueta: 'Comercial', plegable: true, rutas: ['/reservas', '/envios', '/zonas-envio', '/promociones'] },
  { id: 'analisis', etiqueta: 'Análisis', plegable: false, rutas: ['/reportes'] },
  {
    id: 'organizacion',
    etiqueta: 'Organización',
    plegable: true,
    rutas: ['/sucursales', '/ciudades', '/empleados', '/usuarios', '/roles', '/mi-empresa'],
  },
  {
    id: 'plataforma',
    etiqueta: 'Plataforma',
    plegable: false,
    rutas: ['/plataforma/empresas', '/plataforma/planes', '/plataforma/suscripciones'],
  },
];
const SECCION_POR_DEFECTO = 'organizacion';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    PopoverModule,
    AvisoSuscripcionComponent,
    IconoComponent,
    IndicadorConexionComponent,
    MarcaComponent,
  ],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly planService = inject(PlanService);
  private readonly miEmpresaService = inject(MiEmpresaService);
  private readonly injector = inject(Injector);
  protected readonly notificacionesService = inject(NotificacionesService);
  private readonly conectividad = inject(ConectividadService);

  protected readonly usuario = this.authService.usuario;
  /** El superadministrador no tiene empresa: sin notificaciones, plan ni aviso de suscripción. */
  protected readonly esSuperadmin = this.authService.esSuperadmin;
  protected readonly rutaExplicacionPlan = RUTA_EXPLICACION_PLAN;
  protected readonly paramsExplicacionPlan = PARAMS_EXPLICACION_PLAN;

  private readonly puedeVer = (item: ItemMenu) => {
    if (this.authService.esSuperadmin()) return item.rol === ROL_SUPERADMINISTRADOR;
    if (item.rol) return false;
    return !item.permiso || this.authService.tienePermiso(item.permiso);
  };

  /** Un ítem cuyo plan no incluye la funcionalidad queda en su lugar, deshabilitado. */
  private readonly aVista = (item: ItemMenu): ItemVista => ({
    ...item,
    deshabilitado: item.funcion !== undefined && !this.planService.incluye(item.funcion),
  });

  protected readonly itemsInicio = computed(() => ITEMS_INICIO.filter(this.puedeVer).map(this.aVista));
  protected readonly itemsFin = computed(() => ITEMS_FIN.filter(this.puedeVer).map(this.aVista));
  protected readonly gruposMenu = computed<GrupoVista[]>(() =>
    GRUPOS_MENU.map((grupo) => ({ ...grupo, items: grupo.items.filter(this.puedeVer).map(this.aVista) })).filter(
      (grupo) => grupo.items.length > 0,
    ),
  );
  /** Nombre del plan para el texto de ayuda de los ítems deshabilitados. */
  protected readonly nombrePlan = this.planService.nombrePlan;

  /** El menú tal como se dibuja: las mismas opciones (ya filtradas por permiso y rol) en las secciones del canvas. */
  protected readonly secciones = computed<SeccionVista[]>(() => {
    const todos: ItemVista[] = [
      ...this.itemsInicio(),
      ...this.gruposMenu().flatMap((grupo) => grupo.items),
      ...this.itemsFin(),
    ];
    const conocidas = new Set(SECCIONES_MENU.flatMap((seccion) => seccion.rutas));
    const secciones: SeccionVista[] = SECCIONES_MENU.map((seccion) => ({
      id: seccion.id,
      etiqueta: seccion.etiqueta,
      plegable: seccion.plegable,
      items: seccion.rutas
        .map((ruta) => todos.find((item) => item.ruta === ruta))
        .filter((item): item is ItemVista => item !== undefined),
    }));
    const nuevas = todos.filter((item) => !conocidas.has(item.ruta));
    secciones.find((seccion) => seccion.id === SECCION_POR_DEFECTO)?.items.push(...nuevas);
    return secciones.filter((seccion) => seccion.items.length > 0);
  });

  /** Marca de la sesión: la empresa de quien entró, o la plataforma para el superadministrador. */
  protected readonly nombreMarca = computed(() =>
    this.esSuperadmin() ? 'FashionStore' : (this.usuario()?.empresa_nombre ?? 'FashionStore'),
  );
  protected readonly logoMarca = signal<string | null>(null);
  protected readonly rolesTexto = computed(() =>
    (this.usuario()?.roles ?? []).map((rol) => rol.charAt(0).toUpperCase() + rol.slice(1)).join(', '),
  );

  /** En pantallas angostas el menú es un cajón que se abre con el botón de la barra. */
  protected readonly menuAbierto = signal(false);
  /** Verdadero mientras la pantalla es angosta (el menú es un cajón). */
  protected readonly pantallaAngosta = signal(false);
  /** Cajón abierto: se comporta como un diálogo modal y el resto de la página queda `inert`. */
  protected readonly cajonActivo = computed(() => this.pantallaAngosta() && this.menuAbierto());
  protected readonly etiquetaCampana = computed(() => {
    const noLeidas = this.notificacionesService.noLeidas();
    return noLeidas > 0 ? `Notificaciones, ${noLeidas} sin leer` : 'Notificaciones';
  });

  @ViewChild('menu') private menu?: ElementRef<HTMLElement>;
  @ViewChild('botonMenu') private botonMenu?: ElementRef<HTMLButtonElement>;
  private consultaAngosta?: MediaQueryList;
  private readonly alCambiarAncho = (evento: MediaQueryListEvent) => this.pantallaAngosta.set(evento.matches);

  private readonly gruposAbiertos = signal<ReadonlySet<string>>(new Set());

  private intervalo?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      this.consultaAngosta = window.matchMedia(CONSULTA_CAJON);
      this.pantallaAngosta.set(this.consultaAngosta.matches);
      this.consultaAngosta.addEventListener('change', this.alCambiarAncho);
    }

    if (!this.authService.esSuperadmin()) {
      this.planService.cargar();
      this.cargarLogo();
      this.notificacionesService.cargar().subscribe();
      // ~20s: "casi en tiempo real" sin WebSockets, mismo mecanismo de
      // polling que ya usa checkout-estado.component.ts para el pago.
      // Sin conexión no se consulta: cada intento fallido sería un aviso de error cada 20 s.
      this.intervalo = setInterval(() => {
        if (this.conectividad.enLinea()) this.notificacionesService.cargar().subscribe();
      }, INTERVALO_NOTIFICACIONES_MS);
    }

    this.abrirGrupoDeRuta(this.router.url);
    this.router.events
      .pipe(
        filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
        // Sin esto, cada vez que un usuario staff navega del back office a
        // la tienda pública y vuelve (LayoutComponent se destruye y se
        // recrea), esta suscripción vieja queda viva para siempre y sigue
        // ejecutando abrirGrupoDeRuta sobre un componente ya destruido.
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((evento) => {
        this.abrirGrupoDeRuta(evento.urlAfterRedirects);
        this.menuAbierto.set(false);
      });
  }

  ngOnDestroy(): void {
    clearInterval(this.intervalo);
    this.consultaAngosta?.removeEventListener('change', this.alCambiarAncho);
  }

  /** El logo solo lo puede leer quien administra la empresa (`/mi-empresa`); sin él queda el monograma. */
  private cargarLogo(): void {
    if (!this.authService.tienePermiso('empresa.gestionar')) return;
    this.miEmpresaService.obtener().subscribe({
      next: (empresa) => this.logoMarca.set(empresa.logo_url),
      error: () => undefined,
    });
  }

  private abrirGrupoDeRuta(url: string): void {
    const seccion = SECCIONES_MENU.find((s) => s.rutas.some((ruta) => url.startsWith(ruta)));
    if (!seccion) return;
    this.gruposAbiertos.update((set) => new Set(set).add(seccion.id));
  }

  alternarMenu(): void {
    if (this.menuAbierto()) this.cerrarMenu(true);
    else this.abrirMenu();
  }

  /** Abre el cajón y lleva el foco a su primera opción visible. */
  abrirMenu(): void {
    this.menuAbierto.set(true);
    afterNextRender(
      () => {
        const candidatos = this.menu?.nativeElement.querySelectorAll<HTMLElement>('a.layout__enlace:not([aria-disabled="true"])');
        Array.from(candidatos ?? [])
          .find((enlace) => enlace.closest('[hidden]') === null)
          ?.focus();
      },
      { injector: this.injector },
    );
  }

  /** Cierra el cajón; con `devolverFoco` el foco vuelve al botón que lo abrió. */
  cerrarMenu(devolverFoco = false): void {
    this.menuAbierto.set(false);
    if (devolverFoco) {
      afterNextRender(() => this.botonMenu?.nativeElement.focus(), { injector: this.injector });
    }
  }

  @HostListener('document:keydown.escape')
  protected alPulsarEscape(): void {
    if (this.menuAbierto()) this.cerrarMenu(true);
  }

  toggleGrupo(id: string): void {
    this.gruposAbiertos.update((set) => {
      const nuevo = new Set(set);
      nuevo.has(id) ? nuevo.delete(id) : nuevo.add(id);
      return nuevo;
    });
  }

  estaAbierto(id: string): boolean {
    const seccion = SECCIONES_MENU.find((s) => s.id === id);
    return seccion !== undefined && !seccion.plegable ? true : this.gruposAbiertos().has(id);
  }

  /** Texto de ayuda del ítem deshabilitado. */
  protected ayudaDeshabilitado(): string {
    const plan = this.nombrePlan();
    return `${plan ? `Tu plan ${plan}` : 'Tu plan'} no incluye esto. Más info en Mi empresa.`;
  }

  marcarLeida(notificacionId: number): void {
    this.notificacionesService.marcarLeida(notificacionId).subscribe();
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}

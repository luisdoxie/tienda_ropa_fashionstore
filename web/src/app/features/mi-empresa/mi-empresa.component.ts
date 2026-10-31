import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  OnInit,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { ProgressBarModule } from 'primeng/progressbar';
import { startWith } from 'rxjs';
import { MiEmpresa, DescripcionFuncion, FUNCIONES_PLAN } from '../../core/models/plan.models';
import { DIAS_AVISO_VENCIMIENTO, PlanService } from '../../core/plan.service';
import { esUrlHttp } from '../../core/seo.service';
import { AcentoSobreOscuro, calcularPaletaAcento } from '../../core/utils/color';
import { formatearFecha } from '../../shared/aviso-suscripcion/aviso-suscripcion.component';
import { IconoComponent } from '../../shared/icono/icono.component';
import { MarcaComponent } from '../../shared/marca/marca.component';
import { MiEmpresaService } from './data/mi-empresa.service';

/** Mismo patrón que `COLOR_ACENTO_PATRON` del backend (`#RRGGBB`). */
export const PATRON_COLOR_ACENTO = /^#[0-9A-Fa-f]{6}$/;

/** Valor de `?ver=` que lleva directo a la lista de funcionalidades. */
export const ANCLA_FUNCIONALIDADES = 'funcionalidades';

const COLOR_POR_DEFECTO_SELECTOR = '#9a3e1f';
/** Modificador de `.fs-chip` de cada estado ('' = gris). */
type ClaseChip = '' | 'fs-chip--exito' | 'fs-chip--advertencia' | 'fs-chip--error';

const ESTADOS: Readonly<Record<string, { texto: string; clase: ClaseChip }>> = {
  activa: { texto: 'Activa', clase: 'fs-chip--exito' },
  vencida: { texto: 'Vencida', clase: 'fs-chip--error' },
  suspendida: { texto: 'Suspendida', clase: 'fs-chip--advertencia' },
  cancelada: { texto: 'Cancelada', clase: '' },
  sin_suscripcion: { texto: 'Sin suscripción', clase: '' },
};

/** Texto de la línea roja cuando la suscripción no está activa. */
const TEXTO_NO_ACTIVA: Readonly<Record<string, string>> = {
  vencida: 'Suscripción vencida',
  suspendida: 'Suscripción suspendida',
  cancelada: 'Suscripción cancelada',
  sin_suscripcion: 'Sin suscripción registrada',
};

const EXPLICACION_NO_ACTIVA: Readonly<Record<string, string>> = {
  vencida: 'Tu suscripción venció. Las operaciones de tu empresa están bloqueadas hasta que se renueve.',
  suspendida: 'Tu suscripción está suspendida. Las operaciones de tu empresa están bloqueadas hasta que se reactive.',
  cancelada: 'Tu suscripción fue cancelada. Las operaciones de tu empresa están bloqueadas.',
  sin_suscripcion: 'Tu empresa no tiene una suscripción registrada. Las operaciones están bloqueadas.',
};

const MENSAJE_CAMPO_SERVIDOR: Readonly<Record<string, string>> = {
  nombre: 'Revisa el nombre: tiene que tener entre 2 y 120 caracteres.',
  logo_url: 'Revisa la dirección del logo.',
  color_acento: 'Revisa el color: tiene que ser del tipo #RRGGBB.',
};

type CampoIdentidad = 'nombre' | 'logo_url' | 'color_acento';

/** El logo, si se escribe, tiene que ser una dirección http o https. */
function logoHttp(control: AbstractControl): ValidationErrors | null {
  const valor = typeof control.value === 'string' ? control.value.trim() : '';
  return valor === '' || esUrlHttp(valor) ? null : { urlHttp: true };
}

/** Sin tildes ni mayúsculas: 'Básico' -> 'basico'. */
function plano(texto: string | null | undefined): string {
  return (texto ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
}

interface VistaPlan {
  nombre: string;
  estado: { texto: string; clase: ClaseChip };
  activa: boolean;
  inicio: string | null;
  vencimiento: string | null;
  textoDias: string | null;
  /** 'rojo' = vencida o no activa, 'ambar' = vence pronto, 'neutro' = con tiempo. */
  tonoDias: 'rojo' | 'ambar' | 'neutro';
  explicacion: string | null;
}

interface VistaLimite {
  maximo: number | null;
  activas: number;
  porcentaje: number;
  lleno: boolean;
  casiLleno: boolean;
}

interface FilaFuncion extends DescripcionFuncion {
  incluida: boolean;
  /** La función existe como bandera del plan, pero todavía no está construida. */
  proximamente: boolean;
}

/** Funcionalidades del plan que aún no existen (analítica ML, trabajo sin conexión, copias de seguridad). */
const FUNCIONES_PROXIMAMENTE: ReadonlySet<string> = new Set(['copias_seguridad']);

/**
 * "Mi empresa": pantalla del administrador de cada empresa. Muestra su plan, los
 * límites y su uso, qué funcionalidades incluye y le deja editar la identidad de
 * su tienda (nombre, logo y color de acento). Responde aunque la suscripción esté
 * vencida o suspendida: justamente ahí hace falta ver el estado.
 *
 * El plan y las funcionalidades vienen de `PlanService`; el cambio de plan lo
 * hace el administrador de la plataforma (no hay pago en línea).
 */
@Component({
  selector: 'app-mi-empresa',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    ButtonModule,
    DialogModule,
    ProgressBarModule,
    IconoComponent,
    MarcaComponent,
  ],
  templateUrl: './mi-empresa.component.html',
  styleUrl: './mi-empresa.component.scss',
})
export class MiEmpresaComponent implements OnInit {
  private readonly servicio = inject(MiEmpresaService);
  protected readonly plan = inject(PlanService);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  protected readonly empresa = signal<MiEmpresa | null>(null);
  private readonly cargandoEmpresa = signal(true);
  private readonly falloEmpresa = signal(false);

  protected readonly cargando = computed(() => this.cargandoEmpresa() || this.plan.cargando());
  protected readonly hayError = computed(() => this.falloEmpresa() || this.plan.error());
  /** Hay datos completos para mostrar la pantalla. */
  protected readonly listo = computed(
    () => !this.cargando() && !this.hayError() && this.empresa() !== null && this.plan.suscripcion() !== null,
  );

  protected readonly dialogoPlan = signal(false);
  protected readonly guardando = signal(false);
  protected readonly guardadoOk = signal(false);
  protected readonly errorGuardar = signal<string | null>(null);
  protected readonly erroresServidor = signal<Partial<Record<CampoIdentidad, string>>>({});
  private readonly logoFallido = signal<string | null>(null);

  protected readonly seccionFunciones = viewChild<ElementRef<HTMLElement>>('seccionFunciones');
  private irAFunciones = false;

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    logo_url: ['', [logoHttp]],
    color_acento: ['', [Validators.pattern(PATRON_COLOR_ACENTO)]],
  });

  private readonly valores = toSignal(this.formulario.valueChanges.pipe(startWith(this.formulario.getRawValue())), {
    requireSync: true,
  });

  // ---- Plan ----

  protected readonly vistaPlan = computed<VistaPlan | null>(() => {
    const suscripcion = this.plan.suscripcion();
    if (suscripcion === null) return null;
    const clave = String(this.plan.estado() ?? suscripcion.estado);
    const activa = clave === 'activa';
    const dias = this.plan.diasParaVencer();

    let textoDias: string | null = null;
    let tonoDias: VistaPlan['tonoDias'] = 'neutro';
    if (!activa) {
      textoDias = TEXTO_NO_ACTIVA[clave] ?? 'Suscripción inactiva';
      tonoDias = 'rojo';
    } else if (dias !== null) {
      if (dias < 0) {
        textoDias = dias === -1 ? 'Venció ayer' : `Venció hace ${-dias} días`;
        tonoDias = 'rojo';
      } else {
        textoDias = dias === 0 ? 'Vence hoy' : dias === 1 ? 'Falta 1 día' : `Faltan ${dias} días`;
        tonoDias = dias <= DIAS_AVISO_VENCIMIENTO ? 'ambar' : 'neutro';
      }
    }

    return {
      nombre: suscripcion.plan_nombre ?? 'Sin plan',
      estado: ESTADOS[clave] ?? { texto: 'Inactiva', clase: '' },
      activa,
      inicio: suscripcion.fecha_inicio ? formatearFecha(suscripcion.fecha_inicio) : null,
      vencimiento: suscripcion.fecha_vencimiento ? formatearFecha(suscripcion.fecha_vencimiento) : null,
      textoDias,
      tonoDias,
      explicacion: activa ? null : (EXPLICACION_NO_ACTIVA[clave] ?? 'Tu suscripción no está activa. Las operaciones de tu empresa están bloqueadas.'),
    };
  });

  protected readonly vistaLimite = computed<VistaLimite | null>(() => {
    const suscripcion = this.plan.suscripcion();
    if (suscripcion === null) return null;
    const maximo = suscripcion.max_sucursales;
    const activas = suscripcion.sucursales_activas;
    const porcentaje = maximo === null ? 0 : maximo <= 0 ? 100 : Math.min(100, Math.round((activas / maximo) * 100));
    return { maximo, activas, porcentaje, lleno: maximo !== null && activas >= maximo, casiLleno: porcentaje >= 80 };
  });

  // ---- Funcionalidades ----

  /** Siempre las 8, incluidas o no: ninguna fila se oculta. */
  protected readonly funciones = computed<FilaFuncion[]>(() => {
    const incluidas = this.plan.suscripcion()?.funcionalidades ?? [];
    return FUNCIONES_PLAN.map((funcion) => ({
      ...funcion,
      incluida: incluidas.includes(funcion.id),
      proximamente: FUNCIONES_PROXIMAMENTE.has(funcion.id),
    }));
  });

  /** Dónde se consigue lo que el plan actual no incluye. */
  protected readonly dondeConseguir = computed(() => {
    const suscripcion = this.plan.suscripcion();
    return plano(suscripcion?.plan_codigo ?? suscripcion?.plan_nombre) === 'basico'
      ? 'Disponible en el plan Profesional'
      : 'Disponible en un plan superior';
  });

  protected readonly textoNoIncluido = computed(() => {
    const nombre = this.plan.suscripcion()?.plan_nombre;
    return nombre ? `No incluido en el plan ${nombre}` : 'No incluido en tu plan';
  });

  // ---- Identidad ----

  private readonly colorValido = computed<string | null>(() => {
    const color = this.valores().color_acento ?? '';
    return PATRON_COLOR_ACENTO.test(color) ? color.toLowerCase() : null;
  });

  /** Color para el selector nativo (solo acepta #rrggbb). */
  protected readonly colorSelector = computed(() => this.colorValido() ?? COLOR_POR_DEFECTO_SELECTOR);
  /** El color elegido es válido pero la tienda no lo usará: contrasta poco con blanco. */
  protected readonly colorPocoContraste = computed(() => {
    const color = this.colorValido();
    return color !== null && calcularPaletaAcento(color) === null;
  });
  /** La paleta que de verdad usará la tienda; null = el color base de FashionStore. */
  private readonly paletaVista = computed(() => calcularPaletaAcento(this.colorValido()));
  /** Marca de la vista previa: el color elegido solo si la tienda lo va a usar. */
  protected readonly chipFondo = computed(() => this.paletaVista()?.acento ?? null);
  protected readonly chipTexto = computed(() => this.paletaVista()?.textoSobreAcento ?? null);
  /** Acento de la portada oscura de la vista previa (null = lima base). */
  protected readonly acentoVista = computed<AcentoSobreOscuro | null>(() => this.paletaVista()?.sobreOscuro ?? null);
  /** Logo guardado de la empresa para la cabecera (solo http/https). */
  protected readonly logoCabecera = computed(() => {
    const url = this.empresa()?.logo_url;
    return esUrlHttp(url) ? url.trim() : null;
  });
  protected readonly chipLogo = computed(() => {
    const url = (this.valores().logo_url ?? '').trim();
    return esUrlHttp(url) && url !== this.logoFallido() ? url : null;
  });
  protected readonly chipInicial = computed(
    () => ((this.valores().nombre ?? '').trim().charAt(0) || '?').toLocaleUpperCase('es'),
  );

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.irAFunciones = params.get('ver') === ANCLA_FUNCIONALIDADES;
      this.desplazarSiCorresponde();
    });
    effect(() => {
      if (this.listo()) untracked(() => this.desplazarSiCorresponde());
    });
    // Cualquier cambio en el formulario borra el aviso de "guardado" y los errores del servidor.
    this.formulario.valueChanges.pipe(takeUntilDestroyed()).subscribe(() => {
      this.guardadoOk.set(false);
      this.errorGuardar.set(null);
      this.erroresServidor.set({});
    });
  }

  ngOnInit(): void {
    this.cargar();
  }

  /** Pide la empresa y el plan. Ambos errores se muestran en la pantalla, con "Reintentar". */
  protected cargar(): void {
    this.cargandoEmpresa.set(true);
    this.falloEmpresa.set(false);
    this.servicio
      .obtener()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (empresa) => {
          this.empresa.set(empresa);
          this.cargarFormulario(empresa);
          this.cargandoEmpresa.set(false);
        },
        error: () => {
          this.cargandoEmpresa.set(false);
          this.falloEmpresa.set(true);
        },
      });
    this.plan
      .consultar()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ error: () => undefined });
  }

  protected abrirDialogoPlan(): void {
    this.dialogoPlan.set(true);
  }

  protected alElegirColor(valor: string): void {
    this.formulario.controls.color_acento.setValue(valor);
    this.formulario.controls.color_acento.markAsDirty();
  }

  protected quitarColor(): void {
    this.formulario.controls.color_acento.setValue('');
    this.formulario.controls.color_acento.markAsDirty();
  }

  protected logoNoCargo(): void {
    this.logoFallido.set(this.chipLogo());
  }

  protected errorDe(campo: CampoIdentidad): string | null {
    const control = this.formulario.controls[campo];
    const servidor = this.erroresServidor()[campo];
    if (servidor) return servidor;
    if (!control.invalid || !(control.touched || control.dirty)) return null;
    if (control.hasError('required')) return 'Escribe el nombre de tu empresa.';
    if (control.hasError('minlength')) return 'El nombre tiene que tener al menos 2 caracteres.';
    if (control.hasError('maxlength')) return 'El nombre puede tener hasta 120 caracteres.';
    if (control.hasError('urlHttp')) return 'Escribe una dirección que empiece con http:// o https://.';
    if (control.hasError('pattern')) return 'Usa el formato #RRGGBB, por ejemplo #9A3E1F.';
    return null;
  }

  protected guardar(): void {
    if (this.guardando()) return;
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }
    const valores = this.formulario.getRawValue();
    const logo = valores.logo_url.trim();
    const color = valores.color_acento.trim();

    this.guardando.set(true);
    this.guardadoOk.set(false);
    this.errorGuardar.set(null);
    this.erroresServidor.set({});
    this.servicio
      .actualizar({ nombre: valores.nombre.trim(), logo_url: logo === '' ? null : logo, color_acento: color === '' ? null : color })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (empresa) => {
          this.guardando.set(false);
          this.empresa.set(empresa);
          this.cargarFormulario(empresa);
          this.guardadoOk.set(true);
        },
        error: (error: unknown) => {
          this.guardando.set(false);
          this.mostrarErrorGuardar(error);
        },
      });
  }

  private cargarFormulario(empresa: MiEmpresa): void {
    this.formulario.reset({
      nombre: empresa.nombre,
      logo_url: empresa.logo_url ?? '',
      color_acento: empresa.color_acento ?? '',
    });
    this.logoFallido.set(null);
  }

  /** Un 422 se reparte entre los campos; cualquier otro error va en una línea junto al botón. */
  private mostrarErrorGuardar(error: unknown): void {
    const detalle = error instanceof HttpErrorResponse ? error.error?.detail : null;
    if (Array.isArray(detalle)) {
      const porCampo: Partial<Record<CampoIdentidad, string>> = {};
      for (const item of detalle) {
        const campo = Array.isArray(item?.loc) ? String(item.loc[item.loc.length - 1]) : '';
        if (campo in MENSAJE_CAMPO_SERVIDOR) porCampo[campo as CampoIdentidad] = MENSAJE_CAMPO_SERVIDOR[campo];
      }
      if (Object.keys(porCampo).length > 0) {
        this.erroresServidor.set(porCampo);
        return;
      }
    }
    this.errorGuardar.set(
      typeof detalle === 'string' && detalle !== ''
        ? detalle
        : 'No pudimos guardar los cambios. Prueba de nuevo en un momento.',
    );
  }

  /** Con `?ver=funcionalidades`, baja suave a esa sección cuando ya está pintada. */
  private desplazarSiCorresponde(): void {
    if (!this.irAFunciones || !this.listo()) return;
    this.irAFunciones = false;
    afterNextRender(
      () => {
        const seccion = this.seccionFunciones()?.nativeElement;
        if (seccion && typeof seccion.scrollIntoView === 'function') {
          seccion.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      },
      { injector: this.injector },
    );
  }
}

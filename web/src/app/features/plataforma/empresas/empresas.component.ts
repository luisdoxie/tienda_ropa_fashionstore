import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  FormBuilder,
  FormsModule,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { Subject, Subscription, debounceTime, distinctUntilChanged, startWith } from 'rxjs';
import { fechaDesdeIso, fechaLocalIso } from '../../../core/date-utils';
import { esUrlHttp } from '../../../core/seo.service';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { MarcaComponent } from '../../../shared/marca/marca.component';
import {
  EmpresaActualizar,
  EmpresaPlataforma,
  EmpresaRegistrar,
  EmpresaResumen,
  PlanPlataforma,
  etiquetaEstadoSuscripcion,
} from '../../../core/models/plataforma.models';
import { codigoEmpresa } from '../../../core/utils/codigo-empresa';
import { calcularPaletaAcento, normalizarHex } from '../../../core/utils/color';
import { fechaPosteriorAHoy, hoyLocal, sumarDias } from '../data/fechas-plataforma';
import { claseChipEstado } from '../data/chip-estado';
import { PlataformaService } from '../data/plataforma.service';

const TAMANIO_PAGINA = 20;
const ESPERA_BUSQUEDA_MS = 350;
const DIAS_VIGENCIA_INICIAL = 30;
const PLAN_POR_DEFECTO = 'basico';
const COLOR_SELECTOR_VACIO = '#9a3e1f';

type FiltroActivo = 'todas' | 'activas' | 'inactivas';

const OPCIONES_ACTIVO: { label: string; value: FiltroActivo }[] = [
  { label: 'Todas', value: 'todas' },
  { label: 'Activas', value: 'activas' },
  { label: 'Inactivas', value: 'inactivas' },
];

const OPCIONES_ESTADO: { label: string; value: string | null }[] = [
  { label: 'Cualquier suscripción', value: null },
  { label: 'Activa', value: 'activa' },
  { label: 'Vencida', value: 'vencida' },
  { label: 'Suspendida', value: 'suspendida' },
  { label: 'Cancelada', value: 'cancelada' },
  { label: 'Sin suscripción', value: 'sin_suscripcion' },
];

/** Lo que el resumen de alta puede mostrar. La clave inicial va aparte, solo en memoria. */
export interface EmpresaCreada {
  id: number;
  codigo: string;
  nombre: string;
  administrador_email: string | null;
}

function nombreValido(control: AbstractControl): ValidationErrors | null {
  const valor = String(control.value ?? '').trim();
  if (valor.length === 0) return { required: true }; // `required` no ve los espacios solos
  if (valor.length < 2) return { corto: true };
  if (valor.length > 120) return { largo: true };
  return codigoEmpresa(valor) === '' ? { sinCodigo: true } : null;
}

function textoNoVacio(control: AbstractControl): ValidationErrors | null {
  return String(control.value ?? '').trim() === '' ? { required: true } : null;
}

function colorOpcional(control: AbstractControl): ValidationErrors | null {
  const valor = String(control.value ?? '').trim();
  return valor === '' || normalizarHex(valor) !== null ? null : { color: true };
}

function urlOpcional(control: AbstractControl): ValidationErrors | null {
  const valor = String(control.value ?? '').trim();
  return valor === '' || /^https?:\/\/\S+$/i.test(valor) ? null : { url: true };
}

/**
 * Empresas de la plataforma (CU-04, solo superadministrador): lista, alta en un
 * solo diálogo con su administrador, edición de la identidad visual y
 * activar/desactivar. El código sale del nombre y NO cambia después; la vista
 * previa es orientativa (el backend genera el código real).
 */
@Component({
  selector: 'app-empresas',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    ReactiveFormsModule,
    ButtonModule,
    ConfirmDialogModule,
    DatePickerModule,
    DialogModule,
    InputTextModule,
    SelectModule,
    TableModule,
    IconoComponent,
    MarcaComponent,
  ],
  providers: [ConfirmationService],
  templateUrl: './empresas.component.html',
  styleUrl: './empresas.component.scss',
})
export class EmpresasComponent implements OnInit, OnDestroy {
  private readonly servicio = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);
  private readonly messageService = inject(MessageService);
  private readonly confirmationService = inject(ConfirmationService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly opcionesActivo = OPCIONES_ACTIVO;
  protected readonly opcionesEstado = OPCIONES_ESTADO;
  protected readonly manana = sumarDias(hoyLocal(), 1);
  protected readonly etiquetaEstado = etiquetaEstadoSuscripcion;
  protected readonly claseChip = claseChipEstado;

  // ---- Lista y filtros ----
  protected readonly empresas = signal<EmpresaPlataforma[]>([]);
  protected readonly planes = signal<PlanPlataforma[]>([]);
  protected readonly cargando = signal(false);
  protected readonly pagina = signal(1);
  protected readonly hayPaginaSiguiente = signal(false);
  protected readonly busqueda = signal('');
  protected readonly filtroActivo = signal<FiltroActivo>('todas');
  protected readonly filtroEstado = signal<string | null>(null);
  protected readonly filtroPlan = signal<string | null>(null);

  protected readonly opcionesPlanFiltro = computed(() => [
    { label: 'Cualquier plan', value: null as string | null },
    ...this.planes().map((p) => ({ label: p.nombre, value: p.codigo as string | null })),
  ]);

  /** El servidor no filtra por estado ni por plan: se hace sobre la página cargada. */
  protected readonly filas = computed(() => {
    const estado = this.filtroEstado();
    const plan = this.filtroPlan();
    return this.empresas().filter((e) => {
      if (estado !== null && (e.suscripcion_estado ?? 'sin_suscripcion') !== estado) return false;
      if (plan !== null && e.plan_codigo !== plan) return false;
      return true;
    });
  });

  private readonly terminoBusqueda$ = new Subject<string>();
  private peticionLista: Subscription | null = null;

  // ---- Alta ----
  protected readonly dialogoNuevoVisible = signal(false);
  protected readonly guardandoAlta = signal(false);
  protected readonly errorNombre = signal<string | null>(null);
  protected readonly errorAlta = signal<string | null>(null);
  protected readonly creada = signal<EmpresaCreada | null>(null);
  /** Solo en memoria y solo para el resumen de alta: nunca en storage, servicio ni logs. */
  protected readonly claveInicial = signal<string | null>(null);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', [Validators.required, nombreValido]],
    logo_url: ['', urlOpcional],
    color_acento: ['', colorOpcional],
    plan_codigo: [''],
    fecha_vencimiento: [null as Date | null, [Validators.required, fechaPosteriorAHoy]],
    administrador: this.fb.nonNullable.group({
      nombre: ['', [textoNoVacio, Validators.maxLength(60)]],
      apellido: ['', [textoNoVacio, Validators.maxLength(60)]],
      email: ['', [Validators.required, Validators.email]],
      telefono: ['', Validators.maxLength(20)],
      password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
    }),
  });

  private readonly nombreAlta = toSignal(
    this.formulario.controls.nombre.valueChanges.pipe(startWith(this.formulario.controls.nombre.value)),
    { initialValue: '' },
  );
  private readonly colorAlta = toSignal(
    this.formulario.controls.color_acento.valueChanges.pipe(startWith(this.formulario.controls.color_acento.value)),
    { initialValue: '' },
  );

  /** Vista previa del código mientras se escribe el nombre. */
  protected readonly codigoVistaPrevia = computed(() => codigoEmpresa(this.nombreAlta()));
  protected readonly colorSelectorAlta = computed(() => normalizarHex(this.colorAlta()) ?? COLOR_SELECTOR_VACIO);
  /** El color es válido pero contrasta poco con blanco: la tienda usará el color base. */
  protected readonly colorPocoContrasteAlta = computed(() => {
    const color = normalizarHex(this.colorAlta());
    return color !== null && calcularPaletaAcento(color) === null;
  });
  protected readonly planesAsignables = computed(() => this.planes().filter((p) => p.activo));
  protected readonly opcionesPlanAlta = computed(() =>
    this.planesAsignables().map((p) => ({
      label: `${p.nombre} (hasta ${p.max_sucursales} sucursales)`,
      value: p.codigo,
    })),
  );

  // ---- Edición ----
  protected readonly dialogoEditarVisible = signal(false);
  protected readonly guardandoEdicion = signal(false);
  protected readonly editando = signal<EmpresaPlataforma | null>(null);
  protected readonly resumen = signal<EmpresaResumen | null>(null);
  protected readonly cargandoResumen = signal(false);

  protected readonly formularioEdicion = this.fb.nonNullable.group({
    nombre: ['', [Validators.required, nombreValido]],
    logo_url: ['', urlOpcional],
    color_acento: ['', colorOpcional],
  });
  private readonly colorEdicion = toSignal(
    this.formularioEdicion.controls.color_acento.valueChanges.pipe(
      startWith(this.formularioEdicion.controls.color_acento.value),
    ),
    { initialValue: '' },
  );
  protected readonly colorSelectorEdicion = computed(() => normalizarHex(this.colorEdicion()) ?? COLOR_SELECTOR_VACIO);
  protected readonly colorPocoContrasteEdicion = computed(() => {
    const color = normalizarHex(this.colorEdicion());
    return color !== null && calcularPaletaAcento(color) === null;
  });

  constructor() {
    this.terminoBusqueda$
      .pipe(debounceTime(ESPERA_BUSQUEDA_MS), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((termino) => {
        this.busqueda.set(termino);
        this.pagina.set(1);
        this.cargar();
      });

    this.formulario.controls.nombre.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.errorNombre.set(null));
  }

  ngOnInit(): void {
    this.servicio.listarPlanes().subscribe({ next: (planes) => this.planes.set(planes), error: () => undefined });
    this.cargar();
  }

  ngOnDestroy(): void {
    this.limpiarClave();
  }

  // ---- Lista ----

  protected cargar(): void {
    this.peticionLista?.unsubscribe();
    this.cargando.set(true);
    const filtro = this.filtroActivo();
    this.peticionLista = this.servicio
      .listarEmpresas({
        q: this.busqueda(),
        activo: filtro === 'todas' ? undefined : filtro === 'activas',
        pagina: this.pagina(),
        tamanio: TAMANIO_PAGINA,
      })
      .subscribe({
        next: (empresas) => {
          this.empresas.set(empresas);
          this.hayPaginaSiguiente.set(empresas.length === TAMANIO_PAGINA);
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
  }

  protected escribirBusqueda(valor: string): void {
    this.terminoBusqueda$.next(valor.trim());
  }

  protected cambiarFiltroActivo(valor: FiltroActivo): void {
    this.filtroActivo.set(valor);
    this.pagina.set(1);
    this.cargar();
  }

  protected irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.update((p) => p - 1);
      this.cargar();
    }
  }

  protected irAPaginaSiguiente(): void {
    if (this.hayPaginaSiguiente()) {
      this.pagina.update((p) => p + 1);
      this.cargar();
    }
  }

  protected nombrePlan(codigo: string | null): string {
    if (!codigo) return '—';
    return this.planes().find((p) => p.codigo === codigo)?.nombre ?? codigo;
  }

  protected fecha(iso: string | null): Date | null {
    return iso ? fechaDesdeIso(iso) : null;
  }

  /** El logo solo se usa si es http/https; si no, la marca muestra las siglas. */
  protected logoValido(url: string | null): string | null {
    return esUrlHttp(url) ? url.trim() : null;
  }

  protected urlTienda(codigo: string): string {
    return `/t/${codigo}`;
  }

  protected urlTiendaCompleta(codigo: string): string {
    const origen = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origen}/t/${codigo}`;
  }

  // ---- Activar / desactivar ----

  protected pedirCambioActivo(empresa: EmpresaPlataforma): void {
    const desactivar = empresa.activo;
    this.confirmationService.confirm({
      header: desactivar ? `Desactivar ${empresa.nombre}` : `Activar ${empresa.nombre}`,
      icon: 'pi pi-exclamation-triangle',
      message: desactivar
        ? 'La tienda dejará de verse y su personal no podrá operar.'
        : 'La tienda volverá a verse y su personal podrá operar.',
      acceptLabel: desactivar ? 'Sí, desactivar' : 'Sí, activar',
      rejectLabel: 'Cancelar',
      accept: () => this.cambiarActivo(empresa, !desactivar),
    });
  }

  private cambiarActivo(empresa: EmpresaPlataforma, activo: boolean): void {
    this.servicio.actualizarEmpresa(empresa.id, { activo }).subscribe({
      next: () => {
        this.messageService.add({
          severity: 'success',
          summary: activo ? 'Empresa activada' : 'Empresa desactivada',
          detail: empresa.nombre,
        });
        this.cargar();
      },
      // El rechazo del backend ya lo muestra el manejo global de errores.
      error: () => undefined,
    });
  }

  // ---- Alta ----

  protected abrirNueva(): void {
    this.limpiarClave();
    this.creada.set(null);
    this.errorNombre.set(null);
    this.errorAlta.set(null);
    const porDefecto =
      this.planesAsignables().find((p) => p.codigo === PLAN_POR_DEFECTO) ?? this.planesAsignables()[0] ?? null;
    this.formulario.reset({
      nombre: '',
      logo_url: '',
      color_acento: '',
      plan_codigo: porDefecto?.codigo ?? '',
      fecha_vencimiento: sumarDias(hoyLocal(), DIAS_VIGENCIA_INICIAL),
      administrador: { nombre: '', apellido: '', email: '', telefono: '', password: '' },
    });
    this.dialogoNuevoVisible.set(true);
  }

  protected elegirColorAlta(valor: string): void {
    this.formulario.controls.color_acento.setValue(valor);
    this.formulario.controls.color_acento.markAsDirty();
  }

  /** El cuerpo exacto del alta. Los opcionales vacíos no se mandan. */
  protected armarAlta(): EmpresaRegistrar {
    const v = this.formulario.getRawValue();
    const admin = v.administrador;
    const color = normalizarHex(v.color_acento);
    const logo = v.logo_url.trim();
    const telefono = admin.telefono.trim();
    return {
      nombre: v.nombre.trim(),
      ...(v.plan_codigo ? { plan_codigo: v.plan_codigo } : {}),
      fecha_vencimiento: fechaLocalIso(v.fecha_vencimiento!),
      ...(color ? { color_acento: color } : {}),
      ...(logo ? { logo_url: logo } : {}),
      administrador: {
        nombre: admin.nombre.trim(),
        apellido: admin.apellido.trim(),
        email: admin.email.trim(),
        ...(telefono ? { telefono } : {}),
        password: admin.password,
      },
    };
  }

  protected crear(): void {
    if (this.guardandoAlta()) return;
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const alta = this.armarAlta();
    this.errorAlta.set(null);
    this.errorNombre.set(null);
    this.guardandoAlta.set(true);
    this.servicio.registrarEmpresa(alta).subscribe({
      next: (empresa) => {
        this.guardandoAlta.set(false);
        this.claveInicial.set(alta.administrador.password);
        this.creada.set({
          id: empresa.id,
          codigo: empresa.codigo,
          nombre: empresa.nombre,
          administrador_email: empresa.administrador_email ?? alta.administrador.email,
        });
        // La clave sale del formulario apenas se copia a la pantalla de resumen.
        this.formulario.reset();
        this.pagina.set(1);
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardandoAlta.set(false);
        this.mostrarErrorAlta(error);
      },
    });
  }

  /** El toast global ya muestra el error; acá se deja además junto al campo o en el diálogo. */
  private mostrarErrorAlta(error: unknown): void {
    if (!(error instanceof HttpErrorResponse)) return;
    const detalle = typeof error.error?.detail === 'string' ? error.error.detail : null;
    if (error.status === 409 && detalle !== null && /ese nombre/i.test(detalle)) {
      this.errorNombre.set('Ya existe una empresa con ese nombre. Prueba con otro nombre comercial.');
    } else if (detalle !== null) {
      this.errorAlta.set(detalle);
    } else if (error.status === 0) {
      this.errorAlta.set('No se pudo conectar con el servidor.');
    }
  }

  protected cerrarNueva(): void {
    this.dialogoNuevoVisible.set(false);
    this.limpiarAlta();
  }

  /** Cierra el resumen: la clave inicial se borra y no se puede volver a ver. */
  protected limpiarAlta(): void {
    this.limpiarClave();
    this.creada.set(null);
    this.errorNombre.set(null);
    this.errorAlta.set(null);
    this.formulario.reset();
  }

  private limpiarClave(): void {
    this.claveInicial.set(null);
  }

  protected async copiarClave(): Promise<void> {
    const clave = this.claveInicial();
    if (clave === null) return;
    try {
      await navigator.clipboard.writeText(clave);
      this.messageService.add({ severity: 'success', summary: 'Clave copiada', life: 2500 });
    } catch {
      this.messageService.add({ severity: 'warn', summary: 'No se pudo copiar', detail: 'Anótala a mano.', life: 4000 });
    }
  }

  // ---- Edición ----

  protected abrirEditar(empresa: EmpresaPlataforma): void {
    this.editando.set(empresa);
    this.resumen.set(null);
    this.formularioEdicion.reset({
      nombre: empresa.nombre,
      logo_url: empresa.logo_url ?? '',
      color_acento: empresa.color_acento ?? '',
    });
    this.dialogoEditarVisible.set(true);

    this.cargandoResumen.set(true);
    this.servicio.resumenEmpresa(empresa.id).subscribe({
      next: (resumen) => {
        this.resumen.set(resumen);
        this.cargandoResumen.set(false);
      },
      error: () => this.cargandoResumen.set(false),
    });
  }

  protected elegirColorEdicion(valor: string): void {
    this.formularioEdicion.controls.color_acento.setValue(valor);
    this.formularioEdicion.controls.color_acento.markAsDirty();
  }

  protected armarEdicion(): EmpresaActualizar {
    const v = this.formularioEdicion.getRawValue();
    const logo = v.logo_url.trim();
    return {
      nombre: v.nombre.trim(),
      logo_url: logo === '' ? null : logo,
      color_acento: normalizarHex(v.color_acento),
    };
  }

  protected guardarEdicion(): void {
    const empresa = this.editando();
    if (empresa === null || this.guardandoEdicion()) return;
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }

    this.guardandoEdicion.set(true);
    this.servicio.actualizarEmpresa(empresa.id, this.armarEdicion()).subscribe({
      next: () => {
        this.guardandoEdicion.set(false);
        this.dialogoEditarVisible.set(false);
        this.messageService.add({ severity: 'success', summary: 'Empresa actualizada', detail: empresa.nombre });
        this.cargar();
      },
      error: () => this.guardandoEdicion.set(false),
    });
  }
}

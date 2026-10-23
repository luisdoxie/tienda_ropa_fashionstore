import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormArray, FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { TextareaModule } from 'primeng/textarea';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { TooltipModule } from 'primeng/tooltip';
import { forkJoin } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { Proveedor, Recepcion, RecepcionCrear } from '../../core/models/abastecimiento.models';
import {
  AjusteCrear,
  EstadoTransferencia,
  FilaConsolidado,
  FilaValuacion,
  MovimientoInventario,
  Stock,
  Transferencia,
  TransferenciaCrear,
} from '../../core/models/inventario.models';
import { Sucursal } from '../../core/models/organizacion.models';
import { IconoComponent } from '../../shared/icono/icono.component';

type PestaniaInventario =
  | 'consolidado'
  | 'kardex'
  | 'recepcion'
  | 'limites'
  | 'alertas'
  | 'valuacion'
  | 'transferencias';

interface FilaLimite {
  stock: Stock;
  minimo: number;
  maximo: number | null;
}

const ETIQUETAS_ESTADO_TRANSFERENCIA: Record<EstadoTransferencia, string> = {
  pendiente: 'Pendiente',
  en_transito: 'En tránsito',
  recibida: 'Recibida',
  anulada: 'Anulada',
};

const CLASE_ESTADO_TRANSFERENCIA: Record<EstadoTransferencia, string> = {
  pendiente: '',
  en_transito: 'fs-chip--advertencia',
  recibida: 'fs-chip--exito',
  anulada: 'fs-chip--error',
};

@Component({
  selector: 'app-inventario',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    ReactiveFormsModule,
    ButtonModule,
    ConfirmDialogModule,
    DialogModule,
    InputNumberModule,
    InputTextModule,
    SelectModule,
    TableModule,
    TabsModule,
    TextareaModule,
    ToggleSwitchModule,
    TooltipModule,
    IconoComponent,
  ],
  providers: [ConfirmationService],
  templateUrl: './inventario.component.html',
  styleUrl: './inventario.component.scss',
})
export class InventarioComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly fb = inject(FormBuilder);
  private readonly messageService = inject(MessageService);
  private readonly confirmationService = inject(ConfirmationService);
  private readonly authService = inject(AuthService);

  protected etiquetaEstado(estado: EstadoTransferencia): string {
    return ETIQUETAS_ESTADO_TRANSFERENCIA[estado];
  }

  protected claseEstado(estado: EstadoTransferencia): string {
    return CLASE_ESTADO_TRANSFERENCIA[estado];
  }

  protected esBajoMinimo(fila: FilaConsolidado): boolean {
    return fila.cantidad_disponible <= fila.stock_minimo;
  }

  protected readonly puedeGestionarInventario = computed(() =>
    this.authService.tienePermiso('inventario.gestionar'),
  );
  protected readonly puedeGestionarAbastecimiento = computed(() =>
    this.authService.tienePermiso('abastecimiento.gestionar'),
  );

  protected readonly pestania = signal<PestaniaInventario>('consolidado');
  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly proveedores = signal<Proveedor[]>([]);

  // ---- Consolidado --------------------------------------------------------

  protected readonly filtroSucursalConsolidado = signal<number | null>(null);
  protected readonly filtroProductoConsolidado = signal<number | null>(null);
  protected readonly filasConsolidado = signal<FilaConsolidado[]>([]);
  protected readonly cargandoConsolidado = signal(false);
  // Búsqueda y "solo bajo mínimo" se aplican sobre las filas ya cargadas.
  protected readonly textoConsolidado = signal('');
  protected readonly soloBajoMinimo = signal(false);
  protected readonly filasConsolidadoVisibles = computed(() => {
    const texto = this.textoConsolidado().trim().toLowerCase();
    const soloBajo = this.soloBajoMinimo();
    return this.filasConsolidado().filter((fila) => {
      if (soloBajo && !this.esBajoMinimo(fila)) return false;
      if (texto === '') return true;
      return [fila.producto, fila.sku, fila.talla, fila.color, fila.sucursal].some((campo) =>
        String(campo ?? '')
          .toLowerCase()
          .includes(texto),
      );
    });
  });
  protected readonly valorConsolidadoVisible = computed(() =>
    this.filasConsolidadoVisibles().reduce((acumulado, fila) => acumulado + Number(fila.valor_inventario), 0),
  );

  // ---- Kardex ---------------------------------------------------------------

  protected readonly kardexVarianteId = signal<number | null>(null);
  protected readonly kardexSucursalId = signal<number | null>(null);
  protected readonly filasKardex = signal<MovimientoInventario[]>([]);
  protected readonly cargandoKardex = signal(false);
  protected readonly kardexConsultado = signal(false);

  // ---- Recepción --------------------------------------------------------------

  protected readonly formularioRecepcion = this.fb.nonNullable.group({
    codigo: ['', Validators.required],
    proveedor_id: [null as number | null, Validators.required],
    sucursal_id: [null as number | null, Validators.required],
    orden_compra_id: [null as number | null],
    observacion: [''],
    detalle: this.fb.array([this.crearLineaRecepcion()]),
  });
  protected readonly recepcionesRecientes = signal<Recepcion[]>([]);

  // ---- Límites (en lote) --------------------------------------------------------

  protected readonly filtroSucursalLimites = signal<number | null>(null);
  protected readonly filasLimites = signal<FilaLimite[]>([]);
  protected readonly cargandoLimites = signal(false);
  protected readonly guardandoLimites = signal(false);

  // ---- Alertas ------------------------------------------------------------------

  protected readonly filtroSucursalAlertas = signal<number | null>(null);
  protected readonly filasAlertas = signal<FilaConsolidado[]>([]);
  protected readonly cargandoAlertas = signal(false);

  // ---- Valuación ----------------------------------------------------------------

  protected readonly filtroSucursalValuacion = signal<number | null>(null);
  protected readonly filasValuacion = signal<FilaValuacion[]>([]);
  protected readonly cargandoValuacion = signal(false);
  protected readonly valuacionTotal = computed(() =>
    this.filasValuacion().reduce((acumulado, fila) => acumulado + Number(fila.valor_total), 0),
  );

  // ---- Transferencias -------------------------------------------------------------

  protected readonly filtroSucursalTransferencias = signal<number | null>(null);
  protected readonly filasTransferencias = signal<Transferencia[]>([]);
  protected readonly cargandoTransferencias = signal(false);
  protected readonly dialogoTransferenciaVisible = signal(false);
  protected readonly formularioTransferencia = this.fb.nonNullable.group({
    codigo: ['', Validators.required],
    sucursal_origen_id: [null as number | null, Validators.required],
    sucursal_destino_id: [null as number | null, Validators.required],
    detalle: this.fb.array([this.crearLineaTransferencia()]),
  });

  // ---- Ajuste (se abre desde una fila del consolidado) ---------------------------

  protected readonly dialogoAjusteVisible = signal(false);
  protected readonly filaAjustando = signal<FilaConsolidado | null>(null);
  protected readonly formularioAjuste = this.fb.nonNullable.group({
    cantidad: [0, Validators.required],
    observacion: [''],
  });

  ngOnInit(): void {
    this.http
      .get<Sucursal[]>(`${environment.apiUrl}/sucursales?pagina=1&tamanio=100`)
      .subscribe((sucursales) => this.sucursales.set(sucursales));

    if (this.puedeGestionarAbastecimiento()) {
      this.http
        .get<Proveedor[]>(`${environment.apiUrl}/proveedores?pagina=1&tamanio=100`)
        .subscribe((proveedores) => this.proveedores.set(proveedores));
      this.cargarRecepcionesRecientes();
    }

    this.buscarConsolidado();
    this.buscarTransferencias();
  }

  cambiarPestania(valor: string): void {
    const pestania = valor as PestaniaInventario;
    this.pestania.set(pestania);
    // Alertas y valuación no dependen de una selección previa del usuario
    // (a diferencia de kardex/límites, que necesitan variante o sucursal
    // elegidas primero): se cargan solas la primera vez que se entra.
    if (pestania === 'alertas' && this.filasAlertas().length === 0) {
      this.buscarAlertas();
    }
    if (pestania === 'valuacion' && this.filasValuacion().length === 0) {
      this.buscarValuacion();
    }
  }

  // ---- Consolidado --------------------------------------------------------

  buscarConsolidado(): void {
    this.cargandoConsolidado.set(true);
    let params = new HttpParams();
    if (this.filtroSucursalConsolidado() !== null) {
      params = params.set('sucursal_id', this.filtroSucursalConsolidado()!);
    }
    if (this.filtroProductoConsolidado() !== null) {
      params = params.set('producto_id', this.filtroProductoConsolidado()!);
    }
    this.http.get<FilaConsolidado[]>(`${environment.apiUrl}/inventario/consolidado`, { params }).subscribe({
      next: (filas) => {
        this.filasConsolidado.set(filas);
        this.cargandoConsolidado.set(false);
      },
      error: () => this.cargandoConsolidado.set(false),
    });
  }

  verKardex(fila: FilaConsolidado): void {
    this.kardexVarianteId.set(fila.variante_id);
    this.kardexSucursalId.set(fila.sucursal_id);
    this.pestania.set('kardex');
    this.buscarKardex();
  }

  abrirAjuste(fila: FilaConsolidado): void {
    this.filaAjustando.set(fila);
    this.formularioAjuste.reset({ cantidad: 0, observacion: '' });
    this.dialogoAjusteVisible.set(true);
  }

  guardarAjuste(): void {
    const fila = this.filaAjustando();
    if (!fila || this.formularioAjuste.invalid) {
      this.formularioAjuste.markAllAsTouched();
      return;
    }
    const valores = this.formularioAjuste.getRawValue();
    if (valores.cantidad === 0) {
      this.messageService.add({ severity: 'warn', summary: 'La cantidad no puede ser cero' });
      return;
    }
    const payload: AjusteCrear = {
      variante_id: fila.variante_id,
      sucursal_id: fila.sucursal_id,
      cantidad: valores.cantidad,
      observacion: valores.observacion || undefined,
    };
    this.http.post(`${environment.apiUrl}/inventario/ajustes`, payload).subscribe(() => {
      this.dialogoAjusteVisible.set(false);
      this.messageService.add({ severity: 'success', summary: 'Ajuste registrado' });
      this.buscarConsolidado();
      this.buscarAlertas();
    });
  }

  // ---- Kardex ---------------------------------------------------------------

  buscarKardex(): void {
    const varianteId = this.kardexVarianteId();
    const sucursalId = this.kardexSucursalId();
    if (varianteId === null || sucursalId === null) {
      return;
    }
    this.cargandoKardex.set(true);
    const params = new HttpParams().set('variante_id', varianteId).set('sucursal_id', sucursalId);
    this.http.get<MovimientoInventario[]>(`${environment.apiUrl}/inventario/movimientos`, { params }).subscribe({
      next: (filas) => {
        this.filasKardex.set(filas);
        this.kardexConsultado.set(true);
        this.cargandoKardex.set(false);
      },
      error: () => this.cargandoKardex.set(false),
    });
  }

  // ---- Recepción --------------------------------------------------------------

  private crearLineaRecepcion() {
    return this.fb.nonNullable.group({
      variante_id: [null as number | null, Validators.required],
      cantidad: [1, [Validators.required, Validators.min(1)]],
      costo_unitario: [0, [Validators.required, Validators.min(0)]],
    });
  }

  protected get lineasRecepcion(): FormArray {
    return this.formularioRecepcion.get('detalle') as FormArray;
  }

  /** Deja el FormArray con una sola línea, en blanco. A propósito NO hace
   * `clear()` + `push()` de entrada: si ya existe una fila la reutiliza con
   * `reset()`, porque reemplazar el FormGroup por una instancia nueva deja
   * a `formControlName` de esa fila apuntando al control viejo la próxima
   * vez que se abre este formulario (el diálogo/panel no se destruye entre
   * usos, así que las directivas de forms no se vuelven a inicializar). */
  private reiniciarLineasRecepcion(): void {
    while (this.lineasRecepcion.length > 1) {
      this.lineasRecepcion.removeAt(this.lineasRecepcion.length - 1);
    }
    if (this.lineasRecepcion.length === 0) {
      this.lineasRecepcion.push(this.crearLineaRecepcion());
    } else {
      this.lineasRecepcion.at(0).reset({ variante_id: null, cantidad: 1, costo_unitario: 0 });
    }
  }

  agregarLineaRecepcion(): void {
    this.lineasRecepcion.push(this.crearLineaRecepcion());
  }

  quitarLineaRecepcion(indice: number): void {
    if (this.lineasRecepcion.length > 1) {
      this.lineasRecepcion.removeAt(indice);
    }
  }

  registrarRecepcion(): void {
    if (this.formularioRecepcion.invalid) {
      this.formularioRecepcion.markAllAsTouched();
      return;
    }
    const valores = this.formularioRecepcion.getRawValue();
    const payload: RecepcionCrear = {
      codigo: valores.codigo,
      proveedor_id: valores.proveedor_id!,
      sucursal_id: valores.sucursal_id!,
      orden_compra_id: valores.orden_compra_id ?? undefined,
      observacion: valores.observacion || undefined,
      detalle: valores.detalle.map((linea) => ({
        variante_id: linea.variante_id!,
        cantidad: linea.cantidad,
        costo_unitario: linea.costo_unitario,
      })),
    };

    this.http.post<Recepcion>(`${environment.apiUrl}/recepciones`, payload).subscribe((recepcion) => {
      this.messageService.add({
        severity: 'success',
        summary: 'Recepción registrada',
        detail: recepcion.codigo,
      });
      this.formularioRecepcion.reset({
        codigo: '',
        proveedor_id: null,
        sucursal_id: null,
        orden_compra_id: null,
        observacion: '',
      });
      this.reiniciarLineasRecepcion();
      this.cargarRecepcionesRecientes();
      this.buscarConsolidado();
    });
  }

  private cargarRecepcionesRecientes(): void {
    this.http
      .get<Recepcion[]>(`${environment.apiUrl}/recepciones`)
      .subscribe((recepciones) => this.recepcionesRecientes.set(recepciones.slice(0, 10)));
  }

  // ---- Límites (en lote) --------------------------------------------------------

  buscarLimites(): void {
    const sucursalId = this.filtroSucursalLimites();
    if (sucursalId === null) {
      return;
    }
    this.cargandoLimites.set(true);
    this.http.get<Stock[]>(`${environment.apiUrl}/inventario/sucursal/${sucursalId}`).subscribe({
      next: (filas) => {
        this.filasLimites.set(
          filas.map((stock) => ({ stock, minimo: stock.stock_minimo, maximo: stock.stock_maximo })),
        );
        this.cargandoLimites.set(false);
      },
      error: () => this.cargandoLimites.set(false),
    });
  }

  guardarLimites(): void {
    const cambiadas = this.filasLimites().filter(
      (fila) => fila.minimo !== fila.stock.stock_minimo || fila.maximo !== fila.stock.stock_maximo,
    );
    if (cambiadas.length === 0) {
      this.messageService.add({ severity: 'info', summary: 'No hay cambios para guardar' });
      return;
    }

    this.guardandoLimites.set(true);
    const peticiones = cambiadas.map((fila) =>
      this.http.put(`${environment.apiUrl}/inventario/stock/${fila.stock.id}/limites`, {
        stock_minimo: fila.minimo,
        stock_maximo: fila.maximo,
      }),
    );
    forkJoin(peticiones).subscribe({
      next: () => {
        this.guardandoLimites.set(false);
        this.messageService.add({ severity: 'success', summary: `${cambiadas.length} fila(s) actualizadas` });
        this.buscarLimites();
      },
      error: () => this.guardandoLimites.set(false),
    });
  }

  // ---- Alertas ------------------------------------------------------------------

  buscarAlertas(): void {
    this.cargandoAlertas.set(true);
    let params = new HttpParams();
    if (this.filtroSucursalAlertas() !== null) {
      params = params.set('sucursal_id', this.filtroSucursalAlertas()!);
    }
    this.http.get<FilaConsolidado[]>(`${environment.apiUrl}/inventario/alertas`, { params }).subscribe({
      next: (filas) => {
        this.filasAlertas.set(filas);
        this.cargandoAlertas.set(false);
      },
      error: () => this.cargandoAlertas.set(false),
    });
  }

  // ---- Valuación ----------------------------------------------------------------

  buscarValuacion(): void {
    this.cargandoValuacion.set(true);
    let params = new HttpParams();
    if (this.filtroSucursalValuacion() !== null) {
      params = params.set('sucursal_id', this.filtroSucursalValuacion()!);
    }
    this.http.get<FilaValuacion[]>(`${environment.apiUrl}/inventario/valuacion`, { params }).subscribe({
      next: (filas) => {
        this.filasValuacion.set(filas);
        this.cargandoValuacion.set(false);
      },
      error: () => this.cargandoValuacion.set(false),
    });
  }

  // ---- Transferencias -------------------------------------------------------------

  private crearLineaTransferencia() {
    return this.fb.nonNullable.group({
      variante_id: [null as number | null, Validators.required],
      cantidad: [1, [Validators.required, Validators.min(1)]],
    });
  }

  protected get lineasTransferencia(): FormArray {
    return this.formularioTransferencia.get('detalle') as FormArray;
  }

  /** Ver el comentario de reiniciarLineasRecepcion(): reutiliza la fila 0
   * en vez de reemplazarla, porque el diálogo no se destruye entre
   * aperturas y `clear()+push()` dejaría a `formControlName` apuntando a
   * un control viejo. */
  private reiniciarLineasTransferencia(): void {
    while (this.lineasTransferencia.length > 1) {
      this.lineasTransferencia.removeAt(this.lineasTransferencia.length - 1);
    }
    if (this.lineasTransferencia.length === 0) {
      this.lineasTransferencia.push(this.crearLineaTransferencia());
    } else {
      this.lineasTransferencia.at(0).reset({ variante_id: null, cantidad: 1 });
    }
  }

  agregarLineaTransferencia(): void {
    this.lineasTransferencia.push(this.crearLineaTransferencia());
  }

  quitarLineaTransferencia(indice: number): void {
    if (this.lineasTransferencia.length > 1) {
      this.lineasTransferencia.removeAt(indice);
    }
  }

  buscarTransferencias(): void {
    this.cargandoTransferencias.set(true);
    let params = new HttpParams();
    if (this.filtroSucursalTransferencias() !== null) {
      params = params.set('sucursal_id', this.filtroSucursalTransferencias()!);
    }
    this.http.get<Transferencia[]>(`${environment.apiUrl}/transferencias`, { params }).subscribe({
      next: (filas) => {
        this.filasTransferencias.set(filas);
        this.cargandoTransferencias.set(false);
      },
      error: () => this.cargandoTransferencias.set(false),
    });
  }

  abrirNuevaTransferencia(): void {
    this.formularioTransferencia.reset({
      codigo: '',
      sucursal_origen_id: null,
      sucursal_destino_id: null,
    });
    this.reiniciarLineasTransferencia();
    this.dialogoTransferenciaVisible.set(true);
  }

  crearTransferencia(): void {
    if (this.formularioTransferencia.invalid) {
      this.formularioTransferencia.markAllAsTouched();
      return;
    }
    const valores = this.formularioTransferencia.getRawValue();
    const payload: TransferenciaCrear = {
      codigo: valores.codigo,
      sucursal_origen_id: valores.sucursal_origen_id!,
      sucursal_destino_id: valores.sucursal_destino_id!,
      detalle: valores.detalle.map((linea) => ({ variante_id: linea.variante_id!, cantidad: linea.cantidad })),
    };
    this.http.post<Transferencia>(`${environment.apiUrl}/transferencias`, payload).subscribe(() => {
      this.dialogoTransferenciaVisible.set(false);
      this.messageService.add({ severity: 'success', summary: 'Transferencia creada' });
      this.buscarTransferencias();
    });
  }

  enviarTransferencia(transferencia: Transferencia): void {
    this.http.post<Transferencia>(`${environment.apiUrl}/transferencias/${transferencia.id}/enviar`, {}).subscribe(() => {
      this.messageService.add({ severity: 'success', summary: 'Transferencia enviada' });
      this.buscarTransferencias();
      this.buscarConsolidado();
    });
  }

  recibirTransferencia(transferencia: Transferencia): void {
    this.http.post<Transferencia>(`${environment.apiUrl}/transferencias/${transferencia.id}/recibir`, {}).subscribe(() => {
      this.messageService.add({ severity: 'success', summary: 'Transferencia recibida' });
      this.buscarTransferencias();
      this.buscarConsolidado();
    });
  }

  confirmarAnularTransferencia(transferencia: Transferencia): void {
    this.confirmationService.confirm({
      message: `¿Anular la transferencia ${transferencia.codigo}?`,
      header: 'Confirmar',
      icon: 'pi pi-exclamation-triangle',
      acceptLabel: 'Sí, anular',
      rejectLabel: 'Cancelar',
      accept: () => this.anularTransferencia(transferencia),
    });
  }

  private anularTransferencia(transferencia: Transferencia): void {
    this.http.delete<Transferencia>(`${environment.apiUrl}/transferencias/${transferencia.id}`).subscribe(() => {
      this.messageService.add({ severity: 'success', summary: 'Transferencia anulada' });
      this.buscarTransferencias();
    });
  }
}

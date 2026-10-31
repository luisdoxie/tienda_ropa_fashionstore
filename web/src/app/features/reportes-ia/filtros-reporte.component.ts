import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, input, linkedSignal, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePickerModule } from 'primeng/datepicker';
import { InputNumberModule } from 'primeng/inputnumber';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { FiltroCatalogo, SolicitudReporte, SolicitudResuelta } from '../../core/models/reportes-ia.models';
import { IconoComponent } from '../../shared/icono/icono.component';
import {
  CampoFiltro,
  ETIQUETA_FILTRO,
  FormularioFiltros,
  MAX_NOMBRES_POR_FILTRO,
  camposDeCatalogo,
  errorDeFormulario,
  etiquetaDeValor,
  formularioDesdeResuelta,
  solicitudDesdeFormulario,
} from './reportes-ia.util';

interface OpcionEnum {
  label: string;
  value: string | null;
}

/**
 * Filtros editables de un reporte, GENERADOS desde el catálogo del tipo (un tipo nuevo del servidor no obliga a cambiar
 * el web). "Actualizar reporte" arma una `SolicitudReporte` con nombres y fechas y la emite: no interviene la IA.
 * "Restablecer" vuelve al "entendí esto" de la primera respuesta.
 */
@Component({
  selector: 'app-filtros-reporte',
  standalone: true,
  imports: [NgTemplateOutlet, FormsModule, DatePickerModule, InputNumberModule, MultiSelectModule, SelectModule, IconoComponent],
  templateUrl: './filtros-reporte.component.html',
  styleUrl: './filtros-reporte.component.scss',
})
export class FiltrosReporteComponent {
  /** Lo último que el servidor entendió: de aquí salen los valores del formulario. */
  readonly solicitud = input.required<SolicitudResuelta>();
  /** El "entendí esto" de la primera respuesta (a lo que vuelve Restablecer). */
  readonly inicial = input<SolicitudResuelta | null>(null);
  /** Filtros del reporte según el catálogo. */
  readonly filtros = input.required<Record<string, FiltroCatalogo>>();
  /** Nombres disponibles; `null` si la lista no se pudo cargar (entonces el filtro es de solo lectura). */
  readonly sucursales = input<string[] | null>(null);
  readonly categorias = input<string[] | null>(null);
  /** El usuario tiene sucursal asignada: el servidor la fuerza y el filtro no se edita. */
  readonly sucursalFija = input(false);
  readonly deshabilitado = input(false);
  readonly ocupado = input(false);

  readonly actualizar = output<SolicitudReporte>();
  readonly restablecer = output<void>();

  protected readonly maxNombres = MAX_NOMBRES_POR_FILTRO;
  protected readonly etiquetas = ETIQUETA_FILTRO;
  protected readonly etiquetaValor = etiquetaDeValor;

  protected readonly form = linkedSignal<FormularioFiltros>(() => formularioDesdeResuelta(this.solicitud()));
  protected readonly campos = computed<CampoFiltro[]>(() => camposDeCatalogo(this.filtros()));
  protected readonly error = computed(() => errorDeFormulario(this.form(), this.filtros()));
  protected readonly bloqueado = computed(() => this.deshabilitado() || this.ocupado());

  protected poner<K extends keyof FormularioFiltros>(clave: K, valor: FormularioFiltros[K]): void {
    this.form.update((actual) => ({ ...actual, [clave]: valor }));
  }

  /** Las opciones de un filtro de lista cerrada; si no es obligatorio se agrega "todos/automático". */
  protected opciones(campo: CampoFiltro): OpcionEnum[] {
    const base = campo.definicion.valores.map((v) => ({ label: etiquetaDeValor(campo.clave, v), value: v }));
    if (campo.definicion.obligatorio) return base;
    const vacio = campo.clave === 'canal' ? 'Todos los canales' : 'Automático';
    return [{ label: vacio, value: null }, ...base];
  }

  /** El filtro de lista se edita solo si hay nombres que elegir y el usuario no está atado a su sucursal. */
  protected editable(clave: 'sucursales' | 'categorias'): boolean {
    if (clave === 'sucursales' && this.sucursalFija()) return false;
    const lista = clave === 'sucursales' ? this.sucursales() : this.categorias();
    return lista !== null && lista.length > 0;
  }

  protected enviar(): void {
    if (this.bloqueado() || this.error() !== null) return;
    const tipo = this.solicitud().tipo_reporte;
    this.actualizar.emit(solicitudDesdeFormulario(tipo, this.form(), this.filtros()));
  }

  protected volver(): void {
    if (this.bloqueado()) return;
    const inicial = this.inicial() ?? this.solicitud();
    this.form.set(formularioDesdeResuelta(inicial));
    this.restablecer.emit();
  }
}

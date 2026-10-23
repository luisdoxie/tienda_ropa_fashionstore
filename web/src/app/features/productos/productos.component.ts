import { DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, FormControl, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { environment } from '../../../environments/environment';
import {
  Categoria,
  CatalogoDetalle,
  Coleccion,
  Color,
  Genero,
  ImagenProducto,
  Material,
  Producto,
  ProductoCrear,
  Talla,
  Temporada,
  VarianteActualizar,
  VarianteAdmin,
  VariantesGenerarRequest,
} from '../../core/models/catalogo.models';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Producto>[] = [
  { campo: 'codigo', encabezado: 'Código' },
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'precio_base', encabezado: 'Precio base' },
  { campo: 'genero', encabezado: 'Género' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

const OPCIONES_GENERO: { label: string; value: Genero }[] = [
  { label: 'Hombre', value: 'hombre' },
  { label: 'Mujer', value: 'mujer' },
  { label: 'Unisex', value: 'unisex' },
  { label: 'Niño', value: 'nino' },
];

@Component({
  selector: 'app-productos',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    FormsModule,
    ButtonModule,
    ConfirmDialogModule,
    DialogModule,
    IconoComponent,
    InputNumberModule,
    InputTextModule,
    SelectModule,
    TablaGenericaComponent,
    ToggleSwitchModule,
  ],
  providers: [ConfirmationService],
  templateUrl: './productos.component.html',
  styleUrl: './productos.component.scss',
})
export class ProductosComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly opcionesGenero = OPCIONES_GENERO;
  protected readonly dialogoVisible = signal(false);
  protected readonly editando = signal<Producto | null>(null);

  protected readonly categorias = signal<Categoria[]>([]);
  protected readonly materiales = signal<Material[]>([]);
  protected readonly temporadas = signal<Temporada[]>([]);
  protected readonly colecciones = signal<Coleccion[]>([]);
  protected readonly tallas = signal<Talla[]>([]);
  protected readonly colores = signal<Color[]>([]);

  protected readonly variantes = signal<VarianteAdmin[]>([]);
  protected readonly imagenes = signal<ImagenProducto[]>([]);
  protected readonly dialogoVariantesVisible = signal(false);
  protected readonly subiendoImagen = signal(false);

  protected archivoImagen: File | null = null;

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Producto>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly confirmationService = inject(ConfirmationService);

  protected readonly formulario = this.fb.nonNullable.group({
    codigo: ['', Validators.required],
    nombre: ['', Validators.required],
    descripcion: [''],
    categoria_id: [null as number | null, Validators.required],
    material_id: [null as number | null],
    temporada_id: [null as number | null],
    coleccion_id: [null as number | null],
    genero: ['unisex' as Genero, Validators.required],
    precio_base: [0, [Validators.required, Validators.min(0)]],
    admite_probador: [false],
    tallas_ids: this.fb.nonNullable.control<number[]>([], Validators.required),
    colores_ids: this.fb.nonNullable.control<number[]>([], Validators.required),
  });

  protected readonly formularioVariantes = this.fb.nonNullable.group({
    tallas_ids: this.fb.nonNullable.control<number[]>([], Validators.required),
    colores_ids: this.fb.nonNullable.control<number[]>([], Validators.required),
  });

  protected readonly formularioImagen = this.fb.nonNullable.group({
    color_id: [null as number | null],
    es_principal: [false],
  });

  ngOnInit(): void {
    this.http.get<Categoria[]>(`${environment.apiUrl}/categorias?pagina=1&tamanio=100`).subscribe((v) => this.categorias.set(v));
    this.http.get<Material[]>(`${environment.apiUrl}/materiales?pagina=1&tamanio=100`).subscribe((v) => this.materiales.set(v));
    this.http.get<Temporada[]>(`${environment.apiUrl}/temporadas?pagina=1&tamanio=100`).subscribe((v) => this.temporadas.set(v));
    this.http.get<Coleccion[]>(`${environment.apiUrl}/colecciones?pagina=1&tamanio=100`).subscribe((v) => this.colecciones.set(v));
    this.http.get<Talla[]>(`${environment.apiUrl}/tallas?pagina=1&tamanio=100`).subscribe((v) => this.tallas.set(v));
    this.http.get<Color[]>(`${environment.apiUrl}/colores?pagina=1&tamanio=100`).subscribe((v) => this.colores.set(v));
  }

  /** Error de un campo obligatorio del formulario del producto, una vez tocado. */
  protected invalido(campo: 'codigo' | 'nombre' | 'categoria_id'): boolean {
    const control = this.formulario.controls[campo];
    return control.invalid && control.touched;
  }

  // Tallas y colores se eligen como chips: cada uno alterna su id en el arreglo del control.
  /** Tallas o colores sin elegir, una vez que el usuario los tocó o intentó guardar. */
  protected sinElegir(control: FormControl<number[]>): boolean {
    return control.touched && control.value.length === 0;
  }

  protected tieneId(control: FormControl<number[]>, id: number): boolean {
    return control.value.includes(id);
  }

  protected alternarId(control: FormControl<number[]>, id: number): void {
    const actual = control.value;
    control.setValue(actual.includes(id) ? actual.filter((valor) => valor !== id) : [...actual, id]);
    control.markAsTouched();
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.variantes.set([]);
    this.imagenes.set([]);
    this.formulario.reset({
      codigo: '',
      nombre: '',
      descripcion: '',
      categoria_id: null,
      material_id: null,
      temporada_id: null,
      coleccion_id: null,
      genero: 'unisex',
      precio_base: 0,
      admite_probador: false,
      tallas_ids: [],
      colores_ids: [],
    });
    this.formulario.controls.tallas_ids.enable();
    this.formulario.controls.colores_ids.enable();
    this.dialogoVisible.set(true);
  }

  abrirEditar(producto: Producto): void {
    this.editando.set(producto);
    // tallas_ids/colores_ids solo existen en ProductoCrear (la combinatoria
    // de variantes se arma una sola vez, al crear) -- sin deshabilitarlos
    // aquí, sus validadores `required` con el array vacío invalidan el
    // formulario entero y "Guardar" no hace nada (mismo gotcha que ya
    // resuelve promociones.component.ts con las líneas de alcance).
    this.formulario.controls.tallas_ids.disable();
    this.formulario.controls.colores_ids.disable();
    this.formulario.reset({
      codigo: producto.codigo,
      nombre: producto.nombre,
      descripcion: producto.descripcion ?? '',
      categoria_id: producto.categoria_id,
      material_id: producto.material_id,
      temporada_id: producto.temporada_id,
      coleccion_id: producto.coleccion_id,
      genero: producto.genero,
      precio_base: producto.precio_base,
      admite_probador: producto.admite_probador,
      tallas_ids: [],
      colores_ids: [],
    });
    this.cargarVariantes(producto.id);
    this.cargarImagenes(producto.id);
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const producto = this.editando();

    if (producto) {
      const datos = {
        codigo: valores.codigo,
        nombre: valores.nombre,
        descripcion: valores.descripcion || null,
        categoria_id: valores.categoria_id!,
        material_id: valores.material_id,
        temporada_id: valores.temporada_id,
        coleccion_id: valores.coleccion_id,
        genero: valores.genero,
        precio_base: valores.precio_base,
        admite_probador: valores.admite_probador,
      };
      this.http.put(`${environment.apiUrl}/productos/${producto.id}`, datos).subscribe(() => {
        this.dialogoVisible.set(false);
        this.tabla.recargar();
      });
      return;
    }

    const datos: ProductoCrear = {
      codigo: valores.codigo,
      nombre: valores.nombre,
      descripcion: valores.descripcion || null,
      categoria_id: valores.categoria_id!,
      material_id: valores.material_id,
      temporada_id: valores.temporada_id,
      coleccion_id: valores.coleccion_id,
      genero: valores.genero,
      precio_base: valores.precio_base,
      admite_probador: valores.admite_probador,
      tallas_ids: valores.tallas_ids,
      colores_ids: valores.colores_ids,
    };
    this.http.post(`${environment.apiUrl}/productos`, datos).subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }

  private cargarVariantes(productoId: number): void {
    this.http
      .get<VarianteAdmin[]>(`${environment.apiUrl}/productos/${productoId}/variantes`)
      .subscribe((variantes) => this.variantes.set(variantes));
  }

  private cargarImagenes(productoId: number): void {
    // No hay GET /imagenes de listado propio -- se reusa el detalle
    // público, que ya trae `imagenes` (mismo endpoint que consume
    // /producto/:id del lado cliente).
    this.http
      .get<CatalogoDetalle>(`${environment.apiUrl}/catalogo/${productoId}`)
      .subscribe((detalle) => this.imagenes.set(detalle.imagenes));
  }

  tallaCodigo(tallaId: number): string {
    return this.tallas().find((t) => t.id === tallaId)?.codigo ?? '';
  }

  colorNombre(colorId: number): string {
    return this.colores().find((c) => c.id === colorId)?.nombre ?? '';
  }

  actualizarPrecioVariante(variante: VarianteAdmin, precio: number | null): void {
    const datos: VarianteActualizar = { precio };
    this.http.put(`${environment.apiUrl}/variantes/${variante.id}`, datos).subscribe(() => {
      const producto = this.editando();
      if (producto) this.cargarVariantes(producto.id);
    });
  }

  alternarActivoVariante(variante: VarianteAdmin, activo: boolean): void {
    const datos: VarianteActualizar = { activo };
    this.http.put(`${environment.apiUrl}/variantes/${variante.id}`, datos).subscribe(() => {
      const producto = this.editando();
      if (producto) this.cargarVariantes(producto.id);
    });
  }

  abrirDialogoVariantes(): void {
    this.formularioVariantes.reset({ tallas_ids: [], colores_ids: [] });
    this.dialogoVariantesVisible.set(true);
  }

  guardarVariantesNuevas(): void {
    const producto = this.editando();
    if (!producto || this.formularioVariantes.invalid) {
      this.formularioVariantes.markAllAsTouched();
      return;
    }
    const datos: VariantesGenerarRequest = this.formularioVariantes.getRawValue();
    this.http
      .post(`${environment.apiUrl}/productos/${producto.id}/variantes`, datos)
      .subscribe(() => {
        this.dialogoVariantesVisible.set(false);
        this.cargarVariantes(producto.id);
      });
  }

  onArchivoSeleccionado(evento: Event): void {
    const input = evento.target as HTMLInputElement;
    this.archivoImagen = input.files?.[0] ?? null;
  }

  subirImagen(): void {
    const producto = this.editando();
    if (!producto || !this.archivoImagen) return;

    const { color_id, es_principal } = this.formularioImagen.getRawValue();
    const cuerpo = new FormData();
    cuerpo.append('archivo', this.archivoImagen);
    if (color_id !== null) cuerpo.append('color_id', String(color_id));
    cuerpo.append('es_principal', String(es_principal));

    this.subiendoImagen.set(true);
    this.http.post(`${environment.apiUrl}/productos/${producto.id}/imagenes`, cuerpo).subscribe({
      next: () => {
        this.subiendoImagen.set(false);
        this.archivoImagen = null;
        this.formularioImagen.reset({ color_id: null, es_principal: false });
        this.cargarImagenes(producto.id);
      },
      error: () => this.subiendoImagen.set(false),
    });
  }

  eliminarImagen(imagen: ImagenProducto): void {
    this.confirmationService.confirm({
      header: 'Confirmar',
      icon: 'pi pi-exclamation-triangle',
      message: '¿Eliminar esta imagen del producto?',
      acceptLabel: 'Sí, eliminar',
      rejectLabel: 'Cancelar',
      accept: () => this.borrarImagen(imagen),
    });
  }

  private borrarImagen(imagen: ImagenProducto): void {
    const producto = this.editando();
    this.http.delete(`${environment.apiUrl}/imagenes/${imagen.id}`).subscribe(() => {
      if (producto) this.cargarImagenes(producto.id);
    });
  }

  marcarPrincipal(imagen: ImagenProducto): void {
    const producto = this.editando();
    this.http.put(`${environment.apiUrl}/imagenes/${imagen.id}/principal`, {}).subscribe(() => {
      if (producto) this.cargarImagenes(producto.id);
    });
  }
}

import { DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { AuthService } from '../../../core/auth.service';
import { CatalogoDetalle, Color, Talla } from '../../../core/models/catalogo.models';
import { Disponibilidad } from '../../../core/models/inventario.models';
import { Sucursal } from '../../../core/models/organizacion.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CarritoService } from '../data/carrito.service';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { ReservaCarritoService } from '../state/reserva-carrito.service';
import { TiendaActualService } from '../state/tienda-actual.service';

@Component({
  selector: 'app-producto-detalle',
  standalone: true,
  imports: [RouterLink, DecimalPipe, IconoComponent],
  templateUrl: './producto-detalle.component.html',
  styleUrl: './producto-detalle.component.scss',
})
export class ProductoDetalleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  protected readonly tienda = inject(TiendaActualService);
  private readonly disponibilidadService = inject(DisponibilidadService);
  private readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  protected readonly authService = inject(AuthService);

  private readonly productoId = Number(this.route.snapshot.paramMap.get('id'));
  protected readonly returnTo = `/producto/${this.productoId}`;

  protected readonly detalle = signal<CatalogoDetalle | null>(null);
  protected readonly tallas = signal<Talla[]>([]);
  protected readonly colores = signal<Color[]>([]);
  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly disponibilidad = signal<Disponibilidad[]>([]);
  protected readonly imagenActiva = signal(0);

  protected readonly cargando = signal(true);
  protected readonly error = signal(false);
  protected readonly agregando = signal(false);
  protected readonly agregado = signal(false);

  protected readonly tallaId = signal<number | null>(null);
  protected readonly colorId = signal<number | null>(null);

  protected readonly tallasDisponibles = computed(() => {
    const ids = new Set(this.detalle()?.variantes.map((v) => v.talla_id) ?? []);
    return this.tallas().filter((t) => ids.has(t.id));
  });

  protected readonly coloresDisponibles = computed(() => {
    const ids = new Set(this.detalle()?.variantes.map((v) => v.color_id) ?? []);
    return this.colores().filter((c) => ids.has(c.id));
  });

  protected readonly colorSeleccionado = computed(() => this.colores().find((c) => c.id === this.colorId()) ?? null);

  protected readonly varianteActiva = computed(() => {
    const tallaId = this.tallaId();
    const colorId = this.colorId();
    if (tallaId === null || colorId === null) return null;
    return this.detalle()?.variantes.find((v) => v.talla_id === tallaId && v.color_id === colorId) ?? null;
  });

  protected readonly precio = computed(() => this.varianteActiva()?.precio_efectivo ?? this.detalle()?.precio_base ?? 0);

  protected readonly imagenes = computed(() => {
    const todas = this.detalle()?.imagenes ?? [];
    const colorId = this.colorId();
    const filtradas = colorId !== null ? todas.filter((img) => img.color_id === null || img.color_id === colorId) : todas;
    return filtradas.length > 0 ? filtradas : todas;
  });

  protected readonly disponibilidadPorSucursal = computed(() => {
    const mapa = new Map(this.disponibilidad().map((d) => [d.sucursal_id, d.cantidad_disponible]));
    return this.sucursales().map((sucursal) => ({ sucursal, cantidad: mapa.get(sucursal.id) ?? 0 }));
  });

  ngOnInit(): void {
    forkJoin({
      detalle: this.http.get<CatalogoDetalle>(this.tienda.urlPublica(`catalogo/${this.productoId}`)),
      tallas: this.http.get<Talla[]>(this.tienda.urlPublica('tallas'), { params: { tamanio: 100 } }),
      colores: this.http.get<Color[]>(this.tienda.urlPublica('colores'), { params: { tamanio: 100 } }),
      sucursales: this.disponibilidadService.sucursales(),
    }).subscribe({
      next: ({ detalle, tallas, colores, sucursales }) => {
        this.detalle.set(detalle);
        this.tallas.set(tallas);
        this.colores.set(colores);
        this.sucursales.set(sucursales);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  seleccionarTalla(id: number): void {
    this.tallaId.set(id);
    this.imagenActiva.set(0);
    this.cargarDisponibilidad();
  }

  seleccionarColor(id: number): void {
    this.colorId.set(id);
    this.imagenActiva.set(0);
    this.cargarDisponibilidad();
  }

  private cargarDisponibilidad(): void {
    const variante = this.varianteActiva();
    if (!variante) {
      this.disponibilidad.set([]);
      return;
    }
    this.disponibilidadService.porVariante(variante.id).subscribe({
      next: (filas) => this.disponibilidad.set(filas),
      error: () => this.disponibilidad.set([]),
    });
  }

  agregarAlCarrito(): void {
    const variante = this.varianteActiva();
    if (!variante || this.agregando()) return;

    this.agregando.set(true);
    this.carritoService.agregar(variante.id, 1).subscribe({
      next: () => {
        this.agregando.set(false);
        this.agregado.set(true);
        setTimeout(() => this.agregado.set(false), 2500);
      },
      error: () => {
        this.agregando.set(false);
      },
    });
  }

  reservarParaProbar(): void {
    const variante = this.varianteActiva();
    const detalle = this.detalle();
    if (!variante || !detalle) return;

    this.reservaCarritoService.agregar({
      varianteId: variante.id,
      productoNombre: detalle.nombre,
      tallaCodigo: this.tallas().find((t) => t.id === variante.talla_id)?.codigo ?? '',
      colorNombre: this.colores().find((c) => c.id === variante.color_id)?.nombre ?? '',
      imagenPrincipal: this.imagenes()[0]?.url ?? null,
    });
  }
}

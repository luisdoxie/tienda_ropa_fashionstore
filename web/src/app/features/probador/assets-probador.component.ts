import { HttpClient } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';
import { environment } from '../../../environments/environment';
import { ActivoProbador, TipoActivoProbador } from '../../core/models/probador.models';

const TIPOS: { label: string; value: TipoActivoProbador }[] = [
  { label: 'Imagen de la prenda (PNG con transparencia)', value: 'overlay_2d' },
  { label: 'Flat-lay para IA', value: 'flatlay_ia' },
  { label: 'Miniatura', value: 'thumb' },
];

const ETIQUETAS_TIPO: Record<TipoActivoProbador, string> = {
  overlay_2d: 'Imagen de la prenda',
  flatlay_ia: 'Flat-lay para IA',
  thumb: 'Miniatura',
};

@Component({
  selector: 'app-assets-probador',
  standalone: true,
  imports: [FormsModule, ButtonModule, InputTextModule, SelectModule, TagModule],
  templateUrl: './assets-probador.component.html',
  styleUrl: './assets-probador.component.scss',
})
export class AssetsProbadorComponent {
  private readonly http = inject(HttpClient);

  protected readonly tipos = TIPOS;

  protected readonly varianteId = signal<number | null>(null);
  protected readonly assets = signal<ActivoProbador[]>([]);
  protected readonly assetSeleccionado = signal<ActivoProbador | null>(null);

  protected readonly tipoNuevo = signal<TipoActivoProbador>('overlay_2d');
  protected archivoNuevo: File | null = null;

  protected etiquetaTipo(tipo: TipoActivoProbador): string {
    return ETIQUETAS_TIPO[tipo] ?? tipo;
  }

  // ---- Carga de assets -------------------------------------------------

  cargarAssets(): void {
    const id = this.varianteId();
    if (id === null) return;
    this.http
      .get<ActivoProbador[]>(`${environment.apiUrl}/probador/assets`, { params: { variante_id: id } })
      .subscribe((assets) => this.assets.set(assets));
  }

  seleccionarAsset(asset: ActivoProbador): void {
    this.assetSeleccionado.set(asset);
  }

  // ---- Subida de un asset nuevo ------------------------------------------

  onArchivoSeleccionado(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.archivoNuevo = input.files?.[0] ?? null;
  }

  subirAsset(): void {
    const id = this.varianteId();
    if (id === null || !this.archivoNuevo) return;

    const formulario = new FormData();
    formulario.append('variante_id', String(id));
    formulario.append('tipo', this.tipoNuevo());
    formulario.append('archivo', this.archivoNuevo);

    this.http.post<ActivoProbador>(`${environment.apiUrl}/probador/assets`, formulario).subscribe((asset) => {
      this.archivoNuevo = null;
      this.cargarAssets();
      this.seleccionarAsset(asset);
    });
  }

  // ---- Validación ---------------------------------------------------------

  validarAsset(): void {
    const asset = this.assetSeleccionado();
    if (!asset) return;
    this.http
      .put<ActivoProbador>(`${environment.apiUrl}/probador/assets/${asset.id}/validar`, {})
      .subscribe((actualizado) => {
        this.assetSeleccionado.set(actualizado);
        this.cargarAssets();
      });
  }
}

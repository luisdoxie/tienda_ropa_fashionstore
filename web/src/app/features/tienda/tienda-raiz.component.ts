import { Component, OnDestroy, computed, effect, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { SeoService } from '../../core/seo.service';
import { calcularPaletaAcento } from '../../core/utils/color';
import { TiendaActualService } from './state/tienda-actual.service';
import { TiendaNoDisponibleComponent } from './tienda-no-disponible.component';

/** Primer segmento después de /t/:codigo/ que no se indexa (carrito, cuenta, login...). */
const SEGMENTOS_PRIVADOS = [
  'carrito',
  'reserva',
  'mis-reservas',
  'mis-compras',
  'checkout',
  'login',
  'registro',
  'recuperar',
  'restablecer',
];

/**
 * Padre de /t/:codigo. El resolver ya fijó la empresa en `TiendaActualService`;
 * acá se decide qué pantalla toca y se aplica la marca (color de acento) SOLO a
 * este elemento -- el back office, la plataforma y los tokens base de
 * styles.scss no se tocan.
 */
@Component({
  selector: 'app-tienda-raiz',
  standalone: true,
  imports: [RouterOutlet, TiendaNoDisponibleComponent],
  templateUrl: './tienda-raiz.component.html',
  styleUrl: './tienda-raiz.component.scss',
  host: { '[style]': 'estilosMarca()' },
})
export class TiendaRaizComponent implements OnDestroy {
  protected readonly tienda = inject(TiendaActualService);
  private readonly seo = inject(SeoService);
  private readonly router = inject(Router);

  constructor() {
    // Título y metas de la tienda cuando cargó; título genérico si no.
    effect(() => {
      const estado = this.tienda.estado();
      const empresa = this.tienda.empresa();
      if (estado === 'lista' && empresa !== null) {
        this.seo.fijarTienda(empresa);
      } else if (estado === 'no_encontrada' || estado === 'no_disponible' || estado === 'error') {
        this.seo.fijarGenerico();
      }
    });

    // Las pantallas privadas de la tienda (carrito, cuenta...) no se indexan.
    this.router.events
      .pipe(
        filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe((evento) => {
        const segmentos = evento.urlAfterRedirects.split(/[?#]/)[0].split('/').filter(Boolean);
        // ['t', codigo, primerSegmento, ...]
        this.seo.noIndex(segmentos[0] === 't' && SEGMENTOS_PRIVADOS.includes(segmentos[2] ?? ''));
      });
  }

  /** Variables CSS de la marca; vacío si no hay color o no contrasta (queda el terracota base). */
  protected readonly estilosMarca = computed<Record<string, string>>(() => {
    const sinMarca: Record<string, string> = {};
    if (this.tienda.estado() !== 'lista') return sinMarca;
    const paleta = calcularPaletaAcento(this.tienda.empresa()?.color_acento);
    if (paleta === null) return sinMarca;
    return {
      '--fs-acento': paleta.acento,
      '--fs-acento-hover': paleta.acentoHover,
      '--fs-acento-suave': paleta.acentoSuave,
      '--p-primary-color': paleta.acento,
      '--p-primary-hover-color': paleta.acentoHover,
      '--p-primary-active-color': paleta.acentoHover,
      '--p-primary-contrast-color': paleta.textoSobreAcento,
    };
  });

  reintentar(): void {
    const codigo = this.tienda.codigo();
    if (codigo !== null) this.tienda.cargar(codigo).subscribe();
  }

  ngOnDestroy(): void {
    this.tienda.salir();
    this.seo.restaurar();
  }
}

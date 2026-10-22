import { Injectable, inject } from '@angular/core';
import { Meta, Title } from '@angular/platform-browser';
import { EmpresaPublica } from './models/empresa.models';

export const TITULO_PLATAFORMA = 'FashionStore | Tiendas de ropa';
const DESCRIPCION_PLATAFORMA = 'Elegí tu tienda de ropa en FashionStore.';

const SELECTORES_OG = ["property='og:title'", "property='og:description'", "property='og:image'"];
const SELECTOR_ROBOTS = "name='robots'";

/** true solo para URLs http/https absolutas (nunca javascript:, data:, etc.). */
export function esUrlHttp(valor: string | null | undefined): valor is string {
  if (typeof valor !== 'string') return false;
  try {
    const protocolo = new URL(valor.trim()).protocol;
    return protocolo === 'http:' || protocolo === 'https:';
  } catch {
    return false;
  }
}

/**
 * Título y metas de la página. La plataforma ("/") y cada tienda (/t/:codigo)
 * fijan los suyos; las pantallas privadas de la tienda (carrito, login...) se
 * marcan `noindex`. Todo se limpia con `restaurar()` al salir de la tienda.
 */
@Injectable({ providedIn: 'root' })
export class SeoService {
  private readonly title = inject(Title);
  private readonly meta = inject(Meta);

  /** Página de la plataforma: título y descripción genéricos, sin og:* ni robots. */
  fijarPlataforma(): void {
    this.title.setTitle(TITULO_PLATAFORMA);
    this.meta.updateTag({ name: 'description', content: DESCRIPCION_PLATAFORMA });
    this.quitarOg();
    this.noIndex(false);
  }

  fijarTienda(empresa: EmpresaPublica): void {
    const titulo = `${empresa.nombre} | FashionStore`;
    const descripcion = `Comprá ropa en ${empresa.nombre}, con la tecnología de FashionStore.`;
    this.title.setTitle(titulo);
    this.meta.updateTag({ name: 'description', content: descripcion });
    this.meta.updateTag({ property: 'og:title', content: titulo });
    this.meta.updateTag({ property: 'og:description', content: descripcion });
    if (esUrlHttp(empresa.logo_url)) {
      this.meta.updateTag({ property: 'og:image', content: empresa.logo_url.trim() });
    } else {
      this.meta.removeTag("property='og:image'");
    }
  }

  /** Título genérico cuando la tienda no carga (no encontrada, no disponible, error). */
  fijarGenerico(): void {
    this.title.setTitle('FashionStore');
    this.quitarOg();
  }

  noIndex(activo: boolean): void {
    if (activo) {
      this.meta.updateTag({ name: 'robots', content: 'noindex' });
    } else {
      this.meta.removeTag(SELECTOR_ROBOTS);
    }
  }

  /** Vuelve a lo de la plataforma (al salir de /t/:codigo). */
  restaurar(): void {
    this.fijarPlataforma();
  }

  private quitarOg(): void {
    for (const selector of SELECTORES_OG) this.meta.removeTag(selector);
  }
}

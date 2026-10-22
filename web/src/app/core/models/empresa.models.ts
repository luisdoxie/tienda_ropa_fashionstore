/** Lo único que se publica de una empresa (GET /public/tiendas y /public/{codigo}/tienda). */
export interface EmpresaPublica {
  codigo: string;
  nombre: string;
  logo_url: string | null;
  color_acento: string | null;
  /** Solo en GET /public/{codigo}/tienda: false si la suscripción no está activa. */
  disponible?: boolean;
}

/** Una tarjeta de la página de la plataforma ("/"). */
export type ResumenTienda = Pick<EmpresaPublica, 'codigo' | 'nombre' | 'logo_url' | 'color_acento'>;

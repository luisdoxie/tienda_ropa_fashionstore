export type TipoActivoProbador = 'overlay_2d' | 'flatlay_ia' | 'thumb';
export type EstadoActivoProbador = 'pendiente' | 'validado' | 'rechazado';

export interface ActivoProbador {
  id: number;
  variante_id: number;
  tipo: TipoActivoProbador;
  public_id: string;
  url: string;
  ancho_px: number | null;
  alto_px: number | null;
  estado: EstadoActivoProbador;
  creado_en: string;
}

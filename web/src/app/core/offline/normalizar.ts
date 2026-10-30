/** Texto en minúsculas y sin tildes ni espacios sobrantes: la forma en que se guarda y se busca (`nombre_norm`). */
export function normalizarTexto(texto: string | null | undefined): string {
  return (texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

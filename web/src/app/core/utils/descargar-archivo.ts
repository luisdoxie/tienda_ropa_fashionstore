import { ArchivoDescargado } from '../models/reportes-ia.models';

/**
 * Le entrega el archivo al navegador con un enlace temporal. No guarda nada en la aplicación: el `Blob` se libera al
 * terminar, así el contenido del reporte no queda en el navegador.
 */
export function descargarArchivo(archivo: ArchivoDescargado): void {
  const url = URL.createObjectURL(archivo.blob);
  const enlace = document.createElement('a');
  enlace.href = url;
  enlace.download = archivo.nombre;
  enlace.style.display = 'none';
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  // Algunos navegadores necesitan que la URL siga viva un instante para iniciar la descarga.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

import { Injectable } from '@angular/core';
import { BaseOffline } from './db-offline';
import type { AlcanceOffline } from './offline.models';
import { RepositorioLocal } from './repositorio-local';

/**
 * Dueño de la única conexión a IndexedDB. Entrega repositorios YA acotados a una empresa y un usuario: nadie más toca
 * la base. En las pruebas se reemplaza `base` por otra con `fake-indexeddb`.
 */
@Injectable({ providedIn: 'root' })
export class AlmacenOfflineService {
  readonly base = new BaseOffline();

  repositorio(alcance: AlcanceOffline): RepositorioLocal {
    return new RepositorioLocal(this.base, alcance);
  }
}

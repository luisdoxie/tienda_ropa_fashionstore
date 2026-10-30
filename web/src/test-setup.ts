/**
 * Preparación global de las pruebas (angular.json > test > setupFiles). Da a TODOS los archivos de prueba un IndexedDB
 * falso y nuevo.
 *
 * Por qué no basta `import 'fake-indexeddb/auto'` en cada spec: el ejecutor agrupa los módulos en la suite completa, así
 * que ese import solo corre una vez, y Dexie recuerda lo que vio la PRIMERA vez que se cargó (si fue antes de existir un
 * IndexedDB, queda "sin IndexedDB" para siempre). Aquí se instala una fábrica nueva en cada archivo y se le dice a Dexie
 * cuál usar.
 */
import Dexie from 'dexie';
import { IDBFactory, IDBKeyRange } from 'fake-indexeddb';

const global = globalThis as unknown as Record<string, unknown>;
global['indexedDB'] = new IDBFactory();
global['IDBKeyRange'] = IDBKeyRange;
Dexie.dependencies.indexedDB = global['indexedDB'] as IDBFactory;
Dexie.dependencies.IDBKeyRange = IDBKeyRange as unknown as typeof globalThis.IDBKeyRange;

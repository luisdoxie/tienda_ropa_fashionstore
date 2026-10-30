import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { fechaLocalIso } from '../../core/date-utils';
import { PaginaBitacora, RegistroBitacora } from '../../core/models/auditoria.models';
import { EmpresaPlataforma } from '../../core/models/plataforma.models';
import { Usuario } from '../../core/models/seguridad.models';
import { BitacoraComponent } from './bitacora.component';

const API = environment.apiUrl;
const URL_ADMIN = `${API}/bitacora`;
const URL_PLATAFORMA = `${API}/plataforma/bitacora`;

function registro(id: number, extra: Partial<RegistroBitacora> = {}): RegistroBitacora {
  return {
    id,
    empresa_id: null,
    usuario_id: 5,
    usuario_nombre: 'Ana Paz',
    entidad: 'suscripcion',
    entidad_id: 12,
    accion: 'cambiar_plan',
    datos: { plan_antes: 'basico', plan_despues: 'profesional', suscripcion_nueva_id: 12 },
    ip: '190.1.2.3',
    creado_en: '2026-10-28T14:30:00',
    ...extra,
  };
}

function pagina(items: RegistroBitacora[], total = items.length, numero = 1): PaginaBitacora {
  return { total, pagina: numero, tamanio: 20, items };
}

function usuario(id: number, nombre: string, roles: string[]): Usuario {
  return { id, nombre, apellido: 'Gómez', email: `u${id}@x.com`, telefono: null, activo: true, roles };
}

function empresa(id: number, nombre: string): EmpresaPlataforma {
  return {
    id,
    codigo: nombre.toLowerCase().replace(/\s+/g, '-'),
    nombre,
    logo_url: null,
    color_acento: null,
    activo: true,
    plan_codigo: 'basico',
    suscripcion_estado: 'activa',
    fecha_inicio: null,
    fecha_vencimiento: null,
    administrador_email: null,
  };
}

/** Lo que muestra `date: 'dd/MM/yyyy HH:mm'` para un instante, en la zona local del navegador. */
function formato(fecha: Date): string {
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${dos(fecha.getDate())}/${dos(fecha.getMonth() + 1)}/${fecha.getFullYear()} ${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`;
}

function haceDias(dias: number): string {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() - dias);
  return fechaLocalIso(fecha);
}

describe('BitacoraComponent', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<BitacoraComponent>;
  let el: HTMLElement;

  interface Opciones {
    plataforma?: boolean;
    permisos?: string[];
  }

  /** Monta la pantalla (ngOnInit incluido). Nada se responde todavía: cada prueba flushea lo que le interesa. */
  function montar({ plataforma = false, permisos = ['bitacora.ver', 'usuarios.gestionar'] }: Opciones = {}): void {
    TestBed.configureTestingModule({
      imports: [BitacoraComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: { tienePermiso: (p: string) => permisos.includes(p) } },
        { provide: ActivatedRoute, useValue: { snapshot: { data: { plataforma } } } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(BitacoraComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  /** La consulta de la bitácora que está esperando respuesta (admin o plataforma). */
  function consulta(plataforma = false): TestRequest {
    return http.expectOne((r) => r.url === (plataforma ? URL_PLATAFORMA : URL_ADMIN));
  }

  function responder(datos: PaginaBitacora, plataforma = false): void {
    consulta(plataforma).flush(datos);
    fixture.detectChanges();
  }

  /** Monta como administrador y responde lo inicial (usuarios y primera página). */
  function montarConFilas(items: RegistroBitacora[] = [registro(1)], total = items.length, opciones: Opciones = {}): void {
    montar(opciones);
    if (opciones.plataforma) {
      http.expectOne((r) => r.url === `${API}/plataforma/empresas`).flush([empresa(7, 'Boutique Andina')]);
    } else if ((opciones.permisos ?? ['usuarios.gestionar']).includes('usuarios.gestionar')) {
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([usuario(5, 'Ana', ['administrador']), usuario(6, 'Luis', ['cajero'])]);
    }
    responder(pagina(items, total), opciones.plataforma ?? false);
  }

  const celdas = (fila: Element) => Array.from(fila.querySelectorAll('td')).map((td) => (td.textContent ?? '').replace(/\s+/g, ' ').trim());
  const filas = () => Array.from(el.querySelectorAll('tr.fila'));
  const encabezados = () => Array.from(el.querySelectorAll('thead th')).map((th) => (th.textContent ?? '').trim());
  const resumenPaginacion = () => (el.querySelector('[data-estado="resumen-paginacion"]')?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const boton = (etiqueta: string) => el.querySelector(`button[aria-label="${etiqueta}"]`) as HTMLButtonElement;

  function elegir(filtro: string, valor: unknown): void {
    const campo = fixture.debugElement.query(By.css(`[data-filtro="${filtro}"]`));
    expect(campo, `no existe el filtro ${filtro}`).not.toBeNull();
    campo.triggerEventHandler('ngModelChange', valor);
    fixture.detectChanges();
  }

  afterEach(() => http.verify());

  describe('consulta inicial y tabla', () => {
    it('pide los últimos 30 días, página 1 de 20, a /bitacora y sin empresa_id', () => {
      montar();
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([]);
      const req = consulta();

      expect(req.request.params.get('desde')).toBe(haceDias(30));
      expect(req.request.params.get('hasta')).toBe(haceDias(0));
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      expect(req.request.params.has('empresa_id')).toBe(false);
      expect(req.request.params.has('sin_empresa')).toBe(false);
      req.flush(pagina([]));
    });

    it('dibuja Fecha, Usuario, Acción, Entidad (+ id), Resumen e IP, sin columna Empresa', () => {
      montarConFilas();

      expect(encabezados()).toEqual(['Detalle', 'Fecha', 'Usuario', 'Acción', 'Entidad', 'Resumen', 'IP']);
      const [, fecha, usuarioTxt, accion, entidad, resumen, ip] = celdas(filas()[0]);
      expect(fecha).toBe(formato(new Date(Date.UTC(2026, 9, 28, 14, 30))));
      expect(usuarioTxt).toBe('Ana Paz');
      expect(accion).toBe('Cambiar de plan');
      expect(entidad).toBe('Suscripción #12');
      expect(resumen).toBe('Plan: basico → profesional');
      expect(ip).toBe('190.1.2.3');
    });

    it('la fecha naive del servidor se lee como UTC (no como hora local)', () => {
      montarConFilas([registro(1, { creado_en: '2026-10-30T03:05:00' })]);

      // 03:05 UTC: en cualquier zona distinta de UTC, leerla como local daría otra hora.
      expect(celdas(filas()[0])[1]).toBe(formato(new Date(Date.UTC(2026, 9, 30, 3, 5))));
    });

    it('muestra el nombre que manda el backend, tal cual ("Administrador de la plataforma", IP vacía)', () => {
      montarConFilas([registro(1, { usuario_nombre: 'Administrador de la plataforma', usuario_id: null, ip: null })]);

      const c = celdas(filas()[0]);
      expect(c[2]).toBe('Administrador de la plataforma');
      expect(c[6]).toBe('—');
    });

    it('sin nombre pero con id, muestra "Usuario #id"; sin ninguno, "Sin usuario identificado"', () => {
      montarConFilas([
        registro(1, { usuario_nombre: null, usuario_id: 33 }),
        registro(2, { usuario_nombre: null, usuario_id: null, accion: 'login_fallido', entidad: 'sesion', entidad_id: null }),
      ]);

      expect(celdas(filas()[0])[2]).toBe('Usuario #33');
      expect(celdas(filas()[1])[2]).toBe('Sin usuario identificado');
      expect(celdas(filas()[1])[3]).toBe('Inicio de sesión fallido');
      expect(celdas(filas()[1])[4]).toBe('Sesión');
    });

    it('una entidad o acción que el cliente no conoce se muestra tal cual y no rompe', () => {
      montarConFilas([registro(1, { entidad: 'cosa_nueva', accion: 'accion_rara', entidad_id: null, datos: null })]);

      const c = celdas(filas()[0]);
      expect(c[3]).toBe('accion_rara');
      expect(c[4]).toBe('cosa_nueva');
      expect(c[5]).toBe('');
    });

    it('el resumen sale de claves conocidas y queda vacío si no hay ninguna', () => {
      montarConFilas([
        registro(1, { entidad: 'operacion_sync', accion: 'resolver_conflicto', datos: { operacion_id: 'abcdef12-0000', decision: 'forzar', motivo: 'ya salió' } }),
        registro(2, { datos: { cosa_desconocida: 1 } }),
      ]);

      expect(celdas(filas()[0])[5]).toBe('Decisión: forzar la venta · Operación: abcdef12 · Motivo: ya salió');
      expect(celdas(filas()[1])[5]).toBe('');
    });
  });

  describe('estados', () => {
    it('mientras carga muestra "Cargando registros…" y ninguna tabla', () => {
      montar();
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([]);

      const estado = el.querySelector('[data-estado="cargando"]');
      expect(estado?.textContent).toContain('Cargando registros…');
      expect(el.querySelector('table')).toBeNull();
      expect(el.querySelector('[data-estado="vacio"]')).toBeNull();

      responder(pagina([registro(1)]));
      expect(el.querySelector('[data-estado="cargando"]')).toBeNull();
      expect(el.querySelector('table')).not.toBeNull();
    });

    it('sin registros dice "No hay registros en ese periodo."', () => {
      montarConFilas([]);

      expect(el.querySelector('[data-estado="vacio"]')?.textContent?.trim()).toBe('No hay registros en ese periodo.');
      expect(el.querySelector('table')).toBeNull();
      expect(el.querySelector('[data-estado="error"]')).toBeNull();
    });

    it('con error muestra el aviso y "Reintentar" vuelve a pedir la misma consulta', () => {
      montar({ permisos: ['bitacora.ver'] });
      consulta().flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      const aviso = el.querySelector('[data-estado="error"]') as HTMLElement;
      expect(aviso.textContent).toContain('No pudimos cargar la auditoría');
      expect(aviso.getAttribute('role')).toBe('alert');
      expect(el.querySelector('[data-estado="vacio"]')).toBeNull();

      const reintentar = Array.from(aviso.querySelectorAll('button')).find((b) => (b.textContent ?? '').includes('Reintentar'));
      expect(reintentar).toBeDefined();
      reintentar!.click();
      fixture.detectChanges();

      expect(el.querySelector('[data-estado="error"]')).toBeNull();
      responder(pagina([registro(1)]));
      expect(filas().length).toBe(1);
    });

    it('un error al listar no deja filas viejas a la vista', () => {
      montarConFilas([registro(1)], 40);
      expect(filas().length).toBe(1);

      boton('Página siguiente').click();
      fixture.detectChanges();
      consulta().flush({}, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(filas().length).toBe(0);
      expect(el.querySelector('[data-estado="error"]')).not.toBeNull();
    });
  });

  describe('paginación del servidor', () => {
    it('muestra "Página 1 de 3 · 45 registros" y pide la siguiente con pagina=2', () => {
      montarConFilas([registro(1)], 45);

      expect(resumenPaginacion()).toBe('Página 1 de 3 · 45 registros');
      expect(boton('Página anterior').disabled).toBe(true);
      expect(boton('Página siguiente').disabled).toBe(false);

      boton('Página siguiente').click();
      fixture.detectChanges();
      const req = consulta();
      expect(req.request.params.get('pagina')).toBe('2');
      req.flush(pagina([registro(21, { usuario_nombre: 'Luis Gómez' })], 45, 2));
      fixture.detectChanges();

      expect(resumenPaginacion()).toBe('Página 2 de 3 · 45 registros');
      expect(celdas(filas()[0])[2]).toBe('Luis Gómez');
      expect(boton('Página anterior').disabled).toBe(false);

      boton('Página anterior').click();
      fixture.detectChanges();
      const anterior = consulta();
      expect(anterior.request.params.get('pagina')).toBe('1');
      anterior.flush(pagina([registro(1)], 45));
      fixture.detectChanges();
      expect(resumenPaginacion()).toBe('Página 1 de 3 · 45 registros');
    });

    it('en la última página "siguiente" queda deshabilitado y no pide nada', () => {
      montarConFilas([registro(1)], 21);
      boton('Página siguiente').click();
      fixture.detectChanges();
      responder(pagina([registro(21)], 21, 2));

      expect(resumenPaginacion()).toBe('Página 2 de 2 · 21 registros');
      expect(boton('Página siguiente').disabled).toBe(true);
      boton('Página siguiente').click();
      http.expectNone((r) => r.url === URL_ADMIN);
    });

    it('con un solo registro dice "1 registro" y una sola página', () => {
      montarConFilas([registro(1)], 1);

      expect(resumenPaginacion()).toBe('Página 1 de 1 · 1 registro');
      expect(boton('Página siguiente').disabled).toBe(true);
    });

    it('cambiar un filtro vuelve a la página 1', () => {
      montarConFilas([registro(1)], 45);
      boton('Página siguiente').click();
      fixture.detectChanges();
      responder(pagina([registro(21)], 45, 2));

      elegir('accion', 'cambiar_plan');
      const req = consulta();
      expect(req.request.params.get('pagina')).toBe('1');
      req.flush(pagina([]));
    });
  });

  describe('filtros', () => {
    it('acción, entidad y usuario viajan como accion, entidad y usuario_id', () => {
      montarConFilas();

      elegir('accion', 'resolver_conflicto');
      let req = consulta();
      expect(req.request.params.get('accion')).toBe('resolver_conflicto');
      expect(req.request.params.has('entidad')).toBe(false);
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('entidad', 'operacion_sync');
      req = consulta();
      expect(req.request.params.get('accion')).toBe('resolver_conflicto');
      expect(req.request.params.get('entidad')).toBe('operacion_sync');
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('usuario', 5);
      req = consulta();
      expect(req.request.params.get('usuario_id')).toBe('5');
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('accion', null);
      req = consulta();
      expect(req.request.params.has('accion')).toBe(false);
      expect(req.request.params.get('entidad')).toBe('operacion_sync');
      req.flush(pagina([]));
    });

    it('el rango de fechas viaja como desde y hasta (aaaa-mm-dd)', () => {
      montarConFilas();

      elegir('desde', new Date(2026, 9, 1));
      let req = consulta();
      expect(req.request.params.get('desde')).toBe('2026-10-01');
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('hasta', new Date(2026, 9, 15));
      req = consulta();
      expect(req.request.params.get('desde')).toBe('2026-10-01');
      expect(req.request.params.get('hasta')).toBe('2026-10-15');
      req.flush(pagina([]));
    });

    it('un rango al revés avisa y no consulta; al corregirlo vuelve a consultar', () => {
      montarConFilas();

      elegir('desde', new Date(2099, 0, 2));
      http.expectNone((r) => r.url === URL_ADMIN);
      const aviso = el.querySelector('[data-estado="rango"]');
      expect(aviso?.textContent).toContain('La fecha inicial no puede ser posterior a la final.');
      expect(el.querySelector('table')).toBeNull();

      elegir('desde', new Date(2026, 9, 1));
      expect(el.querySelector('[data-estado="rango"]')).toBeNull();
      responder(pagina([registro(1)]));
      expect(filas().length).toBe(1);
    });

    it('si se borra una fecha no consulta (el rango es obligatorio)', () => {
      montarConFilas();

      elegir('hasta', null);

      http.expectNone((r) => r.url === URL_ADMIN);
      expect(el.querySelector('[data-estado="rango"]')?.textContent).toContain('Elige la fecha inicial y la final.');
    });

    it('ofrece los cambios de plan y suscripción, la resolución de conflictos y las sincronizaciones', () => {
      montarConFilas();
      const interno = fixture.componentInstance as unknown as {
        opcionesAccion(): { label: string; value: string | null }[];
        opcionesEntidad(): { label: string; value: string | null }[];
      };
      const acciones = interno.opcionesAccion().map((o) => o.value);
      const entidades = interno.opcionesEntidad().map((o) => o.value);

      expect(acciones).toEqual(expect.arrayContaining([null, 'cambiar_plan', 'asignar_plan', 'cambiar_estado', 'renovar', 'resolver_conflicto', 'sincronizar_lote']));
      expect(entidades).toEqual(expect.arrayContaining([null, 'suscripcion', 'plan', 'operacion_sync', 'lote_sync']));
      expect(interno.opcionesAccion()[0].label).toBe('Todas las acciones');
      expect(interno.opcionesEntidad()[0].label).toBe('Todas las entidades');
    });

    it('la petición anterior se cancela si llega un filtro nuevo (no pisa la respuesta nueva)', () => {
      montarConFilas();

      elegir('accion', 'renovar');
      const primera = consulta();
      elegir('accion', 'cambiar_plan');
      expect(primera.cancelled).toBe(true);
      const segunda = consulta();
      expect(segunda.request.params.get('accion')).toBe('cambiar_plan');
      segunda.flush(pagina([registro(9)]));
      fixture.detectChanges();

      expect(filas().length).toBe(1);
    });
  });

  describe('fila expandible (JSON como texto)', () => {
    it('al expandir muestra los datos formateados en un <pre> y al repetir los oculta', () => {
      const datos = { plan_antes: 'basico', plan_despues: 'profesional', suscripcion_nueva_id: 12 };
      montarConFilas([registro(1, { datos })]);
      expect(el.querySelector('pre')).toBeNull();

      const alternar = el.querySelector('button.detalle-boton') as HTMLButtonElement;
      expect(alternar.getAttribute('aria-expanded')).toBe('false');
      alternar.click();
      fixture.detectChanges();

      const pre = el.querySelector('pre') as HTMLPreElement;
      expect(pre.textContent).toBe(JSON.stringify(datos, null, 2));
      expect(pre.textContent).toContain('\n  "plan_antes": "basico"');
      expect(alternar.getAttribute('aria-expanded')).toBe('true');
      expect(alternar.getAttribute('aria-controls')).toBe(pre.id);

      alternar.click();
      fixture.detectChanges();
      expect(el.querySelector('pre')).toBeNull();
      expect(alternar.getAttribute('aria-expanded')).toBe('false');
    });

    it('cada fila se expande por separado', () => {
      montarConFilas([registro(1, { datos: { codigo: 'A' } }), registro(2, { datos: { codigo: 'B' } })]);

      const botones = Array.from(el.querySelectorAll('button.detalle-boton')) as HTMLButtonElement[];
      botones[1].click();
      fixture.detectChanges();

      const pres = el.querySelectorAll('pre');
      expect(pres.length).toBe(1);
      expect(pres[0].textContent).toContain('"codigo": "B"');
    });

    it('sin datos dice "Sin datos adicionales."', () => {
      montarConFilas([registro(1, { datos: null }), registro(2, { datos: {} })]);

      (el.querySelectorAll('button.detalle-boton')[0] as HTMLButtonElement).click();
      fixture.detectChanges();
      (el.querySelectorAll('button.detalle-boton')[1] as HTMLButtonElement).click();
      fixture.detectChanges();

      const textos = Array.from(el.querySelectorAll('pre')).map((p) => p.textContent);
      expect(textos).toEqual(['Sin datos adicionales.', 'Sin datos adicionales.']);
    });

    it('un `datos` con etiquetas HTML sale como texto: no se interpreta ni se ejecuta', () => {
      const w = window as unknown as { __pwned?: number };
      delete w.__pwned;
      const datos = {
        nota: '<img src=x onerror="window.__pwned=1">',
        guion: '<script>window.__pwned=2</script>',
        motivo: '<b>negrita</b>',
      };
      montarConFilas([registro(1, { datos })]);

      (el.querySelector('button.detalle-boton') as HTMLButtonElement).click();
      fixture.detectChanges();

      const pre = el.querySelector('pre') as HTMLPreElement;
      // El texto literal está ahí (JSON.stringify solo escapa las comillas)...
      expect(pre.textContent).toContain('<img src=x onerror=\\"window.__pwned=1\\">');
      expect(pre.textContent).toContain('<script>window.__pwned=2</script>');
      // ...y no se creó ningún elemento a partir de él, ni en el detalle ni en el resumen.
      expect(pre.children.length).toBe(0);
      expect(el.querySelector('img')).toBeNull();
      expect(el.querySelector('script')).toBeNull();
      expect(el.querySelector('td.resumen b')).toBeNull();
      expect(celdas(filas()[0])[5]).toBe('Motivo: <b>negrita</b>');
      expect(w.__pwned).toBeUndefined();
    });

    it('cambiar de página cierra los detalles abiertos', () => {
      montarConFilas([registro(1)], 40);
      (el.querySelector('button.detalle-boton') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el.querySelector('pre')).not.toBeNull();

      boton('Página siguiente').click();
      fixture.detectChanges();
      responder(pagina([registro(1)], 40, 2));

      expect(el.querySelector('pre')).toBeNull();
    });
  });

  describe('solo lectura', () => {
    it('no ofrece editar, borrar, guardar ni crear, y ni abrir un detalle manda otra cosa que GETs', () => {
      montarConFilas([registro(1), registro(2)], 40);
      (el.querySelector('button.detalle-boton') as HTMLButtonElement).click();
      fixture.detectChanges();

      const acciones = Array.from(el.querySelectorAll('button, a, [role="button"]')).map(
        (b) => `${b.textContent ?? ''} ${b.getAttribute('aria-label') ?? ''} ${b.className}`.toLowerCase(),
      );
      expect(acciones.length).toBeGreaterThan(0);
      for (const accion of acciones) {
        expect(accion).not.toMatch(/editar|borrar|eliminar|guardar|crear|nuevo|agregar|pi-pencil|pi-trash|pi-plus/);
      }
      expect(el.querySelector('input:not([type="hidden"])[type="text"][formcontrolname]')).toBeNull();
      // Lo único que se pidió fue lectura (afterEach verifica que no quedó nada pendiente).
    });
  });

  describe('administrador de una empresa', () => {
    it('no ve el filtro ni la columna de empresa, y no pide /plataforma/*', () => {
      montarConFilas([registro(1, { empresa_id: 7 })]);

      expect(el.querySelector('[data-filtro="empresa"]')).toBeNull();
      expect(encabezados()).not.toContain('Empresa');
      expect(el.querySelector('td[data-columna="empresa"]')).toBeNull();
      expect(el.textContent).not.toContain('Todas las empresas');
      http.expectNone((r) => r.url.includes('/plataforma/'));
    });

    it('con usuarios.gestionar ofrece el filtro Usuario con el personal (sin clientes)', () => {
      montar();
      http
        .expectOne((r) => r.url === `${API}/usuarios`)
        .flush([usuario(5, 'Ana', ['administrador']), usuario(6, 'Luis', ['cajero']), usuario(7, 'Cris', ['cliente'])]);
      responder(pagina([registro(1)]));

      const interno = fixture.componentInstance as unknown as { opcionesUsuario(): { label: string; value: number | null }[] };
      expect(interno.opcionesUsuario().map((o) => o.label)).toEqual(['Todos los usuarios', 'Ana Gómez', 'Luis Gómez']);
      expect(el.querySelector('[data-filtro="usuario"]')).not.toBeNull();
    });

    it('sin usuarios.gestionar no pide /usuarios (daría 403) y omite el filtro Usuario', () => {
      montarConFilas([registro(1)], 1, { permisos: ['bitacora.ver'] });

      http.expectNone((r) => r.url === `${API}/usuarios`);
      expect(el.querySelector('[data-filtro="usuario"]')).toBeNull();
      expect(filas().length).toBe(1);
    });

    it('si /usuarios falla la pantalla sigue funcionando y solo falta el filtro Usuario', () => {
      montar();
      http.expectOne((r) => r.url === `${API}/usuarios`).flush({}, { status: 403, statusText: 'Forbidden' });
      responder(pagina([registro(1)]));

      expect(filas().length).toBe(1);
      expect(el.querySelector('[data-filtro="usuario"]')).toBeNull();
    });
  });

  describe('superadministrador (/plataforma/auditoria)', () => {
    it('consulta /plataforma/bitacora, muestra la columna y el filtro Empresa y no pide /usuarios', () => {
      montarConFilas(
        [registro(1, { empresa_id: 7 }), registro(2, { empresa_id: null, usuario_nombre: null, usuario_id: null, accion: 'login_fallido', entidad: 'sesion' }), registro(3, { empresa_id: 99 })],
        3,
        { plataforma: true },
      );

      expect(encabezados()).toEqual(['Detalle', 'Fecha', 'Usuario', 'Empresa', 'Acción', 'Entidad', 'Resumen', 'IP']);
      const empresas = Array.from(el.querySelectorAll('td[data-columna="empresa"]')).map((td) => td.textContent?.trim());
      expect(empresas).toEqual(['Boutique Andina', 'Sin empresa', 'Empresa #99']);
      expect(el.querySelector('[data-filtro="empresa"]')).not.toBeNull();
      expect(el.querySelector('[data-filtro="usuario"]')).toBeNull();
      http.expectNone((r) => r.url === `${API}/usuarios`);
      http.expectNone((r) => r.url === URL_ADMIN);
    });

    it('el detalle ocupa todo el ancho de la tabla (8 columnas)', () => {
      montarConFilas([registro(1, { empresa_id: 7 })], 1, { plataforma: true });

      (el.querySelector('button.detalle-boton') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el.querySelector('tr.fila-detalle td')?.getAttribute('colspan')).toBe('8');
    });

    it('la consulta inicial no manda empresa_id ni sin_empresa; elegir una empresa manda empresa_id', () => {
      montar({ plataforma: true });
      http.expectOne((r) => r.url === `${API}/plataforma/empresas`).flush([empresa(7, 'Boutique Andina'), empresa(8, 'Moda Nandú')]);
      let req = consulta(true);
      expect(req.request.params.has('empresa_id')).toBe(false);
      expect(req.request.params.has('sin_empresa')).toBe(false);
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('empresa', 8);
      req = consulta(true);
      expect(req.request.params.get('empresa_id')).toBe('8');
      expect(req.request.params.has('sin_empresa')).toBe(false);
      expect(req.request.params.get('pagina')).toBe('1');
      req.flush(pagina([]));
    });

    it('"Sin empresa" manda sin_empresa=true y ningún empresa_id; "Todas" quita ambos', () => {
      montarConFilas([registro(1)], 1, { plataforma: true });

      elegir('empresa', 'sin');
      let req = consulta(true);
      expect(req.request.params.get('sin_empresa')).toBe('true');
      expect(req.request.params.has('empresa_id')).toBe(false);
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('empresa', 7);
      req = consulta(true);
      expect(req.request.params.get('empresa_id')).toBe('7');
      expect(req.request.params.has('sin_empresa')).toBe(false);
      req.flush(pagina([]));
      fixture.detectChanges();

      elegir('empresa', null);
      req = consulta(true);
      expect(req.request.params.has('empresa_id')).toBe(false);
      expect(req.request.params.has('sin_empresa')).toBe(false);
      req.flush(pagina([]));
    });

    it('la lista de empresas del filtro incluye "Todas las empresas", "Sin empresa" y cada empresa', () => {
      montarConFilas([registro(1)], 1, { plataforma: true });

      const interno = fixture.componentInstance as unknown as { opcionesEmpresa(): { label: string; value: unknown }[] };
      expect(interno.opcionesEmpresa()).toEqual([
        { label: 'Todas las empresas', value: null },
        { label: 'Sin empresa', value: 'sin' },
        { label: 'Boutique Andina', value: 7 },
      ]);
    });

    it('si falla la lista de empresas, la pantalla igual lista y muestra "Empresa #id"', () => {
      montar({ plataforma: true });
      http.expectOne((r) => r.url === `${API}/plataforma/empresas`).flush({}, { status: 500, statusText: 'Error' });
      responder(pagina([registro(1, { empresa_id: 7 })]), true);

      expect(el.querySelector('td[data-columna="empresa"]')?.textContent?.trim()).toBe('Empresa #7');
    });
  });
});

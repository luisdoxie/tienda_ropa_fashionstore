import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { fechaLocalIso } from '../../core/date-utils';
import { FUNCIONES_PLAN, MiEmpresa, MiSuscripcion } from '../../core/models/plan.models';
import { MiEmpresaComponent } from './mi-empresa.component';

const URL_EMPRESA = `${environment.apiUrl}/mi-empresa`;
const URL_SUSCRIPCION = `${environment.apiUrl}/mi-empresa/suscripcion`;

const BASICAS = ['gestion_productos', 'gestion_ventas', 'reservas', 'reportes_convencionales'];
const TODAS = FUNCIONES_PLAN.map((f) => f.id as string);

function empresa(extra: Partial<MiEmpresa> = {}): MiEmpresa {
  return { id: 1, codigo: 'acme', nombre: 'Acme Ropa', logo_url: null, color_acento: null, activo: true, ...extra };
}

/** Fecha 'YYYY-MM-DD' que queda a `dias` días de hoy (calendario local). */
function enDias(dias: number): string {
  const hoy = new Date();
  return fechaLocalIso(new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() + dias));
}

function suscripcion(extra: Partial<MiSuscripcion> = {}): MiSuscripcion {
  return {
    plan_codigo: 'basico',
    plan_nombre: 'Básico',
    estado: 'activa',
    fecha_inicio: '2026-01-05',
    fecha_vencimiento: enDias(60),
    max_sucursales: 2,
    sucursales_activas: 1,
    funcionalidades: BASICAS,
    ...extra,
  };
}

describe('MiEmpresaComponent', () => {
  let controller: HttpTestingController;
  let harness: RouterTestingHarness;

  async function crear(url = '/mi-empresa'): Promise<void> {
    TestBed.configureTestingModule({
      providers: [provideRouter([{ path: 'mi-empresa', component: MiEmpresaComponent }]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    controller = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url, MiEmpresaComponent);
  }

  function pedidoEmpresa(): TestRequest {
    return controller.expectOne((r) => r.url === URL_EMPRESA && r.method === 'GET');
  }

  function pedidoSuscripcion(): TestRequest {
    return controller.expectOne((r) => r.url === URL_SUSCRIPCION);
  }

  /** Crea la pantalla y responde las dos peticiones iniciales. */
  async function cargar(
    sus: Partial<MiSuscripcion> = {},
    emp: Partial<MiEmpresa> = {},
    url = '/mi-empresa',
  ): Promise<void> {
    await crear(url);
    pedidoEmpresa().flush(empresa(emp));
    pedidoSuscripcion().flush(suscripcion(sus));
    harness.detectChanges();
  }

  function html(): HTMLElement {
    return harness.fixture.nativeElement as HTMLElement;
  }

  function boton(texto: string): HTMLButtonElement | undefined {
    return Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes(texto));
  }

  function escribir(selector: string, valor: string): void {
    const input = html().querySelector<HTMLInputElement>(selector)!;
    input.value = valor;
    input.dispatchEvent(new Event('input'));
    harness.detectChanges();
  }

  function filas(): HTMLElement[] {
    return Array.from(html().querySelectorAll<HTMLElement>('.me-funcion'));
  }

  afterEach(() => {
    controller.verify();
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it('muestra el estado de carga y luego la cabecera con el enlace a la tienda', async () => {
    await crear();
    expect(html().textContent).toContain('Cargando los datos de tu empresa');

    pedidoEmpresa().flush(empresa());
    pedidoSuscripcion().flush(suscripcion());
    harness.detectChanges();

    expect(html().textContent).not.toContain('Cargando los datos');
    expect(html().querySelector('.me-nombre')?.textContent).toBe('Acme Ropa');
    expect(html().querySelector('.me-codigo')?.textContent).toContain('acme');
    const enlace = html().querySelector<HTMLAnchorElement>('a.me-tienda');
    expect(enlace?.textContent).toContain('Ver mi tienda');
    expect(enlace?.getAttribute('href')).toBe('/t/acme');
  });

  describe('plan y estado', () => {
    it('plan activo: etiqueta verde, fechas dd/mm/aaaa y días que faltan sin alerta', async () => {
      await cargar({ fecha_inicio: '2026-01-05', fecha_vencimiento: enDias(30) });

      expect(html().querySelector('.me-plan-nombre')?.textContent).toBe('Básico');
      const etiqueta = html().querySelector('.me-estado');
      expect(etiqueta?.textContent).toContain('Activa');
      expect(etiqueta?.classList.contains('fs-chip--exito')).toBe(true);
      expect(html().textContent).toContain('05/01/2026');
      const dias = html().querySelector('.me-dias');
      expect(dias?.textContent).toContain('Faltan 30 días');
      expect(dias?.classList.contains('me-dias--neutro')).toBe(true);
      expect(html().querySelector('.me-bloqueo')).toBeNull();
    });

    it('formatea el vencimiento como dd/mm/aaaa', async () => {
      await cargar({ fecha_vencimiento: '2027-03-09' });
      expect(html().textContent).toContain('09/03/2027');
    });

    it('a 7 días o menos el aviso va en ámbar', async () => {
      await cargar({ fecha_vencimiento: enDias(5) });
      const dias = html().querySelector('.me-dias');
      expect(dias?.textContent).toContain('Faltan 5 días');
      expect(dias?.classList.contains('me-dias--ambar')).toBe(true);
    });

    it('vencida: etiqueta roja, línea roja con el texto y explicación visible', async () => {
      await cargar({ estado: 'vencida', fecha_vencimiento: '2026-10-12' });

      const etiqueta = html().querySelector('.me-estado');
      expect(etiqueta?.textContent).toContain('Vencida');
      expect(etiqueta?.classList.contains('fs-chip--error')).toBe(true);
      const dias = html().querySelector('.me-dias');
      expect(dias?.textContent).toContain('Suscripción vencida');
      expect(dias?.classList.contains('me-dias--rojo')).toBe(true);
      expect(html().querySelector('.me-bloqueo')?.textContent).toContain('bloqueadas');
      // La pantalla sigue mostrándose completa.
      expect(filas().length).toBe(8);
    });

    it('suspendida va en ámbar y cancelada en gris, ambas con su texto', async () => {
      await cargar({ estado: 'suspendida' });
      expect(html().querySelector('.me-estado')?.classList.contains('fs-chip--advertencia')).toBe(true);
      expect(html().querySelector('.me-dias')?.textContent).toContain('Suscripción suspendida');
    });

    it('cancelada: etiqueta gris y texto de cancelada', async () => {
      await cargar({ estado: 'cancelada' });
      expect(html().querySelector('.me-estado')?.className).not.toContain('fs-chip--');
      expect(html().querySelector('.me-dias')?.textContent).toContain('Suscripción cancelada');
    });
  });

  describe('límites y uso', () => {
    it('muestra "1 de 2" y la barra al 50%', async () => {
      await cargar({ max_sucursales: 2, sucursales_activas: 1 });

      expect(html().querySelector('.me-limite__texto')?.textContent).toContain('Sucursales activas: 1 de 2');
      const barra = html().querySelector('p-progressbar');
      expect(barra?.getAttribute('aria-valuenow')).toBe('50');
      expect(html().textContent).not.toContain('Llegaste al límite de tu plan');
    });

    it('al 100% avisa "Llegaste al límite de tu plan"', async () => {
      await cargar({ max_sucursales: 2, sucursales_activas: 2 });

      expect(html().querySelector('.me-limite__texto')?.textContent).toContain('2 de 2');
      expect(html().querySelector('p-progressbar')?.getAttribute('aria-valuenow')).toBe('100');
      expect(html().textContent).toContain('Llegaste al límite de tu plan');
    });

    it('sin máximo definido no dibuja barra', async () => {
      await cargar({ max_sucursales: null, sucursales_activas: 3 });

      expect(html().querySelector('p-progressbar')).toBeNull();
      expect(html().querySelector('.me-limite__texto')?.textContent).toContain('Sucursales activas: 3');
    });
  });

  describe('funcionalidades', () => {
    it('siempre muestra las 8; las no incluidas llevan candado y el nombre del plan', async () => {
      await cargar();

      expect(filas().length).toBe(8);
      expect(filas().map((f) => f.dataset['funcion'])).toEqual(FUNCIONES_PLAN.map((f) => f.id));

      const incluidas = filas().filter((f) => !f.classList.contains('me-funcion--bloqueada'));
      const bloqueadas = filas().filter((f) => f.classList.contains('me-funcion--bloqueada'));
      expect(incluidas.length).toBe(4);
      expect(bloqueadas.length).toBe(4);

      for (const fila of incluidas) {
        expect(fila.querySelector('.me-funcion__icono--ok')).not.toBeNull();
        expect(fila.querySelector('.me-funcion__icono--no')).toBeNull();
      }
      for (const fila of bloqueadas) {
        expect(fila.querySelector('.me-funcion__icono--no')).not.toBeNull();
        expect(fila.textContent).toContain('No incluido en el plan Básico');
        expect(fila.textContent).toContain('Disponible en el plan Profesional');
      }
      expect(incluidas[0].textContent).toContain(FUNCIONES_PLAN[0].descripcion);
    });

    it('si no se sabe cuál plan lo incluye, dice "un plan superior"', async () => {
      await cargar({ plan_codigo: 'empresarial', plan_nombre: 'Empresarial' });

      const bloqueada = html().querySelector('.me-funcion--bloqueada');
      expect(bloqueada?.textContent).toContain('No incluido en el plan Empresarial');
      expect(bloqueada?.textContent).toContain('Disponible en un plan superior');
    });

    it('con un plan que incluye todo no hay candados y siguen las 8 filas', async () => {
      await cargar({ plan_codigo: 'profesional', plan_nombre: 'Profesional', funcionalidades: TODAS });

      expect(filas().length).toBe(8);
      expect(html().querySelectorAll('.me-funcion .me-funcion__icono--no').length).toBe(0);
      expect(html().querySelectorAll('.me-funcion .me-funcion__icono--ok').length).toBe(8);
    });

    it('con una suscripción sin funcionalidades las 8 aparecen bloqueadas', async () => {
      await cargar({ estado: 'sin_suscripcion', plan_codigo: null, plan_nombre: null, funcionalidades: [] });

      expect(filas().length).toBe(8);
      expect(html().querySelectorAll('.me-funcion--bloqueada').length).toBe(8);
      expect(html().querySelector('.me-funcion--bloqueada')?.textContent).toContain('No incluido en tu plan');
    });

    it('marca "Próximamente" lo que aún no existe, sin cambiar lo que incluye el plan', async () => {
      await cargar({ funcionalidades: FUNCIONES_PLAN.map((f) => f.id) });

      const proximas = filas()
        .filter((f) => f.querySelector('.me-proximamente'))
        .map((f) => f.dataset['funcion']);
      expect(proximas).toEqual(['operacion_offline', 'analitica_ml', 'copias_seguridad']);
      // Siguen figurando como incluidas: lo que dice el plan no se toca.
      expect(html().querySelectorAll('.me-funcion--bloqueada').length).toBe(0);
      expect(html().querySelector('[data-funcion="reportes_ia"] .me-proximamente')).toBeNull();
    });

    it('"¿Cómo cambio de plan?" abre el diálogo con las instrucciones', async () => {
      await cargar();
      expect(document.body.textContent).not.toContain('El cambio de plan lo realiza el administrador de la plataforma');

      boton('¿Cómo cambio de plan?')!.click();
      harness.detectChanges();

      expect(document.body.textContent).toContain(
        'El cambio de plan lo realiza el administrador de la plataforma. Pídeselo indicando el nombre de tu empresa y el plan que quieres.',
      );
    });

    it('con ?ver=funcionalidades baja suave a esa sección al terminar de cargar', async () => {
      const desplazar = vi.fn();
      (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView = desplazar;

      await cargar({}, {}, '/mi-empresa?ver=funcionalidades');
      harness.detectChanges();

      expect(desplazar).toHaveBeenCalledTimes(1);
      expect(desplazar).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
      const seccion = html().querySelector('#funcionalidades');
      expect(desplazar.mock.contexts[0]).toBe(seccion);
    });

    it('sin el parámetro no se desplaza', async () => {
      const desplazar = vi.fn();
      (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView = desplazar;

      await cargar();
      harness.detectChanges();

      expect(desplazar).not.toHaveBeenCalled();
    });
  });

  describe('errores de carga', () => {
    it('muestra el error y Reintentar vuelve a pedir empresa y plan', async () => {
      await crear();
      pedidoEmpresa().flush('boom', { status: 500, statusText: 'Server Error' });
      pedidoSuscripcion().flush(suscripcion());
      harness.detectChanges();

      expect(html().textContent).toContain('No pudimos cargar los datos de tu empresa');
      expect(html().querySelector('.me-nombre')).toBeNull();

      boton('Reintentar')!.click();
      harness.detectChanges();
      pedidoEmpresa().flush(empresa());
      pedidoSuscripcion().flush(suscripcion());
      harness.detectChanges();

      expect(html().textContent).not.toContain('No pudimos cargar');
      expect(html().querySelector('.me-nombre')?.textContent).toBe('Acme Ropa');
    });

    it('si falla el plan también muestra el error', async () => {
      await crear();
      pedidoEmpresa().flush(empresa());
      pedidoSuscripcion().flush('boom', { status: 500, statusText: 'Server Error' });
      harness.detectChanges();

      expect(html().textContent).toContain('No pudimos cargar los datos de tu empresa');
      expect(boton('Reintentar')).toBeDefined();
    });
  });

  describe('identidad de la tienda', () => {
    it('carga el formulario con los datos de la empresa', async () => {
      await cargar({}, { nombre: 'Acme', logo_url: 'https://cdn.example.com/l.png', color_acento: '#112233' });

      expect(html().querySelector<HTMLInputElement>('#me-nombre')!.value).toBe('Acme');
      expect(html().querySelector<HTMLInputElement>('#me-logo')!.value).toBe('https://cdn.example.com/l.png');
      expect(html().querySelector<HTMLInputElement>('#me-color')!.value).toBe('#112233');
      expect(html().querySelector<HTMLInputElement>('input[type="color"]')!.value).toBe('#112233');
    });

    it('Guardar manda el PUT con la identidad, muestra el éxito y actualiza la cabecera', async () => {
      await cargar();

      escribir('#me-nombre', '  Acme Moda  ');
      escribir('#me-logo', 'https://cdn.example.com/logo.png');
      escribir('#me-color', '#1F4E79');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      harness.detectChanges();

      const put = controller.expectOne((r) => r.url === URL_EMPRESA && r.method === 'PUT');
      expect(put.request.body).toEqual({
        nombre: 'Acme Moda',
        logo_url: 'https://cdn.example.com/logo.png',
        color_acento: '#1F4E79',
      });
      put.flush(empresa({ nombre: 'Acme Moda', logo_url: 'https://cdn.example.com/logo.png', color_acento: '#1F4E79' }));
      harness.detectChanges();

      expect(html().querySelector('.me-exito')?.textContent).toContain('Guardamos los cambios');
      expect(html().querySelector('.me-nombre')?.textContent).toBe('Acme Moda');
    });

    it('logo y color vacíos se mandan como null', async () => {
      await cargar({}, { logo_url: 'https://cdn.example.com/logo.png', color_acento: '#112233' });

      escribir('#me-logo', '');
      escribir('#me-color', '');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));

      const put = controller.expectOne((r) => r.url === URL_EMPRESA && r.method === 'PUT');
      expect(put.request.body).toEqual({ nombre: 'Acme Ropa', logo_url: null, color_acento: null });
      put.flush(empresa());
    });

    it('un color que no es #RRGGBB muestra el error junto al campo y no manda nada', async () => {
      await cargar();

      escribir('#me-color', '#12G');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      harness.detectChanges();

      expect(html().textContent).toContain('Usa el formato #RRGGBB');
      controller.expectNone((r) => r.method === 'PUT');
    });

    it('el nombre es obligatorio y el logo tiene que ser http o https', async () => {
      await cargar();

      escribir('#me-nombre', '');
      escribir('#me-logo', 'javascript:alert(1)');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      harness.detectChanges();

      expect(html().textContent).toContain('Escribe el nombre de tu empresa.');
      expect(html().textContent).toContain('empiece con http:// o https://');
      controller.expectNone((r) => r.method === 'PUT');
    });

    it('un 422 del servidor se muestra junto al campo, sin el texto técnico', async () => {
      await cargar();

      escribir('#me-color', '#abcdef');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      controller
        .expectOne((r) => r.method === 'PUT')
        .flush(
          { detail: [{ loc: ['body', 'color_acento'], msg: 'String should match pattern' }] },
          { status: 422, statusText: 'Unprocessable Entity' },
        );
      harness.detectChanges();

      expect(html().textContent).toContain('Revisa el color');
      expect(html().textContent).not.toContain('String should match pattern');
      expect(html().querySelector('.me-exito')).toBeNull();
    });

    it('otro error al guardar deja un mensaje y no cambia la cabecera', async () => {
      await cargar();

      escribir('#me-nombre', 'Otro nombre');
      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      controller.expectOne((r) => r.method === 'PUT').flush('boom', { status: 500, statusText: 'Server Error' });
      harness.detectChanges();

      expect(html().textContent).toContain('No pudimos guardar los cambios');
      expect(html().querySelector('.me-nombre')?.textContent).toBe('Acme Ropa');
    });

    it('avisa cuando el color no tiene contraste suficiente, sin bloquear el guardado', async () => {
      await cargar();

      escribir('#me-color', '#FFFF00');
      expect(html().textContent).toContain('contrasta poco con el blanco');

      html().querySelector<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
      const put = controller.expectOne((r) => r.method === 'PUT');
      expect((put.request.body as { color_acento: string }).color_acento).toBe('#FFFF00');
      put.flush(empresa({ color_acento: '#FFFF00' }));

      escribir('#me-color', '#9A3E1F');
      expect(html().textContent).not.toContain('contrasta poco con el blanco');
    });

    it('la vista previa usa el color y la inicial, y el logo solo si es http o https', async () => {
      await cargar({}, { nombre: 'Boutique', color_acento: '#1f4e79' });

      const marca = html().querySelector<HTMLElement>('.me-chip__marca')!;
      expect(marca.style.background).not.toBe('');
      expect(marca.querySelector('.me-chip__inicial')?.textContent).toBe('B');
      expect(marca.querySelector('img')).toBeNull();

      escribir('#me-logo', 'https://cdn.example.com/logo.png');
      expect(html().querySelector('.me-chip__marca img')?.getAttribute('src')).toBe('https://cdn.example.com/logo.png');

      escribir('#me-logo', 'javascript:alert(1)');
      expect(html().querySelector('.me-chip__marca img')).toBeNull();
    });

    it('si el logo no carga, la vista previa vuelve a la inicial', async () => {
      await cargar({}, { nombre: 'Rota', logo_url: 'https://cdn.example.com/rota.png' });

      html().querySelector('.me-chip__marca img')!.dispatchEvent(new Event('error'));
      harness.detectChanges();

      expect(html().querySelector('.me-chip__marca img')).toBeNull();
      expect(html().querySelector('.me-chip__inicial')?.textContent).toBe('R');
    });
  });

  describe('seguridad', () => {
    it('un valor con <script> venido del backend se muestra como texto', async () => {
      const malo = '<script>alert(1)</script>';
      await cargar(
        { plan_nombre: '<img src=x onerror=alert(1)>', estado: 'raro<script>' },
        { nombre: malo, codigo: 'acme' },
      );

      expect(html().querySelector('.me-nombre')?.textContent).toBe(malo);
      expect(html().querySelector('.me-plan-nombre')?.textContent).toBe('<img src=x onerror=alert(1)>');
      expect(html().querySelector('script')).toBeNull();
      expect(html().querySelector('.me-plan-nombre img')).toBeNull();
      // Un estado desconocido nunca se pinta tal cual.
      expect(html().textContent).not.toContain('raro<script>');
    });
  });
});

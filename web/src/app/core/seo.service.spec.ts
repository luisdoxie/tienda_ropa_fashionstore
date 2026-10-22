import { TestBed } from '@angular/core/testing';
import { Meta, Title } from '@angular/platform-browser';
import { EmpresaPublica } from './models/empresa.models';
import { SeoService, esUrlHttp } from './seo.service';

const EMPRESA: EmpresaPublica = {
  codigo: 'acme',
  nombre: 'Acme Ropa',
  logo_url: 'https://cdn.example.com/acme.png',
  color_acento: null,
};

describe('SeoService', () => {
  let seo: SeoService;
  let title: Title;
  let meta: Meta;

  const contenido = (selector: string) => meta.getTag(selector)?.getAttribute('content') ?? null;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    seo = TestBed.inject(SeoService);
    title = TestBed.inject(Title);
    meta = TestBed.inject(Meta);
  });

  afterEach(() => {
    for (const selector of ["name='description'", "name='robots'", "property='og:title'", "property='og:description'", "property='og:image'"]) {
      meta.removeTag(selector);
    }
  });

  it('fijarPlataforma pone título y descripción y quita og:* y robots', () => {
    seo.fijarTienda(EMPRESA);
    seo.noIndex(true);

    seo.fijarPlataforma();

    expect(title.getTitle()).toBe('FashionStore | Tiendas de ropa');
    expect(contenido("name='description'")).toBe('Elegí tu tienda de ropa en FashionStore.');
    expect(meta.getTag("property='og:title'")).toBeNull();
    expect(meta.getTag("property='og:description'")).toBeNull();
    expect(meta.getTag("property='og:image'")).toBeNull();
    expect(meta.getTag("name='robots'")).toBeNull();
  });

  it('fijarTienda pone título, descripción y og:* con el nombre de la empresa', () => {
    seo.fijarTienda(EMPRESA);

    expect(title.getTitle()).toBe('Acme Ropa | FashionStore');
    expect(contenido("name='description'")).toBe('Comprá ropa en Acme Ropa, con la tecnología de FashionStore.');
    expect(contenido("property='og:title'")).toBe('Acme Ropa | FashionStore');
    expect(contenido("property='og:description'")).toBe('Comprá ropa en Acme Ropa, con la tecnología de FashionStore.');
    expect(contenido("property='og:image'")).toBe('https://cdn.example.com/acme.png');
  });

  it('fijarTienda no pone og:image sin logo o con un logo que no es http/https', () => {
    seo.fijarTienda(EMPRESA);
    seo.fijarTienda({ ...EMPRESA, logo_url: null });
    expect(meta.getTag("property='og:image'")).toBeNull();

    seo.fijarTienda({ ...EMPRESA, logo_url: 'javascript:alert(1)' });
    expect(meta.getTag("property='og:image'")).toBeNull();

    seo.fijarTienda({ ...EMPRESA, logo_url: 'data:image/png;base64,AAAA' });
    expect(meta.getTag("property='og:image'")).toBeNull();
  });

  it('noIndex agrega y quita la meta robots sin duplicarla', () => {
    seo.noIndex(true);
    seo.noIndex(true);
    expect(contenido("name='robots'")).toBe('noindex');
    expect(meta.getTags("name='robots'").length).toBe(1);

    seo.noIndex(false);
    expect(meta.getTag("name='robots'")).toBeNull();
  });

  it('fijarGenerico pone el título "FashionStore" y quita og:*', () => {
    seo.fijarTienda(EMPRESA);
    seo.fijarGenerico();

    expect(title.getTitle()).toBe('FashionStore');
    expect(meta.getTag("property='og:title'")).toBeNull();
  });

  it('restaurar vuelve a lo de la plataforma', () => {
    seo.fijarTienda(EMPRESA);
    seo.noIndex(true);

    seo.restaurar();

    expect(title.getTitle()).toBe('FashionStore | Tiendas de ropa');
    expect(meta.getTag("name='robots'")).toBeNull();
    expect(meta.getTag("property='og:title'")).toBeNull();
  });

  it('esUrlHttp solo acepta http y https', () => {
    expect(esUrlHttp('https://a.com/x.png')).toBe(true);
    expect(esUrlHttp('http://a.com/x.png')).toBe(true);
    expect(esUrlHttp('ftp://a.com/x.png')).toBe(false);
    expect(esUrlHttp('/relativa.png')).toBe(false);
    expect(esUrlHttp('')).toBe(false);
    expect(esUrlHttp(null)).toBe(false);
  });
});

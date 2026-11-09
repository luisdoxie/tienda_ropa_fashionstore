import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/catalogo/state/precarga_catalogo.dart';

CatalogoItem _item(int id, {bool conFoto = true}) => CatalogoItem(
  id: id,
  codigo: 'P$id',
  nombre: 'Prenda $id',
  categoriaId: 1,
  genero: 'unisex',
  precioBase: 100,
  admiteProbador: false,
  imagenPrincipal: conFoto ? 'https://fotos.test/$id.jpg' : null,
);

/// Un listado de [total] prendas servido en páginas del tamaño que pida quien llama.
Future<List<CatalogoItem>> Function(int, int) _listado(int total, {Set<int> sinFoto = const {}}) {
  return (pagina, tamanio) async {
    final desde = (pagina - 1) * tamanio;
    final hasta = (desde + tamanio) > total ? total : desde + tamanio;
    return [for (var i = desde + 1; i <= hasta; i++) _item(i, conFoto: !sinFoto.contains(i))];
  };
}

void main() {
  group('PrecargaCatalogo', () {
    test('baja la foto de cada prenda del listado completo, en orden y sin repetir', () async {
      final bajadas = <String>[];
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(120),
        descargar: (url) async {
          bajadas.add(url);
          return 1000;
        },
        hayConexion: () => true,
        esWifi: () async => true,
        simultaneas: 1,
      );

      final total = await precarga.ejecutar();

      expect(total, 120);
      expect(bajadas, [for (var i = 1; i <= 120; i++) 'https://fotos.test/$i.jpg']);
    });

    test('las prendas sin foto se saltan y no rompen la pasada', () async {
      final bajadas = <String>[];
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(10, sinFoto: {3, 4}),
        descargar: (url) async {
          bajadas.add(url);
          return 10;
        },
        hayConexion: () => true,
        esWifi: () async => true,
      );

      await precarga.ejecutar();

      expect(bajadas.length, 8);
      expect(bajadas, isNot(contains('https://fotos.test/3.jpg')));
    });

    test('lo que ya estaba guardado (0 bytes) no cuenta como descargado y no se vuelve a bajar', () async {
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(5),
        descargar: (url) async => url.endsWith('/2.jpg') ? 0 : 500,
        hayConexion: () => true,
        esWifi: () async => true,
      );

      expect(await precarga.ejecutar(), 4);
    });

    test('con datos móviles solo baja las primeras; el resto espera al Wi‑Fi', () async {
      final bajadas = <String>[];
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          bajadas.add(url);
          return 100;
        },
        hayConexion: () => true,
        esWifi: () async => false,
        conCualquierRed: 30,
        simultaneas: 1,
      );

      await precarga.ejecutar();

      expect(bajadas.length, 30);
      expect(bajadas.last, 'https://fotos.test/30.jpg');
    });

    test('con Wi‑Fi baja todas', () async {
      var bajadas = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          bajadas++;
          return 100;
        },
        hayConexion: () => true,
        esWifi: () async => true,
      );

      await precarga.ejecutar();

      expect(bajadas, 100);
    });

    test('no pasa de maxPrendas aunque el servidor tenga más', () async {
      var bajadas = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(500),
        descargar: (url) async {
          bajadas++;
          return 100;
        },
        hayConexion: () => true,
        esWifi: () async => true,
        maxPrendas: 300,
      );

      await precarga.ejecutar();

      expect(bajadas, 300);
    });

    test('se detiene al llegar al tope de bytes', () async {
      var bajadas = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          bajadas++;
          return 1000;
        },
        hayConexion: () => true,
        esWifi: () async => true,
        simultaneas: 1,
        maxBytes: 5000,
      );

      await precarga.ejecutar();

      expect(bajadas, 5);
    });

    test('sin conexión no pide nada ni descarga', () async {
      var listados = 0;
      var bajadas = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: (p, t) async {
          listados++;
          return const [];
        },
        descargar: (url) async {
          bajadas++;
          return 1;
        },
        hayConexion: () => false,
        esWifi: () async => true,
      );

      expect(await precarga.ejecutar(), 0);
      expect(listados, 0);
      expect(bajadas, 0);
    });

    test('si la conexión se corta a la mitad, deja de descargar', () async {
      var conexion = true;
      var bajadas = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          bajadas++;
          if (bajadas == 10) conexion = false;
          return 100;
        },
        hayConexion: () => conexion,
        esWifi: () async => true,
        simultaneas: 1,
      );

      await precarga.ejecutar();

      expect(bajadas, 10);
    });

    test('una foto que falla no detiene a las demás, pero varios fallos seguidos sí', () async {
      var intentos = 0;
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          intentos++;
          if (url.endsWith('/5.jpg')) throw Exception('falló');
          return 100;
        },
        hayConexion: () => true,
        esWifi: () async => true,
        simultaneas: 1,
      );
      expect(await precarga.ejecutar(), 99);
      expect(intentos, 100);

      var seguidos = 0;
      final sinRed = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          seguidos++;
          throw Exception('sin red');
        },
        hayConexion: () => true,
        esWifi: () async => true,
        simultaneas: 1,
      );
      await sinRed.ejecutar();
      expect(seguidos, fallosSeguidosMax);
    });

    test('una segunda pasada mientras hay una en curso no hace nada', () async {
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(10),
        descargar: (url) async {
          await Future<void>.delayed(const Duration(milliseconds: 5));
          return 1;
        },
        hayConexion: () => true,
        esWifi: () async => true,
      );

      final primera = precarga.ejecutar();
      expect(precarga.enCurso, isTrue);
      expect(await precarga.ejecutar(), 0);
      expect(await primera, 10);
      expect(precarga.enCurso, isFalse);
    });

    test('cancelar detiene la pasada', () async {
      late PrecargaCatalogo precarga;
      var bajadas = 0;
      precarga = PrecargaCatalogo(
        listarPagina: _listado(100),
        descargar: (url) async {
          bajadas++;
          if (bajadas == 3) precarga.cancelar();
          return 1;
        },
        hayConexion: () => true,
        esWifi: () async => true,
        simultaneas: 1,
      );

      await precarga.ejecutar();

      expect(bajadas, 3);
    });

    group('fase 2: detalle y galería', () {
      /// La prenda [id] tiene su foto principal y dos más.
      Future<List<String>> galeria(int id) async => [
        'https://fotos.test/$id.jpg',
        'https://fotos.test/$id-b.jpg',
        'https://fotos.test/$id-c.jpg',
      ];

      test('de las primeras prendas guarda el detalle y baja todas sus fotos, sin repetir la principal', () async {
        final bajadas = <String>[];
        final detalles = <int>[];
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(10),
          descargar: (url) async {
            bajadas.add(url);
            return 10;
          },
          detalle: (id) {
            detalles.add(id);
            return galeria(id);
          },
          hayConexion: () => true,
          esWifi: () async => true,
          maxDetalles: 4,
        );

        final total = await precarga.ejecutar();

        expect(detalles.toSet(), {1, 2, 3, 4}, reason: 'solo las primeras');
        // 10 principales + 2 extras por cada una de las 4 primeras.
        expect(total, 10 + 8);
        expect(bajadas.where((u) => u == 'https://fotos.test/1.jpg'), hasLength(1));
        expect(bajadas, containsAll(['https://fotos.test/3-b.jpg', 'https://fotos.test/3-c.jpg']));
        expect(bajadas, isNot(contains('https://fotos.test/5-b.jpg')));
      });

      test('sin la función de detalle no hay fase 2', () async {
        var bajadas = 0;
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(5),
          descargar: (url) async {
            bajadas++;
            return 1;
          },
          hayConexion: () => true,
          esWifi: () async => true,
        );

        await precarga.ejecutar();

        expect(bajadas, 5);
      });

      test('con datos móviles el detalle solo se guarda de las primeras 30 prendas', () async {
        final detalles = <int>[];
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(100),
          descargar: (url) async => 1,
          detalle: (id) async {
            detalles.add(id);
            return const [];
          },
          hayConexion: () => true,
          esWifi: () async => false,
          conCualquierRed: 30,
          maxDetalles: 60,
          simultaneas: 1,
        );

        await precarga.ejecutar();

        expect(detalles, [for (var i = 1; i <= 30; i++) i]);
      });

      test('si la fase 1 se detuvo (tope de bytes), no empieza la fase 2', () async {
        var detalles = 0;
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(20),
          descargar: (url) async => 1000,
          detalle: (id) async {
            detalles++;
            return const [];
          },
          hayConexion: () => true,
          esWifi: () async => true,
          simultaneas: 1,
          maxBytes: 3000,
        );

        await precarga.ejecutar();

        expect(detalles, 0);
      });

      test('un detalle que falla no impide guardar el de las demás', () async {
        final detalles = <int>[];
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(5),
          descargar: (url) async => 1,
          detalle: (id) async {
            detalles.add(id);
            if (id == 2) throw Exception('falló');
            return const [];
          },
          hayConexion: () => true,
          esWifi: () async => true,
          simultaneas: 1,
        );

        await precarga.ejecutar();

        expect(detalles, [1, 2, 3, 4, 5]);
      });
    });

    group('no repetir el recorrido completo', () {
      test('una pasada completa no se repite antes del intervalo, y sí después', () async {
        var ahora = DateTime.utc(2026, 11, 9, 10);
        var bajadas = 0;
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(5),
          descargar: (url) async {
            bajadas++;
            return 1;
          },
          hayConexion: () => true,
          esWifi: () async => true,
          intervaloMinimo: const Duration(minutes: 10),
          ahora: () => ahora,
        );

        expect(await precarga.ejecutar(), 5);

        ahora = ahora.add(const Duration(minutes: 9));
        expect(await precarga.ejecutar(), 0);
        expect(bajadas, 5);

        ahora = ahora.add(const Duration(minutes: 2));
        expect(await precarga.ejecutar(), 5);
        expect(bajadas, 10);
      });

      test('una pasada interrumpida SÍ se puede repetir enseguida', () async {
        var conexion = true;
        var bajadas = 0;
        final precarga = PrecargaCatalogo(
          listarPagina: _listado(10),
          descargar: (url) async {
            bajadas++;
            if (bajadas == 3) conexion = false;
            return 1;
          },
          hayConexion: () => conexion,
          esWifi: () async => true,
          simultaneas: 1,
          ahora: () => DateTime.utc(2026, 11, 9, 10),
        );

        await precarga.ejecutar();
        expect(bajadas, 3);

        conexion = true;
        await precarga.ejecutar();
        expect(bajadas, greaterThan(3));
      });
    });

    test('una pasada que se quedó sin Wi‑Fi se repite apenas haya Wi‑Fi, sin esperar el intervalo', () async {
      var wifi = false;
      var bajadas = 0;
      final guardadas = <String>{};
      final precarga = PrecargaCatalogo(
        listarPagina: _listado(40),
        descargar: (url) async {
          // Como la caché real: lo que ya estaba guardado no se vuelve a bajar (0 bytes).
          if (!guardadas.add(url)) return 0;
          bajadas++;
          return 1;
        },
        hayConexion: () => true,
        esWifi: () async => wifi,
        conCualquierRed: 30,
        simultaneas: 1,
        ahora: () => DateTime.utc(2026, 11, 9, 10),
      );

      expect(await precarga.ejecutar(), 30);

      wifi = true;
      expect(await precarga.ejecutar(), 10, reason: 'solo las 10 que faltaban');
      expect(bajadas, 40);
      // Ya completa: no se repite.
      expect(await precarga.ejecutar(), 0);
    });

    test('un error al listar no sale como excepción', () async {
      final precarga = PrecargaCatalogo(
        listarPagina: (p, t) async => throw Exception('servidor caído'),
        descargar: (url) async => 1,
        hayConexion: () => true,
        esWifi: () async => true,
      );

      expect(await precarga.ejecutar(), 0);
      expect(precarga.enCurso, isFalse);
    });
  });
}

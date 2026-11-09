import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/imagenes/cache_fotos.dart';

void main() {
  group('ArchivosDuraderos', () {
    late Directory raiz;

    setUp(() async {
      raiz = await Directory.systemTemp.createTemp('fotos_test');
    });

    tearDown(() async {
      if (await raiz.exists()) await raiz.delete(recursive: true);
    });

    test('crea su carpeta dentro de la carpeta de datos que se le da y devuelve archivos de ahí', () async {
      final sistema = ArchivosDuraderos('fotos', base: () async => raiz);

      final archivo = await sistema.createFile('a.jpg');
      await archivo.writeAsBytes([1, 2, 3]);

      expect(archivo.path, startsWith(raiz.path));
      expect(archivo.path, contains('fotos'));
      expect(await File(archivo.path).readAsBytes(), [1, 2, 3]);
    });

    test('si la carpeta se borró, la vuelve a crear en vez de fallar', () async {
      final sistema = ArchivosDuraderos('fotos', base: () async => raiz);
      final primero = await sistema.createFile('a.jpg');
      await primero.writeAsBytes([1]);

      await Directory('${raiz.path}${Platform.pathSeparator}fotos').delete(recursive: true);

      final segundo = await sistema.createFile('b.jpg');
      await segundo.writeAsBytes([2]);
      expect(await File(segundo.path).readAsBytes(), [2]);
    });
  });

  test('la caché de fotos recuerda muchas más que la de fábrica (200) y por más de 30 días', () {
    expect(maxFotosEnCache, greaterThan(200));
    expect(vigenciaFotosEnCache.inDays, greaterThan(30));
  });
}

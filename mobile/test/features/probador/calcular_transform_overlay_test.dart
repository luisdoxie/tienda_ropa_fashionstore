import 'dart:math' as math;
import 'dart:ui' show Size;

import 'package:camera/camera.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';
import 'package:mobile/features/probador/models/activo_probador.dart';
import 'package:mobile/features/probador/presentation/probador_screen.dart';

/// Reproduce a mano lo que hace `Canvas`:
/// translate(centro) -> rotate(angulo) -> scale(escala) -> translate(-anclaMedioPx)
/// aplicado a un punto en el sistema de coordenadas del asset. Sirve para
/// verificar, sin necesitar un Canvas real, dónde termina cada punto del
/// asset después de la transformación completa.
Offset _aplicarTransform(Offset puntoAsset, TransformOverlay t) {
  final relativo = (puntoAsset - t.anclaMedioPx) * t.escala;
  final cosA = math.cos(t.angulo);
  final sinA = math.sin(t.angulo);
  final rotado = Offset(relativo.dx * cosA - relativo.dy * sinA, relativo.dx * sinA + relativo.dy * cosA);
  return t.centro + rotado;
}

void main() {
  group('calcularTransformOverlay', () {
    // Anclajes de ejemplo: hombros a 30%/70% del ancho, mitad de la altura.
    const anclajes = AnclajesProbador(
      hombroIzq: Ancla(x: 0.3, y: 0.2),
      hombroDer: Ancla(x: 0.7, y: 0.2),
      cadera: Ancla(x: 0.5, y: 0.7),
    );

    test('el punto medio de los anclajes del asset cae exactamente en el centro real', () {
      // Hombros reales detectados: horizontales, separados 200px, centrados en (400, 300).
      const pIzq = Offset(300, 300);
      const pDer = Offset(500, 300);

      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 600,
        altoAssetPx: 600,
        factorAncho: 2.6,
      );

      expect(transform, isNotNull);
      // Este es el paso que "casi siempre se omite": sin la traslación
      // negativa del punto medio de los anclajes, la imagen se dibuja con
      // su ESQUINA (0,0) en el centro, no con el punto medio de los
      // hombros del asset. Si esto falla, la prenda aparece corrida.
      final anclaMedioTransformado = _aplicarTransform(transform!.anclaMedioPx, transform);
      expect(anclaMedioTransformado.dx, closeTo(400, 0.001));
      expect(anclaMedioTransformado.dy, closeTo(300, 0.001));
    });

    test('sin la traslación negativa (bug clásico), el punto medio NO cae en el centro', () {
      // Reproduce el bug que describe el enunciado: dibujar con
      // translate(centro) -> rotate -> scale, SIN el translate(-anclaMedio).
      // El origen del asset (0,0), no su punto medio de hombros, es lo que
      // termina en el centro real -> la prenda queda corrida.
      const pIzq = Offset(300, 300);
      const pDer = Offset(500, 300);

      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 600,
        altoAssetPx: 600,
        factorAncho: 2.6,
      );

      final sinFix = TransformOverlay(
        centro: transform!.centro,
        angulo: transform.angulo,
        escala: transform.escala,
        anclaMedioPx: Offset.zero, // el bug: "olvidarse" de restar el ancla
      );
      final anclaMedioTransformado = _aplicarTransform(transform.anclaMedioPx, sinFix);

      expect(anclaMedioTransformado.dx, isNot(closeTo(400, 5)));
    });

    test('ancho = distancia euclidiana entre hombros', () {
      const pIzq = Offset(100, 100);
      const pDer = Offset(400, 500); // dx=300, dy=400 -> triángulo 3-4-5: distancia = 500
      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 500,
        altoAssetPx: 500,
        factorAncho: 1,
      );
      expect(transform!.escala, closeTo(1.0, 0.0001)); // 500/500 * 1
    });

    test('angulo = atan2(dy, dx) entre los hombros', () {
      const pIzq = Offset(0, 0);
      const pDer = Offset(0, 100); // hombro derecho más abajo -> cabeza inclinada
      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 500,
        altoAssetPx: 500,
        factorAncho: 1,
      );
      expect(transform!.angulo, closeTo(math.atan2(100, 0), 0.0001));
    });

    test('centro = punto medio entre hombros', () {
      const pIzq = Offset(100, 200);
      const pDer = Offset(300, 220);
      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 500,
        altoAssetPx: 500,
        factorAncho: 1,
      );
      expect(transform!.centro, const Offset(200, 210));
    });

    test('hombros en el mismo punto (ancho 0) no produce una transformación', () {
      const p = Offset(50, 50);
      final transform = calcularTransformOverlay(
        pIzq: p,
        pDer: p,
        anclajes: anclajes,
        anchoAssetPx: 500,
        altoAssetPx: 500,
        factorAncho: 1,
      );
      expect(transform, isNull);
    });

    test('asset sin tamaño (0 o negativo) no produce una transformación', () {
      const pIzq = Offset(0, 0);
      const pDer = Offset(100, 0);
      final transform = calcularTransformOverlay(
        pIzq: pIzq,
        pDer: pDer,
        anclajes: anclajes,
        anchoAssetPx: 0,
        altoAssetPx: 500,
        factorAncho: 1,
      );
      expect(transform, isNull);
    });
  });

  group('trasladarX', () {
    // Buffer típico de la cámara en landscape (ML Kit siempre lo entrega
    // así, antes de rotar): 640x480. Canvas de 400px de ancho.
    const tamanioImagen = Size(640, 480);
    const anchoCanvas = 400.0;
    const x = 100.0;

    // La cámara frontal se ve espejada en pantalla (CameraPreview la
    // renderiza como un espejo real); la trasera nunca se espeja. Esto
    // tiene que valer para las CUATRO rotaciones, no solo 0/180deg -antes
    // del fix, 90/270deg ignoraban `direccionLente` por completo y el
    // resultado "coincidía" con lo correcto solo gracias a la convención
    // de fabricación más común (sensorOrientation 270° en la frontal, 90°
    // en la trasera): con esa convención invertida, habría quedado mal.
    for (final rotacion in InputImageRotation.values) {
      test('$rotacion: frontal espeja, trasera no', () {
        final frontal = trasladarX(x, const Size(anchoCanvas, 800), tamanioImagen, rotacion, CameraLensDirection.front);
        final trasera = trasladarX(x, const Size(anchoCanvas, 800), tamanioImagen, rotacion, CameraLensDirection.back);

        // Espejar dos veces el mismo punto (frontal) da el reflejo de
        // (trasera) respecto al centro del canvas: frontal + trasera ==
        // ancho del canvas, exactamente. Si alguna rama dejara de mirar
        // `direccionLente`, frontal y trasera darían el mismo valor.
        expect(frontal, isNot(closeTo(trasera, 0.001)));
        expect(frontal + trasera, closeTo(anchoCanvas, 0.001));
      });
    }

    test('rotation0deg trasera: sin espejar, proporcional directo', () {
      final resultado = trasladarX(
        x,
        const Size(anchoCanvas, 800),
        tamanioImagen,
        InputImageRotation.rotation0deg,
        CameraLensDirection.back,
      );
      expect(resultado, closeTo(x * anchoCanvas / tamanioImagen.width, 0.001));
    });

    test('rotation90deg y rotation270deg dan el mismo resultado para la misma lente', () {
      // La rotación decide con qué lado del buffer (ancho o alto) se
      // normaliza X; el espejado lo decide únicamente la lente. Con la
      // misma lente, ambas rotaciones "verticales" tienen que dar
      // exactamente el mismo número.
      for (final lente in CameraLensDirection.values) {
        final en90 = trasladarX(x, const Size(anchoCanvas, 800), tamanioImagen, InputImageRotation.rotation90deg, lente);
        final en270 = trasladarX(
          x,
          const Size(anchoCanvas, 800),
          tamanioImagen,
          InputImageRotation.rotation270deg,
          lente,
        );
        expect(en90, closeTo(en270, 0.001));
      }
    });
  });
}

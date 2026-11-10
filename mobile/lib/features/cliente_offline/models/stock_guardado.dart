import '../../catalogo/models/referencia.dart';
import 'linea_carrito_local.dart';

/// El stock por sucursal de UNA variante tal como se vio la última vez con conexión. Es un dato viejo por definición: sirve
/// para orientar sin red, nunca para prometer. El servidor vuelve a comprobar el stock al cobrar.
class StockGuardado {
  const StockGuardado({required this.porSucursal, required this.vistoEn});

  /// Sucursal → unidades disponibles. Una sucursal que no aparece no tenía stock registrado.
  final Map<int, int> porSucursal;

  /// Cuándo se vio (instante UTC).
  final DateTime vistoEn;

  int enSucursal(int sucursalId) => porSucursal[sucursalId] ?? 0;
}

enum EstadoStockSucursal {
  /// Todas las prendas tenían la cantidad pedida en esa sucursal.
  conStock,

  /// Alguna prenda no tenía la cantidad pedida en esa sucursal.
  sinStock,

  /// Falta ver el stock de alguna prenda: no se puede saber.
  sinDatos,
}

/// Lo que se sabe del stock de una sucursal para las prendas del carrito, y de cuándo es el dato más viejo usado.
class StockDeSucursal {
  const StockDeSucursal(this.estado, this.vistoEn);

  final EstadoStockSucursal estado;

  /// El dato más viejo de los usados (null si no se usó ninguno).
  final DateTime? vistoEn;
}

/// Qué se sabe del stock de [sucursalId] para todas las [lineas], con lo [guardado] por variante.
///
/// Si alguna prenda no tenía la cantidad pedida, es `sinStock` aunque de otra falten datos (ya es seguro que no alcanza).
/// Si ninguna falla pero de alguna no se vio el stock, es `sinDatos`.
StockDeSucursal stockDeSucursal(int sucursalId, List<LineaCarritoLocal> lineas, Map<int, StockGuardado> guardado) {
  var faltanDatos = false;
  var faltaStock = false;
  DateTime? masViejo;
  for (final linea in lineas) {
    final stock = guardado[linea.varianteId];
    if (stock == null) {
      faltanDatos = true;
      continue;
    }
    if (masViejo == null || stock.vistoEn.isBefore(masViejo)) masViejo = stock.vistoEn;
    if (stock.enSucursal(sucursalId) < linea.cantidad) faltaStock = true;
  }
  final estado = faltaStock
      ? EstadoStockSucursal.sinStock
      : faltanDatos || lineas.isEmpty
      ? EstadoStockSucursal.sinDatos
      : EstadoStockSucursal.conStock;
  return StockDeSucursal(estado, masViejo);
}

/// La sucursal que se sugiere sola por el stock guardado: la ÚNICA de [retirables] donde todas las prendas tenían stock.
/// Null si hay varias, ninguna o faltan datos.
int? sucursalUnicaConStock(
  List<SucursalRef> retirables,
  List<LineaCarritoLocal> lineas,
  Map<int, StockGuardado> guardado,
) {
  final conStock = [
    for (final s in retirables)
      if (stockDeSucursal(s.id, lineas, guardado).estado == EstadoStockSucursal.conStock) s.id,
  ];
  return conStock.length == 1 ? conStock.single : null;
}

/// La sucursal que se guarda junto a una prenda recién agregada sin conexión: la ÚNICA de [retirables] donde se vio stock
/// de esa variante. Null si hay varias, ninguna o nunca se vio su stock.
SucursalRef? sucursalUnicaConStockDeVariante(List<SucursalRef> retirables, StockGuardado? stock) {
  if (stock == null) return null;
  final conStock = [
    for (final s in retirables)
      if (stock.enSucursal(s.id) > 0) s,
  ];
  return conStock.length == 1 ? conStock.single : null;
}

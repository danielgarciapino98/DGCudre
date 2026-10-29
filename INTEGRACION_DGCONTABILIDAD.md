# Integración prevista con DGContabilidad

Repositorio de referencia: https://github.com/danielgarciapino98/DGContabilidad

## Objetivo
Integrar las capacidades contables de DGContabilidad en DGCuadres/POS como módulos conectados a una sola base de datos y a un único sistema de usuarios/permisos. No se deben copiar a ciegas las dos bases de datos ni reemplazar la aplicación actual: hay que adaptar el esquema, preservar los datos y validar los saldos con migraciones controladas.

## Funciones identificadas en el README de DGContabilidad
- Punto de venta con cobros en CUP, USD, EUR y MLC.
- Caja: apertura, gastos, arqueo y cierre.
- Catálogo de productos.
- Almacén con entradas, salidas, mermas y ajustes.
- Fichas de costo con insumos, rendimiento, costo unitario, margen y precio sugerido.
- Gastos vinculados a cuentas contables.
- Nómina con períodos, bonos, deducciones y estado pendiente/pagado.
- Impuestos configurables.
- Contabilidad de partida doble, cuentas, asientos, diario, períodos y balance de comprobación.
- Reportes PDF.
- Asistente LIA de solo lectura, conectado a datos reales del negocio.

## Mapa de integración propuesto
| Área | Tratamiento |
|---|---|
| POS y caja | Reutilizar la lógica actual de ventas/cuadres cuando sea posible; documentar equivalencias antes de migrar. |
| Inventario/almacén | Ampliar los puntos de venta existentes con almacenes y transferencias trazables. Mantener historial de movimientos. |
| Fichas de costo | Incorporar como módulo separado; no cambiar automáticamente el precio de venta sugerido. |
| Gastos y nómina | Relacionar movimientos con cuentas y períodos, sin descontar deducciones automáticamente. |
| Contabilidad | Crear libro de cuentas y asientos de partida doble; las operaciones que generen asientos deben hacerlo en una transacción coherente y auditable. |
| Impuestos | Mantener tasas configurables; no asumir que se aplican automáticamente hasta definir reglas y validarlas. |
| Reportes | Consolidar informes de caja, ventas, inventario y contabilidad, con exportación PDF. |
| IA del propietario | Solo el propietario podrá consultar datos financieros completos. Las respuestas deben citar datos consultados, distinguir datos ausentes y nunca inventar cifras. |
| Acceso web móvil | Vendedores, almacén y administradores verán solo acciones y datos autorizados para su rol y punto asignado. |

## Secuencia segura
1. Auditar el esquema real de ambas aplicaciones y los datos de ejemplo; hacer copias de seguridad locales.
2. Definir un esquema canónico y migraciones idempotentes, probadas con copias, nunca con los únicos archivos de datos.
3. Incorporar roles y permisos en el backend antes de habilitar interfaces para empleados.
4. Integrar inventario y fichas de costo, después gastos/nómina e impuestos.
5. Implementar contabilidad de partida doble con pruebas de débitos = créditos y conciliación con caja/ventas.
6. Añadir panel del propietario e IA de solo lectura con límite configurable de consultas.
7. Añadir pruebas automatizadas, datos ficticios y procedimiento de restauración antes de fusionar o desplegar.

## Hallazgo sobre el repositorio de referencia
El árbol de archivos visible en la rama principal contiene el punto de entrada `main.py`, README y scripts, pero no muestra los paquetes `arranque/`, `interfaz/` y `nucleo/` importados por `main.py`. Antes de intentar ejecutar o copiar módulos, hay que localizar y subir la fuente real que falta o confirmar si el repositorio está incompleto. El archivo `dgcuadres.db` también es una base de datos y no debe publicarse si contiene información comercial real.

## Estado
Este documento registra el alcance deseado; no significa que las funciones de DGContabilidad ya estén integradas. La integración funcional requiere adaptar código, migraciones, permisos y pruebas.

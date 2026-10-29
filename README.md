# DGCuadres/POS — Cuadre e Inventario Multi-Punto de Venta

Sistema de cuadre de caja e inventario, con soporte para múltiples puntos
de venta, control de personal, balances contables con gráficos, y
exportación de informes en PDF.

## Instalación

```bash
cd DGCuadres_POS
python3 -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Tkinter viene incluido con Python en Windows/Mac. En Linux, si falta:
`sudo apt install python3-tk`.

## Licencia y acceso de administrador

La aplicación requiere un código de licencia firmado, válido durante seis
meses desde su activación y vinculado a una computadora. En la pantalla de
activación, el cliente debe enviarte el identificador mostrado por la
aplicación. Emite un código para ese identificador; si lo comparte, solo
funcionará en la computadora a la que fue emitido. Si cambia de computadora,
debe solicitar una licencia nueva. El código se valida sin conexión y no se
puede reactivar en la misma instalación para reiniciar el plazo. Al iniciar
por primera vez, actívelo y registre el usuario y contraseña del administrador;
en los siguientes inicios se solicitará iniciar sesión. La contraseña se
guarda con hash y salt en la base de datos.

La clave privada para emitir códigos se guarda fuera del proyecto en
`%APPDATA%\DGCuadresPOS\license_signing_private.pem`. No se incluye en el
ejecutable ni debe enviarse a los clientes. Para emitir un código desde el
equipo autorizado, ejecuta `tools\generar_licencia.bat`, escribe el nombre del
cliente y pega el identificador que te envió. El `.bat` muestra el código que
debes enviarle. También puedes emitirlo desde PowerShell:

```powershell
.\.venv\Scripts\python.exe -m tools.issue_license "Nombre del cliente" "IDENTIFICADOR_DE_ACTIVACION"
```

Conserve una copia segura de la clave privada. Si se pierde, los códigos
emitidos con ella no podrán renovarse con una clave nueva sin actualizar
también la clave pública incluida en la aplicación.
El `.bat` y el emisor no se incluyen en el ejecutable ni en el instalador:
PyInstaller parte de `main.py` y excluye el módulo emisor, e Inno Setup solo
empaqueta el ejecutable.

`requirements.txt` instala `reportlab` y `matplotlib` (necesarios para los
informes en PDF y los gráficos), `pywin32` (solo en Windows, para imprimir
en una impresora instalada del sistema) y `python-escpos`/`pyusb`
(opcionales, solo si va a usar el modo de impresión USB/red directo).

## Primer uso

1. Al abrir por primera vez, cree un **punto de venta** (ej. "Confituras",
   "Pizzas"). Puede crear tantos como necesite.
2. En **Productos**, seleccione el punto de venta arriba y cargue el
   catálogo (código, nombre, unidad de medida, costo, precio de venta,
   stock inicial). Las cantidades admiten hasta dos cifras decimales para
   artículos vendidos por peso, volumen u otra unidad fraccionaria.
3. En **Cuadre**, abra el turno indicando cajero, supervisor y fondo para
   cambio.
4. Durante el turno: doble clic en Inicial/Entradas/Traslados/Roturas/
   Final para editar. Use **Contar Efectivo** y **Gastos del Turno** para
   el desglose detallado.
5. Al cerrar el turno se le preguntará si desea ver e imprimir el ticket
   (con vista previa antes de imprimir), y si desea hacer un backup.
6. En **Configuración** puede fijar tasas independientes para USD y EUR.
   Cada turno conserva ambas tasas al abrirse; los ingresos en efectivo,
   transferencias, USD y EUR se suman en la moneda principal. Desde esa
   misma pantalla puede exportar una copia de seguridad o restaurarla;
   antes de reemplazar los datos se crea una copia automática de la base
   actual.
7. **Productos → Exportar inventario actual** genera un PDF del inventario
   y sus vencimientos. El detalle de cada turno también incluye el IPV
   (movimientos de inventario). En el cuadre activo puede buscar productos
   por nombre o código. **Información** muestra el contacto de WhatsApp y el
   estado de la licencia instalada.

## Novedades de esta versión

### Ventanas emergentes
Todas las ventanas (gastos, efectivo, edición de producto, etc.) ahora
usan una base común (`ui/dialogs.py`) que las centra automáticamente
sobre la ventana principal y las hace **realmente redimensionables**
(con scroll donde hace falta), en vez de quedar con tamaño fijo.

### Impresión configurable, con vista previa
- Antes de imprimir cualquier ticket, el sistema **pregunta primero** y
  muestra una **vista previa** en fuente monoespaciada (el mismo ancho
  que se imprimirá) para confirmar el formato antes de gastar papel.
- En **Configuración → Impresora de Tickets**, elija el modo **"sistema"**
  (recomendado): el programa detecta y lista las impresoras **ya
  instaladas** en su computadora (Windows vía `pywin32`, Linux/Mac vía
  CUPS) y usted elige explícitamente cuál usar — nunca se envía a la
  predeterminada del sistema, así que funciona aunque tenga varias
  impresoras instaladas.
- **Corrección del problema de "letras gigantes / mitad de hoja"**: antes,
  el modo de respaldo abría el ticket con el visor de texto del sistema
  operativo (Notepad y similares), que imprime con su propia fuente
  grande en una hoja completa. Ahora, en modo "sistema"/"usb"/"red" se
  envían **comandos ESC/POS reales** (inicialización + fuente pequeña +
  corte de papel) directamente a la impresora térmica, controlando el
  tamaño de letra desde el propio firmware de la impresora, sin depender
  del driver de Windows. El modo "archivo" ahora solo **guarda** el
  ticket como texto (no lo envía a imprimir), para usarlo nada más como
  respaldo o revisión manual.
- Ancho del ticket, fuente (normal/compacta) y corte de papel son
  configurables desde la pantalla de Configuración.

### Historial y corrección de turnos cerrados
- Doble clic en un turno del historial abre su **detalle completo**:
  productos vendidos, gastos, efectivo contado, con botones para
  **imprimir el ticket**, **exportar un PDF con mejor presentación** (no
  el formato angosto térmico, sino un informe A4 con tablas y colores), y
  **corregir** el turno.
- **Corregir Gastos/Efectivo**: permite ajustar gastos o el conteo de
  efectivo de un turno cerrado en cualquier momento (aunque hayan pasado
  días), sin afectar el inventario de turnos posteriores.
- **Reabrir Turno Completo**: permite editar las cantidades de producto
  (inicial/entradas/traslados/roturas/final) de un turno cerrado, pero
  **solo si es el turno más reciente** de ese punto de venta — reabrir un
  turno intermedio dejaría descuadrado el inventario de los turnos que
  vinieron después, así que el sistema lo bloquea con una explicación
  clara y sugiere usar "Corregir Gastos/Efectivo" en su lugar.

### Pestaña de Control de Personal
Nueva pestaña **👤 Personal**: resumen por trabajador de cuántos turnos
ha manejado como cajero/supervisor, y el total acumulado de **faltantes**
y **sobrantes** de caja. Doble clic en cualquier turno del historial del
trabajador abre su detalle completo (mismo panel que el Historial).

### Pestaña de Balance / Informes Contables
Nueva pestaña **📊 Balance**, con dos formas de definir el rango:
- **Por rango de fechas** (con atajos: Hoy, 7 días, 30 días, Este mes).
- **Por rango de turnos** ("desde el turno #X hasta el turno #Y"), útil
  para recalcular un balance exacto entre dos cuadres específicos.

Muestra ventas netas, utilidad bruta, margen de beneficio, gastos totales
y diferencia de caja acumulada, con gráficos de evolución diaria y de
productos más vendidos. Incluye un botón para **exportar el informe
contable completo a PDF** (con gráficos, detalle de turnos y desempeño
por trabajador).

### Interfaz
Paleta de colores y tipografía renovadas para un aspecto más profesional
(barra de navegación oscura, tarjetas de KPI, tablas con mejor contraste),
y la aplicación ahora se presenta como **DGCuadres/POS**.

## Migrar los datos del sistema anterior

```bash
python migrate_legacy.py ruta/al/ipv_pos_viejo.db "Confituras" dgcuadres_pos.db
```

## Configurar la impresora térmica

En **Configuración → Impresora de Tickets**:

1. Instale primero el driver de su impresora térmica en Windows/Linux/Mac
   como lo haría con cualquier impresora (ya lo tiene hecho, según indicó).
2. Elija el modo **"sistema"**.
3. Presione **"🔄 Actualizar Lista"** y seleccione su impresora del
   desplegable.
4. Ajuste el ancho del ticket si su rollo es de 58mm en vez de 80mm
   (32 caracteres en vez de 42).
5. Guarde. A partir de ahora, todo ticket se enviará a esa impresora
   específica, sin pasar por la predeterminada del sistema.

Si tiene más de una impresora instalada y en algún momento quiere
cambiar cuál usa DGCuadres/POS, solo vuelva a esta pantalla y elija otra
del desplegable.

## Estructura del proyecto

```
DGCuadres_POS/
├── main.py                   Punto de entrada
├── config.py                  Config (config.ini)
├── database.py                 Esquema SQLite y reglas de negocio
├── printer.py                   Detección de impresoras, ESC/POS y fallback
├── reports.py                    Generación de PDFs (cuadre y balance) con gráficos
├── migrate_legacy.py            Migración desde el sistema anterior
└── ui/
    ├── dialogs.py                Ventana base: centrado + redimensionable + vista previa de impresión
    ├── main_app.py                Navegación y selector de punto de venta
    ├── shift_view.py               Apertura, edición y cierre de turno
    ├── shift_detail_view.py         Detalle de un turno: imprimir/exportar PDF/corregir/reabrir
    ├── cash_count_dialog.py         Conteo de efectivo por denominación
    ├── expenses_dialog.py           Gastos del turno, uno por uno
    ├── history_view.py              Historial de turnos cerrados
    ├── staff_view.py                 Control de personal (faltantes/sobrantes)
    ├── reports_view.py               Balance contable con gráficos y exportación PDF
    ├── products_view.py              Maestro de productos y trabajadores
    ├── points_view.py                Alta/baja de puntos de venta
    ├── settings_view.py              Configuración de empresa/impresora/denominaciones
    └── style.py                       Paleta y estilos ttk compartidos
```

## IA local integrada
La aplicación incluye un asistente conectado a un servidor compatible con OpenAI por defecto en `http://127.0.0.1:8081`. Si el servicio lo requiere, configure la API key (Bearer) desde Configuración. La IA consulta los datos mediante herramientas controladas y no ejecuta SQL directamente. Las operaciones que modifican datos muestran una confirmación antes de ejecutarse.

Desde **Configuración**, puede deshabilitar el apartado de IA para ocultar sus accesos en las interfaces de escritorio y web. Al deshabilitarlo se conservan los datos de conexión, y al volver a habilitarlo se recupera el asistente.

El servidor IA debe estar en ejecución: DGCuadres/POS no lo inicia ni lo detiene. La interfaz web para acceder desde el móvil es opcional y se inicia desde Configuración dentro del programa de escritorio. Consulte [README_WEB.md](./README_WEB.md).

### Personal, pagos y vencimientos
- Los trabajadores se registran desde **Personal**, con cargo, contacto y remuneración configurable por mes, turno u otra modalidad. Los descuentos se registran aparte y quedan pendientes hasta que el usuario los autorice; no se descuentan automáticamente de caja.
- Los gastos del turno admiten categorías como salario, inversión, multa, mantenimiento y consumo de mercancía, y pueden asociarse opcionalmente a un trabajador.
- En **Configuración**, defina un código de moneda extranjera y su tipo de cambio manual. Cada turno conserva la tasa vigente al abrirse; el efectivo inicial se registra por denominaciones y al cuadrar se separan el efectivo, las transferencias y la moneda extranjera.
- La fecha de vencimiento del producto es opcional. **Productos → Próximos a vencer** muestra los vencimientos dentro de los siguientes 30 días.
- Los puntos con turnos guardados no se pueden eliminar para proteger el historial; se pueden desactivar. Los puntos sin turnos sí se pueden eliminar después de confirmar.

## Compilar a EXE en Windows
1. Instale Python 3 e Inno Setup 6 en el equipo de compilación. `compilar.bat` crea `.venv` si no existe e instala las dependencias de `requirements.txt`.
2. Ejecute `compilar.bat`. Se compila `DG POS v1.exe` y, si Inno Setup 6 está instalado, se genera automáticamente `dist\DGCuadresPOS-Setup.exe`.
3. Si Inno Setup no está instalado, instálelo y abra `DGCuadresPOS.iss` con Inno Setup Compiler, o ejecute `ISCC.exe DGCuadresPOS.iss`.

`dg.png` se usa como icono de la ventana y se convierte a `dg.ico` durante la compilación. El instalador se instala por usuario en `%LOCALAPPDATA%\Programs\DGCuadresPOS`, por lo que no requiere permisos de administrador.

La compilación no incluye `config.ini` ni `dgcuadres_pos.db`: así no se distribuyen credenciales o datos del equipo que compila. La aplicación crea la configuración y la base de datos iniciales en la carpeta de instalación la primera vez que se ejecuta. No desinstale el programa sin respaldar antes la base de datos; el desinstalador no la elimina deliberadamente.

El archivo `.spec` incluye también los datos del paquete `python-escpos` necesarios para inicializar la impresión térmica dentro del ejecutable.

El instalador no contiene licencias ni solicita códigos durante la instalación. Al abrir la aplicación se introduce un código firmado de seis meses; la clave privada de emisión permanece en el equipo autorizado y nunca se distribuye con el instalador.

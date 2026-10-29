"""
Generación e impresión de tickets térmicos.

Modos de impresión (config.ini -> [Impresora] modo):
- "sistema" (recomendado): envía el ticket a una impresora YA INSTALADA en
  el sistema operativo, elegida explícitamente por NOMBRE (nunca la
  predeterminada del spooler, para que funcione aunque haya varias
  impresoras instaladas). Se envían bytes ESC/POS reales (inicialización +
  fuente pequeña + corte de papel) para evitar que el driver imprima con
  una fuente enorme y desperdicie papel: ese es el mismo bug que producía
  "letras gigantes a mitad de hoja".
- "usb": impresión ESC/POS directa por USB (requiere python-escpos + pyusb).
- "red": impresión ESC/POS por red/TCP (requiere python-escpos).
- "archivo": SOLO genera un .txt con el ticket, sin enviarlo a imprimir.
  Útil como respaldo o para revisar el formato antes de imprimir.

Si el modo elegido falla (impresora apagada, librería no instalada, etc.)
el sistema cae automáticamente a "archivo" para no perder el ticket.
"""
import os
import platform
import subprocess
import tempfile
from datetime import datetime

from config import config

try:
    from escpos.printer import Usb, Network
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False

try:
    import win32print
    WIN32PRINT_AVAILABLE = True
except ImportError:
    WIN32PRINT_AVAILABLE = False


class PrinterError(Exception):
    pass


# ----------------------------------------------------------------------
# Comandos ESC/POS crudos: se anteponen al texto para forzar fuente
# pequeña, ancho correcto y corte de papel, sin depender de que el driver
# de Windows/Linux respete un tamaño de fuente razonable por su cuenta.
# ----------------------------------------------------------------------
ESC = b"\x1b"
GS = b"\x1d"

CMD_INIT = ESC + b"@"                 # Reinicia la impresora a sus valores de fábrica
CMD_FONT_A = ESC + b"M" + b"\x00"     # Fuente A (normal, la más común en 80mm)
CMD_FONT_B = ESC + b"M" + b"\x01"     # Fuente B (compacta, más caracteres por línea)
CMD_NORMAL_SIZE = GS + b"!" + b"\x00"  # Tamaño normal (sin doble ancho/alto)
CMD_ALIGN_LEFT = ESC + b"a" + b"\x00"
CMD_CUT_PARTIAL = GS + b"V" + b"\x42" + b"\x00"  # Corte parcial con avance
CMD_FEED_LINES = ESC + b"d"           # + n: avanza n líneas


def _wrap_escpos(text: str) -> bytes:
    """Envuelve el texto plano del ticket con comandos ESC/POS reales
    (inicialización, fuente pequeña normal, y corte) para que la
    impresora térmica lo imprima en su tamaño nativo, sin desperdiciar
    papel ni usar una fuente gigante."""
    font_cmd = CMD_FONT_B if config.fuente_ticket == "B" else CMD_FONT_A
    body = text.encode("cp437", errors="replace")

    data = CMD_INIT + font_cmd + CMD_NORMAL_SIZE + CMD_ALIGN_LEFT + body
    data += CMD_FEED_LINES + b"\x02"
    if config.cortar_papel:
        data += CMD_CUT_PARTIAL
    return data


# ----------------------------------------------------------------------
# Detección de impresoras instaladas en el sistema operativo
# ----------------------------------------------------------------------
def list_system_printers():
    """Devuelve la lista de nombres de impresoras instaladas en el SO actual."""
    system = platform.system()

    if system == "Windows":
        if not WIN32PRINT_AVAILABLE:
            return []
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return sorted(p[2] for p in win32print.EnumPrinters(flags))
        except Exception:
            return []

    # Linux / macOS: usar CUPS vía `lpstat -p`
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=5)
        printers = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("printer "):
                printers.append(line.split()[1])
        return sorted(printers)
    except Exception:
        return []


def get_default_system_printer():
    system = platform.system()
    if system == "Windows" and WIN32PRINT_AVAILABLE:
        try:
            return win32print.GetDefaultPrinter()
        except Exception:
            return None
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
        line = out.stdout.strip()
        if ":" in line:
            return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def _print_raw_to_named_printer(printer_name, raw_bytes):
    """Envía bytes crudos (ya con comandos ESC/POS) a una impresora del
    sistema operativo elegida explícitamente por nombre."""
    system = platform.system()

    if system == "Windows":
        if not WIN32PRINT_AVAILABLE:
            raise PrinterError("pywin32 no está instalado (pip install pywin32).")
        h_printer = win32print.OpenPrinter(printer_name)
        try:
            job = ("Ticket DGCuadres/POS", None, "RAW")
            win32print.StartDocPrinter(h_printer, 1, job)
            win32print.StartPagePrinter(h_printer)
            win32print.WritePrinter(h_printer, raw_bytes)
            win32print.EndPagePrinter(h_printer)
            win32print.EndDocPrinter(h_printer)
        finally:
            win32print.ClosePrinter(h_printer)
        return

    # Linux / macOS: enviar por CUPS con la opción "raw" para que no
    # aplique su propio formateo de página/fuente sobre el ticket.
    fn = os.path.join(tempfile.gettempdir(), f"dgcuadres_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin")
    with open(fn, "wb") as f:
        f.write(raw_bytes)
    result = subprocess.run(
        ["lp", "-d", printer_name, "-o", "raw", fn],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise PrinterError(result.stderr.strip() or "El comando 'lp' falló.")


def _get_escpos_printer():
    """Crea y devuelve una instancia conectada de python-escpos, o None."""
    if not ESCPOS_AVAILABLE:
        return None
    modo = config.get("Impresora", "modo", "sistema").strip().lower()
    try:
        if modo == "usb":
            vendor = int(config.get("Impresora", "usb_vendor_id", "0x0483"), 16)
            product = int(config.get("Impresora", "usb_product_id", "0x5743"), 16)
            in_ep = int(config.get("Impresora", "usb_in_ep", "0x81"), 16)
            out_ep = int(config.get("Impresora", "usb_out_ep", "0x03"), 16)
            return Usb(vendor, product, in_ep=in_ep, out_ep=out_ep)
        elif modo == "red":
            ip = config.get("Impresora", "red_ip", "192.168.1.100")
            puerto = config.getint("Impresora", "red_puerto", 9100)
            return Network(ip, port=puerto)
    except Exception:
        return None
    return None


class TicketPrinter:
    """Construye el contenido del ticket (texto plano, ancho fijo) y lo envía a imprimir."""

    # ------------------------------------------------------------------
    @classmethod
    def build_shift_ticket(cls, shift, items, expenses, cash_counts, totals):
        w = config.ancho_ticket
        sep = "-" * w + "\n"
        cur = config.moneda

        t = ""
        t += config.get("Empresa", "nombre", "")[:w].center(w) + "\n"
        t += config.get("Empresa", "direccion", "")[:w].center(w) + "\n"
        t += f"Tel: {config.get('Empresa', 'telefono', '')}"[:w].center(w) + "\n"
        t += "=" * w + "\n"
        t += "CUADRE DE TURNO"[:w].center(w) + "\n"
        t += f"Punto: {shift.get('point_name', '')}\n"
        t += f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        t += f"Entrego: {shift['cashier_name']}\n"
        t += f"Cuadro : {shift['supervisor_name']}\n"
        t += f"Folio  : #{shift['id']}\n"
        t += sep

        def money_line(label, value):
            val_str = f"{cur}{value:,.2f}"
            pad = w - len(label) - len(val_str)
            return f"{label}{' ' * max(1, pad)}{val_str}\n"

        t += money_line("Fondo Cambio", totals["fondo_cambio"])
        t += money_line("Venta Bruta", totals["total_sold"])
        t += money_line("Costo", totals["total_cost"])
        t += money_line("Gastos", totals["total_expenses"])
        t += money_line("Transferencias", totals.get("transfer_total", 0))
        for receipt in totals.get("foreign_currency_receipts", []):
            t += money_line(
                f"{receipt['currency_code']} equiv.",
                receipt["amount"] * receipt["exchange_rate"],
            )
        t += money_line("Efvo Esperado", totals["expected_cash"])
        t += money_line("Efvo Contado", totals["total_cash_counted"])
        t += money_line("Total Recibido", totals.get("total_received", totals["total_cash_counted"]))
        t += "-" * w + "\n"
        t += money_line("UTILIDAD", totals["total_profit"])

        diff = totals["difference"]
        diff_str = f"+{cur}{diff:.2f} SOBRA" if diff >= 0 else f"-{cur}{abs(diff):.2f} FALTA"
        t += f"{'DIFERENCIA'}{diff_str.rjust(max(1, w - 10))}\n"
        t += sep

        if cash_counts:
            t += "EFECTIVO CONTADO\n"
            for cc in cash_counts:
                line = f"{cur}{cc['denomination']:.0f} x{cc['quantity']}"
                val_str = f"{cur}{cc['subtotal']:.2f}"
                pad = w - len(line) - len(val_str)
                t += f"{line}{' ' * max(1, pad)}{val_str}\n"
            t += sep

        if expenses:
            t += "GASTOS\n"
            for e in expenses:
                t += f"{e['persona'][:w]}\n"
                concepto_val = f"{e['concepto']}"
                val_str = f"{cur}{e['importe']:.2f}"
                line = f" {concepto_val}"[: w - len(val_str) - 1]
                pad = w - len(line) - len(val_str)
                t += f"{line}{' ' * max(1, pad)}{val_str}\n"
            t += sep

        t += "PRODUCTOS VENDIDOS\n"
        for it in items:
            if it["sold_qty"] > 0:
                t += f"{it['product_name'][:w]}\n"
                detail = f" {it['sold_qty']:.2f} x {cur}{it['sale_price']:.2f}"
                val_str = f"{cur}{it['total_sale']:.2f}"
                pad = w - len(detail) - len(val_str)
                t += f"{detail}{' ' * max(1, pad)}{val_str}\n"
        t += sep

        traslados = [i for i in items if i["traslados"] > 0]
        if traslados:
            t += "TRASLADOS (no es perdida)\n"
            for d in traslados:
                t += f" > {d['product_name'][:w-6]} x{d['traslados']:.2f}\n"
            t += sep

        roturas = [i for i in items if i["roturas"] > 0]
        if roturas:
            t += "ROTURAS / MERMAS\n"
            for d in roturas:
                t += f" * {d['product_name'][:w-6]} x{d['roturas']:.2f}\n"
            t += sep

        stock_min = config.stock_minimo
        low_stock = [i for i in items if i["final_stock"] <= stock_min]
        if low_stock:
            t += "STOCK BAJO / AGOTADO\n"
            for ls in low_stock:
                status = "AGOTADO" if ls["final_stock"] == 0 else f"Quedan {ls['final_stock']:.2f}"
                t += f" ! {ls['product_name'][:w-14]} [{status}]\n"
            t += sep

        t += "\n" + config.get("Empresa", "pie_pagina", "")[:w].center(w) + "\n"
        return t

    @classmethod
    def build_inventory_ticket(cls, point_name, products, shift_items_by_product):
        w = config.ancho_ticket
        sep = "-" * w + "\n"

        t = "ESTADO DE INVENTARIO"[:w].center(w) + "\n"
        t += f"Punto: {point_name}\n"
        t += f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        t += sep

        t += "ENTRADAS DEL TURNO\n"
        has_entries = False
        for p_id, it in shift_items_by_product.items():
            if it["entries"] > 0:
                t += f"+{it['entries']:.2f} {it['product_name'][:w-8]}\n"
                has_entries = True
        if not has_entries:
            t += "Sin entradas registradas\n"
        t += sep

        t += "STOCK ACTUAL\n"
        for p in products:
            name = p["name"][:w-6]
            stock = f"{p['stock_current']:.2f}"
            pad = w - len(name) - len(stock)
            t += f"{name}{' ' * max(1, pad)}{stock}\n"

        t += sep
        return t

    # ------------------------------------------------------------------
    @classmethod
    def print_ticket(cls, text):
        """Envía el ticket según el modo configurado. Si falla, cae a archivo."""
        modo = config.get("Impresora", "modo", "sistema").strip().lower()

        if modo == "sistema":
            printer_name = config.get("Impresora", "impresora_sistema", "").strip()
            if not printer_name:
                fn = cls._save_to_file(text)
                return False, f"No hay ninguna impresora seleccionada en Configuración.\nSe guardó como: {fn}"
            try:
                _print_raw_to_named_printer(printer_name, _wrap_escpos(text))
                return True, f"Ticket enviado a la impresora '{printer_name}'."
            except Exception as e:
                fn = cls._save_to_file(text)
                return False, f"No se pudo imprimir en '{printer_name}' ({e}).\nSe guardó como: {fn}"

        if modo in ("usb", "red"):
            printer = _get_escpos_printer()
            if printer is not None:
                try:
                    printer.set(align="left", font="a" if config.fuente_ticket == "A" else "b")
                    printer.text(text)
                    if config.cortar_papel:
                        printer.cut()
                    printer.close()
                    return True, "Ticket enviado a la impresora térmica."
                except Exception as e:
                    fn = cls._save_to_file(text)
                    return False, f"No se pudo conectar con la impresora ({e}).\nSe guardó como: {fn}"
            else:
                fn = cls._save_to_file(text)
                msg = (
                    "python-escpos no está instalado o no se pudo inicializar la impresora.\n"
                    f"Se guardó como: {fn}"
                ) if not ESCPOS_AVAILABLE else (
                    f"No se pudo inicializar la impresora configurada.\nSe guardó como: {fn}"
                )
                return False, msg

        fn = cls._save_to_file(text)
        return True, f"Ticket guardado como archivo:\n{fn}"

    @staticmethod
    def _save_to_file(text):
        """Solo guarda el ticket como .txt; NO lo envía a imprimir (evita que
        el visor de texto por defecto del sistema operativo lo imprima con
        una fuente enorme en una hoja completa)."""
        fn = os.path.join(tempfile.gettempdir(), f"dgcuadres_ticket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text)
        return fn

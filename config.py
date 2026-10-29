"""
Carga y acceso centralizado a la configuración del sistema (config.ini).
"""
import configparser
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if not getattr(__import__("sys"), "frozen", False) else os.path.dirname(os.path.abspath(__import__("sys").executable))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")

_DEFAULTS = {
    "Empresa": {
        "nombre": "MI NEGOCIO / PUNTO DE VENTA",
        "direccion": "Calle Principal #123",
        "telefono": "+53 50000000",
        "pie_pagina": "¡Gracias por su preferencia!",
    },
    "Impresora": {
        "modo": "usb",  # sistema | usb | red | archivo
        "impresora_sistema": "",
        "nombre_impresora": "Xprinter 80mm",
        "ancho_ticket": "42",
        "fuente": "A",  # A (normal) o B (compacta)
        "cortar_papel": "true",
        "usb_vendor_id": "0x0483",
        "usb_product_id": "0x5743",
        "usb_in_ep": "0x81",
        "usb_out_ep": "0x03",
        "red_ip": "192.168.1.100",
        "red_puerto": "9100",
        "stock_minimo_alerta": "5",
    },
    "General": {
        "db_path": "dgcuadres_pos.db",
        "moneda": "$",
        "foreign_currency_code": "USD",
        "exchange_rate": "1",
        "exchange_rate_usd": "1",
        "exchange_rate_eur": "1",
    },
    "IA": {
        "enabled": "true",
        "url": "http://127.0.0.1:8081",
        "modelo": "",
        "api_key": "",
        "max_tokens": "900",
    },
    "Web": {
        "enabled": "false",
        "host": "127.0.0.1",
        "port": "8000",
    },
}


class Config:
    """Envoltorio simple sobre configparser con valores por defecto."""

    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self._parser = configparser.ConfigParser()
        self._load_or_create()

    def _load_or_create(self):
        if not os.path.exists(self.path):
            for section, values in _DEFAULTS.items():
                self._parser[section] = values
            self.save()
        else:
            self._parser.read(self.path, encoding="utf-8")
            # Asegura que existan todas las claves esperadas aunque el
            # archivo del usuario sea antiguo o incompleto.
            changed = False
            for section, values in _DEFAULTS.items():
                if section not in self._parser:
                    self._parser[section] = {}
                    changed = True
                for key, val in values.items():
                    if key not in self._parser[section]:
                        if section == "General" and key == "exchange_rate_usd":
                            legacy_code = self._parser.get("General", "foreign_currency_code", fallback="USD").upper()
                            val = (
                                self._parser.get("General", "exchange_rate", fallback="1")
                                if legacy_code == "USD" else "1"
                            )
                        elif section == "General" and key == "exchange_rate_eur":
                            legacy_code = self._parser.get("General", "foreign_currency_code", fallback="USD").upper()
                            val = (
                                self._parser.get("General", "exchange_rate", fallback="1")
                                if legacy_code == "EUR" else "1"
                            )
                        self._parser[section][key] = val
                        changed = True
            if changed:
                self.save()

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            self._parser.write(f)

    def get(self, section, key, fallback=None):
        return self._parser.get(section, key, fallback=fallback)

    def getint(self, section, key, fallback=0):
        return self._parser.getint(section, key, fallback=fallback)

    def getfloat(self, section, key, fallback=0.0):
        return self._parser.getfloat(section, key, fallback=fallback)

    def set(self, section, key, value):
        if section not in self._parser:
            self._parser[section] = {}
        self._parser[section][key] = str(value)

    @property
    def stock_minimo(self):
        return self.getint("Impresora", "stock_minimo_alerta", 5)

    @property
    def ancho_ticket(self):
        return self.getint("Impresora", "ancho_ticket", 42)

    @property
    def fuente_ticket(self):
        return self.get("Impresora", "fuente", "A").strip().upper()

    @property
    def cortar_papel(self):
        return self.get("Impresora", "cortar_papel", "true").strip().lower() in ("true", "1", "si", "sí")

    @property
    def ia_enabled(self):
        return self.get("IA", "enabled", "true").strip().lower() in ("true", "1", "yes", "si", "sí")

    @property
    def moneda(self):
        return self.get("General", "moneda", "$")


config = Config()

"""
DGCuadres/POS — Cuadre e Inventario Multi-Punto de Venta.

Ejecutar con: python main.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from ui.main_app import MainApp

if __name__ == "__main__":
    db_path = config.get("General", "db_path", "dgcuadres_pos.db")
    if not os.path.isabs(db_path):
        base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        db_path = os.path.join(base_dir, db_path)
    root = tk.Tk()
    app = MainApp(root, db_path=db_path)
    root.mainloop()

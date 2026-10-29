from pathlib import Path
try:
    from PIL import Image
except ImportError:
    raise SystemExit("Falta Pillow. Ejecute: python -m pip install Pillow")

root = Path(__file__).resolve().parent
src = root / "dg.png"
out = root / "dg.ico"
img = Image.open(src).convert("RGBA")
img.save(out, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"Icono creado: {out}")

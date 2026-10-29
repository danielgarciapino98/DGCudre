"""
Migra los datos del sistema anterior (base de datos de un solo punto de
venta, esquema del script original) hacia el nuevo esquema multi-punto.

Uso:
    python migrate_legacy.py ruta/a/ipv_pos_viejo.db "Nombre del Punto" [nueva_ipv_pos.db]

Ejemplo:
    python migrate_legacy.py ipv_pos_viejo.db "Confituras" ipv_pos.db

Qué migra:
- Trabajadores -> tabla workers (se ignoran duplicados)
- Productos -> tabla products, asociados al punto de venta indicado
  (se ignoran duplicados por código)
- Turnos cerrados -> tabla shifts + shift_items, con gastos como una sola
  línea "Gasto migrado" y efectivo contado como una sola denominación
  ficticia (porque el sistema anterior no guardaba el desglose)
"""
import sqlite3
import sys

from database import Database, BusinessError


def migrate(old_db_path, point_name, new_db_path="dgcuadres_pos.db"):
    old_conn = sqlite3.connect(old_db_path)
    old_conn.row_factory = sqlite3.Row
    oc = old_conn.cursor()

    db = Database(new_db_path)

    try:
        db.add_point(point_name)
        print(f"Punto de venta creado: {point_name}")
    except BusinessError:
        print(f"El punto de venta '{point_name}' ya existía, se usará el existente.")
    point = next(p for p in db.get_points(only_active=False) if p["name"] == point_name)
    point_id = point["id"]

    # Trabajadores
    oc.execute("SELECT name FROM workers")
    n_workers = 0
    for row in oc.fetchall():
        try:
            db.add_worker(row["name"])
            n_workers += 1
        except BusinessError:
            pass
    print(f"Trabajadores migrados: {n_workers}")

    # Productos -> id viejo : id nuevo
    old_to_new_product = {}
    oc.execute("SELECT * FROM products")
    n_products = 0
    for row in oc.fetchall():
        try:
            db.add_product(
                point_id, row["code"], row["name"], "unidad",
                row["cost_price"], row["sale_price"], row["stock_pos"],
            )
            n_products += 1
        except BusinessError:
            pass
        c = db.conn.cursor()
        c.execute("SELECT id FROM products WHERE point_id=? AND code=?", (point_id, row["code"]))
        new_row = c.fetchone()
        if new_row:
            old_to_new_product[row["id"]] = new_row["id"]
    print(f"Productos migrados: {n_products}")

    # Turnos cerrados
    oc.execute("SELECT * FROM shifts WHERE status='CLOSED'")
    n_shifts = 0
    for s in oc.fetchall():
        with db.tx():
            cur = db.conn.execute(
                """INSERT INTO shifts (point_id, cashier_name, supervisor_name, opened_at, closed_at,
                       fondo_cambio, total_sold, total_cost, total_profit, total_cash_counted,
                       total_expenses, difference, status)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'CLOSED')""",
                (point_id, s["cashier_name"], s["supervisor_name"], s["date_str"], s["date_str"],
                 s["total_sold"], s["total_cost"], s["total_profit"], s["total_cash"],
                 s["total_expenses"], s["difference"]),
            )
            new_shift_id = cur.lastrowid

            oc.execute("SELECT * FROM shift_items WHERE shift_id=?", (s["id"],))
            for it in oc.fetchall():
                new_pid = old_to_new_product.get(it["product_id"])
                if not new_pid:
                    continue
                prod = db.get_product(new_pid)
                db.conn.execute(
                    """INSERT INTO shift_items
                       (shift_id, product_id, product_code, product_name, unit,
                        initial_stock, entries, traslados, roturas, final_stock,
                        sold_qty, sale_price, cost_price, total_sale, total_cost, profit)
                       VALUES (?, ?, ?, ?, 'unidad', ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_shift_id, new_pid, prod["code"], prod["name"],
                     it["initial_stock"], it["entries"], it["exits"], it["final_stock"],
                     it["sold_qty"], it["sale_price"], it["cost_price"],
                     it["total_sale"], it["total_cost"], it["profit"]),
                )

            if s["total_expenses"]:
                db.conn.execute(
                    "INSERT INTO shift_expenses (shift_id, persona, concepto, importe) VALUES (?, ?, ?, ?)",
                    (new_shift_id, "N/A", "Gasto migrado del sistema anterior", s["total_expenses"]),
                )
            if s["total_cash"]:
                db.conn.execute(
                    "INSERT INTO shift_cash_counts (shift_id, denomination, quantity, subtotal) VALUES (?, 1, ?, ?)",
                    (new_shift_id, s["total_cash"], s["total_cash"]),
                )
        n_shifts += 1
    print(f"Turnos migrados: {n_shifts}")
    print("Migración completa.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    old_path = sys.argv[1]
    point_name = sys.argv[2]
    new_path = sys.argv[3] if len(sys.argv) > 3 else "dgcuadres_pos.db"
    migrate(old_path, point_name, new_path)

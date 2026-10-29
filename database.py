"""
Capa de persistencia (SQLite) y reglas de negocio del sistema IPV.

Diseño clave:
- Un negocio puede tener N "puntos de venta" (points), cada uno con su
  propio catálogo de productos y su propio historial de cuadres.
- Un "shift" (turno/cuadre) pertenece a un punto de venta concreto.
- Cada línea de producto en un turno (shift_item) distingue dos tipos de
  salida: TRASLADOS (mercancía que se mueve a otro punto/almacén, no es
  pérdida) y ROTURAS (mermas/deterioro, sí es pérdida). El Excel original
  solo tenía una columna de "salidas"; aquí se separan porque cambian el
  análisis de pérdidas.
- El efectivo se cuenta por denominación (billetes/monedas), igual que en
  el Excel, y los gastos del turno se registran uno por uno (persona,
  concepto, importe) en vez de un monto único.
"""
import sqlite3
import math
from contextlib import contextmanager
from datetime import date, datetime, timezone

DEFAULT_DENOMINATIONS = [1000, 500, 200, 100, 50, 20, 10, 5, 3, 1]


class BusinessError(Exception):
    """Error de validación de reglas de negocio (se muestra tal cual al usuario)."""


class Database:
    def __init__(self, db_name="dgcuadres_pos.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(self.db_name)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._seed_denominations()

    # ------------------------------------------------------------------
    # Infraestructura
    # ------------------------------------------------------------------
    def get_license(self):
        row = self.conn.execute("SELECT * FROM app_license WHERE id=1").fetchone()
        return dict(row) if row else None

    def activate_license(self, license_code):
        from licensing import add_six_months, verify_license_code

        license_data = verify_license_code(license_code)
        current = self.get_license()
        if current and current["license_code"] == license_code.strip():
            raise BusinessError(
                "Este código ya fue activado. Solicite un código nuevo para renovar."
            )

        activated_at = datetime.now(timezone.utc)
        expires_on = add_six_months(activated_at.date()).isoformat()
        with self.tx():
            self.conn.execute(
                """INSERT INTO app_license
                       (id, license_code, customer, issued_on, expires_on, activated_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       license_code=excluded.license_code,
                       customer=excluded.customer,
                       issued_on=excluded.issued_on,
                       expires_on=excluded.expires_on,
                       activated_at=excluded.activated_at""",
                (license_data["code"], license_data["customer"],
                 license_data["issued_on"], expires_on, activated_at.isoformat(timespec="seconds")),
            )

    def has_administrator(self):
        return self.conn.execute("SELECT 1 FROM administrators LIMIT 1").fetchone() is not None

    def register_administrator(self, username, password):
        from auth import hash_password

        username = username.strip().casefold()
        if len(username) < 3:
            raise BusinessError("El usuario debe tener al menos 3 caracteres.")
        if len(username) > 100:
            raise BusinessError("El usuario no puede superar 100 caracteres.")
        if len(password) < 10:
            raise BusinessError("La contraseña debe tener al menos 10 caracteres.")
        if len(password) > 1024:
            raise BusinessError("La contraseña no puede superar 1024 caracteres.")
        salt, digest = hash_password(password)
        with self.tx():
            if self.conn.execute("SELECT 1 FROM administrators LIMIT 1").fetchone():
                raise BusinessError("El administrador ya está registrado.")
            self.conn.execute(
                "INSERT INTO administrators (username, password_salt, password_hash) VALUES (?, ?, ?)",
                (username, salt, digest),
            )

    def authenticate_administrator(self, username, password):
        from auth import verify_password

        username = username.strip().casefold()
        if len(password) > 1024:
            return None
        row = self.conn.execute(
            "SELECT id, username, password_salt, password_hash FROM administrators WHERE username=?",
            (username,),
        ).fetchone()
        if row is None:
            verify_password(password, "00" * 16, "00" * 32)
            return None
        if not verify_password(password, row["password_salt"], row["password_hash"]):
            return None
        return {"id": row["id"], "username": row["username"]}

    @contextmanager
    def tx(self):
        """Context manager de transacción explícita con rollback en error."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _create_schema(self):
        c = self.conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS app_license (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            license_code TEXT NOT NULL,
            customer TEXT NOT NULL,
            issued_on TEXT NOT NULL,
            expires_on TEXT NOT NULL,
            activated_at TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS administrators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            active INTEGER DEFAULT 1,
            role TEXT NOT NULL DEFAULT '',
            contact TEXT NOT NULL DEFAULT '',
            compensation_type TEXT NOT NULL DEFAULT 'mensual',
            compensation_amount REAL NOT NULL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            point_id INTEGER NOT NULL REFERENCES points(id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            unit TEXT DEFAULT 'unidad',
            cost_price REAL NOT NULL DEFAULT 0,
            sale_price REAL NOT NULL DEFAULT 0,
            stock_current REAL NOT NULL DEFAULT 0,
            expiration_date TEXT,
            active INTEGER DEFAULT 1,
            UNIQUE(point_id, code)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS denominations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value REAL UNIQUE NOT NULL,
            active INTEGER DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            point_id INTEGER NOT NULL REFERENCES points(id),
            cashier_name TEXT NOT NULL,
            supervisor_name TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            fondo_cambio REAL DEFAULT 0,
            foreign_currency_code TEXT NOT NULL DEFAULT 'USD',
            exchange_rate REAL NOT NULL DEFAULT 1,
            exchange_rate_eur REAL NOT NULL DEFAULT 1,
            transfer_total REAL NOT NULL DEFAULT 0,
            foreign_currency_total REAL NOT NULL DEFAULT 0,
            total_sold REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            total_profit REAL DEFAULT 0,
            total_cash_counted REAL DEFAULT 0,
            total_expenses REAL DEFAULT 0,
            difference REAL DEFAULT 0,
            status TEXT DEFAULT 'OPEN'
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shift_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            product_code TEXT NOT NULL,
            product_name TEXT NOT NULL,
            unit TEXT DEFAULT 'unidad',
            initial_stock REAL DEFAULT 0,
            entries REAL DEFAULT 0,
            traslados REAL DEFAULT 0,
            roturas REAL DEFAULT 0,
            final_stock REAL DEFAULT 0,
            sold_qty REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            total_sale REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            profit REAL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shift_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
            persona TEXT NOT NULL,
            concepto TEXT NOT NULL,
            importe REAL NOT NULL DEFAULT 0,
            category TEXT NOT NULL DEFAULT 'Operativo',
            worker_name TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shift_cash_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
            denomination REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shift_currency_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
            currency_code TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            exchange_rate REAL NOT NULL,
            UNIQUE(shift_id, currency_code)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shift_opening_cash_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
            denomination REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS worker_salary_deductions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_name TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            authorized INTEGER NOT NULL DEFAULT 0,
            authorized_at TEXT
        )""")

        self._ensure_column("products", "expiration_date", "TEXT")
        for column, definition in (
            ("role", "TEXT NOT NULL DEFAULT ''"),
            ("contact", "TEXT NOT NULL DEFAULT ''"),
            ("compensation_type", "TEXT NOT NULL DEFAULT 'mensual'"),
            ("compensation_amount", "REAL NOT NULL DEFAULT 0"),
        ):
            self._ensure_column("workers", column, definition)
        for column, definition in (
            ("foreign_currency_code", "TEXT NOT NULL DEFAULT 'USD'"),
            ("exchange_rate", "REAL NOT NULL DEFAULT 1"),
            ("exchange_rate_eur", "REAL NOT NULL DEFAULT 1"),
            ("transfer_total", "REAL NOT NULL DEFAULT 0"),
            ("foreign_currency_total", "REAL NOT NULL DEFAULT 0"),
        ):
            self._ensure_column("shifts", column, definition)
        self._ensure_column("shift_expenses", "category", "TEXT NOT NULL DEFAULT 'Operativo'")
        self._ensure_column("shift_expenses", "worker_name", "TEXT")
        c.execute(
            """INSERT OR IGNORE INTO shift_currency_receipts
               (shift_id, currency_code, amount, exchange_rate)
               SELECT id, upper(foreign_currency_code), foreign_currency_total, exchange_rate
               FROM shifts WHERE foreign_currency_total > 0"""
        )

        c.execute("CREATE INDEX IF NOT EXISTS idx_products_point ON products(point_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_shifts_point ON shifts(point_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_shift_items_shift ON shift_items(shift_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_shift_expenses_shift ON shift_expenses(shift_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_shift_cash_shift ON shift_cash_counts(shift_id)")
        self.conn.commit()

    def _ensure_column(self, table, column, definition):
        existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _seed_denominations(self):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM denominations")
        if c.fetchone()[0] == 0:
            with self.tx():
                self.conn.executemany(
                    "INSERT INTO denominations (value) VALUES (?)",
                    [(v,) for v in DEFAULT_DENOMINATIONS],
                )

    # ------------------------------------------------------------------
    # Puntos de venta
    # ------------------------------------------------------------------
    def get_points(self, only_active=True):
        c = self.conn.cursor()
        q = "SELECT * FROM points"
        if only_active:
            q += " WHERE active=1"
        q += " ORDER BY name ASC"
        c.execute(q)
        return [dict(r) for r in c.fetchall()]

    def add_point(self, name):
        name = name.strip()
        if not name:
            raise BusinessError("El nombre del punto de venta no puede estar vacío.")
        try:
            with self.tx():
                self.conn.execute("INSERT INTO points (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            raise BusinessError(f"Ya existe un punto de venta llamado '{name}'.")

    def rename_point(self, point_id, new_name):
        new_name = new_name.strip()
        if not new_name:
            raise BusinessError("El nombre del punto de venta no puede estar vacío.")
        try:
            with self.tx():
                self.conn.execute("UPDATE points SET name=? WHERE id=?", (new_name, point_id))
        except sqlite3.IntegrityError:
            raise BusinessError(f"Ya existe un punto de venta llamado '{new_name}'.")

    def set_point_active(self, point_id, active: bool):
        with self.tx():
            self.conn.execute("UPDATE points SET active=? WHERE id=?", (1 if active else 0, point_id))

    def delete_point(self, point_id):
        if not self.get_point(point_id):
            raise BusinessError("El punto de venta ya no existe.")
        if self.conn.execute("SELECT 1 FROM shifts WHERE point_id=? LIMIT 1", (point_id,)).fetchone():
            raise BusinessError(
                "Este punto tiene turnos guardados y no se puede eliminar sin perder historial. "
                "Puede desactivarlo para ocultarlo de los selectores."
            )
        with self.tx():
            self.conn.execute("DELETE FROM products WHERE point_id=?", (point_id,))
            self.conn.execute("DELETE FROM points WHERE id=?", (point_id,))

    def get_point(self, point_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM points WHERE id=?", (point_id,))
        r = c.fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------
    # Trabajadores (compartidos entre puntos)
    # ------------------------------------------------------------------
    def get_workers(self):
        c = self.conn.cursor()
        c.execute("SELECT name FROM workers WHERE active=1 ORDER BY name ASC")
        return [r["name"] for r in c.fetchall()]

    def get_worker(self, name):
        row = self.conn.execute("SELECT * FROM workers WHERE name=? AND active=1", (name,)).fetchone()
        return dict(row) if row else None

    def add_worker(self, name, role="", contact="", compensation_type="mensual", compensation_amount=0):
        name = name.strip()
        if not name:
            raise BusinessError("El nombre no puede estar vacío.")
        if compensation_type not in ("mensual", "por_turno", "otro"):
            raise BusinessError("Seleccione un tipo de remuneración válido.")
        if compensation_amount < 0:
            raise BusinessError("La remuneración no puede ser negativa.")
        try:
            with self.tx():
                self.conn.execute(
                    """INSERT INTO workers (name, role, contact, compensation_type, compensation_amount)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, role.strip(), contact.strip(), compensation_type, compensation_amount),
                )
        except sqlite3.IntegrityError:
            raise BusinessError(f"El trabajador '{name}' ya existe.")

    def update_worker(self, worker_id, name, role="", contact="", compensation_type="mensual", compensation_amount=0):
        name = name.strip()
        if not name:
            raise BusinessError("El nombre no puede estar vacío.")
        if compensation_type not in ("mensual", "por_turno", "otro"):
            raise BusinessError("Seleccione un tipo de remuneración válido.")
        if compensation_amount < 0:
            raise BusinessError("La remuneración no puede ser negativa.")
        try:
            with self.tx():
                previous = self.conn.execute(
                    "SELECT name FROM workers WHERE id=? AND active=1", (worker_id,)
                ).fetchone()
                if not previous:
                    raise BusinessError("El trabajador ya no existe.")
                old_name = previous["name"]
                self.conn.execute(
                    """UPDATE workers SET name=?, role=?, contact=?, compensation_type=?, compensation_amount=?
                       WHERE id=?""",
                    (name, role.strip(), contact.strip(), compensation_type, compensation_amount, worker_id),
                )
                if old_name != name:
                    self.conn.execute("UPDATE shifts SET cashier_name=? WHERE cashier_name=?", (name, old_name))
                    self.conn.execute("UPDATE shifts SET supervisor_name=? WHERE supervisor_name=?", (name, old_name))
                    self.conn.execute("UPDATE shift_expenses SET worker_name=? WHERE worker_name=?", (name, old_name))
                    self.conn.execute(
                        "UPDATE worker_salary_deductions SET worker_name=? WHERE worker_name=?", (name, old_name)
                    )
        except sqlite3.IntegrityError:
            raise BusinessError(f"El trabajador '{name}' ya existe.")

    def add_worker_salary_deduction(self, worker_name, amount, reason):
        if not self.get_worker(worker_name):
            raise BusinessError("Seleccione un trabajador activo.")
        reason = reason.strip()
        if amount <= 0:
            raise BusinessError("El descuento debe ser mayor que cero.")
        if not reason:
            raise BusinessError("Indique el motivo del descuento.")
        with self.tx():
            self.conn.execute(
                """INSERT INTO worker_salary_deductions (worker_name, amount, reason, created_at)
                   VALUES (?, ?, ?, ?)""",
                (worker_name, amount, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    def get_worker_salary_deductions(self, worker_name):
        rows = self.conn.execute(
            """SELECT * FROM worker_salary_deductions WHERE worker_name=?
               ORDER BY created_at DESC, id DESC""",
            (worker_name,),
        )
        return [dict(row) for row in rows]

    def authorize_worker_salary_deduction(self, deduction_id, authorized):
        with self.tx():
            cursor = self.conn.execute(
                """UPDATE worker_salary_deductions SET authorized=?,
                   authorized_at=CASE WHEN ?=1 THEN ? ELSE NULL END WHERE id=?""",
                (1 if authorized else 0, 1 if authorized else 0,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), deduction_id),
            )
            if not cursor.rowcount:
                raise BusinessError("No se encontró ese descuento.")

    # ------------------------------------------------------------------
    # Productos
    # ------------------------------------------------------------------
    def get_products(self, point_id, only_active=True):
        c = self.conn.cursor()
        q = "SELECT * FROM products WHERE point_id=?"
        params = [point_id]
        if only_active:
            q += " AND active=1"
        q += " ORDER BY name ASC"
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def get_product(self, product_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM products WHERE id=?", (product_id,))
        r = c.fetchone()
        return dict(r) if r else None

    def add_product(self, point_id, code, name, unit, cost_price, sale_price, stock_current, expiration_date=None):
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise BusinessError("Código y nombre son obligatorios.")
        if not all(math.isfinite(value) for value in (cost_price, sale_price, stock_current)):
            raise BusinessError("Los precios y el stock deben ser números válidos.")
        if cost_price < 0 or sale_price < 0:
            raise BusinessError("Los precios no pueden ser negativos.")
        if stock_current < 0:
            raise BusinessError("El stock inicial no puede ser negativo.")
        self._validate_expiration_date(expiration_date)
        try:
            with self.tx():
                self.conn.execute(
                    """INSERT INTO products
                       (point_id, code, name, unit, cost_price, sale_price, stock_current, expiration_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (point_id, code, name, unit or "unidad", cost_price, sale_price, stock_current, expiration_date),
                )
        except sqlite3.IntegrityError:
            raise BusinessError(f"El código '{code}' ya existe en este punto de venta.")

    def update_product(self, product_id, code, name, unit, cost_price, sale_price, stock_current, expiration_date=None):
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise BusinessError("Código y nombre son obligatorios.")
        if not all(math.isfinite(value) for value in (cost_price, sale_price, stock_current)):
            raise BusinessError("Los precios y el stock deben ser números válidos.")
        if cost_price < 0 or sale_price < 0:
            raise BusinessError("Los precios no pueden ser negativos.")
        if stock_current < 0:
            raise BusinessError("El stock no puede ser negativo.")
        self._validate_expiration_date(expiration_date)
        try:
            with self.tx():
                self.conn.execute(
                    """UPDATE products SET code=?, name=?, unit=?, cost_price=?, sale_price=?, stock_current=?,
                       expiration_date=?
                       WHERE id=?""",
                    (code, name, unit or "unidad", cost_price, sale_price, stock_current, expiration_date, product_id),
                )
        except sqlite3.IntegrityError:
            raise BusinessError(f"El código '{code}' ya existe en este punto de venta.")

    @staticmethod
    def _validate_expiration_date(value):
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise BusinessError("La fecha de vencimiento debe tener el formato AAAA-MM-DD.") from exc

    def get_expiring_products(self, date_to, point_id=None):
        query = """SELECT p.*, pt.name AS point_name FROM products p
                   JOIN points pt ON pt.id=p.point_id
                   WHERE p.active=1 AND p.expiration_date IS NOT NULL
                   AND p.expiration_date>=? AND p.expiration_date<=?"""
        params = [date.today().isoformat(), date_to]
        if point_id:
            query += " AND p.point_id=?"
            params.append(point_id)
        query += " ORDER BY p.expiration_date, p.name"
        return [dict(row) for row in self.conn.execute(query, params)]

    def deactivate_product(self, product_id):
        with self.tx():
            self.conn.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))

    # ------------------------------------------------------------------
    # Denominaciones de efectivo
    # ------------------------------------------------------------------
    def get_denominations(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM denominations WHERE active=1 ORDER BY value DESC")
        return [dict(r) for r in c.fetchall()]

    def set_denominations(self, values):
        """Reemplaza el listado completo de denominaciones activas."""
        with self.tx():
            self.conn.execute("UPDATE denominations SET active=0")
            for v in values:
                self.conn.execute(
                    """INSERT INTO denominations (value, active) VALUES (?, 1)
                       ON CONFLICT(value) DO UPDATE SET active=1""",
                    (v,),
                )

    # ------------------------------------------------------------------
    # Turnos / Cuadre
    # ------------------------------------------------------------------
    def get_active_shift(self, point_id):
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM shifts WHERE point_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
            (point_id,),
        )
        r = c.fetchone()
        return dict(r) if r else None

    def start_shift(self, point_id, cashier, supervisor, fondo_cambio=0.0, opening_counts=None,
                    foreign_currency_code="USD", exchange_rate=1.0, exchange_rate_eur=1.0):
        products = self.get_products(point_id)
        if not products:
            raise BusinessError(
                "Este punto de venta no tiene productos. Agrega productos antes de abrir un turno."
            )
        if not math.isfinite(exchange_rate) or exchange_rate <= 0:
            raise BusinessError("La tasa de cambio USD debe ser un número mayor que cero.")
        if not math.isfinite(exchange_rate_eur) or exchange_rate_eur <= 0:
            raise BusinessError("La tasa de cambio EUR debe ser un número mayor que cero.")
        foreign_currency_code = foreign_currency_code.strip().upper()
        if not foreign_currency_code or len(foreign_currency_code) > 8:
            raise BusinessError("El código de moneda debe tener entre 1 y 8 caracteres.")
        if opening_counts is not None:
            fondo_cambio = sum(float(denom) * int(quantity) for denom, quantity in opening_counts.items())
        with self.tx():
            cur = self.conn.execute(
                """INSERT INTO shifts
                   (point_id, cashier_name, supervisor_name, opened_at, fondo_cambio,
                    foreign_currency_code, exchange_rate, exchange_rate_eur)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (point_id, cashier, supervisor, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 fondo_cambio, foreign_currency_code, exchange_rate, exchange_rate_eur),
            )
            shift_id = cur.lastrowid
            if opening_counts is not None:
                for denomination, quantity in opening_counts.items():
                    quantity = int(quantity)
                    if quantity < 0:
                        raise BusinessError("La cantidad de cada denominación no puede ser negativa.")
                    if quantity:
                        denomination = float(denomination)
                        self.conn.execute(
                            """INSERT INTO shift_opening_cash_counts
                               (shift_id, denomination, quantity, subtotal) VALUES (?, ?, ?, ?)""",
                            (shift_id, denomination, quantity, denomination * quantity),
                        )
            for p in products:
                self.conn.execute(
                    """INSERT INTO shift_items
                       (shift_id, product_id, product_code, product_name, unit,
                        initial_stock, final_stock, sale_price, cost_price)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shift_id, p["id"], p["code"], p["name"], p["unit"],
                     p["stock_current"], p["stock_current"], p["sale_price"], p["cost_price"]),
                )
        return shift_id

    def get_shift_opening_cash_counts(self, shift_id):
        rows = self.conn.execute(
            "SELECT * FROM shift_opening_cash_counts WHERE shift_id=? ORDER BY denomination DESC",
            (shift_id,),
        )
        return [dict(row) for row in rows]

    def save_shift_payments(self, shift_id, transfer_total, foreign_currency_total):
        if transfer_total < 0 or foreign_currency_total < 0:
            raise BusinessError("Los pagos recibidos no pueden ser negativos.")
        with self.tx():
            cursor = self.conn.execute(
                "UPDATE shifts SET transfer_total=?, foreign_currency_total=? WHERE id=?",
                (transfer_total, foreign_currency_total, shift_id),
            )
            if not cursor.rowcount:
                raise BusinessError("No existe ese turno.")


    def get_shift_items(self, shift_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM shift_items WHERE shift_id=? ORDER BY product_name ASC", (shift_id,))
        return [dict(r) for r in c.fetchall()]

    def update_item_counts(self, item_id, initial_st, entries, traslados, roturas, final_st):
        quantities = (("conteo inicial", initial_st), ("entradas", entries),
                      ("traslados", traslados), ("roturas", roturas),
                      ("conteo final", final_st))
        if any(not math.isfinite(val) for _, val in quantities):
            raise BusinessError("Las cantidades deben ser números válidos.")
        initial_st, entries, traslados, roturas, final_st = (
            round(val, 2) for _, val in quantities
        )
        quantities = (("conteo inicial", initial_st), ("entradas", entries),
                      ("traslados", traslados), ("roturas", roturas),
                      ("conteo final", final_st))
        for label, val in quantities:
            if val < 0:
                raise BusinessError(f"El valor de {label} no puede ser negativo.")

        dispo = round(initial_st + entries - traslados - roturas, 2)
        if dispo < 0:
            raise BusinessError(
                "Las salidas (traslados + roturas) superan lo disponible (inicial + entradas)."
            )
        if final_st > dispo:
            raise BusinessError(f"El conteo final ({final_st}) no puede superar lo disponible ({dispo}).")

        sold = round(dispo - final_st, 2)

        c = self.conn.cursor()
        c.execute("SELECT sale_price, cost_price FROM shift_items WHERE id=?", (item_id,))
        row = c.fetchone()
        if row is None:
            raise BusinessError("La línea de producto no existe en este turno.")

        total_sale = sold * row["sale_price"]
        total_cost = sold * row["cost_price"]
        profit = total_sale - total_cost

        with self.tx():
            self.conn.execute(
                """UPDATE shift_items SET
                       initial_stock=?, entries=?, traslados=?, roturas=?, final_stock=?,
                       sold_qty=?, total_sale=?, total_cost=?, profit=?
                   WHERE id=?""",
                (initial_st, entries, traslados, roturas, final_st,
                 sold, total_sale, total_cost, profit, item_id),
            )

    # -- Gastos del turno (uno por uno) --
    def get_shift_expenses(self, shift_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM shift_expenses WHERE shift_id=? ORDER BY id ASC", (shift_id,))
        return [dict(r) for r in c.fetchall()]

    def add_shift_expense(self, shift_id, persona, concepto, importe, category="Operativo", worker_name=None):
        persona = persona.strip()
        concepto = concepto.strip()
        category = category.strip()
        if not concepto or not category:
            raise BusinessError("El concepto y el tipo de gasto son obligatorios.")
        if not persona:
            persona = category
        if importe < 0:
            raise BusinessError("El importe del gasto no puede ser negativo.")
        with self.tx():
            self.conn.execute(
                """INSERT INTO shift_expenses
                   (shift_id, persona, concepto, importe, category, worker_name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shift_id, persona, concepto, importe, category, worker_name),
            )

    def delete_shift_expense(self, expense_id):
        with self.tx():
            self.conn.execute("DELETE FROM shift_expenses WHERE id=?", (expense_id,))

    # -- Conteo de efectivo por denominación --
    def get_shift_cash_counts(self, shift_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM shift_cash_counts WHERE shift_id=? ORDER BY denomination DESC", (shift_id,))
        return [dict(r) for r in c.fetchall()]

    def save_shift_cash_counts(self, shift_id, counts: dict):
        """counts: {denominacion(float): cantidad(int)}"""
        for denomination, quantity in counts.items():
            if float(denomination) <= 0 or int(quantity) != quantity or quantity < 0:
                raise BusinessError("Las denominaciones deben ser positivas y sus cantidades enteras no negativas.")
        with self.tx():
            self.conn.execute("DELETE FROM shift_cash_counts WHERE shift_id=?", (shift_id,))
            for denom, qty in counts.items():
                if qty and qty > 0:
                    self.conn.execute(
                        "INSERT INTO shift_cash_counts (shift_id, denomination, quantity, subtotal) VALUES (?, ?, ?, ?)",
                        (shift_id, denom, qty, denom * qty),
                    )

    def save_shift_receipts(self, shift_id, counts, transfer_total, foreign_currency_total):
        shift = self.get_shift_by_id(shift_id)
        currency_code = shift["foreign_currency_code"] if shift else "USD"
        return self.save_shift_receipts_multi(
            shift_id, counts, transfer_total, {currency_code: foreign_currency_total}
        )

    def get_shift_currency_receipts(self, shift_id):
        rows = self.conn.execute(
            "SELECT currency_code, amount, exchange_rate FROM shift_currency_receipts "
            "WHERE shift_id=? ORDER BY currency_code",
            (shift_id,),
        )
        return [dict(row) for row in rows]

    def save_shift_receipts_multi(self, shift_id, counts, transfer_total, foreign_currency_totals):
        if not math.isfinite(transfer_total) or transfer_total < 0:
            raise BusinessError("Los pagos recibidos no pueden ser negativos.")
        normalized_totals = {}
        for code, amount in foreign_currency_totals.items():
            code = str(code).strip().upper()
            if code not in ("USD", "EUR") or not math.isfinite(amount) or amount < 0:
                raise BusinessError("Los importes extranjeros deben ser válidos para USD o EUR.")
            normalized_totals[code] = amount
        for denomination, quantity in counts.items():
            if float(denomination) <= 0 or int(quantity) != quantity or quantity < 0:
                raise BusinessError("Las denominaciones deben ser positivas y sus cantidades enteras no negativas.")
        with self.tx():
            shift = self.conn.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
            if not shift:
                raise BusinessError("No existe ese turno.")
            self.conn.execute("DELETE FROM shift_cash_counts WHERE shift_id=?", (shift_id,))
            for denomination, quantity in counts.items():
                if quantity:
                    denomination = float(denomination)
                    self.conn.execute(
                        """INSERT INTO shift_cash_counts
                           (shift_id, denomination, quantity, subtotal) VALUES (?, ?, ?, ?)""",
                        (shift_id, denomination, quantity, denomination * quantity),
                    )
            rates = {"USD": shift["exchange_rate"], "EUR": shift["exchange_rate_eur"]}
            self.conn.execute("DELETE FROM shift_currency_receipts WHERE shift_id=?", (shift_id,))
            for code, amount in normalized_totals.items():
                self.conn.execute(
                    """INSERT INTO shift_currency_receipts
                       (shift_id, currency_code, amount, exchange_rate) VALUES (?, ?, ?, ?)""",
                    (shift_id, code, amount, rates[code]),
                )
            self.conn.execute(
                """UPDATE shifts SET transfer_total=?, foreign_currency_total=?,
                   foreign_currency_code='USD', exchange_rate=? WHERE id=?""",
                (transfer_total, normalized_totals.get("USD", 0), rates["USD"], shift_id),
            )

    # -- Cierre de turno --
    def compute_shift_totals(self, shift_id):
        """Calcula (sin cerrar) los totales de venta/costo/utilidad/gastos/efectivo/diferencia."""
        items = self.get_shift_items(shift_id)
        total_sold = sum(i["total_sale"] for i in items)
        total_cost = sum(i["total_cost"] for i in items)
        total_profit = sum(i["profit"] for i in items)

        expenses = self.get_shift_expenses(shift_id)
        total_expenses = sum(e["importe"] for e in expenses)

        cash_counts = self.get_shift_cash_counts(shift_id)
        total_cash_counted = sum(cc["subtotal"] for cc in cash_counts)

        shift = self.get_shift_by_id(shift_id)
        fondo = shift["fondo_cambio"] if shift else 0.0
        transfer_total = shift["transfer_total"] if shift else 0.0
        currency_receipts = self.get_shift_currency_receipts(shift_id)
        if not currency_receipts and shift and shift["foreign_currency_total"]:
            currency_receipts = [{
                "currency_code": shift["foreign_currency_code"],
                "amount": shift["foreign_currency_total"],
                "exchange_rate": shift["exchange_rate"],
            }]
        foreign_currency_totals = {}
        for receipt in currency_receipts:
            code = receipt["currency_code"]
            foreign_currency_totals[code] = foreign_currency_totals.get(code, 0) + receipt["amount"]
        foreign_currency_total = foreign_currency_totals.get("USD", 0)
        exchange_rate = shift["exchange_rate"] if shift else 1.0
        foreign_currency_equivalent = sum(
            receipt["amount"] * receipt["exchange_rate"] for receipt in currency_receipts
        )
        total_received = total_cash_counted + transfer_total + foreign_currency_equivalent
        expected_cash = fondo + total_sold - total_expenses
        difference = total_received - expected_cash

        return {
            "total_sold": total_sold,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "total_expenses": total_expenses,
            "total_cash_counted": total_cash_counted,
            "transfer_total": transfer_total,
            "foreign_currency_total": foreign_currency_total,
            "foreign_currency_totals": foreign_currency_totals,
            "foreign_currency_receipts": currency_receipts,
            "foreign_currency_equivalent": foreign_currency_equivalent,
            "total_received": total_received,
            "foreign_currency_code": shift["foreign_currency_code"] if shift else "USD",
            "exchange_rate": exchange_rate,
            "expected_cash": expected_cash,
            "difference": difference,
            "fondo_cambio": fondo,
        }

    def close_shift(self, shift_id):
        totals = self.compute_shift_totals(shift_id)
        with self.tx():
            self.conn.execute(
                """UPDATE shifts SET
                       total_sold=?, total_cost=?, total_profit=?, total_cash_counted=?,
                       total_expenses=?, difference=?, status='CLOSED', closed_at=?
                   WHERE id=?""",
                (totals["total_sold"], totals["total_cost"], totals["total_profit"],
                 totals["total_cash_counted"], totals["total_expenses"], totals["difference"],
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), shift_id),
            )
            items = self.get_shift_items(shift_id)
            for it in items:
                self.conn.execute(
                    "UPDATE products SET stock_current=? WHERE id=?",
                    (it["final_stock"], it["product_id"]),
                )
        return totals

    def reopen_shift(self, shift_id):
        """Reabre un turno cerrado por error (uso administrativo)."""
        with self.tx():
            self.conn.execute("UPDATE shifts SET status='OPEN', closed_at=NULL WHERE id=?", (shift_id,))

    def search_shifts(self, point_id=None, text=""):
        c = self.conn.cursor()
        q = "SELECT s.*, p.name AS point_name FROM shifts s JOIN points p ON s.point_id = p.id WHERE s.status='CLOSED'"
        params = []
        if point_id:
            q += " AND s.point_id=?"
            params.append(point_id)
        if text:
            q += " AND (s.cashier_name LIKE ? OR s.supervisor_name LIKE ? OR s.opened_at LIKE ? OR p.name LIKE ?)"
            like = f"%{text}%"
            params += [like, like, like, like]
        q += " ORDER BY s.id DESC"
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def get_shift_by_id(self, shift_id):
        c = self.conn.cursor()
        c.execute(
            "SELECT s.*, p.name AS point_name FROM shifts s JOIN points p ON s.point_id = p.id WHERE s.id=?",
            (shift_id,),
        )
        r = c.fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------
    # Balances / Informes contables (rango de fechas)
    # ------------------------------------------------------------------
    def get_shifts_in_range(self, date_from, date_to, point_id=None):
        """Turnos CERRADOS cuya fecha de apertura cae en [date_from, date_to] (YYYY-MM-DD)."""
        c = self.conn.cursor()
        q = """SELECT s.*, p.name AS point_name FROM shifts s
               JOIN points p ON s.point_id = p.id
               WHERE s.status='CLOSED' AND substr(s.opened_at,1,10) BETWEEN ? AND ?"""
        params = [date_from, date_to]
        if point_id:
            q += " AND s.point_id=?"
            params.append(point_id)
        q += " ORDER BY s.opened_at ASC"
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def get_shifts_by_id_range(self, point_id, start_id, end_id):
        """Turnos CERRADOS de un punto con id entre start_id y end_id (inclusive)."""
        lo, hi = min(start_id, end_id), max(start_id, end_id)
        c = self.conn.cursor()
        c.execute(
            """SELECT s.*, p.name AS point_name FROM shifts s
               JOIN points p ON s.point_id = p.id
               WHERE s.status='CLOSED' AND s.point_id=? AND s.id BETWEEN ? AND ?
               ORDER BY s.id ASC""",
            (point_id, lo, hi),
        )
        return [dict(r) for r in c.fetchall()]

    @staticmethod
    def summarize_shifts(shifts):
        """Agrega una lista de turnos (dicts) en el mismo formato que get_balance_summary."""
        total_sold = sum(s["total_sold"] for s in shifts)
        total_cost = sum(s["total_cost"] for s in shifts)
        total_profit = sum(s["total_profit"] for s in shifts)
        total_expenses = sum(s["total_expenses"] for s in shifts)
        total_cash = sum(s["total_cash_counted"] for s in shifts)
        total_difference = sum(s["difference"] for s in shifts)
        margen = (total_profit / total_sold * 100) if total_sold else 0.0
        ventas_netas = total_sold - total_expenses
        return {
            "shifts_count": len(shifts),
            "total_sold": total_sold,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "total_expenses": total_expenses,
            "ventas_netas": ventas_netas,
            "margen_beneficio": margen,
            "total_cash_counted": total_cash,
            "total_difference": total_difference,
            "shifts": shifts,
        }

    def get_balance_summary(self, date_from, date_to, point_id=None):
        """Totales agregados del rango: ventas netas, costo, utilidad, margen, gastos, diferencia."""
        shifts = self.get_shifts_in_range(date_from, date_to, point_id)
        return self.summarize_shifts(shifts)

    def get_top_products_for_shift_ids(self, shift_ids, limit=10):
        if not shift_ids:
            return []
        c = self.conn.cursor()
        placeholders = ",".join("?" * len(shift_ids))
        c.execute(
            f"""SELECT product_name, SUM(sold_qty) AS qty, SUM(total_sale) AS total, SUM(profit) AS profit
               FROM shift_items WHERE shift_id IN ({placeholders})
               GROUP BY product_name HAVING qty > 0 ORDER BY total DESC LIMIT ?""",
            (*shift_ids, limit),
        )
        return [dict(r) for r in c.fetchall()]

    def get_daily_series_for_shift_ids(self, shift_ids):
        if not shift_ids:
            return []
        c = self.conn.cursor()
        placeholders = ",".join("?" * len(shift_ids))
        c.execute(
            f"""SELECT substr(opened_at,1,10) AS day, SUM(total_sold) AS sold, SUM(total_cost) AS cost,
                       SUM(total_profit) AS profit, SUM(total_expenses) AS expenses
               FROM shifts WHERE id IN ({placeholders}) GROUP BY day ORDER BY day ASC""",
            shift_ids,
        )
        return [dict(r) for r in c.fetchall()]

    def get_top_products_in_range(self, date_from, date_to, point_id=None, limit=10):
        c = self.conn.cursor()
        q = """SELECT si.product_name, SUM(si.sold_qty) AS qty, SUM(si.total_sale) AS total,
                      SUM(si.profit) AS profit
               FROM shift_items si
               JOIN shifts s ON si.shift_id = s.id
               WHERE s.status='CLOSED' AND substr(s.opened_at,1,10) BETWEEN ? AND ?"""
        params = [date_from, date_to]
        if point_id:
            q += " AND s.point_id=?"
            params.append(point_id)
        q += " GROUP BY si.product_name HAVING qty > 0 ORDER BY total DESC LIMIT ?"
        params.append(limit)
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def get_daily_series(self, date_from, date_to, point_id=None):
        """Serie diaria de venta/costo/utilidad/gastos para graficar la evolución."""
        c = self.conn.cursor()
        q = """SELECT substr(s.opened_at,1,10) AS day,
                      SUM(s.total_sold) AS sold, SUM(s.total_cost) AS cost,
                      SUM(s.total_profit) AS profit, SUM(s.total_expenses) AS expenses
               FROM shifts s
               WHERE s.status='CLOSED' AND substr(s.opened_at,1,10) BETWEEN ? AND ?"""
        params = [date_from, date_to]
        if point_id:
            q += " AND s.point_id=?"
            params.append(point_id)
        q += " GROUP BY day ORDER BY day ASC"
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def get_expenses_in_range(self, date_from, date_to, point_id=None):
        c = self.conn.cursor()
        q = """SELECT e.*, s.opened_at, p.name AS point_name FROM shift_expenses e
               JOIN shifts s ON e.shift_id = s.id
               JOIN points p ON s.point_id = p.id
               WHERE s.status='CLOSED' AND substr(s.opened_at,1,10) BETWEEN ? AND ?"""
        params = [date_from, date_to]
        if point_id:
            q += " AND s.point_id=?"
            params.append(point_id)
        q += " ORDER BY s.opened_at ASC"
        c.execute(q, params)
        return [dict(r) for r in c.fetchall()]

    def is_latest_shift(self, shift_id):
        """True si no existe ningún turno posterior (abierto o cerrado) en el mismo punto."""
        shift = self.get_shift_by_id(shift_id)
        if not shift:
            return False
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM shifts WHERE point_id=? AND id>?", (shift["point_id"], shift_id))
        return c.fetchone()[0] == 0

    def reopen_shift(self, shift_id):
        """
        Reabre un turno CERRADO para poder corregir cantidades de producto.
        Solo se permite si es el turno más reciente de su punto de venta:
        reabrir un turno intermedio invalidaría el inventario inicial de
        los turnos posteriores, que ya partieron de su stock final.
        """
        if not self.is_latest_shift(shift_id):
            raise BusinessError(
                "Solo se puede reabrir el turno más reciente de este punto de venta. "
                "Los turnos posteriores ya usaron el inventario final de este turno como "
                "punto de partida; reabrirlo los dejaría descuadrados. "
                "Para corregir un turno antiguo, use 'Corregir Gastos/Efectivo', que no "
                "afecta el inventario."
            )
        with self.tx():
            self.conn.execute("UPDATE shifts SET status='OPEN', closed_at=NULL WHERE id=?", (shift_id,))

    def recompute_closed_shift_totals(self, shift_id):
        """
        Recalcula los totales de un turno YA CERRADO a partir de sus gastos y
        conteo de efectivo actuales (tras editarlos desde el historial), sin
        tocar el inventario ni las cantidades vendidas. Seguro de usar en
        cualquier turno cerrado, sin importar su antigüedad.
        """
        shift = self.get_shift_by_id(shift_id)
        if not shift or shift["status"] != "CLOSED":
            raise BusinessError("Solo se pueden corregir turnos que ya estén cerrados.")
        totals = self.compute_shift_totals(shift_id)
        with self.tx():
            self.conn.execute(
                """UPDATE shifts SET total_expenses=?, total_cash_counted=?, difference=? WHERE id=?""",
                (totals["total_expenses"], totals["total_cash_counted"], totals["difference"], shift_id),
            )
        return totals

    # ------------------------------------------------------------------
    # Control de personal
    # ------------------------------------------------------------------
    def get_worker_shift_history(self, worker_name):
        """Todos los turnos cerrados donde `worker_name` participó (como cajero o supervisor)."""
        c = self.conn.cursor()
        c.execute(
            """SELECT s.*, p.name AS point_name FROM shifts s
               JOIN points p ON s.point_id = p.id
               WHERE s.status='CLOSED' AND (s.cashier_name=? OR s.supervisor_name=?)
               ORDER BY s.opened_at DESC""",
            (worker_name, worker_name),
        )
        return [dict(r) for r in c.fetchall()]

    def get_worker_summary(self):
        """Resumen por trabajador: turnos como cajero, total de faltantes y de sobrantes."""
        workers = self.get_workers()
        summary = []
        for w in workers:
            shifts = self.get_worker_shift_history(w)
            worker = self.get_worker(w)
            as_cashier = [s for s in shifts if s["cashier_name"] == w]
            faltantes = sum(-s["difference"] for s in as_cashier if s["difference"] < 0)
            sobrantes = sum(s["difference"] for s in as_cashier if s["difference"] > 0)
            deductions = self.get_worker_salary_deductions(w)
            summary.append({
                "id": worker["id"],
                "name": w,
                "turnos_cajero": len(as_cashier),
                "turnos_supervisor": len([s for s in shifts if s["supervisor_name"] == w]),
                "total_faltantes": faltantes,
                "total_sobrantes": sobrantes,
                "neto": sobrantes - faltantes,
                "role": worker["role"],
                "contact": worker["contact"],
                "compensation_type": worker["compensation_type"],
                "compensation_amount": worker["compensation_amount"],
                "authorized_deductions": sum(d["amount"] for d in deductions if d["authorized"]),
                "pending_deductions": sum(d["amount"] for d in deductions if not d["authorized"]),
            })
        return summary

    def close(self):
        self.conn.close()

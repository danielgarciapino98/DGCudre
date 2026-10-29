"""
Generación de informes contables en PDF: cuadre individual y balance de
un rango de fechas / turnos, con tablas y gráficos (matplotlib embebido).
"""
import os
import tempfile
from datetime import datetime
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, LongTable, TableStyle, Image,
)

from config import config

PRIMARY = colors.HexColor("#1e3a8a")
ACCENT = colors.HexColor("#2563eb")
GREEN = colors.HexColor("#16a34a")
RED = colors.HexColor("#dc2626")
GRAY = colors.HexColor("#64748b")
LIGHT = colors.HexColor("#f1f5f9")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("TitleBrand", parent=styles["Title"], textColor=PRIMARY, fontSize=20))
    styles.add(ParagraphStyle("SubtitleBrand", parent=styles["Normal"], textColor=GRAY, fontSize=10))
    styles.add(ParagraphStyle("SectionHeader", parent=styles["Heading2"], textColor=PRIMARY,
                               spaceBefore=14, spaceAfter=6))
    return styles


def _header(story, styles, subtitle):
    story.append(Paragraph(config.get("Empresa", "nombre", "Mi Negocio"), styles["TitleBrand"]))
    story.append(Paragraph(subtitle, styles["SubtitleBrand"]))
    story.append(Paragraph(
        f"{config.get('Empresa', 'direccion', '')} · Tel: {config.get('Empresa', 'telefono', '')}",
        styles["SubtitleBrand"],
    ))
    story.append(Spacer(1, 10))


def _money(v):
    cur = config.moneda
    return f"{cur}{v:,.2f}"


def _kpi_table(pairs):
    """pairs: lista de (etiqueta, valor_formateado, color_opcional)"""
    data = []
    row = []
    for i, (label, value, color) in enumerate(pairs):
        cell = Table([[Paragraph(f"<font size=8 color='#64748b'>{label}</font>")],
                      [Paragraph(f"<font size=14 color='{color.hexval() if hasattr(color,'hexval') else color}'><b>{value}</b></font>")]],
                     colWidths=[95])
        cell.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        row.append(cell)
    return row


# ------------------------------------------------------------------
# Cuadre individual (versión "bonita" A4, en vez del ticket térmico)
# ------------------------------------------------------------------
def generate_shift_pdf(shift, items, expenses, cash_counts, totals, out_path=None):
    styles = _styles()
    out_path = out_path or os.path.join(tempfile.gettempdir(), f"cuadre_turno_{shift['id']}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []
    _header(story, styles, f"Cuadre de Turno #{shift['id']} — {shift.get('point_name', '')}")

    info_data = [
        ["Apertura", shift["opened_at"], "Cierre", shift.get("closed_at") or "—"],
        ["Entregó", shift["cashier_name"], "Cuadró", shift["supervisor_name"]],
    ]
    info_table = Table(info_data, colWidths=[70, 150, 70, 150])
    info_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
        ("TEXTCOLOR", (2, 0), (2, -1), GRAY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    diff = totals["difference"]
    diff_color = GREEN if diff >= 0 else RED
    diff_label = "SOBRA" if diff >= 0 else "FALTA"
    kpis = [
        ("VENTA BRUTA", _money(totals["total_sold"]), PRIMARY),
        ("UTILIDAD", _money(totals["total_profit"]), GREEN),
        ("GASTOS", _money(totals["total_expenses"]), RED),
        (f"DIFERENCIA ({diff_label})", _money(abs(diff)), diff_color),
    ]
    kpi_row = Table([_kpi_table(kpis)])
    kpi_row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    story.append(kpi_row)
    story.append(Spacer(1, 6))

    resumen = [
        ["Concepto", "Importe"],
        ["Fondo de Cambio", _money(totals["fondo_cambio"])],
        ["Venta Bruta Total", _money(totals["total_sold"])],
        ["Costo de Adquisición", _money(totals["total_cost"])],
        ["Gastos del Turno", _money(totals["total_expenses"])],
        ["Transferencias Recibidas", _money(totals.get("transfer_total", 0))],
        *[
            [f"{receipt['currency_code']} recibidos ({receipt['amount']:,.2f})",
             _money(receipt["amount"] * receipt["exchange_rate"])]
            for receipt in totals.get("foreign_currency_receipts", [])
        ],
        ["Efectivo Esperado", _money(totals["expected_cash"])],
        ["Efectivo Real Contado", _money(totals["total_cash_counted"])],
        ["Total Recibido (equivalente)", _money(totals.get("total_received", totals["total_cash_counted"]))],
        ["Utilidad del Turno", _money(totals["total_profit"])],
    ]
    t = Table(resumen, colWidths=[300, 140])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
    ]))
    story.append(Paragraph("Resumen de Caja", styles["SectionHeader"]))
    story.append(t)

    if cash_counts:
        story.append(Paragraph("Desglose de Efectivo Contado", styles["SectionHeader"]))
        rows = [["Denominación", "Cantidad", "Subtotal"]]
        for cc in cash_counts:
            rows.append([_money(cc["denomination"]), str(cc["quantity"]), _money(cc["subtotal"])])
        ct = Table(rows, colWidths=[150, 150, 140])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ]))
        story.append(ct)

    if expenses:
        story.append(Paragraph("Gastos del Turno", styles["SectionHeader"]))
        rows = [["Tipo", "Referencia", "Trabajador", "Concepto", "Importe"]]
        for e in expenses:
            rows.append([
                Paragraph(escape(str(e.get("category") or "Operativo")), styles["Normal"]),
                Paragraph(escape(str(e.get("persona") or "—")), styles["Normal"]),
                Paragraph(escape(str(e.get("worker_name") or "—")), styles["Normal"]),
                Paragraph(escape(str(e["concepto"])), styles["Normal"]),
                _money(e["importe"]),
            ])
        et = LongTable(rows, colWidths=[52, 78, 78, 207, 75], repeatRows=1)
        et.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), RED), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(et)

    if items:
        story.append(Paragraph("IPV del Cuadre · Movimientos de Inventario", styles["SectionHeader"]))
        rows = [["Código", "Producto", "Inicial", "Entradas", "Traslados", "Roturas", "Vendido", "Final"]]
        for it in items:
            rows.append([
                Paragraph(escape(str(it["product_code"])), styles["Normal"]),
                Paragraph(escape(str(it["product_name"])), styles["Normal"]),
                f"{it['initial_stock']:.2f}", f"{it['entries']:.2f}",
                f"{it['traslados']:.2f}", f"{it['roturas']:.2f}",
                f"{it['sold_qty']:.2f}", f"{it['final_stock']:.2f}",
            ])
        pt = LongTable(rows, colWidths=[45, 142, 45, 45, 48, 42, 45, 45], repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(pt)

    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} por DGCuadres/POS",
                            styles["SubtitleBrand"]))

    doc.build(story)
    return out_path


# ------------------------------------------------------------------
# Balance contable de un rango de fechas
# ------------------------------------------------------------------
def _chart_daily_series(daily_series, out_path):
    days = [d["day"] for d in daily_series]
    sold = [d["sold"] for d in daily_series]
    profit = [d["profit"] for d in daily_series]
    expenses = [d["expenses"] for d in daily_series]

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=150)
    ax.plot(days, sold, marker="o", color="#2563eb", label="Ventas", linewidth=2)
    ax.plot(days, profit, marker="o", color="#16a34a", label="Utilidad", linewidth=2)
    ax.plot(days, expenses, marker="o", color="#dc2626", label="Gastos", linewidth=2)
    ax.set_title("Evolución diaria", fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _chart_top_products(top_products, out_path):
    names = [p["product_name"][:18] for p in top_products][:8][::-1]
    totals = [p["total"] for p in top_products][:8][::-1]

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=150)
    ax.barh(names, totals, color="#2563eb")
    ax.set_title("Top productos por venta", fontsize=11)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.tick_params(axis="both", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def generate_balance_pdf(date_from, date_to, point_label, summary, top_products, daily_series,
                          worker_summary=None, out_path=None):
    styles = _styles()
    out_path = out_path or os.path.join(tempfile.gettempdir(), f"balance_{date_from}_{date_to}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []
    _header(story, styles, f"Balance Contable · {point_label} · {date_from} a {date_to}")

    diff = summary["total_difference"]
    diff_color = GREEN if diff >= 0 else RED
    kpis = [
        ("VENTAS NETAS", _money(summary["ventas_netas"]), PRIMARY),
        ("UTILIDAD BRUTA", _money(summary["total_profit"]), GREEN),
        ("MARGEN DE BENEFICIO", f"{summary['margen_beneficio']:.1f}%", ACCENT),
        ("GASTOS TOTALES", _money(summary["total_expenses"]), RED),
        ("DIF. DE CAJA ACUM.", _money(diff), diff_color),
    ]
    kpi_row = Table([_kpi_table(kpis)])
    kpi_row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    story.append(kpi_row)
    story.append(Spacer(1, 6))

    resumen = [
        ["Concepto", "Importe"],
        ["Turnos cerrados en el período", str(summary["shifts_count"])],
        ["Venta Bruta Total", _money(summary["total_sold"])],
        ["Costo de Adquisición", _money(summary["total_cost"])],
        ["Gastos Totales", _money(summary["total_expenses"])],
        ["Ventas Netas (venta - gastos)", _money(summary["ventas_netas"])],
        ["Utilidad Bruta", _money(summary["total_profit"])],
        ["Margen de Beneficio", f"{summary['margen_beneficio']:.2f} %"],
        ["Efectivo Contado Acumulado", _money(summary["total_cash_counted"])],
        ["Diferencia de Caja Acumulada", _money(summary["total_difference"])],
    ]
    t = Table(resumen, colWidths=[300, 140])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
    ]))
    story.append(Paragraph("Resumen del Período", styles["SectionHeader"]))
    story.append(t)

    if len(daily_series) >= 2:
        chart1 = _chart_daily_series(daily_series, os.path.join(tempfile.gettempdir(), "chart_daily.png"))
        story.append(Paragraph("Evolución en el Tiempo", styles["SectionHeader"]))
        story.append(Image(chart1, width=170 * mm, height=75 * mm))

    if top_products:
        chart2 = _chart_top_products(top_products, os.path.join(tempfile.gettempdir(), "chart_top.png"))
        story.append(Paragraph("Productos Más Vendidos", styles["SectionHeader"]))
        story.append(Image(chart2, width=170 * mm, height=75 * mm))

        rows = [["Producto", "Cantidad", "Venta Total", "Utilidad"]]
        for p in top_products[:10]:
            rows.append([p["product_name"], str(p["qty"]), _money(p["total"]), _money(p["profit"])])
        pt = Table(rows, colWidths=[190, 80, 90, 90])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ]))
        story.append(pt)

    if summary["shifts"]:
        story.append(Paragraph("Detalle de Turnos del Período", styles["SectionHeader"]))
        rows = [["Folio", "Punto", "Fecha", "Cajero", "Venta", "Utilidad", "Diferencia"]]
        for s in summary["shifts"]:
            d = s["difference"]
            d_str = f"+{_money(d)}" if d >= 0 else f"-{_money(abs(d))}"
            rows.append([f"#{s['id']}", Paragraph(escape(str(s["point_name"])), styles["Normal"]),
                         s["opened_at"][:16], Paragraph(escape(str(s["cashier_name"])), styles["Normal"]),
                         _money(s["total_sold"]), _money(s["total_profit"]), d_str])
        st = LongTable(rows, colWidths=[35, 70, 75, 75, 55, 55, 55], repeatRows=1)
        st.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("ALIGN", (4, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ]))
        story.append(st)

    if worker_summary:
        story.append(Paragraph("Desempeño por Trabajador", styles["SectionHeader"]))
        rows = [["Trabajador", "Turnos (cajero)", "Faltantes", "Sobrantes", "Neto"]]
        for w in worker_summary:
            rows.append([w["name"], str(w["turnos_cajero"]), _money(w["total_faltantes"]),
                         _money(w["total_sobrantes"]), _money(w["neto"])])
        wt = LongTable(rows, colWidths=[140, 90, 90, 90, 90], repeatRows=1)
        wt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ]))
        story.append(wt)

    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} por DGCuadres/POS",
                            styles["SubtitleBrand"]))

    doc.build(story)
    return out_path


def generate_inventory_pdf(point_name, products, out_path=None):
    styles = _styles()
    out_path = out_path or os.path.join(
        tempfile.gettempdir(), f"inventario_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    doc = SimpleDocTemplate(
        out_path, pagesize=A4, topMargin=15 * mm, bottomMargin=12 * mm,
        leftMargin=12 * mm, rightMargin=12 * mm,
    )
    story = []
    _header(story, styles, f"Inventario actual · {point_name} · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rows = [["Código", "Producto", "Unidad", "Stock", "Costo", "Precio", "Vencimiento"]]
    for product in products:
        rows.append([
            Paragraph(escape(str(product["code"])), styles["Normal"]),
            Paragraph(escape(str(product["name"])), styles["Normal"]),
            Paragraph(escape(str(product.get("unit") or "")), styles["Normal"]),
            str(product["stock_current"]),
            _money(product["cost_price"]),
            _money(product["sale_price"]),
            str(product.get("expiration_date") or "—"),
        ])
    table = LongTable(rows, colWidths=[58, 155, 42, 45, 62, 62, 65], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Productos incluidos: {len(products)}", styles["SubtitleBrand"]))
    doc.build(story)
    return out_path

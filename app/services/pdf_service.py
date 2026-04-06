"""
Generowanie podglądu faktury jako HTML gotowego do druku.

Endpoint zwraca stronę HTML z @media print CSS.
Użytkownik otwiera w nowej karcie i drukuje do PDF (Ctrl+P / File → Print).
"""
from __future__ import annotations

from html import escape

from app.schemas.invoice import InvoiceResponse

# Klasy statusów do etykiet PL
_STATUS_LABELS: dict[str, str] = {
    "draft": "Szkic",
    "ready_for_submission": "Gotowa do wysyłki",
    "sending": "Wysyłanie",
    "accepted": "Zatwierdzona",
    "rejected": "Odrzucona",
}


def _esc(value: object) -> str:
    return escape(str(value)) if value is not None else ""


def render_invoice_html(invoice: InvoiceResponse) -> str:
    seller = invoice.seller_snapshot
    buyer = invoice.buyer_snapshot
    status_label = _STATUS_LABELS.get(invoice.status, invoice.status)
    number = invoice.number_local or "—"

    rows = ""
    for item in invoice.items:
        rows += f"""
        <tr>
          <td>{_esc(item.name)}</td>
          <td class="num">{_esc(item.quantity)}</td>
          <td>{_esc(item.unit)}</td>
          <td class="num">{_esc(item.unit_price_net)}</td>
          <td class="num">{_esc(item.vat_rate)}%</td>
          <td class="num">{_esc(item.net_total)}</td>
          <td class="num">{_esc(item.vat_total)}</td>
          <td class="num bold">{_esc(item.gross_total)}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faktura {_esc(number)}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, Arial, sans-serif;
    font-size: 13px;
    color: #111;
    padding: 24px;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .meta {{ color: #555; margin-bottom: 20px; font-size: 12px; }}
  .parties {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 20px; }}
  .party h3 {{ font-size: 12px; text-transform: uppercase; color: #888; margin-bottom: 6px; }}
  .party p {{ margin-bottom: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
  th {{ background: #f5f5f5; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
  .num {{ text-align: right; }}
  .bold {{ font-weight: 700; }}
  .totals {{ text-align: right; }}
  .totals p {{ margin-bottom: 4px; }}
  .totals .total-gross {{ font-size: 18px; font-weight: 700; margin-top: 8px; }}
  .badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    background: #e0e0e0;
    color: #333;
  }}
  .badge-draft {{ background: #e9ecef; color: #333; }}
  .badge-accepted {{ background: #d4edda; color: #155724; }}
  .badge-rejected {{ background: #f8d7da; color: #721c24; }}
  .badge-sending {{ background: #fff3cd; color: #856404; }}
  .badge-ready_for_submission {{ background: #cce5ff; color: #004085; }}
  .print-btn {{
    display: block;
    margin: 0 auto 24px;
    padding: 10px 32px;
    background: #0d6efd;
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
  }}
  @media print {{
    .print-btn {{ display: none; }}
    body {{ padding: 0; }}
  }}
</style>
</head>
<body>
<button class="print-btn" onclick="window.print()">Drukuj / Zapisz jako PDF</button>

<h1>Faktura {_esc(number)}</h1>
<div class="meta">
  Status: <span class="badge badge-{_esc(invoice.status)}">{_esc(status_label)}</span>
  &nbsp;&bull;&nbsp; Data wystawienia: {_esc(invoice.issue_date)}
  &nbsp;&bull;&nbsp; Data sprzedaży: {_esc(invoice.sale_date)}
  &nbsp;&bull;&nbsp; Waluta: {_esc(invoice.currency)}
</div>

<div class="parties">
  <div class="party">
    <h3>Sprzedawca</h3>
    <p><strong>{_esc(seller.get("name", ""))}</strong></p>
    <p>NIP: {_esc(seller.get("nip", ""))}</p>
    <p>{_esc(seller.get("address", ""))}</p>
    <p>{_esc(seller.get("city", ""))}</p>
  </div>
  <div class="party">
    <h3>Nabywca</h3>
    <p><strong>{_esc(buyer.get("name", ""))}</strong></p>
    <p>NIP: {_esc(buyer.get("nip", ""))}</p>
    <p>{_esc(buyer.get("address", ""))}</p>
    <p>{_esc(buyer.get("city", ""))}</p>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>Nazwa</th>
      <th>Ilość</th>
      <th>J.m.</th>
      <th class="num">Cena netto</th>
      <th class="num">VAT %</th>
      <th class="num">Netto</th>
      <th class="num">VAT</th>
      <th class="num">Brutto</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<div class="totals">
  <p>Razem netto: <strong>{_esc(invoice.total_net)} {_esc(invoice.currency)}</strong></p>
  <p>Razem VAT: <strong>{_esc(invoice.total_vat)} {_esc(invoice.currency)}</strong></p>
  <p class="total-gross">Do zapłaty: {_esc(invoice.total_gross)} {_esc(invoice.currency)}</p>
</div>

</body>
</html>"""

#!/usr/bin/env python3
"""
Seed: faktury sprzedaży i zakupów dla marca i kwietnia 2026.

Sprzedaż:   4 faktury w marcu, 7 w kwietniu
Zakupy:     9 faktur w marcu, 7 w kwietniu
"""
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

BASE_URL  = "http://localhost:8000"
USERNAME  = "admin"
PASSWORD  = "admin123"
BUYER_PL  = "695322e7-4ade-48a5-8057-274441853751"
BUYER_DE  = "8badc66c-4f4c-4529-89f0-d65c919cbcad"


def login():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def h(token):
    return {"Authorization": f"Bearer {token}"}


def post_invoice(token, data):
    r = requests.post(f"{BASE_URL}/api/v1/invoices/", json=data, headers=h(token), timeout=10)
    if r.status_code not in (200, 201):
        print(f"  BŁĄD {r.status_code}: {r.text[:120]}")
        return None
    inv = r.json()
    num = inv.get('number_local') or '(szkic)'
    print(f"  ✓ {num:20}  {inv['total_gross']:>10} {inv['currency']}  {inv['issue_date']}")
    return inv


SALE_MARCH = [
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-03", "sale_date": "2026-03-03",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Usługa wdrożeniowa", "quantity": "8", "unit": "godz",
                "unit_price_net": "180.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-10", "sale_date": "2026-03-10",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Abonament SaaS", "quantity": "1", "unit": "mies",
                "unit_price_net": "450.00", "vat_rate": "0.23"},
               {"name": "Wsparcie techniczne", "quantity": "3", "unit": "godz",
                "unit_price_net": "120.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_DE, "issue_date": "2026-03-17", "sale_date": "2026-03-17",
     "currency": "EUR", "direction": "sale",
     "items": [{"name": "Consulting services", "quantity": "12", "unit": "h",
                "unit_price_net": "90.00", "vat_rate": "0.00"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-25", "sale_date": "2026-03-25",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Projekt UX/UI", "quantity": "1", "unit": "szt",
                "unit_price_net": "2400.00", "vat_rate": "0.23"}]},
]

SALE_APRIL = [
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-01", "sale_date": "2026-04-01",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Usługa programistyczna", "quantity": "10", "unit": "godz",
                "unit_price_net": "160.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-03", "sale_date": "2026-04-03",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Szkolenie online", "quantity": "2", "unit": "dzień",
                "unit_price_net": "800.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_DE, "issue_date": "2026-04-05", "sale_date": "2026-04-05",
     "currency": "EUR", "direction": "sale",
     "items": [{"name": "API integration", "quantity": "15", "unit": "h",
                "unit_price_net": "95.00", "vat_rate": "0.00"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-07", "sale_date": "2026-04-07",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Licencja roczna", "quantity": "3", "unit": "szt",
                "unit_price_net": "399.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-09", "sale_date": "2026-04-09",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Hosting premium", "quantity": "1", "unit": "mies",
                "unit_price_net": "900.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-11", "sale_date": "2026-04-11",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Analiza bezpieczeństwa", "quantity": "5", "unit": "godz",
                "unit_price_net": "220.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-14", "sale_date": "2026-04-14",
     "currency": "PLN", "direction": "sale",
     "items": [{"name": "Dokumentacja techniczna", "quantity": "1", "unit": "szt",
                "unit_price_net": "1800.00", "vat_rate": "0.23"},
               {"name": "Review kodu", "quantity": "4", "unit": "godz",
                "unit_price_net": "150.00", "vat_rate": "0.23"}]},
]

PURCHASE_MARCH = [
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-02", "sale_date": "2026-03-02",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Laptop Dell XPS", "quantity": "1", "unit": "szt",
                "unit_price_net": "4500.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-04", "sale_date": "2026-03-04",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Licencja Adobe CC", "quantity": "1", "unit": "rok",
                "unit_price_net": "2700.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-06", "sale_date": "2026-03-06",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Najem biura", "quantity": "1", "unit": "mies",
                "unit_price_net": "1200.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-09", "sale_date": "2026-03-09",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Usługi księgowe", "quantity": "1", "unit": "mies",
                "unit_price_net": "600.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-12", "sale_date": "2026-03-12",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Internet światłowodowy", "quantity": "1", "unit": "mies",
                "unit_price_net": "180.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-15", "sale_date": "2026-03-15",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Oprogramowanie antywirusowe", "quantity": "5", "unit": "szt",
                "unit_price_net": "89.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-18", "sale_date": "2026-03-18",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Drukarka laserowa", "quantity": "1", "unit": "szt",
                "unit_price_net": "1100.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-21", "sale_date": "2026-03-21",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Paliwo – delegacja", "quantity": "1", "unit": "szt",
                "unit_price_net": "340.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-03-28", "sale_date": "2026-03-28",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Materiały biurowe", "quantity": "1", "unit": "kpl",
                "unit_price_net": "210.00", "vat_rate": "0.23"},
               {"name": "Toner zamiennik", "quantity": "2", "unit": "szt",
                "unit_price_net": "95.00", "vat_rate": "0.23"}]},
]

PURCHASE_APRIL = [
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-02", "sale_date": "2026-04-02",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Najem biura", "quantity": "1", "unit": "mies",
                "unit_price_net": "1200.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-03", "sale_date": "2026-04-03",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Usługi księgowe", "quantity": "1", "unit": "mies",
                "unit_price_net": "600.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-04", "sale_date": "2026-04-04",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Internet światłowodowy", "quantity": "1", "unit": "mies",
                "unit_price_net": "180.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-06", "sale_date": "2026-04-06",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Subskrypcja GitHub Teams", "quantity": "3", "unit": "szt",
                "unit_price_net": "44.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-08", "sale_date": "2026-04-08",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "AWS – chmura obliczeniowa", "quantity": "1", "unit": "mies",
                "unit_price_net": "750.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-10", "sale_date": "2026-04-10",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Szkolenie BHP", "quantity": "4", "unit": "os",
                "unit_price_net": "85.00", "vat_rate": "0.23"}]},
    {"buyer_id": BUYER_PL, "issue_date": "2026-04-13", "sale_date": "2026-04-13",
     "currency": "PLN", "direction": "purchase",
     "items": [{"name": "Paliwo – delegacja", "quantity": "1", "unit": "szt",
                "unit_price_net": "280.00", "vat_rate": "0.23"},
               {"name": "Opłata parkingowa", "quantity": "1", "unit": "szt",
                "unit_price_net": "45.00", "vat_rate": "0.23"}]},
]


def main():
    print("=== Seed faktur miesięcznych ===\n")
    token = login()
    print(f"✓ Zalogowano\n")

    print("[1/4] Sprzedaż – marzec 2026 (4 faktury)")
    for inv in SALE_MARCH:
        post_invoice(token, inv)

    print("\n[2/4] Sprzedaż – kwiecień 2026 (7 faktur)")
    for inv in SALE_APRIL:
        post_invoice(token, inv)

    print("\n[3/4] Zakupy – marzec 2026 (9 faktur)")
    for inv in PURCHASE_MARCH:
        post_invoice(token, inv)

    print("\n[4/4] Zakupy – kwiecień 2026 (7 faktur)")
    for inv in PURCHASE_APRIL:
        post_invoice(token, inv)

    print("\n✓ Gotowe!")


if __name__ == "__main__":
    main()

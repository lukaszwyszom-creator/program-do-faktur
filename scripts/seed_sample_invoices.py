#!/usr/bin/env python3
"""
Skrypt ładujący przykładowe dane do działającej instancji API.

Użycie:
    python scripts/seed_sample_invoices.py

Tworzy:
  - 2 kontrahentów (krajowy + zagraniczny)
  - 5 przykładowych faktur sprzedaży
"""
import sys
import json
from datetime import date, timedelta

try:
    import requests
except ImportError:
    sys.exit("Brak biblioteki requests. Zainstaluj: pip install requests")

BASE_URL = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "admin123"

TODAY = date.today()


def login() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        sys.exit(f"Błąd logowania: {resp.status_code} {resp.text}")
    token = resp.json().get("access_token")
    print(f"✓ Zalogowano jako {USERNAME}")
    return token


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_contractor(token: str, data: dict) -> str:
    resp = requests.post(
        f"{BASE_URL}/api/v1/contractors",
        json=data,
        headers=headers(token),
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        sys.exit(f"Błąd tworzenia kontrahenta: {resp.status_code} {resp.text}")
    cid = resp.json()["id"]
    print(f"  ✓ Kontrahent: {data['name']} → {cid}")
    return cid


def create_invoice(token: str, data: dict) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/v1/invoices",
        json=data,
        headers=headers(token),
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        sys.exit(f"Błąd tworzenia faktury: {resp.status_code} {resp.text}")
    inv = resp.json()
    print(f"  ✓ Faktura {inv.get('number_local', inv['id'][:8]+'...')} — {inv['total_gross']} {inv['currency']}")
    return inv


def main():
    print("=== Seed danych przykładowych ===\n")

    token = login()

    # --- Kontrahenci ---
    print("\n[1/3] Tworzenie kontrahentów...")

    buyer_pl = create_contractor(token, {
        "nip": "1234563218",
        "name": "Firma Testowa Krajowa Sp. z o.o.",
        "street": "ul. Testowa",
        "building_no": "1",
        "city": "Warszawa",
        "postal_code": "00-001",
        "country": "PL",
    })

    buyer_de = create_contractor(token, {
        "nip": "DE123456789",
        "name": "Deutsche Test GmbH",
        "street": "Teststrasse",
        "building_no": "10",
        "city": "Berlin",
        "postal_code": "10115",
        "country": "DE",
    })

    # --- Faktury ---
    print("\n[2/3] Tworzenie faktur...")

    invoices = [
        {
            "buyer_id": buyer_pl,
            "issue_date": str(TODAY - timedelta(days=30)),
            "sale_date": str(TODAY - timedelta(days=30)),
            "currency": "PLN",
            "direction": "sale",
            "items": [
                {"name": "Usługa programistyczna", "quantity": "10", "unit": "godz",
                 "unit_price_net": "150.00", "vat_rate": "0.23"},
                {"name": "Konsultacja", "quantity": "2", "unit": "godz",
                 "unit_price_net": "200.00", "vat_rate": "0.23"},
            ],
        },
        {
            "buyer_id": buyer_pl,
            "issue_date": str(TODAY - timedelta(days=20)),
            "sale_date": str(TODAY - timedelta(days=20)),
            "currency": "PLN",
            "direction": "sale",
            "items": [
                {"name": "Hosting serwera", "quantity": "1", "unit": "mies",
                 "unit_price_net": "500.00", "vat_rate": "0.23"},
                {"name": "Domena .pl", "quantity": "1", "unit": "rok",
                 "unit_price_net": "80.00", "vat_rate": "0.23"},
                {"name": "Certyfikat SSL", "quantity": "1", "unit": "rok",
                 "unit_price_net": "120.00", "vat_rate": "0.23"},
            ],
        },
        {
            "buyer_id": buyer_pl,
            "issue_date": str(TODAY - timedelta(days=15)),
            "sale_date": str(TODAY - timedelta(days=15)),
            "currency": "PLN",
            "direction": "sale",
            "items": [
                {"name": "Licencja oprogramowania", "quantity": "5", "unit": "szt",
                 "unit_price_net": "299.00", "vat_rate": "0.23"},
            ],
        },
        {
            "buyer_id": buyer_de,
            "issue_date": str(TODAY - timedelta(days=10)),
            "sale_date": str(TODAY - timedelta(days=10)),
            "currency": "EUR",
            "direction": "sale",
            "items": [
                {"name": "Software development", "quantity": "20", "unit": "h",
                 "unit_price_net": "85.00", "vat_rate": "0.00"},
            ],
        },
        {
            "buyer_id": buyer_pl,
            "issue_date": str(TODAY - timedelta(days=3)),
            "sale_date": str(TODAY - timedelta(days=3)),
            "currency": "PLN",
            "direction": "sale",
            "items": [
                {"name": "Projekt graficzny", "quantity": "1", "unit": "szt",
                 "unit_price_net": "1200.00", "vat_rate": "0.23"},
                {"name": "Poprawki", "quantity": "3", "unit": "godz",
                 "unit_price_net": "120.00", "vat_rate": "0.23"},
            ],
        },
    ]

    created = [create_invoice(token, inv) for inv in invoices]

    print(f"\n[3/3] Podsumowanie")
    print(f"  Kontrahenci: 2")
    print(f"  Faktury:     {len(created)}")
    total = sum(float(inv["total_gross"]) for inv in created if inv["currency"] == "PLN")
    print(f"  Łączna wartość brutto (PLN): {total:.2f} zł")
    print("\n✓ Gotowe! Odśwież aplikację: http://localhost:3000")


if __name__ == "__main__":
    main()

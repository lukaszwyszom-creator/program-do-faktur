#!/usr/bin/env python3
"""
Samodzielny skrypt testowy dla przepływu uwierzytelnienia KSeF 2.0.

Uruchomienie:
    pip install httpx cryptography
    python scripts/test_ksef_auth.py --nip <NIP> --token <KSEF_TOKEN> [--env test|production]

Lub przez zmienne środowiskowe:
    KSEF_NIP=9670402857 KSEF_TOKEN=xxx python scripts/test_ksef_auth.py
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime

# Sprawdź zależności
try:
    import httpx
except ImportError:
    sys.exit("Brak pakietu 'httpx'. Zainstaluj: pip install httpx")

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.x509 import load_der_x509_certificate
except ImportError:
    sys.exit("Brak pakietu 'cryptography'. Zainstaluj: pip install cryptography")


_KSEF_URLS = {
    "test": "https://api-test.ksef.mf.gov.pl/v2",
    "production": "https://api.ksef.mf.gov.pl/v2",
}
_USAGE_TOKEN_ENCRYPTION = "KsefTokenEncryption"


def log(step: str, msg: str, data: dict | str | None = None) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n[{ts}] {'='*10} {step} {'='*10}")
    print(f"  {msg}")
    if data:
        if isinstance(data, dict):
            print(json.dumps(data, indent=4, ensure_ascii=False))
        else:
            print(f"  {data}")


def step1_get_challenge(base_url: str) -> dict:
    log("KROK 1", "POST /auth/challenge")
    resp = httpx.post(f"{base_url}/auth/challenge", timeout=30)
    log("KROK 1", f"Status: {resp.status_code}", resp.json())
    resp.raise_for_status()
    return resp.json()


def step2_get_public_key(base_url: str) -> bytes:
    log("KROK 2", "GET /security/public-key-certificates")
    resp = httpx.get(f"{base_url}/security/public-key-certificates", timeout=30)
    certs = resp.json()
    log("KROK 2", f"Status: {resp.status_code}, liczba certyfikatów: {len(certs)}")
    for c in certs:
        print(f"  - usage: {c.get('usage')}, subject: {c.get('subject', '')[:60]}")
    resp.raise_for_status()

    for cert_info in certs:
        if _USAGE_TOKEN_ENCRYPTION in cert_info.get("usage", []):
            log("KROK 2", f"Znaleziono certyfikat '{_USAGE_TOKEN_ENCRYPTION}'")
            return base64.b64decode(cert_info["certificate"])

    sys.exit(f"BŁĄD: Brak certyfikatu o użyciu '{_USAGE_TOKEN_ENCRYPTION}'")


def step3_encrypt_token(ksef_token: str, timestamp_ms: int, cert_der: bytes) -> str:
    log("KROK 3", f"Szyfrowanie tokena RSA-OAEP (timestampMs={timestamp_ms})")
    cert = load_der_x509_certificate(cert_der)
    public_key = cert.public_key()
    plaintext = f"{ksef_token}|{timestamp_ms}".encode("utf-8")
    print(f"  Plaintext (przed szyfrowaniem): {ksef_token[:4]}...{ksef_token[-4:]}|{timestamp_ms}")
    encrypted = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    result = base64.b64encode(encrypted).decode("ascii")
    log("KROK 3", f"Zaszyfrowano. Długość base64: {len(result)} znaków")
    return result


def step4_init_auth(base_url: str, nip: str, challenge: str, encrypted_token: str) -> dict:
    log("KROK 4", f"POST /auth/ksef-token (NIP={nip})")
    payload = {
        "challenge": challenge,
        "contextIdentifier": {"type": "Nip", "value": nip},
        "encryptedToken": encrypted_token,
    }
    print(f"  Payload (bez encryptedToken): challenge={challenge}")
    resp = httpx.post(f"{base_url}/auth/ksef-token", json=payload, timeout=30)

    # Loguj pełną odpowiedź
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    log("KROK 4", f"Status: {resp.status_code}", body if isinstance(body, dict) else {"raw": str(body)[:300]})
    resp.raise_for_status()
    return resp.json()


def step5_redeem_tokens(base_url: str, authentication_token: str) -> dict:
    log("KROK 5", "POST /auth/token/redeem (polling dla statusu 450)")
    url = f"{base_url}/auth/token/redeem"
    max_wait = 30.0
    delay = 0.5
    elapsed = 0.0
    attempt = 0

    while True:
        attempt += 1
        print(f"\n  Próba #{attempt} (elapsed={elapsed:.1f}s, delay={delay:.1f}s)")
        resp = httpx.post(url, headers={"Authorization": f"Bearer {authentication_token}"}, timeout=30)

        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:300]}

        print(f"  Status: {resp.status_code}")
        print(f"  Body: {json.dumps(body, ensure_ascii=False)[:400]}")

        if resp.status_code == 400 and elapsed < max_wait:
            detail_list = body.get("exception", {}).get("exceptionDetailList", []) if isinstance(body, dict) else []
            still_processing = any(
                d.get("exceptionCode") == 21301
                and any("450" in str(x) for x in d.get("details", []))
                for d in detail_list
            )
            if still_processing:
                print(f"  → Auth w toku (status 450), czekam {delay:.1f}s...")
                time.sleep(delay)
                elapsed += delay
                delay = min(delay * 1.5, 5.0)
                continue
            else:
                print(f"  → Inny błąd 400 (nie status 450), nie ponawiam.")

        if resp.status_code != 200:
            print(f"\n  BŁĄD: /token/redeem zwrócił {resp.status_code}")
            print(f"  Szczegóły: {json.dumps(body, indent=2, ensure_ascii=False)}")
            sys.exit(1)

        log("KROK 5", f"Sukces po {attempt} próbach, elapsed={elapsed:.1f}s", body)
        return body


def main() -> None:
    parser = argparse.ArgumentParser(description="Test uwierzytelnienia KSeF 2.0")
    parser.add_argument("--nip", default=os.getenv("KSEF_NIP"), help="NIP podatnika")
    parser.add_argument("--token", default=os.getenv("KSEF_TOKEN"), help="Token KSeF")
    parser.add_argument("--env", default=os.getenv("KSEF_ENV", "test"), choices=["test", "production"])
    args = parser.parse_args()

    if not args.nip:
        sys.exit("Podaj NIP: --nip <NIP> lub KSEF_NIP=<NIP>")
    if not args.token:
        sys.exit("Podaj token KSeF: --token <TOKEN> lub KSEF_TOKEN=<TOKEN>")

    base_url = _KSEF_URLS[args.env]
    print(f"\nŚrodowisko: {args.env} ({base_url})")
    print(f"NIP: {args.nip}")
    print(f"Token KSeF: {args.token[:4]}...{args.token[-4:]} (długość: {len(args.token)})")

    try:
        # Krok 1: Challenge
        challenge_data = step1_get_challenge(base_url)

        # Krok 2+3: Klucz publiczny + szyfrowanie
        cert_der = step2_get_public_key(base_url)
        encrypted = step3_encrypt_token(args.token, challenge_data["timestampMs"], cert_der)

        # Krok 4: Inicjacja uwierzytelnienia
        auth_init = step4_init_auth(base_url, args.nip, challenge_data["challenge"], encrypted)
        auth_token = auth_init["authenticationToken"]["token"]
        ref_number = auth_init.get("referenceNumber", "N/A")
        print(f"\n  referenceNumber: {ref_number}")
        print(f"  authenticationToken (skrót): {auth_token[:20]}...{auth_token[-10:]}")

        # Krok 5: Redeem z pollingiem
        tokens = step5_redeem_tokens(base_url, auth_token)

        # Podsumowanie
        print("\n" + "="*50)
        print("SUKCES — Uwierzytelnienie zakończone pomyślnie!")
        print("="*50)
        at = tokens.get("accessToken", {})
        rt = tokens.get("refreshToken", {})
        print(f"  accessToken  (skrót): {at.get('token','?')[:20]}...")
        print(f"  accessToken  ważny do: {at.get('validUntil','?')}")
        print(f"  refreshToken (skrót): {rt.get('token','?')[:20]}...")
        print(f"  refreshToken ważny do: {rt.get('validUntil','?')}")

    except KeyboardInterrupt:
        print("\n\nPrzerwano.")
    except Exception as exc:
        print(f"\n\nNIEOCZEKIWANY BŁĄD: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

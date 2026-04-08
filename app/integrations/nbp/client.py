"""Klient REST API NBP (Narodowy Bank Polski) — kursy walut.

API: https://api.nbp.pl/api/exchangerates/rates/a/{code}/{date}/?format=json
Tabela A — kursy średnie walut obcych ogłaszane przez NBP.

W przypadku braku kursu dla danej daty (weekend, święto) automatycznie
cofa się o co najwyżej ``_MAX_LOOKBACK_DAYS`` dni roboczych wstecz.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

_NBP_BASE = "https://api.nbp.pl/api/exchangerates/rates/a"
_MAX_LOOKBACK_DAYS = 7
_REQUEST_TIMEOUT = 10


class NbpRateError(Exception):
    """Zbiorowy wyjątek dla błędów klienta NBP."""


class NbpRateClient:
    """Pobiera kurs średni (mid) z tabeli kursów NBP (tabela A).

    Parametry:
        session: opcjonalny ``requests.Session``; jeśli None, tworzony jest nowy.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def get_mid_rate(self, currency_code: str, rate_date: date) -> Decimal:
        """Zwraca kurs średni (mid) z tabeli A NBP.

        Jeśli dla ``rate_date`` nie ma kursu (weekend/święto), sprawdza
        kolejne dni wstecz (do ``_MAX_LOOKBACK_DAYS``).

        Args:
            currency_code: kod waluty ISO 4217, np. "USD", "EUR".
            rate_date: data kursu; zazwyczaj dzień poprzedzający datę faktury.

        Returns:
            Kurs środkowy jako Decimal.

        Raises:
            NbpRateError: gdy nie znaleziono kursu lub API zwróciło błąd.
        """
        code = currency_code.upper()
        for days_back in range(_MAX_LOOKBACK_DAYS + 1):
            d = rate_date - timedelta(days=days_back)
            url = f"{_NBP_BASE}/{code}/{d.isoformat()}/?format=json"
            try:
                resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise NbpRateError(
                    f"Błąd połączenia z NBP API: {exc}"
                ) from exc

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    mid = data["rates"][0]["mid"]
                    logger.debug("NBP %s/%s mid=%s (szukano %s)", code, d, mid, rate_date)
                    return Decimal(str(mid))
                except (KeyError, IndexError, ValueError) as exc:
                    raise NbpRateError(
                        f"Nieprawidłowa odpowiedź NBP API dla {code}/{d}: {exc}"
                    ) from exc
            elif resp.status_code == 404:
                logger.debug("NBP 404 dla %s/%s — próba %d dni wstecz", code, d, days_back)
                continue
            else:
                raise NbpRateError(
                    f"NBP API HTTP {resp.status_code} dla {code}/{d}: {resp.text[:200]}"
                )

        raise NbpRateError(
            f"Brak kursu NBP dla {code} w dniu {rate_date} "
            f"(sprawdzono {_MAX_LOOKBACK_DAYS} dni wstecz)."
        )

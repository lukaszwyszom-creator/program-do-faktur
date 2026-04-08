"""Walidator kursu walutowego faktury względem oficjalnego kursu NBP.

Pobiera kurs ze stołu A NBP i porównuje z wartością podaną na fakturze.
Tolerancja domyślna: 0,0100 PLN (1 grosz na jednostkę waluty).
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.exceptions import InvalidInvoiceError
from app.domain.models.invoice import Invoice
from app.integrations.nbp.client import NbpRateClient, NbpRateError

_DEFAULT_TOLERANCE = Decimal("0.0100")


class NbpRateValidator:
    """Waliduje exchange_rate na fakturze względem oficjalnego kursu NBP.

    Args:
        nbp_client: instancja ``NbpRateClient``.
        tolerance: maksymalna dozwolona różnica w PLN. Domyślnie 1 grosz.
    """

    def __init__(
        self,
        nbp_client: NbpRateClient,
        tolerance: Decimal = _DEFAULT_TOLERANCE,
    ) -> None:
        self._nbp_client = nbp_client
        self._tolerance = tolerance

    def validate(self, invoice: Invoice) -> None:
        """Sprawdza kurs wymiany na fakturze względem tabeli A NBP.

        Walidacja jest pomijana jeśli:
        - ``invoice.exchange_rate`` jest None
        - waluta faktury to PLN

        Raises:
            InvalidInvoiceError: gdy kurs jest poza dozwoloną tolerancją.
            InvalidInvoiceError: gdy nie można pobrać kursu z NBP (błąd sieci/API).
        """
        if invoice.exchange_rate is None or invoice.currency == "PLN":
            return

        rate_date = invoice.exchange_rate_date or invoice.issue_date
        try:
            official_rate = self._nbp_client.get_mid_rate(invoice.currency, rate_date)
        except NbpRateError as exc:
            raise InvalidInvoiceError(
                f"Nie można pobrać kursu NBP dla {invoice.currency}/{rate_date}: {exc}"
            ) from exc

        invoice.validate_exchange_rate_against_nbp(official_rate, self._tolerance)

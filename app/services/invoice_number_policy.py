from __future__ import annotations


class InvoiceNumberPolicy:
    """
    Policy odpowiedzialna wyłącznie za format numeru faktury.

    Brak IO.
    Brak zależności od repozytoriów.
    Brak stanu (stateless).
    """

    @staticmethod
    def generate(year: int, month: int, seq: int) -> str:
        """
        Generuje numer faktury w formacie:
        FV/{seq}/{MM}/{YYYY}

        Przykład:
        FV/12/04/2026
        """
        mm = f"{month:02d}"
        return f"FV/{seq}/{mm}/{year}"
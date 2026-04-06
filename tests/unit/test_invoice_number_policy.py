"""Testy InvoiceNumberPolicy."""
from app.services.invoice_number_policy import InvoiceNumberPolicy


class TestInvoiceNumberPolicy:
    def test_generate_basic(self):
        result = InvoiceNumberPolicy.generate(2026, 4, 1)
        assert result == "FV/1/04/2026"

    def test_generate_double_digit_month(self):
        result = InvoiceNumberPolicy.generate(2026, 12, 99)
        assert result == "FV/99/12/2026"

    def test_generate_single_digit_month_padded(self):
        result = InvoiceNumberPolicy.generate(2026, 1, 5)
        assert result == "FV/5/01/2026"

    def test_generate_high_seq(self):
        result = InvoiceNumberPolicy.generate(2026, 6, 1000)
        assert result == "FV/1000/06/2026"

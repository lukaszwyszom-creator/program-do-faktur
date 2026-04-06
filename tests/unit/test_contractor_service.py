"""Testy ContractorService — NIP validation."""
from __future__ import annotations

import pytest

from app.core.exceptions import NotFoundError
from app.services.contractor_service import ContractorService


class TestNipValidation:
    """Testuje statyczne metody walidacji NIP."""

    def test_normalize_strips_dashes(self):
        assert ContractorService._normalize_nip("123-456-78-90") == "1234567890"

    def test_normalize_strips_spaces(self):
        assert ContractorService._normalize_nip("123 456 78 90") == "1234567890"

    def test_validate_correct_nip(self):
        # 5260250995 — poprawny NIP (Poczta Polska)
        ContractorService._validate_nip("5260250995")  # nie rzuca

    def test_validate_wrong_length_raises(self):
        with pytest.raises(NotFoundError, match="NIP"):
            ContractorService._validate_nip("123456789")  # 9 cyfr

    def test_validate_wrong_checksum_raises(self):
        with pytest.raises(NotFoundError, match="NIP"):
            ContractorService._validate_nip("1234567890")  # zły checksum

    def test_validate_non_digit_raises(self):
        with pytest.raises(NotFoundError, match="NIP"):
            ContractorService._validate_nip("12345678AB")

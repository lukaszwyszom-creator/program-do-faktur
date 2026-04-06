from __future__ import annotations

from datetime import datetime, timedelta


class RegonMapper:
    """Mapowanie odpowiedzi REGON do modelu wewnetrznego."""

    def to_contractor_fields(self, payload: dict, *, fetched_at: datetime, cache_ttl_days: int) -> dict:
        return {
            "nip": payload.get("Nip") or payload.get("nip"),
            "regon": payload.get("Regon") or payload.get("regon"),
            "krs": payload.get("Krs") or payload.get("krs") or None,
            "name": payload.get("Nazwa") or payload.get("nazwa") or "Nieznany kontrahent",
            "legal_form": payload.get("Typ") or payload.get("typ") or None,
            "street": payload.get("Ulica") or payload.get("ulica") or None,
            "building_no": payload.get("NrNieruchomosci") or payload.get("nrNieruchomosci") or None,
            "apartment_no": payload.get("NrLokalu") or payload.get("nrLokalu") or None,
            "postal_code": payload.get("KodPocztowy") or payload.get("kodPocztowy") or None,
            "city": payload.get("Miejscowosc") or payload.get("miejscowosc") or None,
            "voivodeship": payload.get("Wojewodztwo") or payload.get("wojewodztwo") or None,
            "county": payload.get("Powiat") or payload.get("powiat") or None,
            "commune": payload.get("Gmina") or payload.get("gmina") or None,
            "country": "PL",
            "status": payload.get("StatusNip") or payload.get("statusNip") or None,
            "source": "regon",
            "source_fetched_at": fetched_at,
            "cache_valid_until": fetched_at + timedelta(days=cache_ttl_days),
            "lookup_last_status": "success",
            "lookup_last_error": None,
            "raw_payload_json": payload,
        }

from __future__ import annotations

import xml.etree.ElementTree as ET

from zeep import Client
from zeep.transports import Transport

from app.core.exceptions import ExternalServiceError


class RegonClient:
    def __init__(
        self,
        api_key: str | None,
        environment: str,
        timeout_seconds: int,
        wsdl_test: str,
        wsdl_production: str,
    ) -> None:
        self.api_key = api_key
        self.environment = environment
        self.timeout_seconds = timeout_seconds
        self.wsdl_test = wsdl_test
        self.wsdl_production = wsdl_production

    def lookup_by_nip(self, nip: str) -> dict | None:
        if not self.api_key or self.api_key == "change-me":
            raise ExternalServiceError("REGON nie jest skonfigurowany. Ustaw prawidlowy REGON_API_KEY.")

        client = Client(wsdl=self._resolve_wsdl(), transport=Transport(timeout=self.timeout_seconds))
        try:
            session_id = client.service.Zaloguj(self.api_key)
            client.transport.session.headers.update({"sid": session_id})
            result_xml = client.service.DaneSzukajPodmioty({"Nip": nip})
        except Exception as exc:
            raise ExternalServiceError(f"Blad komunikacji z REGON: {exc}") from exc
        finally:
            try:
                if "session_id" in locals():
                    client.transport.session.headers.update({"sid": session_id})
                    client.service.Wyloguj(session_id)
            except Exception:
                pass

        records = self._parse_search_result(result_xml)
        if not records:
            return None
        return records[0]

    def _resolve_wsdl(self) -> str:
        if self.environment == "test":
            return self.wsdl_test
        return self.wsdl_production

    @staticmethod
    def _parse_search_result(result_xml: str | None) -> list[dict]:
        if not result_xml:
            return []

        try:
            root = ET.fromstring(result_xml)
        except ET.ParseError as exc:
            raise ExternalServiceError("REGON zwrocil nieprawidlowy XML.") from exc

        records: list[dict] = []
        for node in root.findall(".//dane"):
            record: dict[str, str] = {}
            for child in node:
                record[child.tag] = child.text or ""
            if record:
                records.append(record)
        return records

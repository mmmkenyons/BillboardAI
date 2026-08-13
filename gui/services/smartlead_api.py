"""HTTP boundary for Smartlead live API access with safe redaction."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SmartleadCampaignDetails,
    SmartleadCampaignSummary,
    SmartleadConnectionTestResult,
)


class SmartleadApiError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 0, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


class SmartleadTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class _NormalizedResponse:
    status_code: int
    headers: dict[str, Any]
    text: str
    payload: Any


class RequestsTransport:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def request(self, method: str, url: str, *, params: dict[str, Any] | None = None, json: Any = None, timeout: float | None = None) -> requests.Response:
        return self._session.request(method=method, url=url, params=params, json=json, timeout=timeout)


def redact_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    return "***REDACTED***"


def redact_url(url: str, api_key: str) -> str:
    text = str(url or "")
    if api_key:
        text = text.replace(api_key, redact_secret(api_key))
    return text


class SmartleadApiClient:
    def __init__(
        self,
        *,
        settings: SmartleadConnectionSettings | None = None,
        transport: SmartleadTransport | None = None,
        sleeper: Any | None = None,
    ) -> None:
        self._settings = settings or SmartleadConnectionSettings()
        self._transport = transport or RequestsTransport()
        self._sleeper = sleeper or time.sleep

    @property
    def settings(self) -> SmartleadConnectionSettings:
        return self._settings

    def test_connection(self) -> SmartleadConnectionTestResult:
        try:
            self.list_campaigns()
            return SmartleadConnectionTestResult(connected=True, status="CONNECTED", message="Smartlead connection successful.")
        except SmartleadApiError as exc:
            return SmartleadConnectionTestResult(connected=False, status=exc.code, message=exc.message)

    def list_campaigns(self) -> list[SmartleadCampaignSummary]:
        payload = self._request_json("GET", "/campaigns/")
        campaigns = payload if isinstance(payload, list) else payload.get("campaigns") or payload.get("data") or []
        result: list[SmartleadCampaignSummary] = []
        for item in campaigns:
            if not isinstance(item, dict):
                continue
            result.append(
                SmartleadCampaignSummary(
                    campaign_id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    status=str(item.get("status") or ""),
                    created_at=str(item.get("created_at") or ""),
                )
            )
        return result

    def get_campaign(self, campaign_id: str) -> SmartleadCampaignDetails:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}")
        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            raise SmartleadApiError("MALFORMED_RESPONSE", "Malformed Smartlead response.")
        sequences = self.get_campaign_sequences(campaign_id)
        accounts = self.get_campaign_email_accounts(campaign_id)
        return SmartleadCampaignDetails(
            campaign_id=str(data.get("id") or campaign_id),
            name=str(data.get("name") or ""),
            status=str(data.get("status") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            client_id=str(data.get("client_id") or ""),
            sequence_count=len(sequences),
            email_account_count=len(accounts),
            raw_sequence_configured=bool(sequences),
            raw_sender_accounts_configured=bool(accounts),
        )

    def create_campaign(self, name: str) -> SmartleadCampaignDetails:
        payload = self._request_json("POST", "/campaigns/create", json_body={"name": str(name or "").strip() or "Untitled Campaign"})
        if not isinstance(payload, dict):
            raise SmartleadApiError("MALFORMED_RESPONSE", "Malformed Smartlead response.")
        campaign_id = str(payload.get("id") or "")
        return SmartleadCampaignDetails(
            campaign_id=campaign_id,
            name=str(payload.get("name") or name),
            status=str(payload.get("status") or "DRAFTED"),
            created_at=str(payload.get("created_at") or ""),
            raw_sequence_configured=False,
            raw_sender_accounts_configured=False,
        )

    def add_leads(self, campaign_id: str, lead_list: list[dict[str, Any]]) -> Any:
        return self._request_json("POST", f"/campaigns/{campaign_id}/leads", json_body={"lead_list": lead_list})

    def get_campaign_leads(self, campaign_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/leads")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            leads = payload.get("data") or payload.get("leads") or payload.get("campaign_leads") or []
            return [item for item in leads if isinstance(item, dict)]
        raise SmartleadApiError("MALFORMED_RESPONSE", "Malformed Smartlead response.")

    def get_campaign_sequences(self, campaign_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/sequences")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("sequences") or []
            return [item for item in data if isinstance(item, dict)]
        return []

    def get_campaign_email_accounts(self, campaign_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/email-accounts")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("email_accounts") or []
            return [item for item in data if isinstance(item, dict)]
        return []

    def build_request_url(self, path: str) -> str:
        base = self._settings.base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    def _request_json(self, method: str, path: str, json_body: Any = None) -> Any:
        api_key = self._settings.resolve_api_key()
        if not api_key:
            raise SmartleadApiError("NOT_CONFIGURED", "Smartlead API key is not configured.")
        url = self.build_request_url(path)
        params = {"api_key": api_key}
        last_error: SmartleadApiError | None = None
        for attempt in range(self._settings.max_retries + 1):
            try:
                raw = self._transport.request(method, url, params=params, json=json_body, timeout=self._settings.timeout_seconds)
            except requests.Timeout:
                last_error = SmartleadApiError("TIMEOUT", "Smartlead connection timed out.")
            except requests.RequestException:
                last_error = SmartleadApiError("UNAVAILABLE", "Smartlead service unavailable.")
            else:
                normalized = self._normalize_response(raw)
                retry_error = self._raise_for_error(normalized)
                if retry_error is None:
                    return normalized.payload
                last_error = retry_error
                if not self._is_retryable(retry_error) or attempt >= self._settings.max_retries:
                    raise retry_error
                self._sleeper(self._retry_delay(attempt, retry_error))
                continue
            if last_error is not None and attempt < self._settings.max_retries and self._is_retryable(last_error):
                self._sleeper(self._retry_delay(attempt, last_error))
                continue
            raise last_error or SmartleadApiError("UNAVAILABLE", "Smartlead request failed.")
        raise last_error or SmartleadApiError("UNAVAILABLE", "Smartlead request failed.")

    def _normalize_response(self, response: Any) -> _NormalizedResponse:
        status_code = int(getattr(response, "status_code", 0) or 0)
        headers = dict(getattr(response, "headers", {}) or {})
        text = str(getattr(response, "text", "") or "")
        try:
            payload = response.json()
        except Exception:
            if 200 <= status_code < 300:
                raise SmartleadApiError("MALFORMED_RESPONSE", "Malformed Smartlead response.")
            payload = {}
        return _NormalizedResponse(status_code=status_code, headers=headers, text=text, payload=payload)

    def _raise_for_error(self, response: _NormalizedResponse) -> SmartleadApiError | None:
        status = response.status_code
        if 200 <= status < 300:
            return None
        error = response.payload.get("error") if isinstance(response.payload, dict) else None
        retry_after = self._parse_retry_after(response, error)
        if status == 401:
            return SmartleadApiError("AUTH_FAILED", "Authentication failed.", status_code=status)
        if status == 404:
            return SmartleadApiError("NOT_FOUND", "Campaign not found.", status_code=status)
        if status == 409:
            return SmartleadApiError("CONFLICT", self._extract_message(response) or "Validation error.", status_code=status)
        if status in (400, 422):
            return SmartleadApiError("VALIDATION_ERROR", self._extract_message(response) or "Validation error.", status_code=status)
        if status == 429:
            return SmartleadApiError("RATE_LIMITED", "Rate limited.", status_code=status, retry_after=retry_after)
        if status in (500, 503):
            return SmartleadApiError("UNAVAILABLE", "Smartlead service unavailable.", status_code=status, retry_after=retry_after)
        return SmartleadApiError("API_ERROR", self._extract_message(response) or f"Smartlead request failed ({status}).", status_code=status, retry_after=retry_after)

    def _extract_message(self, response: _NormalizedResponse) -> str:
        payload = response.payload
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or "").strip()
            for key in ("message", "error"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value.strip()
        return ""

    def _parse_retry_after(self, response: _NormalizedResponse, error: Any) -> float | None:
        header = response.headers.get("Retry-After")
        if header not in (None, ""):
            try:
                return float(header)
            except (TypeError, ValueError):
                pass
        if isinstance(error, dict) and error.get("retry_after") not in (None, ""):
            try:
                return float(error.get("retry_after"))
            except (TypeError, ValueError):
                return None
        return None

    def _is_retryable(self, error: SmartleadApiError) -> bool:
        return error.code in {"RATE_LIMITED", "UNAVAILABLE", "TIMEOUT"}

    def _retry_delay(self, attempt: int, error: SmartleadApiError) -> float:
        if error.retry_after not in (None, 0):
            return float(error.retry_after)
        return float(2 ** attempt)


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
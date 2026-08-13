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
        return []

    def get_campaign_leads_page(self, campaign_id: str, *, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/leads", query_params={"page": int(page), "limit": int(limit)})
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            leads = payload.get("data") or payload.get("leads") or payload.get("campaign_leads") or []
            return [item for item in leads if isinstance(item, dict)]
        return []

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

    def get_campaign_lead(self, campaign_id: str, lead_id: str) -> dict[str, Any] | None:
        """Read a single campaign lead (used to verify existing custom fields)."""
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/leads/{lead_id}")
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return data if isinstance(data, dict) else None

    def update_campaign_lead(self, campaign_id: str, lead_id: str, custom_fields: dict[str, Any]) -> Any:
        """Update custom fields on an existing campaign lead (no duplicate lead creation).

        This is the target update path for bb_mockup_url sync on already-published
        leads. The live payload semantics (path/method) follow the repository's
        canonical Smartlead API convention and are verified with a fake transport.
        """
        return self._request_json(
            "PUT",
            f"/campaigns/{campaign_id}/leads/{lead_id}",
            json_body={"custom_fields": dict(custom_fields or {})},
        )

    def get_campaign_analytics(self, campaign_id: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/analytics")
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return dict(payload.get("data") or {})
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def get_campaign_lead_statistics(self, campaign_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/campaigns/{campaign_id}/leads/statistics")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("leads") or payload.get("statistics") or []
            return [item for item in rows if isinstance(item, dict)]
        return []

    def add_sequence(self, campaign_id: str, payload: dict[str, Any]) -> Any:
        """Create a campaign sequence. Callers gate this behind explicit confirmation."""
        return self._request_json(
            "POST",
            f"/campaigns/{campaign_id}/sequences/create",
            json_body=payload,
        )

    def update_campaign_sequence(self, campaign_id: str, sequence_id: str, payload: dict[str, Any]) -> Any:
        """Update an existing campaign sequence. Callers gate this explicitly; it is
        never invoked automatically and active campaigns are protected upstream."""
        return self._request_json(
            "PUT",
            f"/campaigns/{campaign_id}/sequences/{sequence_id}",
            json_body=payload,
        )

    def start_campaign(self, campaign_id: str) -> Any:
        """Intent-based Smartlead activation seam.

        Smartlead's official documentation is currently internally inconsistent
        about the exact activation wire contract. This method isolates that
        ambiguity behind one narrow API seam so the rest of BillboardAI only
        expresses the intent: start/resume this campaign.

        Current provisional implementation uses PATCH /campaigns/{id}/status
        with {"status": "ACTIVE"}, matching one official signal. This must not
        be treated as fully provider-confirmed for first real activation.
        """
        return self._request_json(
            "PATCH",
            f"/campaigns/{campaign_id}/status",
            json_body={"status": "ACTIVE"},
        )

    def pause_campaign(self, campaign_id: str) -> Any:
        """Intent-based Smartlead pause seam.

        Smartlead pilot safety uses PAUSE as the reversible emergency control.
        STOP is intentionally not exposed here.
        """
        return self._request_json(
            "PATCH",
            f"/campaigns/{campaign_id}/status",
            json_body={"status": "PAUSED"},
        )

    def build_request_url(self, path: str) -> str:
        base = self._settings.base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    def _request_json(self, method: str, path: str, json_body: Any = None, query_params: dict[str, Any] | None = None) -> Any:
        api_key = self._settings.resolve_api_key()
        if not api_key:
            raise SmartleadApiError("NOT_CONFIGURED", "Smartlead API key is not configured.")
        url = self.build_request_url(path)
        params = {"api_key": api_key}
        if query_params:
            params.update({key: value for key, value in query_params.items() if value is not None})
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
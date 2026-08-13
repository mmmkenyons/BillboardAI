from __future__ import annotations

import requests

from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError, redact_secret, redact_url


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else ("" if payload is None else str(payload))

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, params=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings(monkeypatch):
    monkeypatch.setenv("SMARTLEAD_API_KEY", "super-secret-test-key")
    return SmartleadConnectionSettings(max_retries=2)


def test_api_key_injected_correctly(monkeypatch):
    transport = FakeTransport([FakeResponse(payload=[])])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    client.list_campaigns()
    assert transport.calls[0]["params"]["api_key"] == "super-secret-test-key"


def test_api_key_redacted_from_outputs(monkeypatch):
    settings = _settings(monkeypatch)
    url = f"{settings.base_url}/campaigns/?api_key=super-secret-test-key"
    assert "super-secret-test-key" not in redact_url(url, settings.resolve_api_key())
    assert redact_secret(settings.resolve_api_key()) == "***REDACTED***"


def test_connection_success(monkeypatch):
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([FakeResponse(payload=[])]), sleeper=lambda _: None)
    result = client.test_connection()
    assert result.connected is True


def test_auth_failure(monkeypatch):
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([FakeResponse(status_code=401, payload={"message": "Invalid API Key"})]), sleeper=lambda _: None)
    result = client.test_connection()
    assert result.connected is False
    assert result.status == "AUTH_FAILED"


def test_timeout(monkeypatch):
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([requests.Timeout(), requests.Timeout(), requests.Timeout()]), sleeper=lambda _: None)
    result = client.test_connection()
    assert result.status == "TIMEOUT"


def test_429_handling(monkeypatch):
    sleeps = []
    transport = FakeTransport([
        FakeResponse(status_code=429, payload={"error": {"code": "RATE_LIMIT_EXCEEDED", "retry_after": 3}}, headers={"Retry-After": "3"}),
        FakeResponse(payload=[]),
    ])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda value: sleeps.append(value))
    assert client.list_campaigns() == []
    assert sleeps == [3.0]


def test_transient_5xx_bounded_retry(monkeypatch):
    sleeps = []
    transport = FakeTransport([FakeResponse(status_code=500, payload={"error": {"message": "oops"}}), FakeResponse(payload=[])])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda value: sleeps.append(value))
    assert client.list_campaigns() == []
    assert sleeps == [1.0]


def test_malformed_json(monkeypatch):
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([FakeResponse(payload=ValueError("bad json"))]), sleeper=lambda _: None)
    try:
        client.list_campaigns()
    except SmartleadApiError as exc:
        assert exc.code == "MALFORMED_RESPONSE"
    else:
        raise AssertionError("Expected SmartleadApiError")


def test_list_campaigns(monkeypatch):
    payload = [{"id": 1, "name": "A", "status": "DRAFTED", "created_at": "2026-01-01T00:00:00Z"}]
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([FakeResponse(payload=payload)]), sleeper=lambda _: None)
    campaigns = client.list_campaigns()
    assert campaigns[0].campaign_id == "1"


def test_campaign_detail(monkeypatch):
    transport = FakeTransport([
        FakeResponse(payload={"data": {"id": 4, "name": "Draft", "status": "DRAFTED"}}),
        FakeResponse(payload=[]),
        FakeResponse(payload=[]),
    ])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    campaign = client.get_campaign("4")
    assert campaign.campaign_id == "4"
    assert campaign.sequence_count == 0


# ---------------------------------------------------------------------------
# Sprint 5R endpoints
# ---------------------------------------------------------------------------
def test_lead_custom_field_update_endpoint(monkeypatch):
    transport = FakeTransport([FakeResponse(payload={"success": True})])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    client.update_campaign_lead("10", "lead-99", {"bb_mockup_url": "https://cdn.example.com/a.png"})
    call = transport.calls[0]
    assert call["method"].upper() == "PUT"
    assert call["url"].endswith("/campaigns/10/leads/lead-99")
    assert call["json"] == {"custom_fields": {"bb_mockup_url": "https://cdn.example.com/a.png"}}
    assert call["params"]["api_key"] == "super-secret-test-key"


def test_read_campaign_lead_endpoint(monkeypatch):
    transport = FakeTransport([FakeResponse(payload={"data": {"id": "id1", "custom_fields": {"bb_mockup_url": "x"}}})])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    lead = client.get_campaign_lead("10", "id1")
    assert lead["custom_fields"]["bb_mockup_url"] == "x"
    assert transport.calls[0]["method"].upper() == "GET"


def test_read_campaign_leads_endpoint(monkeypatch):
    transport = FakeTransport([FakeResponse(payload={"data": [{"id": "id1", "email": "a@example.com"}]})])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    leads = client.get_campaign_leads("10")
    assert leads[0]["email"] == "a@example.com"
    assert transport.calls[0]["method"].upper() == "GET"


def test_add_sequence_endpoint(monkeypatch):
    transport = FakeTransport([FakeResponse(payload={"id": "seq1"})])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    client.add_sequence("10", {"steps": [{"subject": "{{bb_subject}}", "content": "{{bb_body}}"}]})
    call = transport.calls[0]
    assert call["method"].upper() == "POST"
    assert call["url"].endswith("/campaigns/10/sequences/create")


def test_start_campaign_intent_endpoint_current_provisional_contract(monkeypatch):
    transport = FakeTransport([FakeResponse(payload={"success": True})])
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=transport, sleeper=lambda _: None)
    client.start_campaign("10")
    call = transport.calls[0]
    assert call["method"].upper() == "PATCH"
    assert call["url"].endswith("/campaigns/10/status")
    assert call["json"] == {"status": "ACTIVE"}
    assert call["params"]["api_key"] == "super-secret-test-key"


def test_start_campaign_intent_is_exposed_not_raw_status_update(monkeypatch):
    client = SmartleadApiClient(settings=_settings(monkeypatch), transport=FakeTransport([]), sleeper=lambda _: None)
    assert hasattr(client, "start_campaign")
    assert not hasattr(client, "activate_campaign")
    assert not hasattr(client, "update_campaign_status")
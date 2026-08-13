"""Sprint 5R sequence readiness: fake Smartlead transport only, no network."""

from __future__ import annotations

import pytest

from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import SmartleadCampaignDetails
from gui.models.smartlead_sequence import (
    SEQUENCE_VARIABLE_BODY,
    SEQUENCE_VARIABLE_MOCKUP_URL,
    SEQUENCE_VARIABLE_SUBJECT,
    SequenceChangeStore,
)
from gui.services.smartlead_sequence_readiness import (
    SmartleadSequenceReadinessError,
    SmartleadSequenceReadinessService,
)


def _seq(subject="", body=""):
    return {"id": "s1", "steps": [{"subject": subject, "content": body}]}


def _good_seq():
    return _seq(
        subject="{{bb_subject}}",
        body="{{bb_body}}\n\nView the mockup:\n{{bb_mockup_url}}",
    )


class FakeApiClient:
    def __init__(self, *, status="DRAFTED", sequences=None, accounts=1):
        self._status = status
        self.sequences = list(sequences or [])
        self.accounts = [{"id": str(i)} for i in range(accounts)]
        self.add_sequence_calls = []
        self.activation_calls = []
        self.settings = SmartleadConnectionSettings()

    def get_campaign(self, campaign_id):
        return SmartleadCampaignDetails(campaign_id=campaign_id, name="Camp", status=self._status, sequence_count=len(self.sequences), email_account_count=len(self.accounts))

    def get_campaign_sequences(self, campaign_id):
        return list(self.sequences)

    def get_campaign_email_accounts(self, campaign_id):
        return list(self.accounts)

    def add_sequence(self, campaign_id, payload):
        self.add_sequence_calls.append((campaign_id, payload))
        step = payload["steps"][0]
        self.sequences = [_seq(subject=step["subject"], body=step["content"])]

    def start_campaign(self, campaign_id):  # included ONLY to prove it is never invoked
        self.activation_calls.append(campaign_id)


def _service(api):
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".seq.json")
    os.close(fd)
    os.unlink(path)
    return SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=path))


def test_no_sequence():
    readiness = _service(FakeApiClient(sequences=[])).check_readiness("1")
    assert readiness.sequence_exists is False
    assert readiness.ready_for_manual_activation is False
    assert any("No campaign sequence" in b for b in readiness.blockers)


def test_bb_subject_present():
    readiness = _service(FakeApiClient(sequences=[_seq(subject="{{bb_subject}}", body="hi")])).check_readiness("1")
    assert readiness.bb_subject_present is True


def test_bb_body_present():
    readiness = _service(FakeApiClient(sequences=[_seq(subject="s", body="{{bb_body}}")])).check_readiness("1")
    assert readiness.bb_body_present is True


def test_bb_mockup_url_present():
    readiness = _service(FakeApiClient(sequences=[_seq(subject="s", body="x {{bb_mockup_url}}")])).check_readiness("1")
    assert readiness.bb_mockup_url_present is True


def test_missing_variable_blocker():
    readiness = _service(FakeApiClient(sequences=[_seq(subject="no-var", body="no-var")])).check_readiness("1")
    assert readiness.bb_subject_present is False
    assert any("bb_subject" in b for b in readiness.blockers)
    assert readiness.ready_for_manual_activation is False


def test_sender_accounts_absent():
    readiness = _service(FakeApiClient(accounts=0)).check_readiness("1")
    assert readiness.sender_accounts_present is False
    assert any("sender accounts" in b for b in readiness.blockers)


def test_sender_accounts_present():
    readiness = _service(FakeApiClient(accounts=3)).check_readiness("1")
    assert readiness.sender_accounts_present is True
    assert readiness.sender_account_count == 3


def test_campaign_status_reported():
    readiness = _service(FakeApiClient(status="PAUSED")).check_readiness("1")
    assert readiness.campaign_status == "PAUSED"


def test_draft_safe_for_preparation():
    api = FakeApiClient(status="DRAFTED", sequences=[], accounts=2)
    result = _service(api).prepare_sequence("1", live_enabled=True, confirmed=True)
    assert api.add_sequence_calls
    assert result.ready_for_manual_activation is True


def test_active_campaign_sequence_mutation_blocked():
    api = FakeApiClient(status="ACTIVE", sequences=[], accounts=2)
    with pytest.raises(SmartleadSequenceReadinessError) as exc:
        _service(api).prepare_sequence("1", live_enabled=True, confirmed=True)
    assert exc.value.code == "ACTIVE_BLOCKED"
    assert api.add_sequence_calls == []


def test_proposed_sequence_deterministic():
    svc = _service(FakeApiClient())
    p1 = svc.build_proposal("1")
    p2 = svc.build_proposal("1")
    assert p1.fingerprint() == p2.fingerprint()
    assert SEQUENCE_VARIABLE_SUBJECT in p1.deterministic_subject
    assert SEQUENCE_VARIABLE_BODY in p1.deterministic_body
    assert SEQUENCE_VARIABLE_MOCKUP_URL in p1.deterministic_body


def test_existing_sequence_not_overwritten_automatically():
    api = FakeApiClient(status="DRAFTED", sequences=[_good_seq()], accounts=2)
    with pytest.raises(SmartleadSequenceReadinessError) as exc:
        _service(api).prepare_sequence("1", live_enabled=True, confirmed=True)
    assert exc.value.code == "SEQUENCE_EXISTS"
    assert api.add_sequence_calls == []


def test_explicit_confirmation_required_for_write(tmp_path):
    api = FakeApiClient(status="DRAFTED", sequences=[], accounts=2)
    store = SequenceChangeStore(path=str(tmp_path / "seq.json"))
    svc = SmartleadSequenceReadinessService(api_client=api, change_store=store)
    svc.prepare_sequence("1", live_enabled=True, confirmed=False)
    assert api.add_sequence_calls == []


def test_no_campaign_activation_call():
    api = FakeApiClient(status="DRAFTED", sequences=[], accounts=2)
    _service(api).prepare_sequence("1", live_enabled=True, confirmed=True)
    assert api.activation_calls == []


def test_readiness_true_only_when_all_conditions_satisfied():
    ok = _service(FakeApiClient(sequences=[_good_seq()], accounts=2)).check_readiness("1")
    assert ok.ready_for_manual_activation is True
    missing_sender = _service(FakeApiClient(sequences=[_good_seq()], accounts=0)).check_readiness("1")
    assert missing_sender.ready_for_manual_activation is False
    missing_url = _service(FakeApiClient(sequences=[_seq(subject="{{bb_subject}}", body="{{bb_body}}")], accounts=2)).check_readiness("1")
    assert missing_url.ready_for_manual_activation is False
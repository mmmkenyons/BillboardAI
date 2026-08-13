"""Smartlead sequence readiness + safe optional draft-sequence preparation (5R).

Read-only inspection reports whether the target campaign sequence references the
required BillboardAI variables and has sender accounts attached. Preparation is
offer-only: it requires an explicit action, live-write enablement, explicit
confirmation, a safe (DRAFTED) campaign, and refuses to overwrite an existing
sequence automatically. Active campaigns are never mutated and no campaign is
ever started/activated by this layer.
"""

from __future__ import annotations

from typing import Any

from gui.models.smartlead_sequence import (
    REQUIRED_MOCKUP_SEQUENCE_VARIABLES,
    REQUIRED_SEQUENCE_VARIABLES,
    SEQUENCE_VARIABLE_BODY,
    SEQUENCE_VARIABLE_MOCKUP_URL,
    SEQUENCE_VARIABLE_SUBJECT,
    SmartleadSequenceProposal,
    SmartleadSequenceReadiness,
    SmartleadSequenceState,
    SequenceChangeReceipt,
    SequenceChangeStore,
    extract_sequence_variables,
    sequence_fingerprint,
    utc_now_iso,
)
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError

ACTIVE_CAMPAIGN_STATUSES = {"ACTIVE", "STARTED", "SENDING", "RUNNING"}
MUTATION_BLOCKED_STATUSES = ACTIVE_CAMPAIGN_STATUSES


class SmartleadSequenceReadinessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SmartleadSequenceReadinessService:
    def __init__(
        self,
        *,
        api_client: SmartleadApiClient,
        change_store: SequenceChangeStore | None = None,
    ) -> None:
        self._api_client = api_client
        self._change_store = change_store or SequenceChangeStore()

    # ------------------------------------------------------------------
    # Readiness audit
    # ------------------------------------------------------------------
    def check_readiness(
        self,
        campaign_id: str,
        *,
        require_mockup_url: bool = True,
    ) -> SmartleadSequenceReadiness:
        campaign = self._api_client.get_campaign(campaign_id)
        sequences = self._api_client.get_campaign_sequences(campaign_id)
        accounts = self._api_client.get_campaign_email_accounts(campaign_id)

        subject, body = self._extract_first_step_content(sequences)
        variables = extract_sequence_variables(subject)
        variables.update(extract_sequence_variables(body))
        variables_lower = {name for name in variables}

        bb_subject_present = SEQUENCE_VARIABLE_SUBJECT in variables_lower
        bb_body_present = SEQUENCE_VARIABLE_BODY in variables_lower
        bb_mockup_url_present = SEQUENCE_VARIABLE_MOCKUP_URL in variables_lower
        sequence_exists = bool(sequences)
        sender_account_count = len(accounts)
        sender_accounts_present = sender_account_count > 0
        status = str(campaign.status or "").upper()

        blockers: list[str] = []
        warnings: list[str] = []
        if not sequence_exists:
            blockers.append("No campaign sequence exists.")
        if not bb_subject_present:
            blockers.append(f"Sequence missing required variable {SEQUENCE_VARIABLE_SUBJECT}.")
        if not bb_body_present:
            blockers.append(f"Sequence missing required variable {SEQUENCE_VARIABLE_BODY}.")
        if require_mockup_url and not bb_mockup_url_present:
            blockers.append(f"Sequence missing required variable {SEQUENCE_VARIABLE_MOCKUP_URL}.")
        if not require_mockup_url and not bb_mockup_url_present:
            warnings.append(f"Sequence does not reference {SEQUENCE_VARIABLE_MOCKUP_URL} (mockup link optional for this strategy).")
        if not sender_accounts_present:
            blockers.append("No sender accounts attached.")
        if status in ACTIVE_CAMPAIGN_STATUSES:
            blockers.append("Campaign is already active; not pending activation.")
        elif status == "PAUSED":
            warnings.append("Campaign is PAUSED.")

        required_met = (
            sequence_exists
            and bb_subject_present
            and bb_body_present
            and (bb_mockup_url_present or not require_mockup_url)
            and sender_accounts_present
            and status not in ACTIVE_CAMPAIGN_STATUSES
        )

        return SmartleadSequenceReadiness(
            campaign_id=str(campaign_id),
            campaign_status=status,
            sequence_exists=sequence_exists,
            bb_subject_present=bb_subject_present,
            bb_body_present=bb_body_present,
            bb_mockup_url_present=bb_mockup_url_present,
            sender_accounts_present=sender_accounts_present,
            sender_account_count=sender_account_count,
            ready_for_manual_activation=required_met,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _extract_first_step_content(self, sequences: list[dict[str, Any]]) -> tuple[str, str]:
        if not sequences:
            return "", ""
        first = sequences[0]
        steps = first.get("steps")
        if isinstance(steps, list) and steps:
            first_step = steps[0]
            if isinstance(first_step, dict):
                subject = str(first_step.get("subject") or first_step.get("email_subject") or "")
                body = str(first_step.get("content") or first_step.get("body") or first_step.get("email_body") or "")
                return subject, body
        subject = str(first.get("subject") or first.get("email_subject") or "")
        body = str(first.get("content") or first.get("body") or first.get("email_body") or "")
        return subject, body

    # ------------------------------------------------------------------
    # Canonical proposal (deterministic)
    # ------------------------------------------------------------------
    def build_proposal(self, campaign_id: str) -> SmartleadSequenceProposal:
        """Canonical BillboardAI sequence template. Variable tokens stay literal."""
        subject = f"{{{{{SEQUENCE_VARIABLE_SUBJECT}}}}}"
        body = (
            f"{{{{{SEQUENCE_VARIABLE_BODY}}}}}\n\n"
            f"View the mockup for your business:\n{{{{{SEQUENCE_VARIABLE_MOCKUP_URL}}}}}"
        )
        return SmartleadSequenceProposal(campaign_id=str(campaign_id), subject=subject, body=body)

    # ------------------------------------------------------------------
    # Offer-only preparation (never automatic overwrite, never activation)
    # ------------------------------------------------------------------
    def prepare_sequence(
        self,
        campaign_id: str,
        *,
        proposal: SmartleadSequenceProposal | None = None,
        live_enabled: bool = False,
        confirmed: bool = False,
        mode: str = "LIVE",
    ) -> SmartleadSequenceReadiness:
        if mode != "LIVE":
            return self.check_readiness(campaign_id)
        if not live_enabled or not confirmed:
            return self.check_readiness(campaign_id)
        campaign = self._api_client.get_campaign(campaign_id)
        status = str(campaign.status or "").upper()
        if status in MUTATION_BLOCKED_STATUSES:
            raise SmartleadSequenceReadinessError(
                "ACTIVE_BLOCKED",
                f"Sequence mutation is prevented because campaign is {status} (active campaigns are protected).",
            )
        existing = self._api_client.get_campaign_sequences(campaign_id)
        if existing:
            # Never overwrite an existing sequence automatically.
            readiness = self.check_readiness(campaign_id)
            raise SmartleadSequenceReadinessError(
                "SEQUENCE_EXISTS",
                "A sequence already exists; this tool will not overwrite it automatically. Inspect and update only via an explicit confirmed action.",
            )

        active_proposal = proposal or self.build_proposal(campaign_id)
        before = SmartleadSequenceState(
            campaign_id=str(campaign_id),
            sequence_exists=False,
            sequence_fingerprint="",
            subject="",
            body="",
            captured_at=utc_now_iso(),
        )
        before_fp = sequence_fingerprint(before)
        payload = {
            "name": "BillboardAI-Personalized",
            "steps": [
                {
                    "subject": active_proposal.deterministic_subject,
                    "content": active_proposal.deterministic_body,
                    "delay": 0,
                }
            ],
        }
        try:
            self._api_client.add_sequence(campaign_id, payload)
        except SmartleadApiError as exc:
            raise SmartleadSequenceReadinessError(exc.code, f"Sequence creation failed: {exc.message}") from exc

        after = SmartleadSequenceState(
            campaign_id=str(campaign_id),
            sequence_exists=True,
            sequence_fingerprint="",
            subject=active_proposal.deterministic_subject,
            body=active_proposal.deterministic_body,
            captured_at=utc_now_iso(),
        )
        after_fp = sequence_fingerprint(after)
        self._change_store.append(
            SequenceChangeReceipt(
                campaign_id=str(campaign_id),
                action="SEQUENCE_CREATE",
                before_fingerprint=before_fp,
                after_fingerprint=after_fp,
                changed_at=utc_now_iso(),
            )
        )
        self._change_store.save()
        return self.check_readiness(campaign_id)
"""Sprint 5R hosting: fake provider only, no real Cloudinary / network calls."""

from __future__ import annotations

import json
import os

from gui.models.hosted_asset import (
    HOSTING_MODE_DRY_RUN,
    HOSTING_MODE_LIVE,
    HOSTING_STATUS_BLOCKED,
    HOSTING_STATUS_FAILED,
    HOSTING_STATUS_HOSTED,
    HOSTING_STATUS_PENDING,
    HOSTING_STATUS_REUSED,
    is_valid_public_url,
)
from gui.models.hosted_asset_store import HostedAssetStore
from gui.services.asset_hosting import HostingConnectionResult, UploadedAsset
from gui.services.hosted_mockups import AssetHostingService, build_public_id, sha256_file


class FakeAssetProvider:
    name = "fake"

    def __init__(self):
        self.uploads = []
        self.fail_public_ids = set()
        self.http_public_ids = set()

    def test_connection(self):
        return HostingConnectionResult(connected=True, status="CONNECTED", message="ok")

    def upload_asset(self, *, source_path, public_id):
        self.uploads.append((source_path, public_id))
        if public_id in self.fail_public_ids:
            raise RuntimeError("upload failed for " + public_id)
        if public_id in self.http_public_ids:
            url = f"http://cdn.example.com/{public_id}"
        else:
            url = f"https://cdn.example.com/{public_id}"
        return UploadedAsset(provider_asset_id=public_id, public_url=url, secure_url=url)

    def resolve_existing(self, *, public_id):
        return None

    def delete_asset(self, *, public_id):
        return True


def _seed(root):
    package_dir = os.path.join(str(root), "package")
    handoff_dir = os.path.join(package_dir, "handoff")
    mockups_dir = os.path.join(package_dir, "mockups")
    os.makedirs(mockups_dir, exist_ok=True)
    os.makedirs(handoff_dir, exist_ok=True)

    with open(os.path.join(mockups_dir, "alpha.png"), "w", encoding="utf-8") as handle:
        handle.write("mockup-a-content")
    with open(os.path.join(mockups_dir, "bravo.png"), "w", encoding="utf-8") as handle:
        handle.write("mockup-b-content")

    manifest = {
        "package_id": "pkg-777",
        "prospects": [
            {"prospect_id": "a", "status": "READY", "mockup_relative_path": "mockups/alpha.png", "generation_job_id": "job-a", "project_id": "proj-1"},
            {"prospect_id": "b", "status": "WARNING", "mockup_relative_path": "mockups/bravo.png", "generation_job_id": "job-b", "project_id": "proj-1"},
            {"prospect_id": "c", "status": "BLOCKED", "mockup_relative_path": "mockups/c.png", "generation_job_id": "job-c", "project_id": "proj-1"},
        ],
    }
    with open(os.path.join(package_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    with open(os.path.join(package_dir, "mockups", "c.png"), "w", encoding="utf-8") as handle:
        handle.write("never uploaded")
    handoff = {"package_directory": package_dir, "rows": [
        {"prospect_id": "a", "status": "READY"},
        {"prospect_id": "b", "status": "WARNING"},
        {"prospect_id": "c", "status": "BLOCKED"},
    ]}
    with open(os.path.join(handoff_dir, "smartlead_handoff_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(handoff, handle)
    return package_dir, handoff_dir


def _make_service(root, provider):
    return AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=os.path.join(str(root), "hosted_receipts.json")))


def _status_map(result):
    return {r.prospect_id: r.status for r in result.results}


def test_default_hosting_mode_is_dry_run(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    result = service.host(package_dir, handoff)  # no mode -> dry run
    assert result.mode == HOSTING_MODE_DRY_RUN
    assert provider.uploads == []


def test_dry_run_no_upload_and_pending(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    result = service.dry_run(package_dir, handoff)
    assert result.mode == HOSTING_MODE_DRY_RUN
    assert provider.uploads == []
    assert result.pending == 2
    statuses = _status_map(result)
    assert statuses["a"] == HOSTING_STATUS_PENDING
    assert statuses["b"] == HOSTING_STATUS_PENDING
    assert statuses["c"] == HOSTING_STATUS_BLOCKED


def test_successful_live_upload(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    result = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.hosted == 2
    assert provider.uploads and len(provider.uploads) == 2
    for row in result.results:
        if row.prospect_id in {"a", "b"}:
            assert row.status == HOSTING_STATUS_HOSTED
            assert is_valid_public_url(row.public_url)
    assert any(r.prospect_id == "c" and r.status == HOSTING_STATUS_BLOCKED for r in result.results)


def test_receipt_persisted(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    store = HostedAssetStore(path=os.path.join(str(tmp_path), "receipts.json"))
    service = AssetHostingService(provider=provider, asset_store=store)
    service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    raw = open(store.path, "r", encoding="utf-8").read()
    assert "https://cdn.example.com/" in raw
    assert "pkg-777" in raw


def test_restart_reuse(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    store_path = os.path.join(str(tmp_path), "receipts.json")
    service = AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=store_path))
    first = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert first.hosted == 2
    provider2 = FakeAssetProvider()
    restarted = AssetHostingService(provider=provider2, asset_store=HostedAssetStore(path=store_path))
    second = restarted.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert second.hosted == 0 and second.reused == 2
    assert provider2.uploads == []  # no duplicate hosting


def test_sha256_identity(tmp_path):
    a = os.path.join(str(tmp_path), "x.png")
    b = os.path.join(str(tmp_path), "y.png")
    with open(a, "w", encoding="utf-8") as handle:
        handle.write("aaa")
    with open(b, "w", encoding="utf-8") as handle:
        handle.write("bbb")
    assert sha256_file(a) == sha256_file(a)
    assert sha256_file(a) != sha256_file(b)


def test_changed_source_becomes_stale_and_reupload_candidate(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    with open(os.path.join(package_dir, "mockups", "alpha.png"), "w", encoding="utf-8") as handle:
        handle.write("CHANGED mockup-a-content")
    candidates, _ = service.resolve_candidates(package_dir, handoff)
    enriched = [service._enrich(c) for c in candidates]
    stale = service.find_stale(enriched)
    assert "a" in stale
    dry = service.dry_run(package_dir, handoff)
    statuses = _status_map(dry)
    assert statuses["a"] == HOSTING_STATUS_PENDING  # old URL not silently reused


def test_partial_failure(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    provider.fail_public_ids = {build_public_id(package_id="pkg-777", prospect_id="b", generation_job_id="job-b")}
    service = _make_service(tmp_path, provider)
    result = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.hosted == 1
    assert result.failed == 1
    statuses = _status_map(result)
    assert statuses["a"] == HOSTING_STATUS_HOSTED
    assert statuses["b"] == HOSTING_STATUS_FAILED
    assert service.asset_store.find_by_prospect("a")  # successful a not rolled back


def test_retry_failed_only(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    fail_id = build_public_id(package_id="pkg-777", prospect_id="b", generation_job_id="job-b")
    provider.fail_public_ids = {fail_id}
    store_path = os.path.join(str(tmp_path), "receipts.json")
    service = AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=store_path))
    first = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert first.failed == 1
    provider.fail_public_ids = set()
    service2 = AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=store_path))
    second = service2.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert second.reused >= 1  # a reused, only b attempted
    assert second.failed == 0 and second.hosted == 1


def test_blocked_asset_not_uploaded(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    result = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    ids = {pid for _, pid in provider.uploads}
    assert not any("c" in pid for pid in ids)
    assert result.blocked == 1


def test_public_url_must_be_https(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    provider.http_public_ids = {build_public_id(package_id="pkg-777", prospect_id="a", generation_job_id="job-a")}
    service = _make_service(tmp_path, provider)
    result = service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.failed >= 1
    a_result = next(r for r in result.results if r.prospect_id == "a")
    assert a_result.status == HOSTING_STATUS_FAILED


def test_secret_never_leaked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "super-secret-host-secret")
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    store_path = os.path.join(str(tmp_path), "receipts.json")
    service = AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=store_path))
    service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    raw = open(store_path, "r", encoding="utf-8").read()
    assert "super-secret-host-secret" not in raw


def test_provider_collision_naming_safe(tmp_path):
    pid_a = build_public_id(package_id="pkg-777", prospect_id="a", generation_job_id="job-a")
    pid_b = build_public_id(package_id="pkg-777", prospect_id="b", generation_job_id="job-b")
    assert pid_a != pid_b
    assert pid_a.startswith("billboardai/")
    pid_other = build_public_id(package_id="pkg-999", prospect_id="a", generation_job_id="job-a")
    assert pid_a != pid_other


def test_source_file_unchanged_keeps_fingerprint(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    service = _make_service(tmp_path, FakeAssetProvider())
    c1, _ = service.resolve_candidates(package_dir, handoff)
    f1 = [service._enrich(c).source_fingerprint for c in c1]
    c2, _ = service.resolve_candidates(package_dir, handoff)
    f2 = [service._enrich(c).source_fingerprint for c in c2]
    assert f1 == f2


def test_cross_prospect_isolation(tmp_path):
    package_dir, handoff = _seed(tmp_path)
    provider = FakeAssetProvider()
    service = _make_service(tmp_path, provider)
    service.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
    assert {a.prospect_id for a in service.asset_store.find_by_prospect("a")} == {"a"}
    assert {a.prospect_id for a in service.asset_store.find_by_prospect("b")} == {"b"}
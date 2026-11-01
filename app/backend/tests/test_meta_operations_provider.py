"""Real adapter exercised only with synthetic credentials and injected HTTP."""
import logging
import inspect
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet

from services import meta_operations_provider as provider


@pytest.fixture
def configured(monkeypatch):
    old = {"ENABLED": "true", "APP_ID": "1139445441758834", "APP_SECRET": "SYNTHETIC-CRM-APP-SECRET", "TOKEN_KEY": Fernet.generate_key().decode(),
           "CONFIG_ID": "1146714154579519", "GRAPH_VERSION": "v26.0", "PUBLIC_URL": "https://t24-crm.com",
           "EXPECTED_SCOPES": "instagram_basic,pages_read_engagement,pages_show_list", "LOGIN_CONFIG_REVIEWED": "true"}
    for name, value in old.items(): monkeypatch.setenv("T24_META_" + name, value)
    ops = {**old, "APP_ID": "2233445566778899", "APP_SECRET": "SYNTHETIC-INDEPENDENT-PUBLISHER-SECRET", "TOKEN_KEY": Fernet.generate_key().decode(), "CONFIG_ID": "999111888222", "EXPECTED_SCOPES": ",".join(sorted(provider.SCOPES)), "EXECUTION_ENABLED": "true"}
    for name, value in ops.items(): monkeypatch.setenv("T24_META_OPS_" + name, value)
    return provider.require_config()


def transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda *a, **kw: real(*a, **kw, transport=httpx.MockTransport(handler)))


def grant(**changes):
    return provider.encrypt({"access_token": "SYNTHETIC-OPS-USER-TOKEN", "expires_at": time.time() + 9000,
                             "configuration": provider.configuration_fingerprint(), "observed_scopes": sorted(provider.SCOPES), **changes})


def binding(platform="facebook"):
    return SimpleNamespace(id=1, owner_id=1, customer_id=1, platform=platform, page_id="111", external_id="111" if platform == "facebook" else "222")


def oauth_reply(request):
    path = request.url.path
    if path.endswith("/oauth/access_token"):
        long = request.url.params.get("grant_type") == "fb_exchange_token"
        return {"access_token": "SYNTHETIC-OPS-LONG-TOKEN" if long else "SYNTHETIC-OPS-SHORT-TOKEN", "token_type": "bearer", "expires_in": 9000}
    if path.endswith("/debug_token"):
        return {"data": {"is_valid": True, "app_id": provider.require_config()["APP_ID"], "type": "USER", "user_id": "123", "scopes": sorted(provider.SCOPES), "expires_at": int(time.time() + 8000)}}
    if path.endswith("/me"): return {"id": "123"}
    if path.endswith("/me/permissions"): return {"data": [{"permission": x, "status": "granted"} for x in sorted(provider.SCOPES)]}
    raise AssertionError("Unexpected synthetic route")


def authorize(monkeypatch, *, tasks=None):
    client = provider.OpsClient(grant())
    async def authorized(db, user, target):
        return client, {"token": "SYNTHETIC-PAGE-TOKEN", "tasks": tasks if tasks is not None else {"CREATE_CONTENT", "MODERATE"}}
    monkeypatch.setattr(provider, "_authorized", authorized)
    return client


@pytest.mark.parametrize("changed,value", [("APP_ID", "1625116099132983"), ("APP_ID", "1139445441758834"), ("APP_SECRET", "SYNTHETIC-CRM-APP-SECRET"), ("CONFIG_ID", "1146714154579519"), ("PUBLIC_URL", "https://evil.example"),
                                         ("EXPECTED_SCOPES", "pages_show_list"), ("LOGIN_CONFIG_REVIEWED", "false")])
def test_operations_configuration_cannot_reuse_old_config_or_broaden_origin(configured, monkeypatch, changed, value):
    monkeypatch.setenv("T24_META_OPS_" + changed, value)
    with pytest.raises(provider.OpsProviderError, match="not_configured"): provider.require_config()


def test_operations_key_is_independent_and_old_read_configuration_unchanged(configured, monkeypatch):
    old, old_missing = provider.legacy.settings()
    assert not old_missing and set(old["SCOPES"]) == provider.legacy.READ_SCOPES
    monkeypatch.setenv("T24_META_OPS_TOKEN_KEY", old["TOKEN_KEY"])
    assert "T24_META_OPS_INDEPENDENT_TOKEN_KEY" in provider.settings()[1]
    assert provider.legacy.settings() == (old, old_missing)


def test_independent_publisher_configuration_does_not_depend_on_read_app_being_enabled(configured, monkeypatch):
    monkeypatch.setenv("T24_META_ENABLED", "false")
    monkeypatch.delenv("T24_META_TOKEN_KEY")
    assert provider.legacy.settings()[1]
    assert provider.require_config() == configured


@pytest.mark.asyncio
async def test_operations_exchange_strict_identity_scopes_expiry_without_mutations_or_secret_logs(configured, monkeypatch, caplog):
    seen = []
    transport(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json=oauth_reply(request)))
    caplog.set_level(logging.DEBUG, logger="httpx")
    value = await provider.exchange("SYNTHETIC-ONE-USE-CODE")
    assert value["observed_scopes"] == sorted(provider.SCOPES) and value["user_id"] == "123"
    assert len(seen) == 5 and all(x.method == "GET" and x.url.host == "graph.facebook.com" for x in seen)
    assert seen[0].url.params["redirect_uri"] == provider.CALLBACK
    assert all(x not in caplog.text for x in ("SYNTHETIC-ONE-USE-CODE", "SYNTHETIC-CRM-APP-SECRET", "SYNTHETIC-INDEPENDENT-PUBLISHER-SECRET", "SYNTHETIC-OPS-LONG-TOKEN", "SYNTHETIC-OPS-SHORT-TOKEN"))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unexpected", "missing", "wrong_app", "system_user", "expired", "identity"])
async def test_write_grant_never_silently_accepts_partial_extra_or_wrong_identity(configured, monkeypatch, change):
    def handle(request):
        value = oauth_reply(request)
        if request.url.path.endswith("/debug_token"):
            if change == "unexpected": value["data"]["scopes"].append("ads_management")
            if change == "missing": value["data"]["scopes"].remove("pages_read_user_content")
            if change == "wrong_app": value["data"]["app_id"] = "1625116099132983"
            if change == "system_user": value["data"]["type"] = "SYSTEM_USER"
            if change == "expired": value["data"]["expires_at"] = int(time.time()) - 1
        if request.url.path.endswith("/me") and change == "identity": value["id"] = "999"
        return httpx.Response(200, json=value)
    transport(monkeypatch, handle)
    with pytest.raises(provider.OpsProviderError): await provider.exchange("SYNTHETIC-CODE")


@pytest.mark.asyncio
async def test_page_tokens_are_ephemeral_and_current_linked_instagram_is_verified(configured, monkeypatch):
    def handle(request):
        assert request.method == "GET" and request.url.path == "/v26.0/me/accounts"
        return httpx.Response(200, json={"data": [{"id": "111", "access_token": "SYNTHETIC-PAGE-TOKEN", "tasks": ["CREATE_CONTENT", "MODERATE"], "instagram_business_account": {"id": "222"}}]})
    transport(monkeypatch, handle)
    page = await provider.OpsClient(grant()).page(binding("instagram"))
    assert page["tasks"] == {"CREATE_CONTENT", "MODERATE"}
    wrong = binding("instagram"); wrong.external_id = "333"
    with pytest.raises(provider.OpsProviderError, match="asset_not_authorized"): await provider.OpsClient(grant()).page(wrong)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://evil.example"}, json={}), httpx.Response(503, json={"error": {"code": 2, "message": "SECRET"}})])
async def test_mutation_redirect_and_server_failure_are_uncertain_and_never_retried(configured, monkeypatch, response):
    seen = []
    transport(monkeypatch, lambda request: seen.append(request) or response)
    with pytest.raises(provider.OpsProviderError) as error:
        await provider.OpsClient(grant()).request("POST", "111/feed", data={"message": "approved"}, token="SYNTHETIC-PAGE-TOKEN", mutation=True)
    assert error.value.uncertain is True and len(seen) == 1 and seen[0].url.host == "graph.facebook.com"
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_definite_graph_auth_rejection_is_not_mislabeled_as_published(configured, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(400, json={"error": {"code": 190, "message": "SECRET-TOKEN"}}))
    with pytest.raises(provider.OpsProviderError) as error:
        await provider.OpsClient(grant()).request("POST", "111/feed", data={"message": "approved"}, token="SYNTHETIC-PAGE-TOKEN", mutation=True)
    assert error.value.code == "reconnect_required" and not error.value.uncertain and "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_timeout_after_post_attempt_is_unknown_without_a_second_attempt(configured, monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        raise httpx.ReadTimeout("SYNTHETIC-SECRET-URL", request=request)
    transport(monkeypatch, handle)
    with pytest.raises(provider.OpsProviderError) as error:
        await provider.OpsClient(grant()).request("POST", "111/feed", data={"message": "approved"}, token="SYNTHETIC-PAGE-TOKEN", mutation=True)
    assert error.value.uncertain and len(seen) == 1 and "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_execution_disabled_blocks_every_mutation_before_network(configured, monkeypatch):
    monkeypatch.setenv("T24_META_OPS_EXECUTION_ENABLED", "false")
    async def forbidden(*a, **kw): raise AssertionError("No auth or network work for disabled dispatch")
    monkeypatch.setattr(provider, "_authorized", forbidden)
    with pytest.raises(provider.OpsProviderError, match="execution_disabled"): await provider.dispatch(None, None, binding(), "post", {"content": "approved"})
    with pytest.raises(provider.OpsProviderError, match="execution_disabled"): await provider.publish_container(None, None, binding("instagram"), "333")


@pytest.mark.asyncio
async def test_facebook_exact_approved_caption_and_backend_issued_jpeg_only(configured, monkeypatch):
    seen = []; authorize(monkeypatch)
    transport(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json={"id": "111_444"}))
    text = "Approved 中文\nCaption  "
    value = await provider.dispatch(None, None, binding(), "post", {"content": text})
    assert value["external_id"] == "111_444" and parse_qs(seen[0].content.decode())["message"] == [text]
    with pytest.raises(provider.OpsProviderError, match="content_invalid"):
        await provider.dispatch(None, None, binding(), "post", {"content": text, "image_url": "https://127.0.0.1/private.jpg"})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_instagram_container_checkpoint_precedes_an_explicit_single_publish(configured, monkeypatch):
    seen = []; authorize(monkeypatch)
    def handle(request):
        seen.append(request)
        if request.url.path == "/v26.0/222/media": return httpx.Response(200, json={"id": "333"})
        if request.url.path == "/v26.0/333": return httpx.Response(200, json={"id": "333", "status_code": "FINISHED"})
        if request.url.path == "/v26.0/222/media_publish": return httpx.Response(200, json={"id": "444"})
        raise AssertionError("Unexpected route")
    transport(monkeypatch, handle)
    first = await provider.dispatch(None, None, binding("instagram"), "post", {"content": "Approved", "image_url": "https://t24-crm.com/api/v1/meta-operations/delivery/" + "A" * 43 + ".jpg"})
    assert first == {"status": "processing", "container_id": "333", "stage": "container_created"} and len(seen) == 1
    inspected = await provider.inspect_progress(None, None, binding("instagram"), first)
    assert inspected["status"] == "FINISHED" and [x.method for x in seen] == ["POST", "GET"]
    last = await provider.publish_container(None, None, binding("instagram"), first["container_id"])
    assert last["external_id"] == "444" and [x.method for x in seen] == ["POST", "GET", "POST"]
    assert parse_qs(seen[-1].content.decode())["creation_id"] == ["333"]


@pytest.mark.asyncio
async def test_instagram_text_only_is_rejected_without_post(configured, monkeypatch):
    authorize(monkeypatch)
    transport(monkeypatch, lambda request: (_ for _ in ()).throw(AssertionError("No request")))
    with pytest.raises(provider.OpsProviderError, match="content_invalid"):
        await provider.dispatch(None, None, binding("instagram"), "post", {"content": "Approved caption"})


@pytest.mark.asyncio
async def test_reply_fresh_comment_version_blocks_edited_target_before_post(configured, monkeypatch):
    seen = []; authorize(monkeypatch)
    def handle(request):
        seen.append(request)
        if request.url.path == "/v26.0/111_900": return httpx.Response(200, json={"id": "111_900", "message": "Edited content", "from": {"name": "Customer"}, "created_time": "2026-11-01T00:00:00Z", "object": {"id": "111_800"}})
        if request.url.path == "/v26.0/111_800": return httpx.Response(200, json={"id": "111_800", "from": {"id": "111"}})
        raise AssertionError("No mutation allowed")
    transport(monkeypatch, handle)
    old = {"external_id": "111_900", "content": "Old content", "author_name": "Customer", "created_at": "2026-11-01T00:00:00+00:00", "post_external_id": "111_800", "reply": None}
    with pytest.raises(provider.OpsProviderError, match="target_changed"):
        await provider.dispatch(None, None, binding(), "reply", {"target_id": "111_900", "post_id": "111_800", "message": "Approved reply", "expected_version": provider.comment_version(old)})
    assert all(x.method == "GET" for x in seen)


@pytest.mark.asyncio
async def test_foreign_post_cannot_be_read_or_used_for_reply(configured, monkeypatch):
    seen = []; authorize(monkeypatch)
    transport(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json={"id": "999_888", "from": {"id": "999"}}))
    with pytest.raises(provider.OpsProviderError, match="asset_not_authorized"): await provider.read_comments(None, None, binding(), "999_888")
    assert len(seen) == 1 and seen[0].method == "GET"


@pytest.mark.asyncio
async def test_post_listing_never_follows_untrusted_next_url(configured, monkeypatch):
    authorize(monkeypatch)
    transport(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "111_800", "message": "Post", "created_time": "2026-11-01T00:00:00Z", "permalink_url": "https://www.facebook.com/111/posts/800"}], "paging": {"next": "https://evil.example/?access_token=SECRET", "cursors": {"after": "OPAQUE-CURSOR"}}}))
    value = await provider.read_posts(None, None, binding())
    assert value["next_cursor"] == "OPAQUE-CURSOR" and "evil" not in str(value) and "SECRET" not in str(value)


@pytest.mark.parametrize("value,expected", [
    ("2026-11-01T08:15:30+0000", "2026-11-01T08:15:30+00:00"),
    ("2026-11-01T08:15:30-0700", "2026-11-01T15:15:30+00:00"),
    ("2026-11-01T08:15:30+0530", "2026-11-01T02:45:30+00:00"),
    ("2026-11-01T08:15:30Z", "2026-11-01T08:15:30+00:00"),
    ("2026-11-01T08:15:30+08:00", "2026-11-01T00:15:30+00:00"),
    ("2026-11-01T08:15:30.123456+08:00", "2026-11-01T00:15:30.123456+00:00"),
])
def test_graph_timestamps_normalize_compact_and_aware_iso_to_utc(value, expected):
    assert provider._timestamp(value) == expected


@pytest.mark.parametrize("value", [None, 1793492130, "", "x"*101, "invalid", "2026-11-01", "2026-11-01T08:15:30",
    "2026-11-31T08:15:30+0000", "2026-11-01T08:15:60+0000", "2026-11-01T08:15:30+2400",
    "2026-11-01T08:15:30-2400", "2026-11-01T08:15:30+0060", "2026-11-01T08:15:30+1261",
    "0001-01-01T00:00:00+0001", "9999-12-31T23:59:59-0001"])
def test_graph_timestamp_invalid_or_naive_values_remain_unverified(value):
    assert provider._timestamp(value) is None


def test_graph_timestamp_compact_offset_runs_on_pre311_iso_parser():
    # Execute the actual helper with a real older stdlib when available. This
    # catches the production 3.10/local 3.12 difference without importing any
    # HTTP/auth dependency or contacting a provider in that interpreter.
    code = ("import json,re,sys\nfrom datetime import datetime,timezone\n"
        "if sys.version_info[:2]>(3,10):raise SystemExit(77)\n" + inspect.getsource(provider._timestamp) +
        "\nassert _timestamp('2026-11-01T08:15:30+0000')=='2026-11-01T08:15:30+00:00'\n"
        "assert _timestamp('2026-11-01T08:15:30-0700')=='2026-11-01T15:15:30+00:00'\n"
        "assert _timestamp('2026-11-01T08:15:30Z')=='2026-11-01T08:15:30+00:00'\n"
        "assert _timestamp('2026-11-01T08:15:30') is None\nprint('PRE311_GRAPH_TIMESTAMP_COMPATIBLE')\n")
    for executable in dict.fromkeys((sys.executable, "/usr/bin/python3")):
        if not Path(executable).is_file(): continue
        result = subprocess.run([executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=10)
        if result.returncode == 77: continue
        assert result.returncode == 0 and result.stdout.strip() == "PRE311_GRAPH_TIMESTAMP_COMPATIBLE", result.stderr
        return
    pytest.skip("A pre3.11 stdlib is not installed; deployment must also run this probe with its Python3.10 interpreter")


@pytest.mark.asyncio
async def test_facebook_post_listing_preserves_real_compact_created_time(configured, monkeypatch):
    authorize(monkeypatch); seen = []
    def reply(request):
        seen.append(request)
        return httpx.Response(200, json={"data":[{"id":"111_800", "message":"Synthetic store update",
            "created_time":"2026-11-01T08:15:30+0000", "permalink_url":"https://www.facebook.com/111/posts/800"}]})
    transport(monkeypatch, reply)
    result = await provider.read_posts(None, None, binding())
    assert result["items"][0]["created_at"] == "2026-11-01T08:15:30+00:00"
    assert len(seen) == 1 and seen[0].method == "GET" and "created_time" in seen[0].url.params["fields"]


def test_facebook_comment_snapshot_uses_same_normalized_timestamp():
    row = provider._comment_data({"id":"111_900", "message":"Synthetic customer question", "from":{"name":"Customer"},
        "created_time":"2026-11-01T08:15:30+0000"}, binding(), "111_800")
    assert row["created_at"] == "2026-11-01T08:15:30+00:00"
    assert row["post_external_id"] == "111_800" and len(provider.comment_version(row)) == 64


@pytest.mark.parametrize("scopes", [[{}], ["pages_show_list"], sorted(provider.SCOPES) + ["ads_management"]])
def test_malformed_or_broader_persisted_grants_fail_safely(configured, scopes):
    with pytest.raises(provider.OpsProviderError): provider.OpsClient(grant(observed_scopes=scopes)).access()


@pytest.mark.asyncio
async def test_publisher_oauth_verifies_every_exact_frozen_asset_without_mutation(configured, monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "111", "access_token": "SYNTHETIC-PAGE-TOKEN", "tasks": ["CREATE_CONTENT", "MODERATE"], "instagram_business_account": {"id": "222"}}]})
    transport(monkeypatch, handle)
    targets = [{"id": 10, "source_binding_id": 10, "owner_id": 1, "customer_id": 38, "platform": "facebook", "external_id": "111", "page_id": "111"},
               {"id": 11, "source_binding_id": 11, "owner_id": 1, "customer_id": 38, "platform": "instagram", "external_id": "222", "page_id": "111"}]
    verified = await provider.verify_assets(grant(), targets)
    assert verified == targets and verified is not targets and all(x.method == "GET" for x in seen)
    assert "TOKEN" not in str(verified) and len(seen) == 2
    targets[1]["external_id"] = "333"
    with pytest.raises(provider.OpsProviderError, match="asset_not_authorized"): await provider.verify_assets(grant(), targets)
    assert all(x.method == "GET" for x in seen)


@pytest.mark.asyncio
async def test_independent_authority_survives_read_only_expiry_pause_and_revision(configured, monkeypatch):
    from services import meta_business
    own = SimpleNamespace(id=10, source_binding_id=10, owner_id=1, customer_id=38, platform="facebook", external_id="111", page_id="111",
                          connection_id=9, credential_id=20, connection_revision=7, revision=3, active=True)
    historical = SimpleNamespace(**vars(own)); historical.active = False; historical.revision = 100; historical.connection_revision = 200
    credential = SimpleNamespace(id=20, owner_id=1, connection_id=9, active=True, needs_reconnect=False, revision=7,
                                 token_encrypted=grant(), granted_scopes=sorted(provider.SCOPES))
    tables = []
    class Db:
        async def scalar(self, query):
            table = query.column_descriptions[0]["entity"].__tablename__; tables.append(table)
            return {"meta_operations_bindings": own, "meta_business_bindings": historical, "meta_operations_credentials": credential}[table]
    async def context(*a, **kw): return SimpleNamespace(identity=1)
    async def customer(*a, **kw): return SimpleNamespace(id=38, status="closed", business_name="PokeCo"), {}
    async def page(self, row): return {"token": "SYNTHETIC-PAGE-TOKEN", "tasks": {"CREATE_CONTENT", "MODERATE"}}
    monkeypatch.setattr(meta_business, "context", context); monkeypatch.setattr(meta_business.media, "_customer", customer); monkeypatch.setattr(provider.OpsClient, "page", page)
    client, access = await provider._authorized(Db(), None, own)
    assert access["tasks"] == {"CREATE_CONTENT", "MODERATE"}
    assert tables == ["meta_operations_bindings", "meta_business_bindings", "meta_operations_credentials"]
    assert all("connections" not in name for name in tables)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["own_paused", "own_revision", "source_retargeted", "credential_paused", "credential_revision", "customer_paused"])
async def test_publisher_own_revocation_retarget_or_credential_change_blocks_before_provider(configured, monkeypatch, change):
    from services import meta_business
    expected = SimpleNamespace(id=10, source_binding_id=10, owner_id=1, customer_id=38, platform="facebook", external_id="111", page_id="111",
                               connection_id=9, credential_id=20, connection_revision=7, revision=3, active=True)
    own = SimpleNamespace(**vars(expected)); historical = SimpleNamespace(**vars(expected))
    credential = SimpleNamespace(id=20, owner_id=1, connection_id=9, active=True, needs_reconnect=False, revision=7,
                                 token_encrypted=grant(), granted_scopes=sorted(provider.SCOPES))
    if change == "own_paused": own.active = False
    if change == "own_revision": own.revision += 1
    if change == "source_retargeted": historical.customer_id = 39
    if change == "credential_paused": credential.active = False
    if change == "credential_revision": credential.revision += 1
    class Db:
        async def scalar(self, query):
            return {"meta_operations_bindings": own, "meta_business_bindings": historical, "meta_operations_credentials": credential}[query.column_descriptions[0]["entity"].__tablename__]
    async def context(*a, **kw): return SimpleNamespace(identity=1)
    async def customer(*a, **kw): return SimpleNamespace(id=38, status="paused" if change == "customer_paused" else "closed", business_name="Pokeco"), {}
    async def forbidden(*a, **kw): raise AssertionError("No provider request for stale authority")
    monkeypatch.setattr(meta_business, "context", context); monkeypatch.setattr(meta_business.media, "_customer", customer); monkeypatch.setattr(provider.OpsClient, "page", forbidden)
    with pytest.raises(provider.OpsProviderError): await provider._authorized(Db(), None, expected)


@pytest.mark.asyncio
async def test_populate_existing_cannot_rewrite_expected_binding_revision(configured, monkeypatch):
    from services import meta_business
    own = SimpleNamespace(id=10, source_binding_id=10, owner_id=1, customer_id=38, platform="facebook", external_id="111", page_id="111",
                          connection_id=9, credential_id=20, connection_revision=7, revision=3, active=True)
    class Db:
        async def scalar(self, query): own.revision += 1; return own
    async def context(*a, **kw): return SimpleNamespace(identity=1)
    monkeypatch.setattr(meta_business, "context", context)
    with pytest.raises(provider.OpsProviderError, match="target_changed"): await provider._authorized(Db(), None, own)

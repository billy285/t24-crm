"""Exercise real Meta adapter against an injected HTTP transport only."""
import copy
import logging
import time
import traceback
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet

from services import meta_business_provider as provider


@pytest.fixture
def configured(monkeypatch):
    for key, value in {"ENABLED": "true", "APP_ID": "123456789", "APP_SECRET": "SYNTHETIC-META-APP-SECRET", "CONFIG_ID": "987654321",
                       "GRAPH_VERSION": "v26.0", "TOKEN_KEY": Fernet.generate_key().decode(), "PUBLIC_URL": "https://t24-crm.com",
                       "EXPECTED_SCOPES": "pages_show_list,pages_read_engagement,instagram_basic", "LOGIN_CONFIG_REVIEWED": "true"}.items():
        monkeypatch.setenv("T24_META_" + key, value)
    return provider.require_config()


def transport(monkeypatch, handler):
    real = httpx.AsyncClient
    def client(*args, **kwargs): return real(*args, **kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(provider.httpx, "AsyncClient", client)


def encrypted_token(**updates):
    return provider.encrypt({"access_token": "SYNTHETIC-LONG-USER-TOKEN", "expires_at": time.time() + 10000,
        "configuration": provider.configuration_fingerprint(), **updates})


def valid_reply(request):
    path = request.url.path
    if path.endswith("/oauth/access_token"):
        long = request.url.params.get("grant_type") == "fb_exchange_token"
        return {"access_token": "SYNTHETIC-LONG-USER-TOKEN" if long else "SYNTHETIC-SHORT-USER-TOKEN", "token_type": "bearer", "expires_in": 10000}
    if path.endswith("/debug_token"):
        return {"data": {"is_valid": True, "app_id": "123456789", "type": "USER", "user_id": "100",
                         "scopes": sorted(provider.READ_SCOPES), "expires_at": int(time.time() + 9000)}}
    if path.endswith("/me/permissions"): return {"data": [{"permission": x, "status": "granted"} for x in sorted(provider.READ_SCOPES)]}
    if path.endswith("/me"): return {"id": "100"}
    raise AssertionError("Unexpected provider path")


@pytest.mark.asyncio
async def test_real_code_long_token_inspection_and_granted_scopes_with_no_secret_logs(configured, monkeypatch, caplog):
    requests = []
    def handle(request): requests.append(request); return httpx.Response(200, json=valid_reply(request))
    transport(monkeypatch, handle); caplog.set_level(logging.INFO, logger="httpx")
    result = await provider.MetaClient().exchange("SYNTHETIC-ONE-USE-AUTH-CODE")
    assert result["access_token"] == "SYNTHETIC-LONG-USER-TOKEN" and result["user_id"] == "100"
    assert result["observed_scopes"] == sorted(provider.READ_SCOPES) and result["expires_at"] <= time.time() + 9000
    assert len(requests) == 5 and all(r.method == "GET" and r.url.host == "graph.facebook.com" and r.url.path.startswith("/v26.0/") for r in requests)
    assert requests[0].url.params["redirect_uri"] == provider.CALLBACK
    assert requests[1].url.params["grant_type"] == "fb_exchange_token"
    assert requests[2].headers["authorization"] == "Bearer 123456789|SYNTHETIC-META-APP-SECRET"
    assert requests[3].headers["authorization"] == "Bearer SYNTHETIC-LONG-USER-TOKEN"
    assert all(secret not in caplog.text for secret in ("SYNTHETIC-ONE-USE-AUTH-CODE", "SYNTHETIC-META-APP-SECRET", "SYNTHETIC-LONG-USER-TOKEN", "SYNTHETIC-SHORT-USER-TOKEN"))
    assert configured["TOKEN_KEY"] not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["wrong_app", "wrong_type", "invalid", "wrong_user", "expired", "missing_scope", "declined", "duplicate_permission", "unexpected_debug_write", "unexpected_permission_write"])
async def test_code_exchange_refuses_wrong_app_identity_type_expiry_and_missing_grants(configured, monkeypatch, mutation):
    def handle(request):
        value = valid_reply(request)
        if request.url.path.endswith("/debug_token"):
            data = value["data"]
            if mutation == "wrong_app": data["app_id"] = "999"
            elif mutation == "wrong_type": data["type"] = "SYSTEM_USER"
            elif mutation == "invalid": data["is_valid"] = False
            elif mutation == "expired": data["expires_at"] = int(time.time() - 1)
            elif mutation == "missing_scope": data["scopes"] = ["pages_show_list"]
            elif mutation == "unexpected_debug_write": data["scopes"].append("instagram_content_publish")
        if request.url.path.endswith("/me") and mutation == "wrong_user": value["id"] = "999"
        if request.url.path.endswith("/me/permissions"):
            if mutation == "declined": value["data"][0]["status"] = "declined"
            elif mutation == "duplicate_permission": value["data"].append(copy.deepcopy(value["data"][0]))
            elif mutation == "unexpected_permission_write": value["data"].append({"permission": "pages_manage_posts", "status": "granted"})
        return httpx.Response(200, json=value)
    transport(monkeypatch, handle)
    with pytest.raises(provider.ProviderError): await provider.MetaClient().exchange("SYNTHETIC-CODE")


@pytest.mark.asyncio
async def test_real_assets_project_ids_and_tasks_without_page_tokens_or_external_fetch(configured, monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        assert request.url.path == "/v26.0/me/accounts" and request.headers["authorization"] == "Bearer SYNTHETIC-LONG-USER-TOKEN"
        assert "access_token" not in request.url.params and request.url.params["fields"] == "name,tasks,instagram_business_account"
        if request.url.params.get("after"):
            return httpx.Response(200, json={"data": [{"id": "333", "name": "Second Page", "tasks": ["ANALYZE"]}]})
        return httpx.Response(200, json={"data": [{"id": "111", "name": "Synthetic Page", "access_token": "SECRET-UNREQUESTED-PAGE-TOKEN",
            "tasks": ["CREATE_CONTENT"], "instagram_business_account": {"id": "222"}}],
            "paging": {"next": "https://evil.example/steal?access_token=SECRET", "cursors": {"after": "OPAQUE-CURSOR"}}})
    transport(monkeypatch, handle)
    result = await provider.MetaClient(encrypted_token()).assets()
    assert [x["platform"] for x in result["items"]] == ["facebook", "instagram", "facebook"]
    assert result["items"][1]["page_id"] == "111" and result["items"][1]["external_id"] == "222"
    assert not result["truncated"] and len(seen) == 2 and all(x.url.host == "graph.facebook.com" for x in seen)
    assert "SECRET" not in str(result) and "access_token" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"id": "https://evil.example"}, {"id": "111", "instagram_business_account": {"id": "../private"}}, {"id": "111", "tasks": "MANAGE"}])
async def test_assets_reject_malformed_provider_identity_and_task_shapes(configured, monkeypatch, invalid):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"data": [invalid]}))
    with pytest.raises(provider.ProviderError): await provider.MetaClient(encrypted_token()).assets()


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_error_body_never_becomes_message(configured, monkeypatch):
    requests = []
    def handle(request): requests.append(request); return httpx.Response(302, headers={"Location": "https://evil.example/steal"}, json={"error": {"message": "SECRET-PROVIDER-ERROR"}})
    transport(monkeypatch, handle)
    with pytest.raises(provider.ProviderError) as failure: await provider.MetaClient(encrypted_token()).assets()
    assert str(failure.value) == "provider_unavailable" and len(requests) == 1


@pytest.mark.asyncio
async def test_oversized_response_and_unbounded_pagination_fail_or_stop_without_url_reuse(configured, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 2_000_001))
    with pytest.raises(provider.ProviderError, match="invalid_response"): await provider.MetaClient(encrypted_token()).assets()


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [{"expires_at": 0}, {"expires_at": float("nan")}, {"configuration": "changed"}])
async def test_expired_or_reconfigured_tokens_never_make_network_calls(configured, monkeypatch, updates):
    transport(monkeypatch, lambda request: pytest.fail("No provider call permitted"))
    with pytest.raises(provider.ProviderError, match="reconnect_required"): await provider.MetaClient(encrypted_token(**updates)).assets()


def test_configuration_is_explicit_fixed_callback_user_config_and_independent_key(configured, monkeypatch):
    assert not provider.settings()[1]
    monkeypatch.setenv("T24_GBP_TOKEN_KEY", configured["TOKEN_KEY"])
    assert "T24_META_INDEPENDENT_TOKEN_KEY" in provider.settings()[1]
    monkeypatch.delenv("T24_GBP_TOKEN_KEY")
    monkeypatch.delenv("T24_META_GRAPH_VERSION")
    assert "T24_META_GRAPH_VERSION" in provider.settings()[1]
    with pytest.raises(Exception): provider.authorize_url("s" * 54)


def test_unconfigured_default_never_claims_ready_or_uses_default_graph_version(monkeypatch):
    for key in ("ENABLED", "APP_ID", "APP_SECRET", "TOKEN_KEY", "CONFIG_ID", "GRAPH_VERSION", "PUBLIC_URL", "EXPECTED_SCOPES", "LOGIN_CONFIG_REVIEWED"):
        monkeypatch.delenv("T24_META_" + key, raising=False)
    values, missing = provider.settings()
    assert not provider.enabled() and "T24_META_GRAPH_VERSION" in missing and values["GRAPH_VERSION"] == ""
    assert "T24_META_APP_ID" in missing and "T24_META_TOKEN_KEY" in missing


def test_query_redaction_for_preformatted_format_arguments_and_context_local_httpcore(configured, caplog):
    scrub = provider.MetaNetworkLogFilter()
    for message, args in [("HTTP Request https://graph.facebook.com/v26.0/oauth/access_token?client_secret=SECRET&code=SECRET", ()),
                          ("HTTP Request https://graph.facebook.com/v26.0/oauth/access_token?client_secret=%s&code=%s", ("SECRET", "SECRET")),
                          ("HTTP Request %s", ("https://graph.facebook.com/v26.0/debug_token?input_token=SECRET",)),
                          ("HTTP Request %(url)s", ({"url": "https://graph.facebook.com/v26.0/oauth/access_token?fb_exchange_token=SECRET"},))]:
        record = logging.LogRecord("httpx", logging.INFO, "", 1, message, args, None)
        assert scrub.filter(record) and "SECRET" not in record.getMessage()
    marker = provider.META_NETWORK_ACTIVE.set(True)
    try:
        for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
            record = logging.LogRecord(name, logging.DEBUG, "", 1, "Authorization: Bearer SECRET", (), None)
            assert all(not f.filter(record) for f in logging.getLogger(name).filters if isinstance(f, provider.MetaNetworkLogFilter))
    finally: provider.META_NETWORK_ACTIVE.reset(marker)
    record = logging.LogRecord("httpx", logging.INFO, "", 1, "HTTP Request %s", ("https://mybusiness.googleapis.com/v4/accounts/1?unchanged=1",), None)
    assert scrub.filter(record) and "unchanged=1" in record.getMessage()


@pytest.mark.asyncio
async def test_transport_exception_chain_never_displays_oauth_query_credentials(configured, monkeypatch):
    secret = "".join(["SYNTHETIC", "-PRIVATE-TRANSPORT-MARKER"])
    def handle(request): raise httpx.ConnectError(secret + " " + str(request.url), request=request)
    transport(monkeypatch, handle)
    with pytest.raises(provider.ProviderError) as failure: await provider.MetaClient().exchange(secret)
    assert failure.value.__suppress_context__ is True and str(failure.value) == "provider_unavailable"
    rendered = "".join(traceback.TracebackException.from_exception(failure.value).format(chain=True))
    assert secret not in rendered and configured["APP_SECRET"] not in rendered
    assert provider.META_NETWORK_ACTIVE.get() is False

"""Prospective callback diagnostics: synthetic HTTP/SQLite only, no credentials."""
import asyncio
from datetime import timedelta
import json
import logging

import httpx
import pytest
from sqlalchemy import select

from services import meta_business as service, meta_business_provider as provider
from test_meta_business import meta_env, gbp_env, start, protected_snapshot, State
from test_meta_business_provider import transport, valid_reply

PREFIX = "/api/v1/meta-business"
LOGGER = "meta_business.oauth"
EVENT = "META_OAUTH_CALLBACK_PROVIDER_FAILURE "
CANARY = "SYNTHETIC-SECRET-DO-NOT-LOG"


def events(caplog):
    records = [record for record in caplog.records if record.name == LOGGER]
    output = []
    for record in records:
        assert record.args == () and record.exc_info is None and record.stack_info is None
        assert record.getMessage().startswith(EVENT)
        fields = json.loads(record.getMessage()[len(EVENT):])
        assert set(fields) <= {"stage", "code", "reason", "http_status", "graph_code", "graph_subcode"}
        output.append(fields)
    return output


def safe_output(caplog, response, env, state):
    assert response.status_code == 303 and response.headers["location"] == "/media-ops?meta=failed"
    assert response.headers["referrer-policy"] == "no-referrer" and "no-store" in response.headers["cache-control"]
    for secret in (CANARY, state, "SYNTHETIC-META-APP-SECRET", "SYNTHETIC-LONG-USER-TOKEN", "SYNTHETIC-SHORT-USER-TOKEN"):
        assert secret not in caplog.text and secret not in response.text and all(secret not in value for value in response.headers.values())
    assert provider._CALLBACK_DIAGNOSTICS.get() is None and provider.META_NETWORK_ACTIVE.get() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["code_exchange", "long_lived_exchange", "token_inspection", "identity_read", "permissions_read"])
async def test_valid_claim_is_committed_before_numeric_provider_failure_is_logged(meta_env, monkeypatch, caplog, stage):
    env = meta_env; before = await protected_snapshot(env)
    monkeypatch.setattr(provider, "MetaClient", env.meta_real_client)
    _, body, state = await start(env)
    async def handle(request):
        async with env.sessions() as db:
            claimed = await db.scalar(select(State).where(State.request_id == body["request_id"]))
            assert claimed.consumed is True and claimed.flow_encrypted == ""
        path = request.url.path
        current = ("long_lived_exchange" if request.url.params.get("grant_type") else "code_exchange") if path.endswith("/oauth/access_token") else "token_inspection" if path.endswith("/debug_token") else "permissions_read" if path.endswith("/me/permissions") else "identity_read"
        if current == stage:
            return httpx.Response(400, json={"error": {"message": CANARY + str(request.url), "code": 190,
                "error_subcode": 460, "type": CANARY, "access_token": CANARY, "headers": {"Authorization": CANARY}}})
        return httpx.Response(200, json=valid_reply(request))
    transport(monkeypatch, handle); caplog.set_level(logging.WARNING, logger=LOGGER)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    safe_output(caplog, response, env, state)
    assert events(caplog) == [{"stage": stage, "code": "provider_unavailable", "http_status": 400, "graph_code": 190, "graph_subcode": 460}]
    assert await protected_snapshot(env) == before
    # A replay never reaches the exchange or creates another diagnostic event.
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    assert response.headers["location"].endswith("failed") and len(events(caplog)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["anonymous", "missing_cookie", "expired", "owner_disabled"])
async def test_preclaim_rejections_never_emit_callback_provider_diagnostics(meta_env, monkeypatch, caplog, attack):
    env = meta_env; monkeypatch.setattr(provider, "MetaClient", env.meta_real_client)
    _, body, state = await start(env)
    if attack == "anonymous": state = CANARY; env.meta_client.cookies.clear()
    elif attack == "missing_cookie": env.meta_client.cookies.clear()
    else:
        async with env.sessions() as db:
            row = await db.scalar(select(State).where(State.request_id == body["request_id"]))
            if attack == "expired": row.expires_at = service.now() - timedelta(seconds=1)
            else:
                owner = await db.get(service.Employees, 1); owner.status = "inactive"
            await db.commit()
    transport(monkeypatch, lambda request: pytest.fail("Preclaim rejection must not contact Meta"))
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    safe_output(caplog, response, env, state); assert events(caplog) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,stage,reason", [
    ("short_shape", "short_token_validation", None), ("long_shape", "long_token_validation", None),
    ("inspection", "inspection_validation", None), ("identity", "grants_validation", None),
    ("extra", "scope_validation", "unexpected_scope"), ("missing", "scope_validation", "missing_read"),
    ("both", "scope_validation", "missing_read_and_unexpected_scope"),
    ("scope_shape", "scope_validation", "invalid_scope_shape"), ("expiry", "expiry_validation", None)])
async def test_validation_stages_have_no_stale_http_details_or_scope_names(meta_env, monkeypatch, caplog, mutation, stage, reason):
    env = meta_env; monkeypatch.setattr(provider, "MetaClient", env.meta_real_client); _, _, state = await start(env)
    def handle(request):
        value = valid_reply(request); path = request.url.path
        if path.endswith("/oauth/access_token"):
            long = request.url.params.get("grant_type") == "fb_exchange_token"
            if mutation == ("long_shape" if long else "short_shape"): value.pop("expires_in")
        if path.endswith("/debug_token"):
            if mutation == "inspection": value["data"]["type"] = "SYSTEM_USER"
            if mutation in {"extra", "both"}: value["data"]["scopes"].append("pages_manage_posts")
            if mutation in {"missing", "both"}: value["data"]["scopes"].remove("instagram_basic")
            if mutation == "scope_shape": value["data"]["scopes"] = CANARY
            if mutation == "expiry": value["data"]["expires_at"] = 0
        if path.endswith("/me") and mutation == "identity": value["id"] = "999"
        return httpx.Response(200, json=value)
    transport(monkeypatch, handle); caplog.set_level(logging.WARNING, logger=LOGGER)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    safe_output(caplog, response, env, state)
    result = events(caplog); assert len(result) == 1 and result[0]["stage"] == stage
    assert result[0].get("reason") == reason and not set(result[0]) & {"http_status", "graph_code", "graph_subcode"}
    assert "pages_manage_posts" not in caplog.text and "instagram_basic" not in caplog.text


@pytest.mark.asyncio
async def test_success_and_asset_failures_do_not_emit_callback_diagnostics(meta_env, monkeypatch, caplog):
    env = meta_env; monkeypatch.setattr(provider, "MetaClient", env.meta_real_client); _, _, state = await start(env)
    def handle(request):
        return httpx.Response(400, json={"error": {"code": 190, "message": CANARY}}) if request.url.path.endswith("/me/accounts") else httpx.Response(200, json=valid_reply(request))
    transport(monkeypatch, handle)
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    assert response.headers["location"].endswith("connected") and events(caplog) == []
    assert provider._CALLBACK_DIAGNOSTICS.get() is None
    response = await env.meta_client.get(PREFIX + "/connections/1/assets")
    assert response.status_code == 503 and events(caplog) == [] and CANARY not in caplog.text


@pytest.mark.asyncio
async def test_transport_exception_context_never_reaches_callback_log(meta_env, monkeypatch, caplog):
    env = meta_env; monkeypatch.setattr(provider, "MetaClient", env.meta_real_client); _, _, state = await start(env)
    def handle(request):
        raise httpx.ConnectError(CANARY + str(request.url), request=request)
    transport(monkeypatch, handle); caplog.set_level(logging.WARNING, logger=LOGGER)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": CANARY})
    safe_output(caplog, response, env, state)
    assert events(caplog) == [{"stage": "code_exchange", "code": "provider_unavailable"}]
    rendered = "\n".join(logging.Formatter().format(record) for record in caplog.records if record.name == LOGGER)
    assert "Traceback" not in rendered and CANARY not in rendered and "graph.facebook.com" not in rendered


@pytest.mark.parametrize("status,code,subcode", [(True, True, False), (99, -1, 2147483648), (600, CANARY, CANARY), (400, 190, 460)])
def test_callback_metadata_only_accepts_bounded_integer_fields(status, code, subcode):
    assert provider._CALLBACK_DIAGNOSTICS.get() is None
    with provider.callback_diagnostics():
        provider._callback_stage("code_exchange", claimed=True)
        provider._callback_response_failure(status, {"error": {"code": code, "error_subcode": subcode, "message": CANARY}})
        result = provider.callback_failure_fields(provider.ProviderError(CANARY))
        assert result["code"] == "provider_unavailable" and CANARY not in json.dumps(result)
        assert result == ({"stage": "code_exchange", "code": "provider_unavailable", "http_status": 400, "graph_code": 190, "graph_subcode": 460}
                          if status == 400 else {"stage": "code_exchange", "code": "provider_unavailable"})
        provider._callback_stage("scope_validation")
        assert not set(provider.callback_failure_fields(provider.ProviderError("access_denied"))) & {"http_status", "graph_code", "graph_subcode"}
    assert provider._CALLBACK_DIAGNOSTICS.get() is None


@pytest.mark.asyncio
async def test_concurrent_callback_contexts_reset_without_cross_request_fields(meta_env, monkeypatch, caplog):
    env = meta_env; gate = asyncio.Event(); arrived = 0
    async def callback(db, state, cookie, code):
        nonlocal arrived
        if code == "preclaim": raise provider.ProviderError(CANARY)
        provider._callback_stage("code_exchange", claimed=True)
        provider._callback_response_failure(400, {"error": {"code": 190 if code == "first" else 191}})
        arrived += 1
        if arrived == 2: gate.set()
        await gate.wait()
        raise provider.ProviderError("provider_unavailable")
    monkeypatch.setattr(service, "oauth_callback", callback); caplog.set_level(logging.WARNING, logger=LOGGER)
    responses = await asyncio.gather(*(env.meta_client.get(PREFIX + "/oauth/callback", params={"state": CANARY, "code": code}) for code in ("first", "second")))
    assert all(r.headers["location"].endswith("failed") for r in responses)
    assert sorted(x["graph_code"] for x in events(caplog)) == [190, 191]
    await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": CANARY, "code": "preclaim"})
    assert len(events(caplog)) == 2 and CANARY not in caplog.text and provider._CALLBACK_DIAGNOSTICS.get() is None


def test_callback_context_resets_even_for_cancellation():
    with pytest.raises(asyncio.CancelledError):
        with provider.callback_diagnostics():
            provider._callback_stage("code_exchange", claimed=True)
            raise asyncio.CancelledError()
    assert provider._CALLBACK_DIAGNOSTICS.get() is None

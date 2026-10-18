"""Dedicated restricted-reader transport and credential boundaries; synthetic only."""
import os

import httpx
import pytest
from fastapi import HTTPException

from backend.tests.test_stripe_history_reconciliation import remote_invoice, remote_subscription
from services import stripe_history_provider as provider
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID

KEY = "rk_live_SYNTHETIC_ONLY_NEVER_REAL_1234567890"


def test_only_protected_dedicated_restricted_live_key_file(tmp_path, monkeypatch):
    path = tmp_path / "crm-readonly-key"
    path.write_text(KEY)
    path.chmod(0o600)
    monkeypatch.setattr(provider, "SECRET_FILE", str(path))
    assert provider.read_secret() == KEY
    path.chmod(0o644)
    assert provider.read_secret() is None
    path.chmod(0o600)
    path.write_text("sk_live_NOT_A_RESTRICTED_KEY_1234567890")
    assert provider.read_secret() is None
    path.write_text(KEY)
    link = tmp_path / "link"
    link.symlink_to(path)
    monkeypatch.setattr(provider, "SECRET_FILE", str(link))
    assert provider.read_secret() is None
    monkeypatch.setattr(provider, "SECRET_FILE", str(path))
    hard = tmp_path / "hardlink"
    os.link(path, hard)
    assert provider.read_secret() is None
    monkeypatch.setattr(provider, "SECRET_FILE", "relative-key")
    assert provider.read_secret() is None


@pytest.mark.asyncio
async def test_fixed_account_api_version_get_only_no_private_credentials():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.stripe.com"
        assert request.headers["stripe-version"] == "2025-02-24.acacia"
        assert request.headers["stripe-account"] == STRIPE_ACCOUNT_ID
        if request.url.path == "/v1/balance":
            return httpx.Response(200, json={"object": "balance", "livemode": True})
        if request.url.path == "/v1/subscriptions/sub_history100":
            return httpx.Response(200, json=remote_subscription())
        if request.url.path == "/v1/invoices/in_history100":
            return httpx.Response(200, json=remote_invoice())
        raise AssertionError("Unexpected endpoint")
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    assert (await reader.subscription("sub_history100"))["id"] == "sub_history100"
    assert (await reader.invoice("in_history100"))["id"] == "in_history100"
    assert [request.url.path for request in calls] == ["/v1/balance", "/v1/subscriptions/sub_history100", "/v1/invoices/in_history100"]
    # Target-context capability proof is reused only in this reader instance.
    assert str(provider.SECRET_FILE) == "/run/secrets/t24_crm_stripe_history_readonly"


@pytest.mark.parametrize("case", ["wrong_object", "balance_testmode", "balance_missing_mode", "denied", "redirect", "oversize", "invalid", "testmode", "wrong_subscription"])
@pytest.mark.asyncio
async def test_provider_fail_closed_without_raw_response_or_secret_exposure(case):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        assert request.headers["stripe-account"] == STRIPE_ACCOUNT_ID
        if case == "wrong_object":
            return httpx.Response(200, json={"id": "acct_wrong"})
        if case == "balance_testmode":
            return httpx.Response(200, json={"object": "balance", "livemode": False})
        if case == "balance_missing_mode":
            return httpx.Response(200, json={"object": "balance"})
        if case == "denied":
            return httpx.Response(403, text="SENSITIVE_RESPONSE_BODY")
        if case == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.example/path"})
        if case == "oversize":
            return httpx.Response(200, content=b"x" * (provider.MAX_RESPONSE_BYTES + 1))
        if case == "invalid":
            return httpx.Response(200, content=b"[]")
        if request.url.path == "/v1/balance":
            return httpx.Response(200, json={"object": "balance", "livemode": True})
        if case == "wrong_subscription":
            return httpx.Response(200, json={**remote_subscription(), "id": "sub_wrong"})
        return httpx.Response(200, json={**remote_subscription(), "livemode": False})
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(HTTPException) as caught:
        await reader.subscription("sub_history100")
    assert caught.value.status_code == 503
    assert "SENSITIVE_RESPONSE_BODY" not in str(caught.value.detail) and KEY not in str(caught.value.detail)
    assert len(calls) == (2 if case in {"testmode", "wrong_subscription"} else 1)
    assert calls[0] == "/v1/balance" and "/v1/account" not in calls


@pytest.mark.asyncio
async def test_pagination_bounded_and_external_paths_cannot_be_supplied():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["stripe-account"] == STRIPE_ACCOUNT_ID
        if request.url.path == "/v1/balance":
            return httpx.Response(200, json={"object": "balance", "livemode": True})
        assert request.url.params["limit"] == "10"
        assert request.url.params["customer"] == "cus_history100"
        return httpx.Response(200, json={"object": "list", "data": [remote_subscription()] * 11, "has_more": True})
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(HTTPException):
        await reader.subscriptions("cus_history100")
    with pytest.raises(HTTPException):
        await reader._get("/v1/../private")
    with pytest.raises(HTTPException):
        await reader._get("/v1/account")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unrelated_context_cannot_override_fixed_target_and_denial_never_falls_back():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["stripe-account"] == STRIPE_ACCOUNT_ID
        assert request.url.path == "/v1/balance"
        # Stripe rejects an inaccessible target context. Never retry without
        # the header, under a different target or via /v1/account.
        return httpx.Response(403, text="SENSITIVE_CONTEXT_DENIAL")
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(HTTPException) as caught:
        await reader.subscriptions(customer_id="cus_other_account")
    assert len(calls) == 1 and caught.value.status_code == 503
    assert "SENSITIVE_CONTEXT_DENIAL" not in str(caught.value.detail)

"""Dedicated CRM restricted-key reader. No private credentials or provider writes."""
import json
import os
import re
import stat

import httpx
from fastapi import HTTPException
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID

SECRET_FILE = "/run/secrets/t24_crm_stripe_history_readonly"
API_VERSION = "2025-02-24.acacia"
MAX_RESPONSE_BYTES = 2097152
PAGE_LIMIT = 10


def read_secret():
    try:
        if not os.path.isabs(SECRET_FILE):
            return None
        fd = os.open(SECRET_FILE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()} or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 4096:
                return None
            value = os.read(fd, 4097).decode("ascii").strip()
        finally:
            os.close(fd)
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r"rk_live_[A-Za-z0-9_]{12,250}", value) else None


def unavailable(code="stripe_read_unavailable"):
    raise HTTPException(503, {"code": code, "message": "Stripe 专用只读连接尚未就绪或读取失败，请检查接入；不会猜测数据或记账"})


class StripeHistoryReader:
    def __init__(self, secret=None, *, transport=None):
        self._secret = read_secret() if secret is None else secret
        self._transport = transport
        self._context_validated = False

    async def _get(self, path, parameters=None):
        if not self._secret:
            unavailable("stripe_read_not_configured")
        if not re.fullmatch(r"/v1/(?:balance|subscriptions(?:/sub_[A-Za-z0-9_]{1,220})?|invoices(?:/in_[A-Za-z0-9_]{1,220})?)", path):
            unavailable("stripe_resource_not_allowed")
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
                async with client.stream("GET", "https://api.stripe.com" + path,
                        headers={"Authorization": "Bearer " + self._secret, "Stripe-Version": API_VERSION,
                            "Stripe-Account": STRIPE_ACCOUNT_ID}, params=parameters or {}) as response:
                    if response.status_code != 200:
                        unavailable("stripe_read_access_denied" if response.status_code in {401, 403} else "stripe_read_unavailable")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > MAX_RESPONSE_BYTES:
                            unavailable("stripe_response_too_large")
                    result = json.loads(body)
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, UnicodeError):
            unavailable()
        if not isinstance(result, dict):
            unavailable("stripe_response_invalid")
        return result

    async def account_context(self):
        # Every request names the fixed target account. A live balance response
        # proves this restricted key may read that context; it does not claim
        # an independent read of the key owner's account identity.
        if not self._context_validated:
            balance = await self._get("/v1/balance")
            if balance.get("object") != "balance" or balance.get("livemode") is not True:
                unavailable("stripe_account_context_unverified")
            self._context_validated = True
        return STRIPE_ACCOUNT_ID

    async def subscription(self, subscription_id):
        await self.account_context()
        value = await self._get("/v1/subscriptions/" + subscription_id, {"expand[]": "customer"})
        if value.get("id") != subscription_id or value.get("livemode") is not True:
            unavailable("stripe_subscription_invalid")
        return value

    async def subscriptions(self, customer_id=None, starting_after=None):
        await self.account_context()
        parameters = {"limit": PAGE_LIMIT, "status": "all", "expand[]": "data.customer"}
        if customer_id:
            parameters["customer"] = customer_id
        if starting_after:
            parameters["starting_after"] = starting_after
        return self._page(await self._get("/v1/subscriptions", parameters))

    async def invoices(self, subscription_id, date_start, date_end, starting_after=None):
        await self.account_context()
        parameters = {"limit": PAGE_LIMIT, "subscription": subscription_id,
            "created[gte]": date_start, "created[lt]": date_end, "expand[]": "data.payment_intent.latest_charge.balance_transaction"}
        if starting_after:
            parameters["starting_after"] = starting_after
        return self._page(await self._get("/v1/invoices", parameters))

    async def invoice(self, invoice_id):
        await self.account_context()
        value = await self._get("/v1/invoices/" + invoice_id, {"expand[]": "payment_intent.latest_charge.balance_transaction"})
        if value.get("id") != invoice_id or value.get("livemode") is not True:
            unavailable("stripe_invoice_invalid")
        return value

    @staticmethod
    def _page(value):
        rows = value.get("data")
        if value.get("object") != "list" or not isinstance(rows, list) or len(rows) > PAGE_LIMIT or type(value.get("has_more")) is not bool:
            unavailable("stripe_page_invalid")
        if not all(isinstance(row, dict) and row.get("livemode") is True for row in rows):
            unavailable("stripe_live_data_required")
        return rows, value["has_more"]


def reader():
    return StripeHistoryReader()

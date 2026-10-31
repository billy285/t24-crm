"""Bounded Meta-only connection transport. No publishing, comments or password login.

Business Login config_id/code flow follows the official Business Login manual
flow. Asset discovery follows Meta's verified Instagram Postman collection.
Graph version and the reviewed user-token configuration are explicit settings.
"""
import hashlib
from contextvars import ContextVar
import json
import logging
import math
import os
import re
import time
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

CALLBACK_PATH = "/api/v1/meta-business/oauth/callback"
CALLBACK = "https://t24-crm.com" + CALLBACK_PATH
READ_SCOPES = frozenset({"pages_show_list", "pages_read_engagement", "instagram_basic"})
ID = re.compile(r"[0-9]{1,80}\Z")
META_NETWORK_ACTIVE = ContextVar("t24_meta_network_active", default=False)


class ProviderError(Exception):
    def __init__(self, code="provider_unavailable"):
        self.code = code
        super().__init__(code)


class MetaNetworkLogFilter(logging.Filter):
    """OAuth's documented GET exchange must not expose code/app secret in logs."""
    def filter(self, record):
        # Suppress Meta transport tracing even if an operator enables DEBUG;
        # httpcore may describe raw request headers. Other tasks are unaffected.
        if META_NETWORK_ACTIVE.get(): return False
        # Render before stripping query text: stripping a format placeholder
        # from record.msg while retaining args would make logging print args.
        try: message = record.getMessage()
        except (TypeError, ValueError):
            if "graph.facebook.com" in str(record.msg) or "graph.facebook.com" in str(record.args):
                record.msg = "Meta transport message omitted"; record.args = ()
            return True
        if "https://graph.facebook.com/" in message:
            record.msg = re.sub(r"https://graph[.]facebook[.]com/[^\s\"']+", lambda match: match.group(0).partition("?")[0], message)
            record.args = ()
        return True


for logger_name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    if not any(isinstance(item, MetaNetworkLogFilter) for item in logging.getLogger(logger_name).filters):
        logging.getLogger(logger_name).addFilter(MetaNetworkLogFilter())


def enabled(): return os.getenv("T24_META_ENABLED", "false").strip().lower() == "true"


def settings():
    names = ("APP_ID", "APP_SECRET", "TOKEN_KEY", "CONFIG_ID", "GRAPH_VERSION", "PUBLIC_URL", "EXPECTED_SCOPES")
    values = {key: os.getenv("T24_META_" + key, "").strip() for key in names}
    missing = []
    if not enabled(): missing.append("T24_META_ENABLED")
    if not ID.fullmatch(values["APP_ID"]): missing.append("T24_META_APP_ID")
    if not ID.fullmatch(values["CONFIG_ID"]): missing.append("T24_META_CONFIG_ID")
    if len(values["APP_SECRET"]) < 16 or any(c.isspace() for c in values["APP_SECRET"]): missing.append("T24_META_APP_SECRET")
    if not re.fullmatch(r"v[1-9][0-9]{0,2}[.][0-9]{1,2}", values["GRAPH_VERSION"]): missing.append("T24_META_GRAPH_VERSION")
    try: Fernet(values["TOKEN_KEY"].encode())
    except (ValueError, TypeError): missing.append("T24_META_TOKEN_KEY")
    if values["TOKEN_KEY"] and any(values["TOKEN_KEY"] == os.getenv(key, "").strip() for key in ("T24_GBP_TOKEN_KEY", "PRIVATE_WORKSPACE_ENCRYPTION_KEY", "MASK_KEY")):
        missing.append("T24_META_INDEPENDENT_TOKEN_KEY")
    values["PUBLIC_URL"] = values["PUBLIC_URL"].rstrip("/")
    if values["PUBLIC_URL"] != "https://t24-crm.com": missing.append("T24_META_PUBLIC_URL")
    scopes = values["EXPECTED_SCOPES"].split(",")
    if len(scopes) != len(set(scopes)) or set(scopes) != READ_SCOPES: missing.append("T24_META_EXPECTED_SCOPES")
    values["SCOPES"] = sorted(READ_SCOPES)
    # The config must have been checked as a user-access-token Business Login
    # configuration. System-user configs have a different response contract.
    if os.getenv("T24_META_LOGIN_CONFIG_REVIEWED", "false").strip().lower() != "true": missing.append("T24_META_LOGIN_CONFIG_REVIEWED")
    return values, sorted(set(missing))


def require_config():
    values, missing = settings()
    if missing: raise HTTPException(503, "Meta 连接尚未完成独立应用、版本和只读授权配置")
    return values


def authorization_description(values):
    return {"provider": "Meta", "flow": "Facebook Login for Business", "client_id": values["APP_ID"],
            "config_id": values["CONFIG_ID"], "graph_version": values["GRAPH_VERSION"], "token_type": "user",
            "requested_scopes": values["SCOPES"], "redirect_uri": CALLBACK,
            "asset_types": ["Facebook Page", "关联的Instagram专业账号"],
            "token_storage": "CRM 服务器使用独立密钥加密保存，仅老板管理连接",
            "purpose": "读取授权 Facebook 主页及关联 Instagram 专业账号并绑定客户；本阶段不发布或回复"}


def configuration_fingerprint():
    values = require_config()
    return hashlib.sha256(json.dumps({key: values[key] for key in ("APP_ID", "CONFIG_ID", "GRAPH_VERSION", "PUBLIC_URL", "SCOPES")}, sort_keys=True).encode()).hexdigest()


def encrypt(value):
    return Fernet(require_config()["TOKEN_KEY"].encode()).encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


def decrypt(value):
    try:
        result = json.loads(Fernet(require_config()["TOKEN_KEY"].encode()).decrypt((value or "").encode()))
        if not isinstance(result, dict): raise ValueError()
        return result
    except (InvalidToken, ValueError, TypeError, UnicodeError): raise ProviderError("reconnect_required") from None


def authorize_url(state):
    values = require_config()
    if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", state): raise ProviderError("invalid_response")
    return "https://www.facebook.com/" + values["GRAPH_VERSION"] + "/dialog/oauth?" + urlencode({
        "client_id": values["APP_ID"], "redirect_uri": CALLBACK, "response_type": "code", "state": state, "config_id": values["CONFIG_ID"]})


def _text(value, fallback=""):
    if not isinstance(value, str): return fallback
    return "".join(c for c in value if ord(c) >= 32 and ord(c) != 127)[:255] or fallback


def _error(response, result):
    if response.status_code == 401: return ProviderError("reconnect_required")
    if response.status_code == 403: return ProviderError("access_denied")
    if response.status_code == 429: return ProviderError("quota_limited")
    return ProviderError("provider_unavailable")


class MetaClient:
    def __init__(self, token_encrypted=None):
        self.token_encrypted = token_encrypted
        self.expected_configuration = None

    async def _raw(self, path, *, params=None, token=None):
        values = require_config()
        if self.expected_configuration is not None and configuration_fingerprint() != self.expected_configuration:
            raise ProviderError("reconnect_required")
        if path not in {"oauth/access_token", "me/accounts", "debug_token", "me/permissions", "me"}: raise ProviderError("invalid_response")
        url = "https://graph.facebook.com/" + values["GRAPH_VERSION"] + "/" + path
        try:
            marker = META_NETWORK_ACTIVE.set(True)
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False, trust_env=False) as client:
                    async with client.stream("GET", url, params=params, headers={"Authorization": "Bearer " + token} if token else {}) as response:
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > 2_000_000: raise ProviderError("invalid_response")
            finally: META_NETWORK_ACTIVE.reset(marker)
            try: data = json.loads(body)
            except (ValueError, UnicodeError, RecursionError): raise ProviderError("invalid_response") from None
            if not isinstance(data, dict): raise ProviderError("invalid_response")
            if not 200 <= response.status_code < 300 or "error" in data: raise _error(response, data)
            return data
        except httpx.RequestError: raise ProviderError("provider_unavailable") from None

    async def exchange(self, code):
        values = require_config()
        self.expected_configuration = configuration_fingerprint()
        short = await self._raw("oauth/access_token", params={"client_id": values["APP_ID"], "client_secret": values["APP_SECRET"], "redirect_uri": CALLBACK, "code": code})
        short_token, _ = self._tokens(short)
        long = await self._raw("oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": values["APP_ID"],
            "client_secret": values["APP_SECRET"], "fb_exchange_token": short_token})
        token, expiry = self._tokens(long)
        # The documented app-admin token may inspect a token from the same app.
        debug = await self._raw("debug_token", params={"input_token": token}, token=values["APP_ID"] + "|" + values["APP_SECRET"])
        details = debug.get("data")
        if not isinstance(details, dict) or details.get("is_valid") is not True or details.get("app_id") != values["APP_ID"] or details.get("type") != "USER":
            raise ProviderError("access_denied")
        identity = details.get("user_id")
        if not isinstance(identity, str) or not ID.fullmatch(identity): raise ProviderError("invalid_response")
        me = await self._raw("me", params={"fields": "id"}, token=token)
        permissions = await self._raw("me/permissions", token=token)
        entries = permissions.get("data")
        if me.get("id") != identity or not isinstance(entries, list) or len(entries) > 100: raise ProviderError("access_denied")
        if not all(isinstance(x, dict) and isinstance(x.get("permission"), str) and re.fullmatch(r"[a-z_]{1,100}", x["permission"]) and x.get("status") in {"granted", "declined", "expired"} for x in entries):
            raise ProviderError("invalid_response")
        if len({x["permission"] for x in entries}) != len(entries): raise ProviderError("invalid_response")
        granted = {x["permission"] for x in entries if x["status"] == "granted"}
        inspected_scopes = details.get("scopes")
        allowed = READ_SCOPES | {"public_profile"}
        if (not isinstance(inspected_scopes, list) or len(inspected_scopes) > 100 or not all(isinstance(x, str) for x in inspected_scopes)
                or not READ_SCOPES <= set(inspected_scopes) or not READ_SCOPES <= granted
                or not set(inspected_scopes) <= allowed or not granted <= allowed):
            raise ProviderError("access_denied")
        expires = details.get("expires_at")
        if type(expires) is not int or expires <= time.time() + 30: raise ProviderError("reconnect_required")
        expiry = min(time.time() + expiry, expires)
        data_expiry = details.get("data_access_expires_at")
        if type(data_expiry) is int and data_expiry > 0: expiry = min(expiry, data_expiry)
        if expiry <= time.time() + 30: raise ProviderError("reconnect_required")
        if configuration_fingerprint() != self.expected_configuration: raise ProviderError("reconnect_required")
        return {"access_token": token, "expires_at": expiry, "user_id": identity,
                "granted_read_scopes": sorted(READ_SCOPES), "observed_scopes": sorted(granted), "configuration": self.expected_configuration}

    @staticmethod
    def _tokens(result):
        token, expiry = result.get("access_token"), result.get("expires_in")
        if not isinstance(token, str) or not 10 <= len(token) <= 16384 or any(c.isspace() for c in token): raise ProviderError("invalid_response")
        token_type = result.get("token_type", "bearer")
        if not isinstance(token_type, str) or token_type.lower() != "bearer": raise ProviderError("invalid_response")
        if type(expiry) is not int or not 1 <= expiry <= 366 * 86400: raise ProviderError("invalid_response")
        return token, expiry

    async def assets(self):
        token = decrypt(self.token_encrypted)
        if token.get("configuration") != configuration_fingerprint() or type(token.get("expires_at")) not in {int, float} or not math.isfinite(token["expires_at"]) or token["expires_at"] <= time.time() + 30:
            raise ProviderError("reconnect_required")
        self.expected_configuration = token["configuration"]
        access = token.get("access_token")
        if not isinstance(access, str) or not 10 <= len(access) <= 16384 or any(c.isspace() for c in access): raise ProviderError("reconnect_required")
        output, seen, cursor = [], set(), None
        for _ in range(5):
            params = {"fields": "name,tasks,instagram_business_account", "limit": 100}
            if cursor: params["after"] = cursor
            data = await self._raw("me/accounts", params=params, token=access)
            if not isinstance(data.get("data"), list) or len(data["data"]) > 100: raise ProviderError("invalid_response")
            for page in data["data"]:
                if not isinstance(page, dict) or not isinstance(page.get("id"), str) or not ID.fullmatch(page["id"]): raise ProviderError("invalid_response")
                page_id = page["id"]; name = _text(page.get("name"), "Facebook 主页")
                tasks = page.get("tasks") or []
                if not isinstance(tasks, list) or len(tasks) > 50: raise ProviderError("invalid_response")
                observations = ["Meta 返回 Page 任务：" + item for item in tasks if isinstance(item, str) and re.fullmatch(r"[A-Z_]{1,50}", item)]
                items = [{"platform": "facebook", "external_id": page_id, "page_id": page_id, "name": name, "observations": observations}]
                instagram = page.get("instagram_business_account")
                if instagram is not None:
                    if not isinstance(instagram, dict) or not isinstance(instagram.get("id"), str) or not ID.fullmatch(instagram["id"]): raise ProviderError("invalid_response")
                    items.append({"platform": "instagram", "external_id": instagram["id"], "page_id": page_id,
                                  "name": (name + " · Instagram")[:255], "linked_page_name": name,
                                  "observations": ["Meta 返回此主页关联的 Instagram 专业账号"]})
                for item in items:
                    identity = (item["platform"], item["external_id"])
                    if identity in seen: raise ProviderError("invalid_response")
                    seen.add(identity); output.append(item)
            paging = data.get("paging") or {}
            if not isinstance(paging, dict): raise ProviderError("invalid_response")
            if not paging.get("next"): return {"items": output, "truncated": False}
            cursors = paging.get("cursors") or {}; next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 2048 or next_cursor == cursor: raise ProviderError("invalid_response")
            cursor = next_cursor
        return {"items": output, "truncated": True}

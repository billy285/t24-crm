"""Owner-only Meta operations adapter, isolated from the existing read grant.

No commits, background execution or retry of a mutation live here. The service
must durably claim an approved action before dispatch; Instagram container
creation and publication deliberately require separate durable service steps.
Page tokens are discovered for the selected binding and remain in memory only.
"""
import hashlib
import hmac
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from services import meta_business_provider as legacy

READ_ONLY_APP_IDS = frozenset({"1139445441758834", "1625116099132983"})
PILOT_CUSTOMER_ID = 38
CALLBACK_PATH = "/api/v1/meta-operations/oauth/callback"
CALLBACK = "https://t24-crm.com" + CALLBACK_PATH
SCOPES = frozenset({"pages_show_list", "pages_read_engagement", "instagram_basic", "pages_manage_posts",
                    "pages_read_user_content", "pages_manage_engagement", "instagram_content_publish", "instagram_manage_comments"})
ID = re.compile(r"[0-9]{1,80}\Z")
OBJECT_ID = re.compile(r"[0-9]{1,80}(?:_[0-9]{1,80})?\Z")
DELIVERY_URL = re.compile(r"https://t24-crm[.]com/api/v1/meta-operations/delivery/[A-Za-z0-9_-]{43}[.]jpg\Z")
PUBLISH_TASKS = frozenset({"MANAGE", "CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL", "PROFILE_PLUS_MANAGE", "PROFILE_PLUS_CREATE_CONTENT"})
REPLY_TASKS = frozenset({"MANAGE", "MODERATE", "PROFILE_PLUS_FULL_CONTROL", "PROFILE_PLUS_MANAGE", "PROFILE_PLUS_MODERATE"})
ERROR_CODES = frozenset({"not_configured", "execution_disabled", "authorization_required", "reconnect_required", "access_denied",
                         "asset_not_authorized", "permission_missing", "quota_limited", "invalid_response", "provider_unavailable",
                         "unsupported_kind", "content_invalid", "media_not_ready", "target_changed"})


class OpsProviderError(Exception):
    def __init__(self, code="provider_unavailable", uncertain=False):
        self.code = code if code in ERROR_CODES else "provider_unavailable"
        self.uncertain = uncertain is True
        self.ambiguous = self.uncertain
        super().__init__(self.code)


def enabled(): return os.getenv("T24_META_OPS_ENABLED", "false").strip().lower() == "true"
def execution_enabled(): return os.getenv("T24_META_OPS_EXECUTION_ENABLED", "false").strip().lower() == "true"


def settings():
    names = ("APP_ID", "APP_SECRET", "TOKEN_KEY", "CONFIG_ID", "GRAPH_VERSION", "PUBLIC_URL", "EXPECTED_SCOPES")
    values = {name: os.getenv("T24_META_OPS_" + name, "").strip() for name in names}
    # The Publisher is a distinct Meta app. A grant in the original read-only
    # app could broaden that app's future OAuth scope union, so it is rejected.
    old, _ = legacy.settings()
    missing = []
    if not enabled(): missing.append("T24_META_OPS_ENABLED")
    if not re.fullmatch(r"[0-9]{10,25}", values["APP_ID"]) or values["APP_ID"] in READ_ONLY_APP_IDS | {old["APP_ID"]}: missing.append("T24_META_OPS_APP_ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", values["APP_SECRET"]) or (old["APP_SECRET"] and hmac.compare_digest(values["APP_SECRET"].encode(), old["APP_SECRET"].encode())):
        missing.append("T24_META_OPS_APP_SECRET")
    if not ID.fullmatch(values["CONFIG_ID"]) or values["CONFIG_ID"] in {old["CONFIG_ID"], "1786801695686024", "941072098875174"}:
        missing.append("T24_META_OPS_CONFIG_ID")
    if not re.fullmatch(r"v[1-9][0-9]{0,2}[.][0-9]{1,2}", values["GRAPH_VERSION"]): missing.append("T24_META_OPS_GRAPH_VERSION")
    if values["PUBLIC_URL"] != "https://t24-crm.com": missing.append("T24_META_OPS_PUBLIC_URL")
    try: Fernet(values["TOKEN_KEY"].encode())
    except (ValueError, TypeError): missing.append("T24_META_OPS_TOKEN_KEY")
    if values["TOKEN_KEY"] and any(values["TOKEN_KEY"] == os.getenv(name, "").strip() for name in
            ("T24_META_TOKEN_KEY", "T24_GBP_TOKEN_KEY", "PRIVATE_WORKSPACE_ENCRYPTION_KEY", "MASK_KEY")):
        missing.append("T24_META_OPS_INDEPENDENT_TOKEN_KEY")
    raw_scopes = values["EXPECTED_SCOPES"].split(",")
    if len(raw_scopes) != len(set(raw_scopes)) or set(raw_scopes) != SCOPES: missing.append("T24_META_OPS_EXPECTED_SCOPES")
    if os.getenv("T24_META_OPS_LOGIN_CONFIG_REVIEWED", "false").strip().lower() != "true": missing.append("T24_META_OPS_LOGIN_CONFIG_REVIEWED")
    values["SCOPES"] = sorted(SCOPES)
    return values, sorted(set(missing))


def require_config():
    values, missing = settings()
    if missing: raise OpsProviderError("not_configured")
    return values


def status():
    values, missing = settings()
    return {"enabled": enabled(), "configured": not missing, "execution_enabled": execution_enabled(), "setup_missing": missing,
            "authorization": authorization_description(values) if not missing else None}


def authorization_description(values):
    return {"provider": "Meta", "flow": "Facebook Login for Business", "client_id": values["APP_ID"],
            "config_id": values["CONFIG_ID"], "graph_version": values["GRAPH_VERSION"], "token_type": "user",
            "requested_scopes": values["SCOPES"], "redirect_uri": CALLBACK,
            "asset_types": ["Facebook Page", "关联的Instagram专业账号"],
            "token_storage": "独立 Meta 发布应用与运营凭据加密保存；原只读连接与员工权限保持不变",
            "purpose": "老板确认后发布内容、读取评论并回复；CRM 排期仅执行逐条确认的内容"}


def configuration_fingerprint():
    values = require_config()
    return hashlib.sha256(json.dumps({key: values[key] for key in ("APP_ID", "CONFIG_ID", "GRAPH_VERSION", "PUBLIC_URL", "SCOPES")}, sort_keys=True).encode()).hexdigest()


def encrypt(value):
    return Fernet(require_config()["TOKEN_KEY"].encode()).encrypt(json.dumps(value, separators=(",", ":"), allow_nan=False).encode()).decode()


def decrypt(value):
    try:
        result = json.loads(Fernet(require_config()["TOKEN_KEY"].encode()).decrypt((value or "").encode()))
        if not isinstance(result, dict): raise ValueError()
        return result
    except (InvalidToken, ValueError, TypeError, UnicodeError): raise OpsProviderError("reconnect_required") from None


def authorize_url(state):
    values = require_config()
    if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", state): raise OpsProviderError("invalid_response")
    return "https://www.facebook.com/" + values["GRAPH_VERSION"] + "/dialog/oauth?" + urlencode({
        "client_id": values["APP_ID"], "config_id": values["CONFIG_ID"], "redirect_uri": CALLBACK, "response_type": "code", "state": state})


def _id(value, *, compound=False):
    if not isinstance(value, str) or not (OBJECT_ID if compound else ID).fullmatch(value): raise OpsProviderError("invalid_response")
    return value


def _cursor(value):
    if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise OpsProviderError("invalid_response")
    return value


def _text(value, maximum=20000):
    if value is None: return ""
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in "\n\r\t" for c in value): raise OpsProviderError("invalid_response")
    return value


def _content(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise OpsProviderError("content_invalid")
    return value


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100: return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError: return None


def _permalink(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 33 for c in value): return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in {"facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com"} or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.fragment:
            return None
        if any(re.search(r"token|secret|code|state", key, re.I) for key in parse_qs(parsed.query)): return None
        return value
    except ValueError: return None


class OpsClient:
    def __init__(self, token_encrypted=None):
        self.token_encrypted = token_encrypted
        self.expected_configuration = configuration_fingerprint()

    async def request(self, method, path, *, params=None, data=None, token=None, mutation=False):
        values = require_config()
        if configuration_fingerprint() != self.expected_configuration: raise OpsProviderError("reconnect_required")
        fixed = {"oauth/access_token", "debug_token", "me", "me/permissions", "me/accounts"}
        if not isinstance(path, str): raise OpsProviderError("invalid_response")
        edge = re.fullmatch(r"([0-9]{1,80}(?:_[0-9]{1,80})?)(?:/(published_posts|media|comments|replies|content_publishing_limit|feed|photos|media_publish))?", path)
        if method not in {"GET", "POST"} or not (method == "GET" and path in fixed or edge): raise OpsProviderError("invalid_response")
        if method == "POST" and (not edge or edge.group(2) not in {"feed", "photos", "media", "media_publish", "comments", "replies"} or not mutation):
            raise OpsProviderError("invalid_response")
        if not isinstance(token, str) or not 10 <= len(token) <= 16384 or any(c.isspace() for c in token): raise OpsProviderError("reconnect_required")
        marker = legacy.META_NETWORK_ACTIVE.set(True)
        try:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False, trust_env=False) as client:
                    async with client.stream(method, "https://graph.facebook.com/" + values["GRAPH_VERSION"] + "/" + path,
                                             params=params, data=data, headers={"Authorization": "Bearer " + token}) as response:
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > 2_000_000: raise OpsProviderError("invalid_response", uncertain=mutation)
                try: result = json.loads(body)
                except (ValueError, UnicodeError, RecursionError): raise OpsProviderError("invalid_response", uncertain=mutation) from None
                if not isinstance(result, dict): raise OpsProviderError("invalid_response", uncertain=mutation)
                if not 200 <= response.status_code < 300 or "error" in result:
                    code = "reconnect_required" if response.status_code == 401 else "access_denied" if response.status_code == 403 else "quota_limited" if response.status_code == 429 else "provider_unavailable"
                    error = result.get("error")
                    if isinstance(error, dict) and error.get("code") == 190: code = "reconnect_required"
                    definite_graph_rejection = isinstance(error, dict) and type(error.get("code")) is int and 0 < error["code"] <= 2147483647
                    raise OpsProviderError(code, uncertain=mutation and (response.status_code >= 500 or 300 <= response.status_code < 400 or not definite_graph_rejection))
                return result
            except httpx.RequestError: raise OpsProviderError("provider_unavailable", uncertain=mutation) from None
        finally: legacy.META_NETWORK_ACTIVE.reset(marker)

    @staticmethod
    def _tokens(result):
        token, expiry = result.get("access_token"), result.get("expires_in")
        if not isinstance(token, str) or not 10 <= len(token) <= 16384 or any(c.isspace() for c in token) or type(expiry) is not int or not 1 <= expiry <= 366 * 86400:
            raise OpsProviderError("invalid_response")
        if not isinstance(result.get("token_type", "bearer"), str) or result.get("token_type", "bearer").lower() != "bearer": raise OpsProviderError("invalid_response")
        return token, expiry

    async def exchange(self, code):
        if not isinstance(code, str) or not 1 <= len(code) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in code): raise OpsProviderError("invalid_response")
        values = require_config()
        app_token = values["APP_ID"] + "|" + values["APP_SECRET"]
        short = await self.request("GET", "oauth/access_token", params={"client_id": values["APP_ID"], "client_secret": values["APP_SECRET"], "redirect_uri": CALLBACK, "code": code}, token=app_token)
        short_token, _ = self._tokens(short)
        long = await self.request("GET", "oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": values["APP_ID"], "client_secret": values["APP_SECRET"], "fb_exchange_token": short_token}, token=app_token)
        token, lifetime = self._tokens(long)
        debug = await self.request("GET", "debug_token", params={"input_token": token}, token=app_token)
        details = debug.get("data")
        if not isinstance(details, dict) or details.get("is_valid") is not True or details.get("app_id") != values["APP_ID"] or details.get("type") != "USER": raise OpsProviderError("access_denied")
        identity = _id(details.get("user_id"))
        me = await self.request("GET", "me", params={"fields": "id"}, token=token)
        permissions = await self.request("GET", "me/permissions", token=token)
        entries = permissions.get("data")
        if me.get("id") != identity or not isinstance(entries, list) or len(entries) > 100 or not all(isinstance(x, dict) and isinstance(x.get("permission"), str) and re.fullmatch(r"[a-z_]{1,100}", x["permission"]) and x.get("status") in {"granted", "declined", "expired"} for x in entries): raise OpsProviderError("access_denied")
        if len({x["permission"] for x in entries}) != len(entries): raise OpsProviderError("invalid_response")
        observed = {x["permission"] for x in entries if x["status"] == "granted"}
        inspected = details.get("scopes")
        if not isinstance(inspected, list) or len(inspected) > 100 or not all(isinstance(x, str) for x in inspected) or len(inspected) != len(set(inspected)) or not SCOPES <= observed or not SCOPES <= set(inspected) or not observed <= SCOPES | {"public_profile"} or not set(inspected) <= SCOPES | {"public_profile"}:
            raise OpsProviderError("access_denied")
        expiry = details.get("expires_at")
        if type(expiry) is not int or expiry <= time.time() + 30: raise OpsProviderError("reconnect_required")
        expiry = min(time.time() + lifetime, expiry)
        data_expiry = details.get("data_access_expires_at")
        if type(data_expiry) is int and data_expiry > 0: expiry = min(expiry, data_expiry)
        if expiry <= time.time() + 30 or configuration_fingerprint() != self.expected_configuration: raise OpsProviderError("reconnect_required")
        return {"access_token": token, "expires_at": expiry, "user_id": identity, "observed_scopes": sorted(observed), "configuration": self.expected_configuration}

    def access(self):
        grant = decrypt(self.token_encrypted)
        expiry = grant.get("expires_at")
        scopes = grant.get("observed_scopes")
        if grant.get("configuration") != self.expected_configuration or type(expiry) not in {int, float} or not math.isfinite(expiry) or expiry <= time.time() + 30:
            raise OpsProviderError("reconnect_required")
        if not isinstance(scopes, list) or len(scopes) > 100 or not all(isinstance(x, str) for x in scopes) or len(scopes) != len(set(scopes)) or not SCOPES <= set(scopes) or not set(scopes) <= SCOPES | {"public_profile"}:
            raise OpsProviderError("permission_missing")
        token = grant.get("access_token")
        if not isinstance(token, str) or not 10 <= len(token) <= 16384 or any(c.isspace() for c in token): raise OpsProviderError("reconnect_required")
        return token, scopes

    async def page(self, binding):
        access, _ = self.access(); cursor = None; seen = set()
        for _ in range(5):
            params = {"fields": "id,name,tasks,access_token,instagram_business_account", "limit": 100}
            if cursor: params["after"] = cursor
            result = await self.request("GET", "me/accounts", params=params, token=access)
            rows = result.get("data")
            if not isinstance(rows, list) or len(rows) > 100: raise OpsProviderError("invalid_response")
            for page in rows:
                if not isinstance(page, dict): raise OpsProviderError("invalid_response")
                identity = _id(page.get("id"))
                if identity in seen: raise OpsProviderError("invalid_response")
                seen.add(identity)
                if identity != binding.page_id: continue
                page_token = page.get("access_token"); tasks = page.get("tasks")
                if not isinstance(page_token, str) or not 10 <= len(page_token) <= 16384 or any(c.isspace() for c in page_token) or not isinstance(tasks, list) or len(tasks) > 50 or not all(isinstance(x, str) and re.fullmatch(r"[A-Z_]{1,50}", x) for x in tasks):
                    raise OpsProviderError("invalid_response")
                if binding.platform == "facebook" and binding.external_id != identity: raise OpsProviderError("asset_not_authorized")
                if binding.platform == "instagram":
                    ig = page.get("instagram_business_account")
                    if not isinstance(ig, dict) or ig.get("id") != binding.external_id: raise OpsProviderError("asset_not_authorized")
                return {"token": page_token, "tasks": set(tasks)}
            paging = result.get("paging") or {}
            if not isinstance(paging, dict): raise OpsProviderError("invalid_response")
            if not paging.get("next"): break
            cursors = paging.get("cursors") or {}; next_cursor = _cursor(cursors.get("after") if isinstance(cursors, dict) else None)
            if not next_cursor or next_cursor == cursor: raise OpsProviderError("invalid_response")
            cursor = next_cursor
        raise OpsProviderError("asset_not_authorized")


async def exchange(code): return await OpsClient().exchange(code)


async def verify_assets(token_encrypted, frozen_targets):
    """Verify the exact two pilot identities under the independent Publisher.

    This returns no tokens and performs only GETs. The caller must reread its
    durable OAuth snapshot, owner, customer and own-binding revision after the
    HTTP work before saving a credential or authority row.
    """
    if not isinstance(frozen_targets, list) or not 1 <= len(frozen_targets) <= 2 or not all(isinstance(row, dict) for row in frozen_targets):
        raise OpsProviderError("asset_not_authorized")
    seen_ids, seen_platforms = set(), set(); client = OpsClient(token_encrypted); client.access(); output = []
    for row in frozen_targets:
        if (type(row.get("id")) is not int or row["id"] < 1 or row.get("source_binding_id", row["id"]) != row["id"] or
                type(row.get("owner_id")) is not int or row["owner_id"] < 1 or row.get("customer_id") != PILOT_CUSTOMER_ID or
                row.get("platform") not in {"facebook", "instagram"} or row["id"] in seen_ids or row["platform"] in seen_platforms):
            raise OpsProviderError("asset_not_authorized")
        _id(row.get("external_id")); _id(row.get("page_id"))
        page = await client.page(SimpleNamespace(**row))
        if not page["tasks"] & PUBLISH_TASKS or not page["tasks"] & REPLY_TASKS: raise OpsProviderError("permission_missing")
        seen_ids.add(row["id"]); seen_platforms.add(row["platform"]); output.append(dict(row))
    return output


async def _authorized(db, user, binding):
    # Import lazily so the existing read-only module never imports new tables.
    from models.meta_business import MetaBusinessBinding
    from models.meta_operations import MetaOperationsBinding, MetaOperationsCredential
    from services import meta_business
    keys = ("revision", "source_binding_id", "credential_id", "connection_id", "connection_revision", "platform", "external_id", "page_id", "customer_id", "owner_id")
    try: expected = {key: getattr(binding, key) for key in keys}
    except AttributeError: raise OpsProviderError("target_changed") from None
    if expected["customer_id"] != PILOT_CUSTOMER_ID: raise OpsProviderError("asset_not_authorized")
    if expected["platform"] not in {"facebook", "instagram"}: raise OpsProviderError("unsupported_kind")
    ctx = await meta_business.context(db, user)
    fresh = await db.scalar(select(MetaOperationsBinding).where(MetaOperationsBinding.id == binding.id, MetaOperationsBinding.owner_id == ctx.identity).execution_options(populate_existing=True))
    if not fresh or not fresh.active or any(getattr(fresh, key) != expected[key] for key in keys):
        raise OpsProviderError("target_changed")
    customer, _ = await meta_business.media._customer(db, ctx, fresh.customer_id)
    if customer.id != PILOT_CUSTOMER_ID or customer.status != "closed" or customer.business_name.strip().casefold() != "pokeco": raise OpsProviderError("asset_not_authorized")
    # Historical canonical identity must still refer to the same customer and
    # platform. Read-only token expiry, pause and connection revision are not
    # operational authority; the independent Publisher grant controls writes.
    historical = await db.scalar(select(MetaBusinessBinding).where(MetaBusinessBinding.id == fresh.source_binding_id).execution_options(populate_existing=True))
    canonical = ("owner_id", "customer_id", "platform", "external_id", "page_id", "connection_id")
    if not historical or fresh.source_binding_id != fresh.id or any(getattr(historical, key) != getattr(fresh, key) for key in canonical):
        raise OpsProviderError("target_changed")
    credential = await db.scalar(select(MetaOperationsCredential).where(MetaOperationsCredential.id == fresh.credential_id, MetaOperationsCredential.owner_id == ctx.identity,
        MetaOperationsCredential.connection_id == fresh.connection_id).execution_options(populate_existing=True))
    if not credential or not credential.active or credential.needs_reconnect or not credential.token_encrypted: raise OpsProviderError("authorization_required")
    if credential.revision != fresh.connection_revision: raise OpsProviderError("target_changed")
    client = OpsClient(credential.token_encrypted)
    _, scopes = client.access()
    if not isinstance(credential.granted_scopes, list) or len(credential.granted_scopes) > 100 or not all(isinstance(x, str) for x in credential.granted_scopes) or len(credential.granted_scopes) != len(set(credential.granted_scopes)) or set(credential.granted_scopes) != set(scopes):
        raise OpsProviderError("reconnect_required")
    return client, await client.page(fresh)


async def capabilities(db, user, binding):
    flags = {"can_publish": False, "can_reply": False, "can_read_posts": False, "can_read_comments": False, "blocked_reasons": []}
    try:
        require_config(); _, page = await _authorized(db, user, binding)
        flags.update(can_read_posts=True, can_read_comments=bool(page["tasks"] & REPLY_TASKS))
        if not execution_enabled(): flags["blocked_reasons"].append("execution_disabled")
        else: flags.update(can_publish=bool(page["tasks"] & PUBLISH_TASKS), can_reply=bool(page["tasks"] & REPLY_TASKS))
        if not page["tasks"] & PUBLISH_TASKS: flags["blocked_reasons"].append("permission_missing")
        if not page["tasks"] & REPLY_TASKS: flags["blocked_reasons"].append("permission_missing")
    except OpsProviderError as error: flags["blocked_reasons"].append(error.code)
    flags["blocked_reasons"] = sorted(set(flags["blocked_reasons"]))
    return flags


def _collection(result, *, maximum=50):
    rows = result.get("data")
    if not isinstance(rows, list) or len(rows) > maximum or not all(isinstance(row, dict) for row in rows): raise OpsProviderError("invalid_response")
    paging = result.get("paging") or {}
    if not isinstance(paging, dict): raise OpsProviderError("invalid_response")
    cursor = None
    if paging.get("next"):
        cursors = paging.get("cursors") or {}
        cursor = _cursor(cursors.get("after") if isinstance(cursors, dict) else None)
        if not cursor: raise OpsProviderError("invalid_response")
    return rows, cursor


async def _owned_post(client, page, binding, identity):
    _id(identity, compound=binding.platform == "facebook")
    owner_field = "from" if binding.platform == "facebook" else "owner"
    result = await client.request("GET", identity, params={"fields": "id," + owner_field}, token=page["token"])
    owner = result.get(owner_field)
    if result.get("id") != identity or not isinstance(owner, dict) or owner.get("id") != binding.external_id: raise OpsProviderError("asset_not_authorized")
    return identity


async def read_posts(db, user, binding, cursor=None):
    client, page = await _authorized(db, user, binding)
    field = "message" if binding.platform == "facebook" else "caption"
    stamp = "created_time" if binding.platform == "facebook" else "timestamp"
    permalink = "permalink_url" if binding.platform == "facebook" else "permalink"
    params = {"fields": "id," + field + "," + stamp + "," + permalink, "limit": 50}
    if _cursor(cursor): params["after"] = cursor
    result = await client.request("GET", binding.external_id + ("/published_posts" if binding.platform == "facebook" else "/media"), params=params, token=page["token"])
    rows, next_cursor = _collection(result)
    output = [{"external_id": _id(row.get("id"), compound=binding.platform == "facebook"), "content": _text(row.get(field)), "created_at": _timestamp(row.get(stamp)), "permalink": _permalink(row.get(permalink))} for row in rows]
    if len({x["external_id"] for x in output}) != len(output): raise OpsProviderError("invalid_response")
    return {"items": output, "next_cursor": next_cursor}


def _comment_data(row, binding, post_id):
    author = row.get("from") if binding.platform == "facebook" else None
    return {"external_id": _id(row.get("id"), compound=binding.platform == "facebook"),
            "content": _text(row.get("message" if binding.platform == "facebook" else "text")),
            "author_name": _text(author.get("name"), 255) if isinstance(author, dict) else _text(row.get("username"), 255),
            "created_at": _timestamp(row.get("created_time" if binding.platform == "facebook" else "timestamp")),
            "post_external_id": post_id, "reply": None}


def comment_version(value):
    frozen = {key: value.get(key) for key in ("external_id", "content", "author_name", "created_at", "post_external_id", "reply")}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


async def read_comments(db, user, binding, post_external_id, cursor=None):
    client, page = await _authorized(db, user, binding)
    if not page["tasks"] & REPLY_TASKS: raise OpsProviderError("permission_missing")
    await _owned_post(client, page, binding, post_external_id)
    fields = "id,message,created_time,from" if binding.platform == "facebook" else "id,text,timestamp,username"
    params = {"fields": fields, "limit": 50}
    if _cursor(cursor): params["after"] = cursor
    result = await client.request("GET", post_external_id + "/comments", params=params, token=page["token"])
    rows, next_cursor = _collection(result)
    items = [_comment_data(row, binding, post_external_id) for row in rows]
    if len({x["external_id"] for x in items}) != len(items): raise OpsProviderError("invalid_response")
    return {"items": items, "next_cursor": next_cursor}


async def _read_comment(client, page, binding, comment_external_id, post_external_id=None):
    identity = _id(comment_external_id, compound=binding.platform == "facebook")
    parent_field = "object" if binding.platform == "facebook" else "media"
    fields = "id,message,created_time,from,object{id}" if binding.platform == "facebook" else "id,text,timestamp,username,media{id}"
    result = await client.request("GET", identity, params={"fields": fields}, token=page["token"])
    parent = result.get(parent_field)
    if result.get("id") != identity or not isinstance(parent, dict): raise OpsProviderError("invalid_response")
    post_id = _id(parent.get("id"), compound=binding.platform == "facebook")
    if post_external_id is not None and post_id != post_external_id: raise OpsProviderError("target_changed")
    await _owned_post(client, page, binding, post_id)
    return _comment_data(result, binding, post_id)


async def read_comment(db, user, binding, comment_external_id, post_external_id=None):
    client, page = await _authorized(db, user, binding)
    if not page["tasks"] & REPLY_TASKS: raise OpsProviderError("permission_missing")
    return await _read_comment(client, page, binding, comment_external_id, post_external_id)


def _mutation_allowed(page, tasks):
    if not execution_enabled(): raise OpsProviderError("execution_disabled")
    if not page["tasks"] & tasks: raise OpsProviderError("permission_missing")


def _published(result, *, compound=False):
    try: identity = _id(result.get("id"), compound=compound)
    except OpsProviderError: raise OpsProviderError("invalid_response", uncertain=True) from None
    return {"status": "published", "external_id": identity, "permalink": _permalink(result.get("permalink_url") or result.get("permalink"))}


async def dispatch(db, user, binding, kind, payload, progress=None):
    if not isinstance(payload, dict) or progress is not None: raise OpsProviderError("content_invalid")
    if not execution_enabled(): raise OpsProviderError("execution_disabled")
    client, page = await _authorized(db, user, binding)
    if kind == "reply":
        _mutation_allowed(page, REPLY_TASKS)
        if set(payload) != {"target_id", "post_id", "message", "expected_version"} or not isinstance(payload["expected_version"], str) or not re.fullmatch(r"[a-f0-9]{64}", payload["expected_version"]):
            raise OpsProviderError("content_invalid")
        message = _content(payload["message"], 1000)
        target = await _read_comment(client, page, binding, payload["target_id"], payload["post_id"])
        if not hmac.compare_digest(comment_version(target), payload["expected_version"]): raise OpsProviderError("target_changed")
        edge = "/comments" if binding.platform == "facebook" else "/replies"
        result = await client.request("POST", target["external_id"] + edge, data={"message": message}, token=page["token"], mutation=True)
        return _published(result, compound=binding.platform == "facebook")
    if kind != "post": raise OpsProviderError("unsupported_kind")
    _mutation_allowed(page, PUBLISH_TASKS)
    if not set(payload) <= {"content", "image_url"} or "content" not in payload: raise OpsProviderError("content_invalid")
    content = _content(payload["content"], 5000 if binding.platform == "facebook" else 2200)
    image = payload.get("image_url")
    if image is not None and (not isinstance(image, str) or not DELIVERY_URL.fullmatch(image)): raise OpsProviderError("content_invalid")
    if binding.platform == "instagram":
        if not image: raise OpsProviderError("content_invalid")
        result = await client.request("POST", binding.external_id + "/media", data={"image_url": image, "caption": content}, token=page["token"], mutation=True)
        try: container = _id(result.get("id"))
        except OpsProviderError: raise OpsProviderError("invalid_response", uncertain=True) from None
        return {"status": "processing", "container_id": container, "stage": "container_created"}
    data = {"message": content}
    if image: data.update(url=image, published="true")
    result = await client.request("POST", binding.external_id + ("/photos" if image else "/feed"), data=data, token=page["token"], mutation=True)
    if image and result.get("post_id"):
        result = {**result, "id": result["post_id"]}
    return _published(result, compound=True)


async def inspect_progress(db, user, binding, progress):
    if binding.platform != "instagram" or not isinstance(progress, dict) or set(progress) - {"container_id", "stage", "status"} or "container_id" not in progress:
        raise OpsProviderError("content_invalid")
    container = _id(progress["container_id"])
    client, page = await _authorized(db, user, binding)
    result = await client.request("GET", container, params={"fields": "id,status_code"}, token=page["token"])
    state = result.get("status_code")
    if result.get("id") != container or state not in {"IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED"}: raise OpsProviderError("invalid_response")
    return {"status": state, "container_id": container}


async def publish_container(db, user, binding, container_id):
    if binding.platform != "instagram": raise OpsProviderError("unsupported_kind")
    if not execution_enabled(): raise OpsProviderError("execution_disabled")
    container = _id(container_id)
    client, page = await _authorized(db, user, binding)
    _mutation_allowed(page, PUBLISH_TASKS)
    # This is deliberately one POST; service has already persisted container_id
    # and a publish_started claim after a separate read-only readiness check.
    result = await client.request("POST", binding.external_id + "/media_publish", data={"creation_id": container}, token=page["token"], mutation=True)
    return _published(result)

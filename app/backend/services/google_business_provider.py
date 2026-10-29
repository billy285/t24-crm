"""Google-owned endpoints only. No URL fetching, cookies, private credentials or logs."""
from __future__ import annotations
import base64
import hashlib
import ipaddress
import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

SCOPE = "https://www.googleapis.com/auth/business.manage"
LOCATION = re.compile(r"accounts/[0-9]+/locations/[0-9]+\Z")
REVIEW = re.compile(r"accounts/[0-9]+/locations/[0-9]+/reviews/[A-Za-z0-9_-]+\Z")
POST = re.compile(r"accounts/[0-9]+/locations/[0-9]+/localPosts/[A-Za-z0-9_-]+\Z")
BASES = {"accounts": "https://mybusinessaccountmanagement.googleapis.com/v1/", "locations": "https://mybusinessbusinessinformation.googleapis.com/v1/", "business": "https://mybusiness.googleapis.com/v4/"}
CALLBACK_PATH = "/api/v1/google-business/oauth/callback"


class ProviderError(Exception):
    def __init__(self, code="provider_unavailable", *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def enabled():
    return os.getenv("T24_GBP_ENABLED", "false").strip().lower() == "true"


def _public_host(host):
    if not isinstance(host, str) or not host or len(host) > 253: return False
    try: return ipaddress.ip_address(host).is_global
    except ValueError: pass
    host = host.lower()
    if "." not in host or host.endswith((".localhost", ".local", ".internal", ".test")): return False
    # Reject abbreviated/alternate numeric IP spellings as hostnames.
    if not re.search(r"[a-z]", host.rsplit(".", 1)[-1]): return False
    return all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))


def settings():
    missing = []
    values = {name: os.getenv("T24_GBP_" + name, "").strip() for name in ("CLIENT_ID", "CLIENT_SECRET", "TOKEN_KEY", "PUBLIC_URL")}
    if not enabled(): missing.append("T24_GBP_ENABLED")
    if os.getenv("T24_GBP_API_APPROVED", "false").strip().lower() != "true": missing.append("T24_GBP_API_APPROVED")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", values["CLIENT_ID"]): missing.append("T24_GBP_CLIENT_ID")
    if len(values["CLIENT_SECRET"]) < 16: missing.append("T24_GBP_CLIENT_SECRET")
    try:
        Fernet(values["TOKEN_KEY"].encode())
    except (ValueError, TypeError): missing.append("T24_GBP_TOKEN_KEY")
    try:
        url = urlsplit(values["PUBLIC_URL"])
        if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment or url.path not in {"", "/"} or url.port not in {None, 443}: raise ValueError()
        if not _public_host(url.hostname): raise ValueError()
        values["PUBLIC_URL"] = values["PUBLIC_URL"].rstrip("/")
    except (ValueError, TypeError): missing.append("T24_GBP_PUBLIC_URL")
    return values, sorted(set(missing))


def require_config():
    values, missing = settings()
    if missing: raise HTTPException(503, "Google 商家连接尚未完成配置或 API 接入审批")
    return values


def encrypt(value):
    config = require_config()
    return Fernet(config["TOKEN_KEY"].encode()).encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


def decrypt(value):
    try:
        config = require_config()
        return json.loads(Fernet(config["TOKEN_KEY"].encode()).decrypt((value or "").encode()))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise ProviderError("reconnect_required")


def authorize_url(state, verifier):
    config = require_config()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": config["CLIENT_ID"], "redirect_uri": config["PUBLIC_URL"] + CALLBACK_PATH,
        "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "include_granted_scopes": "false"})


def public_image_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.port not in {None, 443}: return None
        if not _public_host(host): return None
        if len(value) > 2048: return None
        return value
    except (ValueError, TypeError): return None


def public_result_url(value):
    try:
        parsed = urlsplit(str(value or "")); host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and parsed.username is None and parsed.password is None and parsed.port in {None, 443} and (host == "google.com" or host.endswith(".google.com") or host == "g.page"):
            return str(value)[:2048]
    except ValueError: pass
    return None


def _error(status, *, write=False):
    if status in {401}: return ProviderError("reconnect_required")
    if status in {403}: return ProviderError("access_denied")
    if status in {404}: return ProviderError("not_found")
    if status in {429}: return ProviderError("quota_limited")
    if status >= 500 or status in {408}: return ProviderError("provider_unavailable", uncertain=write)
    return ProviderError("invalid_request")


class GoogleClient:
    """One request object, explicit bounded network calls, injectable in synthetic tests."""
    def __init__(self, connection=None):
        self.connection = connection

    async def _raw(self, method, url, *, data=None, params=None, body=None, token=None, write=False):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, data=data, params=params, json=body,
                                                headers={"Authorization": "Bearer " + token} if token else None)
            if response.status_code < 200 or response.status_code >= 300: raise _error(response.status_code, write=write)
            if len(response.content) > 3_000_000: raise ProviderError("invalid_response", uncertain=write)
            result = response.json()
            if not isinstance(result, dict): raise ProviderError("invalid_response", uncertain=write)
            return result
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            raise ProviderError("provider_unavailable", uncertain=write)
        except (ValueError, UnicodeError): raise ProviderError("invalid_response", uncertain=write)

    async def exchange(self, code, verifier):
        config = require_config()
        result = await self._raw("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": config["CLIENT_ID"], "client_secret": config["CLIENT_SECRET"], "redirect_uri": config["PUBLIC_URL"] + CALLBACK_PATH,
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier})
        return self._tokens(result)

    def _tokens(self, result, old=None):
        if not isinstance(result.get("access_token"), str) or len(result["access_token"]) < 10: raise ProviderError("invalid_response")
        refresh = result.get("refresh_token") or (old or {}).get("refresh_token")
        if not isinstance(refresh, str) or len(refresh) < 10: raise ProviderError("reconnect_required")
        scopes = str(result.get("scope") or (old or {}).get("scope") or "").split()
        if SCOPE not in scopes: raise ProviderError("access_denied")
        expires = result.get("expires_in", 3600)
        if not isinstance(expires, (int, float)) or not 1 <= expires <= 86400: raise ProviderError("invalid_response")
        return {"access_token": result["access_token"], "refresh_token": refresh, "scope": " ".join(scopes), "expires_at": time.time() + expires}

    async def _access(self):
        if not self.connection or not self.connection.active or self.connection.needs_reconnect or not self.connection.token_encrypted: raise ProviderError("reconnect_required")
        current = decrypt(self.connection.token_encrypted)
        if not isinstance(current, dict) or not isinstance(current.get("access_token"), str) or not isinstance(current.get("refresh_token"), str) or not isinstance(current.get("expires_at"), (int, float)) or SCOPE not in str(current.get("scope") or "").split():
            raise ProviderError("reconnect_required")
        if current["expires_at"] > time.time() + 120: return current["access_token"]
        config = require_config()
        try:
            data = await self._raw("POST", "https://oauth2.googleapis.com/token", data={"client_id": config["CLIENT_ID"], "client_secret": config["CLIENT_SECRET"], "refresh_token": current.get("refresh_token", ""), "grant_type": "refresh_token"})
        except ProviderError as exc:
            if exc.code == "invalid_request": raise ProviderError("reconnect_required")
            raise
        value = self._tokens(data, current)
        self.connection.token_encrypted = encrypt(value)
        return value["access_token"]

    async def request(self, method, api, path, *, params=None, body=None):
        require_config()
        # Every caller supplies a validated resource path; no user URL can reach here.
        if api not in BASES or path.startswith("/") or ".." in path or "://" in path or any(x in path for x in ("?", "#", "%", "\\")): raise ProviderError("invalid_request")
        token = await self._access()
        return await self._raw(method, BASES[api] + path, params=params, body=body, token=token, write=method not in {"GET"})

    async def locations(self):
        accounts = []; token = None
        for _ in range(10):
            data = await self.request("GET", "accounts", "accounts", params={"pageSize": 20, **({"pageToken": token} if token else {})})
            items = data.get("accounts", [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items): raise ProviderError("invalid_response")
            for item in items:
                name = item.get("name", "")
                if re.fullmatch(r"accounts/[0-9]+", name): accounts.append(name)
            token = data.get("nextPageToken")
            if not token: break
        if token: raise ProviderError("listing_too_large")
        result = []; truncated = False
        for account in accounts:
            token = None
            for _ in range(20):
                data = await self.request("GET", "locations", account + "/locations", params={"readMask": "name,title,storefrontAddress", "pageSize": 100, **({"pageToken": token} if token else {})})
                items = data.get("locations", [])
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items): raise ProviderError("invalid_response")
                for item in items:
                    name = item.get("name", "")
                    if not re.fullmatch(r"locations/[0-9]+", name): continue
                    addr = item.get("storefrontAddress") or {}
                    address = ", ".join([str(v) for v in [*(addr.get("addressLines") or []), addr.get("locality"), addr.get("administrativeArea"), addr.get("postalCode")] if v])[:1000]
                    result.append({"location_name": account + "/" + name, "title": str(item.get("title") or "Google 门店")[:255], "address": address})
                    if len(result) >= 500: return {"items": result, "truncated": True}
                token = data.get("nextPageToken")
                if not token: break
            if token: truncated = True
        return {"items": result, "truncated": truncated}

    async def reviews(self, location, page_token=None):
        if not LOCATION.fullmatch(location): raise ProviderError("invalid_request")
        return await self.request("GET", "business", location + "/reviews", params={"pageSize": 50, "orderBy": "updateTime desc", **({"pageToken": page_token} if page_token else {})})

    async def review(self, name):
        if not REVIEW.fullmatch(name): raise ProviderError("invalid_request")
        return await self.request("GET", "business", name)

    async def reply(self, name, payload):
        if not REVIEW.fullmatch(name): raise ProviderError("invalid_request")
        return await self.request("PUT", "business", name + "/reply", body=payload)

    async def posts(self, location):
        if not LOCATION.fullmatch(location): raise ProviderError("invalid_request")
        return await self.request("GET", "business", location + "/localPosts", params={"pageSize": 100})

    async def post(self, name):
        if not POST.fullmatch(name): raise ProviderError("invalid_request")
        return await self.request("GET", "business", name)

    async def publish(self, location, payload):
        if not LOCATION.fullmatch(location): raise ProviderError("invalid_request")
        return await self.request("POST", "business", location + "/localPosts", body=payload)

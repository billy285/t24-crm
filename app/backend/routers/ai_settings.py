import os
from typing import Optional

from core.database import get_db
from dependencies.auth import get_admin_user
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from schemas.aihub import ChatMessage, GenTxtRequest
from schemas.auth import UserResponse
from services.ai_config import (
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_CONFIG,
    DEFAULT_AI_MODEL,
    humanize_ai_error,
    mask_api_key,
    read_saved_ai_config,
    resolve_ai_runtime_config,
    save_ai_config,
)
from services.aihub import AIHubService
from services.schema_readiness import SchemaUnavailableError
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/api/v1/admin/ai-settings", tags=["admin-ai-settings"])


class AiSettingsResponse(BaseModel):
    enabled: bool
    provider: str = "openai"
    base_url: str
    model: str
    api_key_set: bool
    api_key_preview: str = ""
    source: str = "database"
    updated_at: Optional[str] = None


class AiSettingsUpdate(BaseModel):
    enabled: bool = False
    provider: str = "openai"
    api_key: Optional[str] = None
    clear_api_key: bool = False
    base_url: str = DEFAULT_AI_BASE_URL
    model: str = DEFAULT_AI_MODEL


class AiSettingsTestResponse(BaseModel):
    ok: bool
    model: str
    message: str


def _safe_response(config: dict, source: str, updated_at: Optional[str]) -> AiSettingsResponse:
    api_key = (config.get("api_key") or "").strip()
    return AiSettingsResponse(
        enabled=bool(config.get("enabled")) and bool(api_key),
        provider=config.get("provider") or "openai",
        base_url=(config.get("base_url") or DEFAULT_AI_BASE_URL).rstrip("/"),
        model=config.get("model") or DEFAULT_AI_MODEL,
        api_key_set=bool(api_key),
        api_key_preview=mask_api_key(api_key),
        source=source,
        updated_at=updated_at,
    )


@router.get("", response_model=AiSettingsResponse)
async def get_ai_settings(
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    saved, has_saved_config, updated_at = await read_saved_ai_config(db)
    runtime = await resolve_ai_runtime_config(db)

    response_config = {
        **DEFAULT_AI_CONFIG,
        **saved,
        "api_key": runtime.api_key,
        "base_url": runtime.base_url,
        "model": runtime.model,
        "enabled": runtime.enabled,
    }
    return _safe_response(response_config, "database" if has_saved_config else runtime.source, updated_at)


@router.put("", response_model=AiSettingsResponse)
async def update_ai_settings(
    payload: AiSettingsUpdate,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    saved, _has_saved_config, _updated_at = await read_saved_ai_config(db)

    next_config = {
        **DEFAULT_AI_CONFIG,
        **saved,
        "enabled": payload.enabled,
        "provider": (payload.provider or "openai").strip() or "openai",
        "base_url": (payload.base_url or DEFAULT_AI_BASE_URL).strip().rstrip("/"),
        "model": (payload.model or DEFAULT_AI_MODEL).strip(),
    }

    if payload.clear_api_key:
        next_config["api_key"] = ""
        next_config["enabled"] = False
    elif payload.api_key is not None and payload.api_key.strip():
        next_config["api_key"] = payload.api_key.strip()

    if not next_config["base_url"].startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Base URL 必须以 http:// 或 https:// 开头")

    env_api_key = (os.getenv("APP_AI_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if next_config["enabled"] and not (next_config.get("api_key") or env_api_key):
        raise HTTPException(status_code=400, detail="开启 OpenAI 前，请先填写 API Key")

    try:
        await save_ai_config(db, next_config)
    except SchemaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库结构尚未升级，暂时无法保存 AI 配置，请联系管理员",
        ) from exc
    saved_config, _has_saved_again, updated_at = await read_saved_ai_config(db)
    runtime = await resolve_ai_runtime_config(db)
    response_config = {
        **saved_config,
        "api_key": runtime.api_key,
        "base_url": runtime.base_url,
        "model": runtime.model,
        "enabled": runtime.enabled,
    }
    return _safe_response(response_config, "database", updated_at)


@router.post("/test", response_model=AiSettingsTestResponse)
async def test_ai_settings(
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    runtime = await resolve_ai_runtime_config(db)
    if not runtime.enabled or not runtime.api_key:
        raise HTTPException(status_code=400, detail="OpenAI 尚未启用或 API Key 未配置")

    try:
        service = AIHubService(api_key=runtime.api_key, base_url=runtime.base_url)
        result = await service.gentxt(
            GenTxtRequest(
                model=runtime.model,
                messages=[
                    ChatMessage(role="system", content="You are a connection test. Reply with exactly: OK"),
                    ChatMessage(role="user", content="Return OK"),
                ],
                temperature=0,
                max_tokens=20,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=humanize_ai_error(exc))

    return AiSettingsTestResponse(ok=True, model=result.model, message="OpenAI 连接正常")

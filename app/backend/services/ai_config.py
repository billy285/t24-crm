import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


AI_CONFIG_KEY = "ai_config"
DEFAULT_AI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_AI_MODEL = "gpt-5.4-mini"


DEFAULT_AI_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "provider": "openai",
    "api_key": "",
    "base_url": DEFAULT_AI_BASE_URL,
    "model": DEFAULT_AI_MODEL,
}


@dataclass
class AiRuntimeConfig:
    enabled: bool
    provider: str
    api_key: str
    base_url: str
    model: str
    source: str


async def ensure_ai_config_table(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
              config_key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await db.commit()


async def read_saved_ai_config(db: AsyncSession) -> tuple[Dict[str, Any], bool, Optional[str]]:
    await ensure_ai_config_table(db)
    result = await db.execute(
        text("SELECT value_json, updated_at FROM app_settings WHERE config_key = :key"),
        {"key": AI_CONFIG_KEY},
    )
    row = result.fetchone()
    if not row:
        return dict(DEFAULT_AI_CONFIG), False, None

    try:
        saved = json.loads(row[0]) if row[0] else {}
    except Exception:
        saved = {}

    updated_at = row[1].isoformat() if row[1] is not None and hasattr(row[1], "isoformat") else None
    return {**DEFAULT_AI_CONFIG, **saved}, True, updated_at


async def save_ai_config(db: AsyncSession, config: Dict[str, Any]) -> Dict[str, Any]:
    await ensure_ai_config_table(db)
    normalized = {**DEFAULT_AI_CONFIG, **config}
    value_json = json.dumps(normalized, ensure_ascii=False)
    await db.execute(
        text(
            """
            INSERT INTO app_settings (config_key, value_json, updated_at)
            VALUES (:key, :value_json, CURRENT_TIMESTAMP)
            ON CONFLICT(config_key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"key": AI_CONFIG_KEY, "value_json": value_json},
    )
    await db.commit()
    return normalized


def _env_first(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


async def resolve_ai_runtime_config(db: AsyncSession) -> AiRuntimeConfig:
    saved, has_saved_config, _updated_at = await read_saved_ai_config(db)

    env_api_key = _env_first("APP_AI_KEY", "OPENAI_API_KEY")
    env_base_url = _env_first("APP_AI_BASE_URL", "OPENAI_BASE_URL")
    env_model = _env_first("AI_COPY_MODEL", "APP_AI_TEXT_MODEL", "OPENAI_MODEL")

    api_key = (saved.get("api_key") or "").strip() or env_api_key
    base_url = (saved.get("base_url") or "").strip() or env_base_url or DEFAULT_AI_BASE_URL
    model = (saved.get("model") or "").strip() or env_model or DEFAULT_AI_MODEL

    if has_saved_config:
        enabled = bool(saved.get("enabled")) and bool(api_key)
        source = "database"
    else:
        enabled = bool(api_key)
        source = "environment" if api_key else "default"

    return AiRuntimeConfig(
        enabled=enabled,
        provider=(saved.get("provider") or "openai").strip() or "openai",
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        source=source,
    )


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return f"{api_key[:2]}...{api_key[-2:]}"
    return f"{api_key[:7]}...{api_key[-4:]}"


def humanize_ai_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()

    if "insufficient_quota" in lowered or "exceeded your current quota" in lowered or "429" in lowered:
        return "OpenAI 账号额度不足或未开通计费，请到 OpenAI 平台检查 Billing/余额，或更换有额度的 API Key。"
    if "invalid_api_key" in lowered or "incorrect api key" in lowered or "401" in lowered:
        return "OpenAI API Key 无效，请重新复制正确的 Key 并保存。"
    if "model_not_found" in lowered or "does not exist" in lowered or "404" in lowered:
        return "当前 OpenAI 账号不可用这个模型，请在 AI配置 中更换模型。"
    if "timeout" in lowered or "connection" in lowered or "network" in lowered:
        return "连接 OpenAI 超时或网络不可达，请检查网络、代理或 Base URL。"

    return f"OpenAI 调用失败：{message}"

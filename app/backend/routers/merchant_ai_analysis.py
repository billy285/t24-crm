import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.merchant_ai_analyses import MerchantAiAnalyses
from models.merchant_pool import MerchantPool
from schemas.aihub import ChatMessage, GenTxtRequest
from schemas.auth import UserResponse
from services.ai_config import humanize_ai_error, resolve_ai_runtime_config
from services.aihub import AIHubService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/merchant-pool", tags=["merchant-ai-analysis"])

ADMIN_ROLES = {"admin", "super_admin"}
POOL_ROLES = ADMIN_ROLES | {"sales_manager"}
ELIGIBLE_STATUSES = {"pending", "converted"}


def _role(user: UserResponse) -> str:
    return str(user.role or "").strip().lower()


def _employee_id(user: UserResponse) -> int:
    try:
        return int(user.id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="当前账号未关联有效员工")


def _ensure_pool_role(user: UserResponse) -> None:
    if _role(user) not in POOL_ROLES:
        raise HTTPException(status_code=403, detail="只有销售主管或管理员可以使用商家智能分析")


def _format_time(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _source(key: str, label: str, value: Any, updated_at: Optional[datetime]) -> dict[str, Any]:
    return {
        "id": key,
        "label": label,
        "value": value,
        "updated_at": _format_time(updated_at),
    }


def _insufficient(title: str, missing: str) -> dict[str, Any]:
    return {
        "title": title,
        "kind": "insufficient",
        "content": f"信息不足：未采集{missing}。请通过 API、CSV 或主管补充资料后再判断。",
        "sources": [{"label": "未采集", "updated_at": None}],
    }


def _fact(title: str, content: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {"title": title, "kind": "fact", "content": content, "sources": sources}


async def _get_scoped_merchant(db: AsyncSession, merchant_id: int, user: UserResponse) -> MerchantPool:
    query = select(MerchantPool).where(MerchantPool.id == merchant_id)
    if _role(user) not in ADMIN_ROLES:
        query = query.where(MerchantPool.created_by_id == _employee_id(user))
    merchant = (await db.execute(query)).scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家池记录不存在或不在权限范围内")
    if merchant.pool_status not in ELIGIBLE_STATUSES:
        raise HTTPException(status_code=400, detail="商家尚未通过清洗，不能生成销售分析")
    return merchant


def _build_evidence(merchant: MerchantPool) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    collected_at = merchant.collected_at or merchant.updated_at or merchant.created_at
    evidence: dict[str, dict[str, Any]] = {}
    cards: list[dict[str, Any]] = []

    profile_parts = []
    if merchant.business_name:
        evidence["business_name"] = _source("business_name", "商家名称", merchant.business_name, collected_at)
        profile_parts.append(merchant.business_name)
    if merchant.industry:
        evidence["industry"] = _source("industry", "行业", merchant.industry, collected_at)
        profile_parts.append(f"行业：{merchant.industry}")
    location = "，".join(item for item in [merchant.city, merchant.state, merchant.country] if item)
    if location:
        evidence["location"] = _source("location", "地区", location, collected_at)
        profile_parts.append(f"地区：{location}")
    if merchant.phone:
        evidence["phone"] = _source("phone", "联系电话", merchant.phone, collected_at)
    if profile_parts:
        cards.append(_fact("商家经营概况", "；".join(profile_parts), [evidence[key] for key in ["business_name", "industry", "location"] if key in evidence]))
    else:
        cards.append(_insufficient("商家经营概况", "商家基础资料"))

    if merchant.google_business_url or merchant.google_rating is not None or merchant.google_review_count is not None:
        sources = []
        parts = []
        if merchant.google_business_url:
            evidence["google_url"] = _source("google_url", "Google 商家链接", merchant.google_business_url, collected_at)
            sources.append(evidence["google_url"])
            parts.append("已采集 Google 商家链接")
        if merchant.google_rating is not None:
            evidence["google_rating"] = _source("google_rating", "Google 评分", merchant.google_rating, collected_at)
            sources.append(evidence["google_rating"])
            parts.append(f"评分 {merchant.google_rating:.1f}")
        if merchant.google_review_count is not None:
            evidence["google_reviews"] = _source("google_reviews", "Google 评论数", merchant.google_review_count, collected_at)
            sources.append(evidence["google_reviews"])
            parts.append(f"评论 {merchant.google_review_count} 条")
        cards.append(_fact("Google 商家情况", "；".join(parts), sources))
    else:
        cards.append(_insufficient("Google 商家情况", "Google 链接、评分或评论数"))

    if merchant.yelp_url or merchant.yelp_rating is not None or merchant.yelp_review_count is not None:
        sources = []
        parts = []
        if merchant.yelp_url:
            evidence["yelp_url"] = _source("yelp_url", "Yelp 链接", merchant.yelp_url, collected_at)
            sources.append(evidence["yelp_url"])
            parts.append("已采集 Yelp 链接")
        if merchant.yelp_rating is not None:
            evidence["yelp_rating"] = _source("yelp_rating", "Yelp 评分", merchant.yelp_rating, collected_at)
            sources.append(evidence["yelp_rating"])
            parts.append(f"评分 {merchant.yelp_rating:.1f}")
        if merchant.yelp_review_count is not None:
            evidence["yelp_reviews"] = _source("yelp_reviews", "Yelp 评论数", merchant.yelp_review_count, collected_at)
            sources.append(evidence["yelp_reviews"])
            parts.append(f"评论 {merchant.yelp_review_count} 条")
        cards.append(_fact("Yelp 情况", "；".join(parts), sources))
    else:
        cards.append(_insufficient("Yelp 情况", "Yelp 链接、评分或评论数"))

    if merchant.website:
        evidence["website"] = _source("website", "官网", merchant.website, collected_at)
        cards.append(_fact("官网情况", f"已采集官网：{merchant.website}", [evidence["website"]]))
    else:
        cards.append(_insufficient("官网情况", "官网链接"))

    if merchant.social_profiles:
        evidence["social_profiles"] = _source("social_profiles", "社交平台资料", merchant.social_profiles, collected_at)
        cards.append(_fact("社交平台情况", merchant.social_profiles, [evidence["social_profiles"]]))
    else:
        cards.append(_insufficient("社交平台情况", "Facebook、Instagram、TikTok 等账号或更新记录"))

    if merchant.recent_negative_reviews:
        evidence["negative_reviews"] = _source("negative_reviews", "近期差评重点", merchant.recent_negative_reviews, collected_at)
        cards.append(_fact("近期差评重点", merchant.recent_negative_reviews, [evidence["negative_reviews"]]))
    else:
        cards.append(_insufficient("近期差评重点", "近期评论内容或差评摘要"))

    if merchant.content_update_summary:
        content_time = merchant.content_last_updated_at or collected_at
        evidence["content_updates"] = _source("content_updates", "素材及内容更新", merchant.content_update_summary, content_time)
        cards.append(_fact("素材及内容更新情况", merchant.content_update_summary, [evidence["content_updates"]]))
    else:
        cards.append(_insufficient("素材及内容更新情况", "近期内容、图片、菜单或社交更新记录"))

    return evidence, cards


def _rule_based_recommendations(evidence: dict[str, dict[str, Any]], merchant: MerchantPool) -> list[dict[str, Any]]:
    missing = []
    if "google_url" not in evidence:
        missing.append("Google 商家资料")
    if "website" not in evidence:
        missing.append("官网资料")
    if "social_profiles" not in evidence:
        missing.append("社交平台资料")
    sources = [evidence[key] for key in ["business_name", "industry", "location", "google_rating", "yelp_rating", "negative_reviews"] if key in evidence]
    source_display = sources or [{"label": "已采集资料不足", "updated_at": None}]
    problems = (
        f"已采集资料显示：{'、'.join(missing)}尚未采集。当前只能确认资料缺口，不能判断实际运营质量。"
        if missing else "基础线上资料已采集，但仍需销售在通话中确认当前获客方式、近期目标和预算。"
    )
    package = "基础套餐（建议）" if missing else "进阶套餐（建议）"
    package_note = "仅依据线上资料完整度给出初步建议，需销售确认需求和预算后再报价。"
    location = evidence.get("location", {}).get("value") or "当地"
    industry = evidence.get("industry", {}).get("value") or "本地商家"
    score = min(85, 15 + (10 if merchant.phone else 0) + (10 if merchant.website else 0) + (15 if merchant.google_business_url else 0) + (10 if merchant.yelp_url else 0) + (10 if merchant.social_profiles else 0) + (10 if merchant.recent_negative_reviews else 0) + (5 if merchant.content_update_summary else 0))
    return [
        _fact("主要营销问题", problems, source_display),
        _fact("推荐切入点", f"先用“线上资料补全与本地搜索展示”作为切入点，围绕 {location} 的{industry}商家实际获客方式做确认，不对未采集的平台表现下结论。", source_display),
        _fact("推荐套餐", f"{package}。{package_note}", source_display),
        _fact("开场话术", f"您好，我们在整理 {location} 本地商家的线上展示资料。想先了解一下，您目前主要通过哪些渠道让新客户找到您？如果方便，我们可以根据已公开和您确认的信息，给您一份不涉及承诺的优化清单。", source_display),
        _fact("建议询问的问题", "1. 目前新客主要来自 Google、Yelp、社交平台还是熟客转介绍？\n2. 哪些服务/菜品最希望增加咨询？\n3. 近期是否有差评、菜单变动、活动或图片素材可更新？\n4. 现有线上账号由谁管理、多久更新一次？", source_display),
        _fact("常见异议处理", "若商家说“已有团队”：先确认现有团队负责的平台、更新频率和当前目标，再判断是否存在补充空间；不要评价对方团队好坏。\n若商家说“没有预算”：可先确认最需要改善的单一问题，再讨论可拆分的服务范围。", source_display),
        _fact("成交可能性评分", f"{score}/100（资料完整度辅助分）。该分数只反映可联系性与已采集线上资料的完整程度，不代表商家真实购买意愿；必须以通话反馈为准。", source_display),
    ]


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        result = json.loads(match.group(0))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _ai_prompt(merchant: MerchantPool, evidence: dict[str, dict[str, Any]]) -> str:
    serializable_evidence = list(evidence.values())
    return f"""
你是严谨的电话销售辅助分析师。只能依据下方“证据列表”生成销售建议，绝不能虚构 Google、Yelp、评分、评论、平台账号、经营数据、近期活动或客户意向。

规则：
1. 任何事实性结论必须能引用 evidence_ids 中的至少一个 ID。
2. 如果证据不足，content 必须以“信息不足：”开始，并说明销售需要确认什么。
3. 推荐套餐只能写“基础套餐（建议）”“进阶套餐（建议）”“专业套餐（建议）”“旗舰套餐（建议）”或“信息不足，暂不推荐套餐”，并说明需人工确认。
4. 成交评分必须是 0-100 的整数，并说明它仅是基于资料完整度和已知信号的辅助判断，不是事实。
5. 只输出一个 JSON 对象，不要 Markdown。格式：
{{
  "marketing_problems": {{"content":"...","evidence_ids":["..."]}},
  "entry_point": {{"content":"...","evidence_ids":["..."]}},
  "package": {{"content":"...","evidence_ids":["..."]}},
  "opening_script": {{"content":"...","evidence_ids":["..."]}},
  "questions": {{"content":"...","evidence_ids":["..."]}},
  "objections": {{"content":"...","evidence_ids":["..."]}},
  "conversion_score": {{"content":"...","evidence_ids":["..."]}}
}}

商家：{merchant.business_name}
证据列表：
{json.dumps(serializable_evidence, ensure_ascii=False)}
""".strip()


async def _generate_ai_cards(
    merchant: MerchantPool, evidence: dict[str, dict[str, Any]], db: AsyncSession
) -> tuple[list[dict[str, Any]], bool, Optional[str], str, str]:
    fallback = _rule_based_recommendations(evidence, merchant)
    prompt = _ai_prompt(merchant, evidence)
    runtime = await resolve_ai_runtime_config(db)
    if not runtime.enabled:
        return fallback, False, "AI 尚未配置，已按已采集资料生成保守销售建议。", prompt, runtime.model
    try:
        service = AIHubService(api_key=runtime.api_key, base_url=runtime.base_url)
        response = await service.gentxt(
            GenTxtRequest(
                messages=[
                    ChatMessage(role="system", content="只输出严格 JSON；证据不足时必须明确写信息不足，不得编造。"),
                    ChatMessage(role="user", content=prompt),
                ],
                model=runtime.model,
                temperature=0.2,
                max_tokens=1600,
            )
        )
        parsed = _extract_json_object(response.content)
        labels = [
            ("主要营销问题", "marketing_problems"), ("推荐切入点", "entry_point"), ("推荐套餐", "package"),
            ("开场话术", "opening_script"), ("建议询问的问题", "questions"), ("常见异议处理", "objections"), ("成交可能性评分", "conversion_score"),
        ]
        cards = []
        for title, key in labels:
            item = parsed.get(key) if isinstance(parsed.get(key), dict) else {}
            content = str(item.get("content") or "").strip()
            ids = item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else []
            sources = [evidence[source_id] for source_id in ids if source_id in evidence]
            if not content or (not sources and not content.startswith("信息不足：")):
                return fallback, False, "AI 返回内容未能通过来源校验，已改用保守建议。", prompt, runtime.model
            cards.append({"title": title, "kind": "recommendation" if sources else "insufficient", "content": content, "sources": sources or [{"label": "未采集", "updated_at": None}]})
        return cards, True, None, prompt, runtime.model
    except Exception as exc:
        logger.warning("Merchant AI analysis fallback used: %s", exc)
        return fallback, False, f"{humanize_ai_error(exc)} 已按已采集资料生成保守建议。", prompt, runtime.model


class MerchantAnalysisResponse(BaseModel):
    id: int
    merchant_id: int
    status: str
    analysis: dict[str, Any]
    source_snapshot: list[dict[str, Any]]
    ai_used: bool
    ai_model: Optional[str] = None
    generated_at: datetime
    updated_at: datetime


def _response(item: MerchantAiAnalyses) -> dict[str, Any]:
    return {
        "id": item.id,
        "merchant_id": item.merchant_id,
        "status": item.status,
        "analysis": json.loads(item.analysis_json),
        "source_snapshot": json.loads(item.source_snapshot),
        "ai_used": bool(item.ai_used),
        "ai_model": item.ai_model,
        "generated_at": item.generated_at,
        "updated_at": item.updated_at,
    }


@router.get("/{merchant_id}/analysis", response_model=Optional[MerchantAnalysisResponse])
async def get_merchant_analysis(
    merchant_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_pool_role(current_user)
    await _get_scoped_merchant(db, merchant_id, current_user)
    analysis = (await db.execute(
        select(MerchantAiAnalyses).where(MerchantAiAnalyses.merchant_id == merchant_id).order_by(MerchantAiAnalyses.generated_at.desc()).limit(1)
    )).scalar_one_or_none()
    return _response(analysis) if analysis else None


@router.post("/{merchant_id}/analysis/generate", response_model=MerchantAnalysisResponse)
async def generate_merchant_analysis(
    merchant_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_pool_role(current_user)
    merchant = await _get_scoped_merchant(db, merchant_id, current_user)
    evidence, factual_cards = _build_evidence(merchant)
    recommendation_cards, ai_used, warning, _prompt, model = await _generate_ai_cards(merchant, evidence, db)
    generated_at = datetime.now(timezone.utc)
    analysis_data = {
        "merchant_name": merchant.business_name,
        "warning": warning,
        "cards": factual_cards + recommendation_cards,
    }
    item = MerchantAiAnalyses(
        merchant_id=merchant.id,
        status="ready" if evidence else "information_insufficient",
        analysis_json=json.dumps(analysis_data, ensure_ascii=False),
        source_snapshot=json.dumps(list(evidence.values()), ensure_ascii=False),
        ai_used=ai_used,
        ai_model=model,
        generated_by_id=_employee_id(current_user),
        generated_by_name=current_user.name,
        generated_at=generated_at,
        updated_at=generated_at,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _response(item)

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.aihub import ChatMessage, GenTxtRequest
from schemas.auth import UserResponse
from services.ai_config import humanize_ai_error, resolve_ai_runtime_config
from services.aihub import AIHubService
from services.customer_ai_copies import Customer_ai_copiesService
from services.customers import CustomersService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customer_ai_copies", tags=["customer_ai_copies"], dependencies=[Depends(get_current_user)])


PLATFORM_LABELS = {
    "google_business": "Google商家",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "x": "X",
    "yelp": "Yelp",
    "xiaohongshu": "小红书",
}

CONTENT_TYPE_LABELS = {
    "business_intro": "商家介绍",
    "promotion": "活动推广",
    "holiday": "节日营销",
    "review_reply": "评论回复",
    "weekly_update": "每周更新",
    "package_promo": "套餐宣传",
}

LANGUAGE_LABELS = {
    "zh": "中文",
    "en": "英文",
    "zh_en": "中英双语",
}

TONE_LABELS = {
    "professional": "专业",
    "friendly": "亲切",
    "sales": "促销",
    "lifestyle": "种草",
    "local": "本地生活",
    "concise": "简洁",
}


class CustomerAiCopyData(BaseModel):
    customer_id: int
    customer_name: Optional[str] = None
    platform: str
    content_type: str
    language: Optional[str] = "zh_en"
    tone: Optional[str] = "friendly"
    title: Optional[str] = None
    content: str
    prompt: Optional[str] = None
    extra_requirements: Optional[str] = None
    status: Optional[str] = "draft"
    generated_by: Optional[str] = None
    ai_model: Optional[str] = None
    is_ai_generated: Optional[bool] = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerAiCopyUpdateData(BaseModel):
    customer_name: Optional[str] = None
    platform: Optional[str] = None
    content_type: Optional[str] = None
    language: Optional[str] = None
    tone: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    prompt: Optional[str] = None
    extra_requirements: Optional[str] = None
    status: Optional[str] = None
    generated_by: Optional[str] = None
    ai_model: Optional[str] = None
    is_ai_generated: Optional[bool] = None
    updated_at: Optional[datetime] = None


class CustomerAiCopyResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    customer_id: int
    customer_name: Optional[str] = None
    platform: str
    content_type: str
    language: Optional[str] = None
    tone: Optional[str] = None
    title: Optional[str] = None
    content: str
    prompt: Optional[str] = None
    extra_requirements: Optional[str] = None
    status: Optional[str] = None
    generated_by: Optional[str] = None
    ai_model: Optional[str] = None
    is_ai_generated: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerAiCopyListResponse(BaseModel):
    items: List[CustomerAiCopyResponse]
    total: int
    skip: int
    limit: int


class CustomerAiGenerateRequest(BaseModel):
    customer_id: int
    platform: str = Field(default="google_business")
    content_type: str = Field(default="weekly_update")
    language: str = Field(default="zh_en")
    tone: str = Field(default="friendly")
    extra_requirements: Optional[str] = ""
    variants: int = Field(default=3, ge=1, le=5)
    customer_context: Dict[str, Any] = Field(default_factory=dict)


class CustomerAiGenerateResponse(BaseModel):
    items: List[CustomerAiCopyResponse]
    ai_used: bool
    warning: Optional[str] = None


def _parse_query(query: Optional[str]) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    try:
        parsed = json.loads(query)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid query JSON format")


async def _ensure_customer_access(customer_id: int, current_user: UserResponse, db: AsyncSession):
    customer = await CustomersService(db).get_by_id(customer_id, scope_user=current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _label(mapping: Dict[str, str], key: Optional[str]) -> str:
    return mapping.get(key or "", key or "-")


def _build_prompt(customer: Any, request: CustomerAiGenerateRequest) -> str:
    ctx = request.customer_context or {}
    platform_label = _label(PLATFORM_LABELS, request.platform)
    content_type_label = _label(CONTENT_TYPE_LABELS, request.content_type)
    language_label = _label(LANGUAGE_LABELS, request.language)
    tone_label = _label(TONE_LABELS, request.tone)

    location = ", ".join(
        part
        for part in [
            ctx.get("city") or getattr(customer, "city", None),
            ctx.get("state_label") or getattr(customer, "state", None),
            ctx.get("country_label") or getattr(customer, "country", None),
        ]
        if part
    )

    return f"""
你是一个服务北美本地商家的运营文案专家。请根据客户资料，为指定平台生成可直接给运营人员编辑使用的草稿。

输出要求：
1. 只输出 JSON 数组，不要 Markdown，不要解释。
2. 数组长度必须是 {request.variants}。
3. 每个对象包含 title 和 content 两个字段。
4. 内容需要适配平台规则，不要写“自动发布”，不要承诺未经客户确认的信息。
5. 如果是中英双语，请自然分段，先中文后英文。

客户资料：
- 商家名称：{getattr(customer, "business_name", "")}
- 行业：{ctx.get("industry_label") or getattr(customer, "industry", "") or "-"}
- 地区：{location or "-"}
- 当前平台：{getattr(customer, "current_platform", "") or "-"}
- 意向/服务套餐：{ctx.get("package_labels") or getattr(customer, "interested_packages", "") or "-"}
- 官网：{getattr(customer, "website", "") or "-"}
- 备注：{getattr(customer, "notes", "") or "-"}

生成参数：
- 平台：{platform_label}
- 用途：{content_type_label}
- 语言：{language_label}
- 语气：{tone_label}
- 额外要求：{request.extra_requirements or "-"}
""".strip()


def _extract_json_variants(raw: str, variants: int) -> List[Dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []

    # Accept pure JSON or a JSON block embedded in model output.
    candidates = [text]
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                items = []
                for idx, item in enumerate(parsed[:variants], start=1):
                    if isinstance(item, dict):
                        content = str(item.get("content") or "").strip()
                        title = str(item.get("title") or f"AI文案方案 {idx}").strip()
                    else:
                        content = str(item).strip()
                        title = f"AI文案方案 {idx}"
                    if content:
                        items.append({"title": title, "content": content})
                if items:
                    return items
        except Exception:
            continue

    # Fallback: split plain text into chunks.
    chunks = [chunk.strip(" \n-#：:") for chunk in re.split(r"\n\s*(?:方案|版本|Variant)?\s*\d+[：:.)、-]?\s*", text) if chunk.strip()]
    if not chunks:
        chunks = [text]
    return [{"title": f"AI文案方案 {idx}", "content": chunk} for idx, chunk in enumerate(chunks[:variants], start=1)]


def _template_variants(customer: Any, request: CustomerAiGenerateRequest) -> List[Dict[str, str]]:
    platform_label = _label(PLATFORM_LABELS, request.platform)
    content_type_label = _label(CONTENT_TYPE_LABELS, request.content_type)
    name = getattr(customer, "business_name", "客户")
    city = request.customer_context.get("city") or getattr(customer, "city", "") or "本地"
    industry = request.customer_context.get("industry_label") or getattr(customer, "industry", "") or "商家"
    packages = request.customer_context.get("package_labels") or getattr(customer, "interested_packages", "") or "相关服务"
    return [
        {
            "title": f"{platform_label} {content_type_label} 草稿 1",
            "content": f"{name} 是位于 {city} 的{industry}商家。我们将围绕 {packages} 持续优化线上展示，让更多本地客户更容易了解服务、找到门店并产生咨询。\\n\\n{name} is a local {industry} business in {city}. We are improving its online presence around {packages} so nearby customers can discover the business more easily.",
        },
        {
            "title": f"{platform_label} {content_type_label} 草稿 2",
            "content": f"如果你正在 {city} 附近寻找值得信赖的{industry}服务，可以关注 {name}。我们会持续更新服务亮点、优惠信息和门店动态，帮助客户更快做出选择。",
        },
        {
            "title": f"{platform_label} {content_type_label} 草稿 3",
            "content": f"{name} 正在升级线上运营内容。本次重点围绕 {platform_label} 平台，突出商家特色、位置优势和服务体验，方便后续运营人员根据实际活动进一步修改。",
        },
    ][: request.variants]


async def _generate_variants(
    customer: Any,
    request: CustomerAiGenerateRequest,
    db: AsyncSession,
) -> tuple[List[Dict[str, str]], bool, Optional[str], str, str]:
    prompt = _build_prompt(customer, request)
    runtime = await resolve_ai_runtime_config(db)
    model = runtime.model
    if not runtime.enabled:
        return _template_variants(customer, request), False, "OpenAI 尚未配置，已生成可编辑模板草稿。", prompt, model

    try:
        service = AIHubService(api_key=runtime.api_key, base_url=runtime.base_url)
        response = await service.gentxt(
            GenTxtRequest(
                messages=[
                    ChatMessage(role="system", content="你是严谨的商家运营文案助手，只输出符合要求的 JSON。"),
                    ChatMessage(role="user", content=prompt),
                ],
                model=model,
                temperature=0.75,
                max_tokens=2200,
            )
        )
        items = _extract_json_variants(response.content, request.variants)
        if items:
            return items, True, None, prompt, model
        return _template_variants(customer, request), False, "AI返回内容无法解析，已生成可编辑模板草稿。", prompt, model
    except Exception as exc:
        logger.warning("AI copy generation fallback used: %s", exc)
        return _template_variants(customer, request), False, f"{humanize_ai_error(exc)}已生成可编辑模板草稿。", prompt, model


@router.get("", response_model=CustomerAiCopyListResponse)
async def query_customer_ai_copies(
    query: str = Query(None),
    sort: str = Query("-created_at"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query_dict = _parse_query(query) or {}
    customer_id = query_dict.get("customer_id")
    if customer_id:
        await _ensure_customer_access(int(customer_id), current_user, db)
    elif current_user.role not in {"admin", "super_admin"}:
        query_dict["user_id"] = str(current_user.id)
    return await Customer_ai_copiesService(db).get_list(skip=skip, limit=limit, query_dict=query_dict, sort=sort)


@router.post("", response_model=CustomerAiCopyResponse, status_code=201)
async def create_customer_ai_copy(
    data: CustomerAiCopyData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await _ensure_customer_access(data.customer_id, current_user, db)
    payload = data.model_dump()
    now = datetime.utcnow()
    payload["customer_name"] = payload.get("customer_name") or getattr(customer, "business_name", None)
    payload["generated_by"] = payload.get("generated_by") or current_user.name or current_user.email
    payload["created_at"] = payload.get("created_at") or now
    payload["updated_at"] = payload.get("updated_at") or now
    return await Customer_ai_copiesService(db).create(payload, user_id=str(current_user.id))


@router.put("/{copy_id}", response_model=CustomerAiCopyResponse)
async def update_customer_ai_copy(
    copy_id: int,
    data: CustomerAiCopyUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = Customer_ai_copiesService(db)
    obj = await service.get_by_id(copy_id)
    if not obj:
        raise HTTPException(status_code=404, detail="AI copy not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)
    payload = data.model_dump(exclude_unset=True)
    payload["updated_at"] = payload.get("updated_at") or datetime.utcnow()
    updated = await service.update(copy_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="AI copy not found")
    return updated


@router.delete("/{copy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_ai_copy(
    copy_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = Customer_ai_copiesService(db)
    obj = await service.get_by_id(copy_id)
    if not obj:
        raise HTTPException(status_code=404, detail="AI copy not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)
    deleted = await service.delete(copy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AI copy not found")


@router.post("/generate", response_model=CustomerAiGenerateResponse)
async def generate_customer_ai_copy(
    request: CustomerAiGenerateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await _ensure_customer_access(request.customer_id, current_user, db)
    variants, ai_used, warning, prompt, model = await _generate_variants(customer, request, db)
    service = Customer_ai_copiesService(db)
    now = datetime.utcnow()
    saved = []
    for idx, item in enumerate(variants, start=1):
        saved.append(
            await service.create(
                {
                    "customer_id": request.customer_id,
                    "customer_name": getattr(customer, "business_name", None),
                    "platform": request.platform,
                    "content_type": request.content_type,
                    "language": request.language,
                    "tone": request.tone,
                    "title": item.get("title") or f"AI文案方案 {idx}",
                    "content": item.get("content") or "",
                    "prompt": prompt,
                    "extra_requirements": request.extra_requirements,
                    "status": "draft",
                    "generated_by": current_user.name or current_user.email,
                    "ai_model": model,
                    "is_ai_generated": ai_used,
                    "created_at": now,
                    "updated_at": now,
                },
                user_id=str(current_user.id),
            )
        )
    return CustomerAiGenerateResponse(items=saved, ai_used=ai_used, warning=warning)

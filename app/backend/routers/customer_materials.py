import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from schemas.aihub import ChatMessage, GenTxtRequest
from schemas.auth import UserResponse
from services.ai_config import humanize_ai_error, resolve_ai_runtime_config
from services.aihub import AIHubService
from services.customer_menu_items import Customer_menu_itemsService
from services.customer_materials import Customer_materialsService
from services.customers import CustomersService
from services.operation_logs import Operation_logsService
from services.role_permissions import normalized_role, require_any_page_permission, require_button_permission
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entities/customer_materials",
    tags=["customer_materials"],
    dependencies=[Depends(get_current_user)],
)

MATERIALS_ROOT = Path(__file__).resolve().parent.parent / "data" / "materials"
MAX_UPLOAD_SIZE = 30 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".mp4",
    ".mov",
}

PLATFORM_LABELS = {
    "general": "通用",
    "google_business": "Google商家",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "yelp": "Yelp",
    "tiktok": "TikTok",
    "xiaohongshu": "小红书",
    "brand_website": "品牌官网",
    "ads_campaign": "广告投放",
    "other": "其他",
}

MATERIAL_TYPE_LABELS = {
    "image": "图片",
    "video": "视频",
    "logo": "Logo",
    "menu": "菜单",
    "screenshot": "截图",
    "document": "文档",
    "design": "设计稿",
    "post": "发布素材",
    "other": "其他",
}

USAGE_STATUS_LABELS = {
    "unused": "未使用",
    "planned": "计划使用",
    "used": "已使用",
    "archived": "已归档",
}

APPROVAL_STATUS_LABELS = {
    "pending": "待确认",
    "approved": "已确认",
    "needs_revision": "需修改",
    "rejected": "已拒绝",
}

COPYRIGHT_STATUS_LABELS = {
    "owned": "自有素材",
    "client_provided": "客户提供",
    "licensed": "已授权",
    "ai_generated": "AI生成",
    "unknown": "待确认版权",
}
CUSTOMER_WORKSPACE_PAGES = {"/customers", "/service-board"}


async def _require_material_read(current_user: UserResponse, db: AsyncSession) -> None:
    await require_any_page_permission(db, current_user, CUSTOMER_WORKSPACE_PAGES)


async def _require_material_write(
    current_user: UserResponse,
    db: AsyncSession,
    permission: str,
    *,
    admin_override: bool = False,
) -> None:
    await _require_material_read(current_user, db)
    await require_button_permission(db, current_user, permission, admin_override=admin_override)


class CustomerMaterialData(BaseModel):
    customer_id: int
    title: str
    material_type: str = "image"
    platform: Optional[str] = "general"
    source_type: Optional[str] = "external_link"
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    linked_item_id: Optional[int] = None
    linked_item_snapshot: Optional[str] = None
    usage_status: Optional[str] = "unused"
    approval_status: Optional[str] = "pending"
    copyright_status: Optional[str] = "owned"
    is_favorite: Optional[bool] = False
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerMaterialUpdateData(BaseModel):
    title: Optional[str] = None
    material_type: Optional[str] = None
    platform: Optional[str] = None
    source_type: Optional[str] = None
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    linked_item_id: Optional[int] = None
    linked_item_snapshot: Optional[str] = None
    usage_status: Optional[str] = None
    approval_status: Optional[str] = None
    copyright_status: Optional[str] = None
    is_favorite: Optional[bool] = None
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None


class CustomerMaterialResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    customer_id: int
    title: str
    material_type: str
    platform: Optional[str] = None
    source_type: Optional[str] = None
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    linked_item_id: Optional[int] = None
    linked_item_snapshot: Optional[str] = None
    usage_status: Optional[str] = None
    approval_status: Optional[str] = None
    copyright_status: Optional[str] = None
    is_favorite: Optional[bool] = None
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerMaterialListResponse(BaseModel):
    items: List[CustomerMaterialResponse]
    total: int
    skip: int
    limit: int


class CustomerMaterialAiMatchRequest(BaseModel):
    customer_id: int
    target_platforms: List[str] = []
    extra_requirements: Optional[str] = ""


class CustomerMaterialAiMatchResponse(BaseModel):
    ai_used: bool
    warning: Optional[str] = None
    summary: str
    platform_matches: List[Dict[str, Any]] = []
    material_suggestions: List[Dict[str, Any]] = []
    cautions: List[str] = []
    next_actions: List[str] = []
    model: Optional[str] = None


def _parse_query(query: Optional[str]) -> Optional[dict]:
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


async def _resolve_linked_item(
    db: AsyncSession,
    *,
    customer_id: int,
    linked_item_id: Optional[int],
) -> tuple[Optional[int], Optional[str]]:
    if not linked_item_id:
        return None, None
    linked_item = await Customer_menu_itemsService(db).get_by_id(int(linked_item_id))
    if not linked_item or linked_item.customer_id != customer_id:
        raise HTTPException(status_code=400, detail="绑定的菜单/服务项目不存在或不属于该客户")
    return linked_item.id, linked_item.name


def _safe_filename(filename: str) -> str:
    raw = Path(filename or "material").name
    stem = Path(raw).stem or "material"
    suffix = Path(raw).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-") or "material"
    return f"{safe_stem}{suffix}"


def _material_path_from_record(file_path: Optional[str]) -> Optional[Path]:
    if not file_path:
        return None
    path = (MATERIALS_ROOT / file_path).resolve()
    try:
        path.relative_to(MATERIALS_ROOT.resolve())
    except ValueError:
        return None
    return path


async def _log_material_action(
    db: AsyncSession,
    *,
    current_user: UserResponse,
    customer_id: int,
    action_type: str,
    detail: str,
) -> None:
    try:
        await Operation_logsService(db).create(
            {
                "customer_id": customer_id,
                "action_type": action_type,
                "action_detail": detail,
                "operator_name": current_user.name or current_user.email or "系统",
                "ip_address": "",
                "created_at": datetime.utcnow(),
            },
            user_id=str(current_user.id),
        )
    except Exception as exc:  # pragma: no cover - log failure must not block business flow
        logger.warning("Failed to write customer material operation log: %s", exc)


def _label(mapping: Dict[str, str], key: Optional[str]) -> str:
    return mapping.get(key or "", key or "-")


def _customer_location(customer: Any) -> str:
    return ", ".join(
        str(part)
        for part in [getattr(customer, "city", None), getattr(customer, "state", None), getattr(customer, "country", None)]
        if part
    )


def _material_dict(material: Any) -> Dict[str, Any]:
    return {
        "id": material.id,
        "title": material.title,
        "type": material.material_type,
        "type_label": _label(MATERIAL_TYPE_LABELS, material.material_type),
        "platform": material.platform or "general",
        "platform_label": _label(PLATFORM_LABELS, material.platform),
        "usage_status": material.usage_status,
        "usage_label": _label(USAGE_STATUS_LABELS, material.usage_status),
        "approval_status": material.approval_status,
        "approval_label": _label(APPROVAL_STATUS_LABELS, material.approval_status),
        "copyright_status": material.copyright_status,
        "copyright_label": _label(COPYRIGHT_STATUS_LABELS, material.copyright_status),
        "notes": material.notes or "",
        "file_name": material.file_name or "",
        "has_file": bool(material.file_path),
        "has_link": bool(material.file_url),
        "linked_item_id": getattr(material, "linked_item_id", None),
        "linked_item_snapshot": getattr(material, "linked_item_snapshot", None) or "",
    }


def _item_dict(item: Any) -> Dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "item_type": item.item_type or "",
        "category": item.category or "",
        "price": item.price or "",
        "selling_points": item.selling_points or "",
        "suitable_platforms": item.suitable_platforms or "",
        "is_featured": bool(item.is_featured),
        "status": item.status or "active",
        "notes": item.notes or "",
    }


def _recommended_platforms(material: Any, target_platforms: List[str]) -> List[str]:
    material_type = material.material_type or "other"
    preset = {
        "menu": ["google_business", "yelp", "brand_website", "facebook"],
        "image": ["google_business", "instagram", "facebook", "xiaohongshu"],
        "video": ["instagram", "tiktok", "facebook", "xiaohongshu"],
        "logo": ["google_business", "brand_website", "facebook"],
        "screenshot": ["google_business", "brand_website", "facebook"],
        "document": ["brand_website", "google_business"],
        "design": ["instagram", "facebook", "xiaohongshu"],
        "post": ["facebook", "instagram", "xiaohongshu", "tiktok"],
    }.get(material_type, ["google_business", "facebook", "instagram"])
    if material.platform and material.platform != "general":
        preset.insert(0, material.platform)
    unique = []
    for item in preset:
        if item not in unique:
            unique.append(item)
    if target_platforms:
        scoped = [item for item in unique if item in target_platforms]
        return scoped or target_platforms[:2]
    return unique[:4]


def _fallback_material_match(
    customer: Any,
    materials: List[Any],
    request: CustomerMaterialAiMatchRequest,
    warning: Optional[str] = None,
    model: Optional[str] = None,
    menu_items: Optional[List[Any]] = None,
) -> CustomerMaterialAiMatchResponse:
    target_platforms = request.target_platforms or ["google_business", "facebook", "instagram", "yelp", "tiktok", "xiaohongshu", "brand_website", "ads_campaign"]
    item_names = {item.id: item.name for item in (menu_items or [])}
    platform_scores: Dict[str, Dict[str, Any]] = {
        platform: {"platform": platform, "platform_label": _label(PLATFORM_LABELS, platform), "matched_material_ids": [], "reason": ""}
        for platform in target_platforms
    }
    suggestions: List[Dict[str, Any]] = []
    cautions: List[str] = []

    for material in materials[:30]:
        rec_platforms = _recommended_platforms(material, target_platforms)
        for platform in rec_platforms:
            if platform not in platform_scores:
                platform_scores[platform] = {
                    "platform": platform,
                    "platform_label": _label(PLATFORM_LABELS, platform),
                    "matched_material_ids": [],
                    "reason": "",
                }
            platform_scores[platform]["matched_material_ids"].append(material.id)

        risk_notes = []
        if material.approval_status != "approved":
            risk_notes.append("发布前需要客户确认")
        if material.copyright_status in {"unknown", "rejected"}:
            risk_notes.append("版权/授权需要确认")
        if material.usage_status == "used":
            risk_notes.append("已使用过，建议换角度复用")

        linked_name = item_names.get(getattr(material, "linked_item_id", None)) or getattr(material, "linked_item_snapshot", None)
        subject = f"“{linked_name}”" if linked_name else f"{getattr(customer, 'business_name', '') or '该客户'}的服务/产品亮点"
        suggestions.append({
            "material_id": material.id,
            "title": material.title,
            "linked_item_id": getattr(material, "linked_item_id", None),
            "linked_item_name": linked_name,
            "recommended_platforms": rec_platforms,
            "recommended_platform_labels": [_label(PLATFORM_LABELS, item) for item in rec_platforms],
            "usage_idea": f"可作为{_label(MATERIAL_TYPE_LABELS, material.material_type)}素材，围绕{subject}做内容。",
            "risk_note": "；".join(risk_notes) if risk_notes else "可正常进入运营备选。",
        })

        if risk_notes:
            cautions.append(f"{material.title}：{'；'.join(risk_notes)}")

    platform_matches = []
    for value in platform_scores.values():
        matched = list(dict.fromkeys(value["matched_material_ids"]))
        value["matched_material_ids"] = matched[:10]
        value["score"] = min(100, 45 + len(matched) * 12)
        value["reason"] = "有可复用素材，可安排更新。" if matched else "当前素材不足，建议先向客户补充图片/菜单/项目资料。"
        platform_matches.append(value)
    platform_matches.sort(key=lambda item: item["score"], reverse=True)

    if not materials:
        cautions.append("当前客户暂无素材，建议先收集门头、环境、菜单、项目、Logo、客户授权等基础资料。")
    if not menu_items:
        cautions.append("当前客户暂无菜单/服务项目库，建议先录入主推菜品或服务项目，素材匹配会更准确。")

    summary = (
        f"{getattr(customer, 'business_name', '') or '该客户'} 当前有 {len(materials)} 条素材、{len(menu_items or [])} 个菜单/服务项目。"
        f"可先把未使用、已确认、有授权的素材安排到匹配平台；菜单类适合 Google/Yelp/网站，图片和视频类适合社媒平台。"
    )
    next_actions = [
        "优先使用“已确认 + 未使用 + 授权清晰”的素材。",
        "已使用素材不要原样重复发布，可以换标题、角度、平台或搭配新文案复用。",
        "素材不足时，向客户一次性补要门头、环境、菜单、项目/菜品、Logo、优惠活动信息。",
    ]
    return CustomerMaterialAiMatchResponse(
        ai_used=False,
        warning=warning,
        summary=summary,
        platform_matches=platform_matches[:8],
        material_suggestions=suggestions[:12],
        cautions=cautions[:8],
        next_actions=next_actions,
        model=model,
    )


def _build_ai_match_prompt(customer: Any, materials: List[Any], request: CustomerMaterialAiMatchRequest, menu_items: List[Any]) -> str:
    target_platforms = request.target_platforms or ["google_business", "facebook", "instagram", "yelp", "tiktok", "xiaohongshu", "brand_website", "ads_campaign"]
    material_rows = [_material_dict(item) for item in materials[:40]]
    item_rows = [_item_dict(item) for item in menu_items[:80]]
    selected_platforms = [
        _label(PLATFORM_LABELS, item.strip())
        for item in str(getattr(customer, "selected_platforms", "") or "").split(",")
        if item.strip()
    ]
    return f"""
你是一个本地商家运营主管，负责帮运营人员把客户素材和菜单/服务项目匹配到合适平台，避免素材不相关、重复使用太硬、未授权素材乱用。

只输出 JSON 对象，不要 Markdown，不要解释。JSON 格式必须包含：
{{
  "summary": "一句话总结素材情况",
  "platform_matches": [
    {{"platform": "google_business", "platform_label": "Google商家", "score": 85, "matched_material_ids": [1,2], "reason": "为什么适合"}}
  ],
  "material_suggestions": [
    {{"material_id": 1, "title": "素材名称", "recommended_platforms": ["google_business"], "recommended_platform_labels": ["Google商家"], "usage_idea": "运营怎么用", "risk_note": "注意事项"}}
  ],
  "cautions": ["风险提醒"],
  "next_actions": ["下一步动作"]
}}

要求：
1. 不要建议自动发布，只给运营使用建议。
2. 素材备注、名称、类型比链接更重要，不要假装看过图片具体内容。
3. 如果素材绑定了菜单/服务项目，必须围绕绑定项目给建议；如果没绑定，只能做通用建议。
4. 如果素材是菜单/项目/文档，更适合 Google商家、Yelp、网站或 Facebook 信息型内容。
5. 如果素材是图片/视频/设计稿，更适合 Instagram、Facebook、小红书、TikTok。
5. 未确认、版权未知、已拒绝素材必须提醒不要直接发布。
6. 已使用素材可以复用，但要换角度、换文案或换平台。

客户资料：
- 商家名称：{getattr(customer, "business_name", "")}
- 行业：{getattr(customer, "industry", "") or "-"}
- 地区：{_customer_location(customer) or "-"}
- 合作/意向套餐：{getattr(customer, "interested_packages", "") or "-"}
- 当前平台：{getattr(customer, "current_platform", "") or "-"}
- 平台选择：{"、".join(selected_platforms) if selected_platforms else "-"}
- 备注：{getattr(customer, "notes", "") or "-"}

目标平台：{", ".join(_label(PLATFORM_LABELS, item) for item in target_platforms)}
额外要求：{request.extra_requirements or "-"}

菜单/服务项目库 JSON：
{json.dumps(item_rows, ensure_ascii=False)}

素材列表 JSON：
{json.dumps(material_rows, ensure_ascii=False)}
""".strip()


def _extract_ai_match(raw: str, fallback: CustomerMaterialAiMatchResponse) -> CustomerMaterialAiMatchResponse:
    text = (raw or "").strip()
    candidates = [text]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.insert(0, match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                continue
            return CustomerMaterialAiMatchResponse(
                ai_used=True,
                warning=None,
                summary=str(parsed.get("summary") or fallback.summary),
                platform_matches=parsed.get("platform_matches") if isinstance(parsed.get("platform_matches"), list) else fallback.platform_matches,
                material_suggestions=parsed.get("material_suggestions") if isinstance(parsed.get("material_suggestions"), list) else fallback.material_suggestions,
                cautions=parsed.get("cautions") if isinstance(parsed.get("cautions"), list) else fallback.cautions,
                next_actions=parsed.get("next_actions") if isinstance(parsed.get("next_actions"), list) else fallback.next_actions,
                model=fallback.model,
            )
        except Exception:
            continue
    return CustomerMaterialAiMatchResponse(
        **fallback.model_dump(exclude={"warning", "ai_used"}),
        ai_used=False,
        warning="AI返回内容无法解析，已使用规则生成基础匹配建议。",
    )


@router.get("", response_model=CustomerMaterialListResponse)
async def query_customer_materials(
    query: str = Query(None),
    sort: str = Query("-created_at"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_read(current_user, db)
    query_dict = _parse_query(query) or {}
    customer_id = query_dict.get("customer_id")
    if customer_id:
        await _ensure_customer_access(int(customer_id), current_user, db)
    elif normalized_role(current_user) not in {"admin", "super_admin"}:
        raise HTTPException(status_code=400, detail="customer_id query is required")

    return await Customer_materialsService(db).get_list(
        skip=skip,
        limit=limit,
        query_dict=query_dict,
        sort=sort,
    )


@router.post("/ai-match", response_model=CustomerMaterialAiMatchResponse)
async def ai_match_customer_materials(
    request: CustomerMaterialAiMatchRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_create")
    customer = await _ensure_customer_access(request.customer_id, current_user, db)
    result = await Customer_materialsService(db).get_list(
        skip=0,
        limit=200,
        query_dict={"customer_id": request.customer_id},
        sort="-created_at",
    )
    materials = result["items"]
    item_result = await Customer_menu_itemsService(db).get_list(
        skip=0,
        limit=300,
        query_dict={"customer_id": request.customer_id},
        sort="-updated_at",
    )
    menu_items = item_result["items"]
    runtime = await resolve_ai_runtime_config(db)
    fallback = _fallback_material_match(customer, materials, request, model=runtime.model, menu_items=menu_items)

    if not materials:
        return fallback
    if not runtime.enabled:
        fallback.warning = "AI尚未启用，已使用规则生成基础匹配建议。"
        return fallback

    prompt = _build_ai_match_prompt(customer, materials, request, menu_items)
    try:
        service = AIHubService(api_key=runtime.api_key, base_url=runtime.base_url)
        response = await service.gentxt(
            GenTxtRequest(
                messages=[
                    ChatMessage(role="system", content="你是严谨的素材运营匹配助手，只输出符合要求的 JSON。"),
                    ChatMessage(role="user", content=prompt),
                ],
                model=runtime.model,
                temperature=0.35,
                max_tokens=2200,
            )
        )
        return _extract_ai_match(response.content, fallback)
    except Exception as exc:
        logger.warning("AI material matching fallback used: %s", exc)
        return _fallback_material_match(
            customer,
            materials,
            request,
            warning=f"{humanize_ai_error(exc)}已使用规则生成基础匹配建议。",
            model=runtime.model,
            menu_items=menu_items,
        )


@router.post("", response_model=CustomerMaterialResponse, status_code=201)
async def create_customer_material(
    data: CustomerMaterialData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_create")
    await _ensure_customer_access(data.customer_id, current_user, db)
    payload = data.model_dump()
    now = datetime.utcnow()
    payload["title"] = payload["title"].strip()
    if not payload["title"]:
        raise HTTPException(status_code=400, detail="素材名称不能为空")
    payload["linked_item_id"], payload["linked_item_snapshot"] = await _resolve_linked_item(
        db,
        customer_id=data.customer_id,
        linked_item_id=payload.get("linked_item_id"),
    )
    payload["created_at"] = payload.get("created_at") or now
    payload["updated_at"] = payload.get("updated_at") or now
    payload["source_type"] = payload.get("source_type") or "external_link"

    result = await Customer_materialsService(db).create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=result.customer_id,
        action_type="create_material",
        detail=f"新增素材: {result.title}",
    )
    return result


@router.post("/upload", response_model=CustomerMaterialResponse, status_code=201)
async def upload_customer_material(
    customer_id: int = Form(...),
    title: str = Form(...),
    material_type: str = Form("image"),
    platform: str = Form("general"),
    usage_status: str = Form("unused"),
    approval_status: str = Form("pending"),
    copyright_status: str = Form("owned"),
    linked_item_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    thumbnail_url: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_create")
    await _ensure_customer_access(customer_id, current_user, db)
    resolved_linked_item_id, linked_item_snapshot = await _resolve_linked_item(
        db,
        customer_id=customer_id,
        linked_item_id=linked_item_id,
    )

    safe_name = _safe_filename(file.filename or "material")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    customer_dir = MATERIALS_ROOT / str(customer_id)
    customer_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}_{safe_name}"
    target_path = customer_dir / stored_name
    file_size = 0

    try:
        with target_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE:
                    output.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="文件不能超过 30MB")
                output.write(chunk)
    finally:
        await file.close()

    now = datetime.utcnow()
    payload = {
        "customer_id": customer_id,
        "title": title.strip() or safe_name,
        "material_type": material_type,
        "platform": platform,
        "source_type": "upload",
        "file_name": safe_name,
        "file_path": f"{customer_id}/{stored_name}",
        "file_url": None,
        "thumbnail_url": thumbnail_url,
        "content_type": file.content_type,
        "file_size": file_size,
        "linked_item_id": resolved_linked_item_id,
        "linked_item_snapshot": linked_item_snapshot,
        "usage_status": usage_status,
        "approval_status": approval_status,
        "copyright_status": copyright_status,
        "is_favorite": False,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }

    result = await Customer_materialsService(db).create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=customer_id,
        action_type="create_material",
        detail=f"上传素材: {result.title}",
    )
    return result


@router.put("/{material_id}", response_model=CustomerMaterialResponse)
async def update_customer_material(
    material_id: int,
    data: CustomerMaterialUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_edit")
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    payload = data.model_dump(exclude_unset=True)
    if "linked_item_id" in payload:
        payload["linked_item_id"], payload["linked_item_snapshot"] = await _resolve_linked_item(
            db,
            customer_id=obj.customer_id,
            linked_item_id=payload.get("linked_item_id"),
        )
    payload["updated_at"] = payload.get("updated_at") or datetime.utcnow()
    updated = await service.update(material_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Material not found")

    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=updated.customer_id,
        action_type="edit_material",
        detail=f"编辑素材: {updated.title}",
    )
    return updated


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_delete", admin_override=True)
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = _material_path_from_record(obj.file_path)
    deleted = await service.delete(material_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Material not found")
    if file_path and file_path.exists():
        file_path.unlink(missing_ok=True)

    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=obj.customer_id,
        action_type="delete_material",
        detail=f"删除素材: {obj.title}",
    )


@router.get("/{material_id}/download")
async def download_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_read(current_user, db)
    obj = await Customer_materialsService(db).get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = _material_path_from_record(obj.file_path)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="素材文件不存在")

    return FileResponse(
        file_path,
        media_type=obj.content_type or "application/octet-stream",
        filename=obj.file_name or file_path.name,
    )


@router.post("/{material_id}/duplicate", response_model=CustomerMaterialResponse, status_code=201)
async def duplicate_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_material_write(current_user, db, "task_create")
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = None
    next_file_path = None
    if obj.file_path:
        file_path = _material_path_from_record(obj.file_path)
        if file_path and file_path.exists():
            next_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}_{file_path.name}"
            next_path = file_path.parent / next_name
            shutil.copyfile(file_path, next_path)
            next_file_path = f"{obj.customer_id}/{next_name}"

    now = datetime.utcnow()
    payload = {
        "customer_id": obj.customer_id,
        "title": f"{obj.title} 副本",
        "material_type": obj.material_type,
        "platform": obj.platform,
        "source_type": obj.source_type,
        "file_name": obj.file_name,
        "file_path": next_file_path or obj.file_path,
        "file_url": obj.file_url,
        "thumbnail_url": obj.thumbnail_url,
        "content_type": obj.content_type,
        "file_size": obj.file_size,
        "linked_item_id": obj.linked_item_id,
        "linked_item_snapshot": obj.linked_item_snapshot,
        "usage_status": "unused",
        "approval_status": obj.approval_status,
        "copyright_status": obj.copyright_status,
        "is_favorite": False,
        "notes": obj.notes,
        "created_at": now,
        "updated_at": now,
    }
    duplicated = await service.create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=obj.customer_id,
        action_type="create_material",
        detail=f"复制素材: {obj.title}",
    )
    return duplicated

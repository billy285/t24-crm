import hashlib
import json
import re
from typing import Any, Callable, Dict

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from schemas.auth import UserResponse
from services.schema_readiness import (
    APP_SETTINGS_TABLE,
    SchemaUnavailableError,
    require_tables,
    tables_available,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/app-config", tags=["app-config"])

ADMIN_CONFIG_ROLES = {"admin", "super_admin"}
BUSINESS_DICT_CONFIG_ROLES = {"admin", "super_admin", "ops", "operations"}
SENSITIVE_CONFIG_KEYS = {"payroll_sheets_v1"}
CUSTOMER_FOLLOWUP_ACTIVE = "customerFollowUpStatuses"
CUSTOMER_FOLLOWUP_ARCHIVE = "customerFollowUpStatusArchive"
CUSTOMER_FOLLOWUP_FIELDS = (CUSTOMER_FOLLOWUP_ACTIVE, CUSTOMER_FOLLOWUP_ARCHIVE)
DEFAULT_CUSTOMER_FOLLOWUP_STATUSES = (
    "in_service:正常服务,awaiting_reply:待客户回复,needs_coordination:需协调处理,"
    "renewal_followup:续费跟进,upsell_discussion:增购沟通,paused_service:暂停服务,"
    "service_ended:服务结束,service_follow_later:后续跟进"
)


DEFAULT_APP_CONFIGS: Dict[str, Any] = {
    "role_permissions": {
        "super_admin": {
            "pages": [
                "/",
                "/merchant-pool",
                "/sales-leads",
                "/customers",
                "/sales",
                "/deals",
                "/finance",
                "/finance-entry",
                "/rmb-profit",
                "/partner-portal",
                "/tasks",
                "/service-board",
                "/media-ops",
                "/callbacks",
                "/employees",
                "/settings",
                "/settings/deduction",
                "/permissions",
            ],
            "buttons": [
                "customer_create",
                "customer_edit",
                "customer_delete",
                "customer_export",
                "customer_assign",
                "customer_transfer",
                "view_password",
                "copy_password",
                "employee_create",
                "employee_edit",
                "employee_disable",
                "employee_reset_password",
                "deal_create",
                "deal_edit",
                "payment_create",
                "payment_edit",
                "task_create",
                "task_edit",
                "task_delete",
                "follow_up_create",
                "follow_up_edit",
                "follow_up_delete",
                "media_account_create",
                "media_account_edit",
                "media_account_delete",
                "settings_edit",
                "permission_edit",
            ],
            "dataScope": "all",
            "sensitiveFields": {"viewPassword": True, "copyPassword": True, "viewFinance": True},
        },
        "admin": {
            "pages": [
                "/",
                "/merchant-pool",
                "/sales-leads",
                "/customers",
                "/sales",
                "/deals",
                "/finance",
                "/rmb-profit",
                "/tasks",
                "/service-board",
                "/media-ops",
                "/callbacks",
                "/employees",
                "/settings",
                "/settings/deduction",
                "/permissions",
            ],
            "buttons": [
                "customer_create",
                "customer_edit",
                "customer_delete",
                "customer_export",
                "customer_assign",
                "customer_transfer",
                "view_password",
                "copy_password",
                "employee_create",
                "employee_edit",
                "employee_disable",
                "employee_reset_password",
                "deal_create",
                "deal_edit",
                "payment_create",
                "payment_edit",
                "task_create",
                "task_edit",
                "task_delete",
                "follow_up_create",
                "follow_up_edit",
                "follow_up_delete",
                "media_account_create",
                "media_account_edit",
                "media_account_delete",
                "settings_edit",
                "permission_edit",
            ],
            "dataScope": "all",
            "sensitiveFields": {"viewPassword": True, "copyPassword": True, "viewFinance": True},
        },
        "sales": {
            "pages": ["/customers", "/sales-leads"],
            "buttons": [],
            "dataScope": "self",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "sales_manager": {
            "pages": ["/customers", "/merchant-pool", "/sales-leads"],
            "buttons": [],
            "dataScope": "department",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "sales_partner": {
            "pages": ["/partner-portal"],
            "buttons": [],
            "dataScope": "self",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "ops": {
            "pages": ["/", "/customers", "/tasks", "/service-board", "/media-ops"],
            "buttons": [
                "customer_edit",
                "task_create",
                "task_edit",
                "media_account_create",
                "media_account_edit",
                "follow_up_create",
                "follow_up_edit",
            ],
            "dataScope": "all",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "design": {
            "pages": ["/", "/tasks"],
            "buttons": ["task_edit"],
            "dataScope": "self",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "finance": {
            "pages": ["/", "/finance-entry", "/customers", "/service-board"],
            "buttons": ["finance_draft_create", "finance_draft_edit", "finance_draft_submit"],
            "dataScope": "self",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
    },
    "customer_code_settings": {
        "useIndustryPrefix": False,
        "defaultPrefix": "C",
        "industryPrefixes": [
            {"industry": "restaurant", "prefix": "R", "label": "餐厅"},
            {"industry": "nail", "prefix": "N", "label": "美甲"},
            {"industry": "massage", "prefix": "M", "label": "按摩"},
            {"industry": "beauty", "prefix": "B", "label": "美容"},
            {"industry": "supermarket", "prefix": "S", "label": "超市"},
            {"industry": "other", "prefix": "O", "label": "其他"},
        ],
        "digitCount": 4,
        "includeYear": True,
        "separator": "",
    },
    "company_info": {"name": "", "address": "", "phone": "", "email": "", "website": "", "logo": "", "description": ""},
    "dict_config": {
        "industries": "restaurant:餐厅,nail:美甲,massage:按摩,beauty:美容,supermarket:超市,other:其他",
        "statuses": "new:新线索,following:跟进中,closed:已成交,paused:暂停,lost:流失",
        "sources": "phone:电话销售,referral:转介绍,ads:广告,private:私域,returning:老客户,other:其他",
        "levels": "high:高意向,normal:普通,low:低意向,vip:VIP",
        "products": "ordering_system:线上点餐系统,social_media:新媒体代运营,ads:广告投放,website:网站设计,combo:组合套餐",
        "incomeTypes": "management_fee:管理费,ads_fee:投流费,management_ads_mixed:管理费+投流费,website_fee:网站费,ordering_fee:点餐系统费,renewal_fee:续费收入,other_income:其他收入",
        "customerPackages": "basic_package:基础套餐,advanced_package:进阶套餐,professional_package:专业套餐,flagship_package:旗舰套餐,custom_package:定制套餐",
        "customerPackagePlatforms": "",
        "countries": "US:美国,CA:加拿大,GB:英国,AU:澳大利亚",
        "billingCycles": "monthly:月付,quarterly:季付,semi_annual:半年付,annual:年付",
        "paymentModes": "subscription_auto:自动订阅扣款,manual_collection:手动收款",
        "paymentMethods": "stripe:Stripe自动扣款,check:支票,zelle:Zelle,apple_cash:Apple Cash,venmo:Venmo,wire:电汇,cash:现金,credit_card:信用卡,other:其他",
        "customerExpenseTypes": "ads_fee:投流成本,website_fee:网站成本,domain_fee:域名费,hosting_fee:主机/服务器费,design_fee:设计制作费,other:其他客户成本",
        "companyExpenseTypes": "salary:工资,internet:网络费,phone:电话费,rent:办公室租金,software:软件订阅费,ai_tools:AI工具费,cloud_services:云服务费,operations_tools:运营工具费,recruitment:招聘费,travel:差旅费,other_company:其他支出",
        "subscriptionStatuses": "active:正常,expiring_soon:即将到期,renewal_pending:待扣款确认,expired:已到期,renewed:已续费,upgraded:已升级结束,stopped:停止续费,paused:暂停,lost:流失",
        "followUpStages": "new_lead:新线索,contacted:已联系,communicating:沟通中,quoted:已报价,considering:考虑中,pending_close:待成交,closed:已成交,not_closed:未成交,lost:流失,follow_later:后续再跟进",
        CUSTOMER_FOLLOWUP_ACTIVE: DEFAULT_CUSTOMER_FOLLOWUP_STATUSES,
        CUSTOMER_FOLLOWUP_ARCHIVE: "",
        "followUpMethods": "phone:电话,wechat:微信,sms:短信,email:邮件",
        "callbackTypes": "satisfaction:满意度回访,renewal:续费提醒,upsell:增值服务推荐,maintenance:售后维护,feedback:意见收集,other:其他",
        "callbackStatuses": "pending:待回访,completed:已完成,no_answer:未接通,rescheduled:已改期,cancelled:已取消",
        "callbackResults": "satisfied:满意,neutral:一般,unsatisfied:不满意,interested:有意向,not_interested:无意向,need_followup:需再跟进",
        "taskTypes": "follow_up:跟进客户,design:设计页面,menu_entry:菜单录入,stripe_setup:Stripe配置,google_auth:Google权限,test_order:测试订单,report:周报提交,renewal_reminder:续费催款,other:其他",
        "taskPriorities": "high:高,medium:中,low:低",
        "taskStatuses": "pending:待处理,in_progress:进行中,completed:已完成,delayed:延期",
    },
    "dashboard_config": {
        "showTotalCustomers": True,
        "showFollowing": True,
        "showClosedMonth": True,
        "showExpiring": True,
        "showRevenue": True,
        "showOverdue": True,
        "showPendingTasks": True,
        "showLost": True,
        "showReminders": True,
        "showRecentCustomers": True,
        "showUpcomingTasks": True,
    },
    "reminder_config": {
        "enableFollowUpReminder": True,
        "followUpDaysBefore": 0,
        "enableExpiryReminder": True,
        "expiryDaysBefore": 7,
        "enableNoFollowReminder": True,
        "noFollowDays": 7,
        "enableOverduePayment": True,
        "enableDelayedTask": True,
    },
    "security_config": {
        "passwordViewRoles": ["super_admin", "admin"],
        "logPasswordViews": True,
        "requireConfirmDelete": True,
        "enableSoftDelete": False,
    },
    "notification_config": {"enableBrowserNotif": False, "enableEmailNotif": False, "notifEmail": ""},
    "export_config": {
        "exportRoles": ["super_admin", "admin", "sales", "finance"],
        "defaultFormat": "xlsx",
        "includeNotes": True,
        "includeSocialLinks": True,
    },
    "payroll_sheets_v1": {"version": 1, "updated_at": None, "sheets": []},
}


class AppConfigValue(BaseModel):
    key: str
    value: Any
    updated_at: str | None = None


class AppConfigUpdate(BaseModel):
    value: Any


class CustomerFollowUpStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    active: StrictStr = Field(max_length=32768)
    archive: StrictStr = Field(max_length=32768)


def customer_followup_fields(value: dict) -> dict[str, str]:
    """Only missing service fields receive defaults; old dictionaries stay intact."""
    return {
        CUSTOMER_FOLLOWUP_ACTIVE: value.get(CUSTOMER_FOLLOWUP_ACTIVE, DEFAULT_CUSTOMER_FOLLOWUP_STATUSES),
        CUSTOMER_FOLLOWUP_ARCHIVE: value.get(CUSTOMER_FOLLOWUP_ARCHIVE, ""),
    }


def validate_customer_followup_fields(active: Any, archive: Any) -> tuple[str, str, set[str]]:
    keys, labels = set(), set()
    normalized = []
    for field in (active, archive):
        if not isinstance(field, str) or len(field) > 32768:
            raise HTTPException(status_code=422, detail="服务跟进阶段须为字符串")
        entries = []
        if field:
            for item in field.split(","):
                if item.count(":") != 1 or not item.isprintable():
                    raise HTTPException(status_code=422, detail="服务跟进阶段格式应为 key:名称，名称不能包含逗号或冒号")
                key, label = (part.strip() for part in item.split(":", 1))
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
                    raise HTTPException(status_code=422, detail="阶段标识须以小写字母开头，仅含小写字母、数字或下划线，最多64位")
                if not 1 <= len(label) <= 40 or not label.isprintable() or any(char in label for char in ",:，："):
                    raise HTTPException(status_code=422, detail="阶段名称须为1至40字，不能包含逗号、冒号或控制字符")
                if key in keys or label.casefold() in labels:
                    raise HTTPException(status_code=422, detail="启用及停用阶段的标识和名称必须各自唯一")
                keys.add(key)
                labels.add(label.casefold())
                entries.append(f"{key}:{label}")
        normalized.append(",".join(entries))
    if not normalized[0]:
        raise HTTPException(status_code=422, detail="至少保留一个启用的服务跟进阶段")
    return normalized[0], normalized[1], keys


def customer_followup_result(value: dict) -> dict[str, str]:
    fields = customer_followup_fields(value)
    active, archive, _ = validate_customer_followup_fields(*[fields[key] for key in CUSTOMER_FOLLOWUP_FIELDS])
    body = json.dumps({"active": active, "archive": archive}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"active": active, "archive": archive, "revision": hashlib.sha256(body.encode()).hexdigest()}


async def require_config_table(db: AsyncSession) -> None:
    try:
        await require_tables(db, {APP_SETTINGS_TABLE})
    except SchemaUnavailableError as exc:
        raise HTTPException(status_code=503, detail="数据库结构尚未升级，暂时无法保存系统配置，请联系管理员") from exc


async def save_dictionary_cas(db: AsyncSession, build: Callable[[dict], dict]) -> dict:
    """Full-row SQL CAS lets service-only revisions merge concurrent other fields.

    A retry always rereads the dictionary. No stale read can replace a newer
    service field or unrelated dictionary value, including first-row creation.
    """
    await require_config_table(db)
    for _attempt in range(6):
        result = await db.execute(text("SELECT value_json FROM app_settings WHERE config_key = :key"), {"key": "dict_config"})
        row = result.fetchone()
        try:
            previous = json.loads(row[0]) if row else {}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=409, detail="现有业务字典格式异常，请先核对配置") from exc
        if not isinstance(previous, dict):
            raise HTTPException(status_code=409, detail="现有业务字典格式异常，请先核对配置")
        updated = build(previous)
        params = {"key": "dict_config", "value_json": json.dumps(updated, ensure_ascii=False)}
        try:
            if row:
                params["previous_json"] = row[0]
                saved = await db.execute(text("UPDATE app_settings SET value_json = :value_json, updated_at = CURRENT_TIMESTAMP WHERE config_key = :key AND value_json = :previous_json"), params)
            else:
                saved = await db.execute(text("INSERT INTO app_settings (config_key, value_json, updated_at) VALUES (:key, :value_json, CURRENT_TIMESTAMP) ON CONFLICT(config_key) DO NOTHING"), params)
            if saved.rowcount == 1:
                await db.commit()
                return updated
        except OperationalError as exc:
            # SQLite can reject a read-to-write snapshot upgrade. Retry only
            # known lock errors; other database errors must remain visible.
            if getattr(exc.orig, "sqlite_errorcode", None) not in {5, 6, 517}:
                raise
        await db.rollback()
    raise HTTPException(status_code=409, detail="配置正在由其他同事更新，请重新读取后重试")


def get_default_config(key: str) -> Any:
    if key not in DEFAULT_APP_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    return DEFAULT_APP_CONFIGS[key]


def ensure_can_update_config(key: str, user: UserResponse) -> None:
    """Keep sensitive settings admin-only while allowing business teams to maintain dictionaries."""
    if key in {"role_permissions", "page_permissions"} and user.role != "super_admin":
        raise HTTPException(status_code=403, detail="仅老板可以修改访问权限")
    if user.role in ADMIN_CONFIG_ROLES:
        return

    if key == "dict_config" and user.role in BUSINESS_DICT_CONFIG_ROLES:
        return

    detail = "当前账号没有维护业务字典的权限" if key == "dict_config" else "Admin access required"
    raise HTTPException(status_code=403, detail=detail)


def ensure_can_read_config(key: str, user: UserResponse) -> None:
    if user.role == "sales_partner":
        raise HTTPException(status_code=403, detail="Partner portal does not expose application configuration")
    if key in SENSITIVE_CONFIG_KEYS and user.role not in ADMIN_CONFIG_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")


async def read_config_value(
    db: AsyncSession,
    key: str,
    *,
    app_settings_available: bool | None = None,
) -> AppConfigValue:
    default_value = get_default_config(key)
    if app_settings_available is None:
        app_settings_available = await tables_available(db, {APP_SETTINGS_TABLE})
    if not app_settings_available:
        return AppConfigValue(key=key, value=default_value, updated_at=None)

    result = await db.execute(
        text("SELECT value_json, updated_at FROM app_settings WHERE config_key = :key"),
        {"key": key},
    )
    row = result.fetchone()
    if not row:
        return AppConfigValue(key=key, value=default_value, updated_at=None)

    try:
        value = json.loads(row[0])
    except Exception:
        value = default_value
    if key == "dict_config" and isinstance(value, dict):
        value = {**value, **customer_followup_fields(value)}
    updated_at = row[1].isoformat() if row[1] is not None and hasattr(row[1], "isoformat") else None
    return AppConfigValue(key=key, value=value, updated_at=updated_at)


@router.get("")
async def get_all_app_configs(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # External partner accounts use frontend defaults for their single portal.
    # Returning no configuration avoids exposing internal company, security,
    # notification, export, or cross-role permission settings.
    if current_user.role == "sales_partner":
        return {"items": {}}
    app_settings_available = await tables_available(db, {APP_SETTINGS_TABLE})
    items = {}
    for key in DEFAULT_APP_CONFIGS:
        if key in SENSITIVE_CONFIG_KEYS and current_user.role not in ADMIN_CONFIG_ROLES:
            continue
        items[key] = (
            await read_config_value(db, key, app_settings_available=app_settings_available)
        ).model_dump()
    return {"items": items}


@router.get("/dict_config/customer-followup-statuses")
async def get_customer_followup_statuses(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_can_read_config("dict_config", current_user)
    config = await read_config_value(db, "dict_config")
    if not isinstance(config.value, dict):
        raise HTTPException(status_code=409, detail="现有业务字典格式异常，请先核对配置")
    return customer_followup_result(config.value)


@router.patch("/dict_config/customer-followup-statuses")
async def update_customer_followup_statuses(
    payload: CustomerFollowUpStatusUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ADMIN_CONFIG_ROLES:
        raise HTTPException(status_code=403, detail="仅管理员可以维护服务跟进阶段")
    active, archive, keys = validate_customer_followup_fields(payload.active, payload.archive)

    def apply(previous: dict) -> dict:
        current = customer_followup_result(previous)
        if current["revision"] != payload.expected_revision:
            raise HTTPException(status_code=409, detail="服务跟进阶段已由其他同事更新，请重新读取后重试")
        _, _, old_keys = validate_customer_followup_fields(current["active"], current["archive"])
        if not old_keys <= keys:
            raise HTTPException(status_code=422, detail="已有阶段标识不能删除或更换；不再使用的阶段请移至停用区")
        return {**previous, CUSTOMER_FOLLOWUP_ACTIVE: active, CUSTOMER_FOLLOWUP_ARCHIVE: archive}

    return customer_followup_result(await save_dictionary_cas(db, apply))


@router.get("/{key}", response_model=AppConfigValue)
async def get_app_config(
    key: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    get_default_config(key)
    ensure_can_read_config(key, current_user)
    return await read_config_value(db, key)


@router.put("/{key}", response_model=AppConfigValue)
async def update_app_config(
    key: str,
    payload: AppConfigUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    get_default_config(key)
    ensure_can_update_config(key, current_user)
    if key == "dict_config":
        if not isinstance(payload.value, dict):
            raise HTTPException(status_code=422, detail="业务字典须为对象")
        checked = False

        def apply(previous: dict) -> dict:
            nonlocal checked
            current_fields = customer_followup_fields(previous)
            if not checked:
                if any(field in payload.value and payload.value[field] != current_fields[field] for field in CUSTOMER_FOLLOWUP_FIELDS):
                    status = 409 if current_user.role in ADMIN_CONFIG_ROLES else 403
                    raise HTTPException(status_code=status, detail="服务跟进阶段须通过专用管理入口及最新版本确认后修改")
                checked = True
            return {**payload.value, **current_fields}

        await save_dictionary_cas(db, apply)
        return await read_config_value(db, key)
    try:
        await require_tables(db, {APP_SETTINGS_TABLE})
    except SchemaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库结构尚未升级，暂时无法保存系统配置，请联系管理员",
        ) from exc
    value_json = json.dumps(payload.value, ensure_ascii=False)
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
        {"key": key, "value_json": value_json},
    )
    await db.commit()
    return await read_config_value(db, key)

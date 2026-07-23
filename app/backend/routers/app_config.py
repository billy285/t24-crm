import json
from typing import Any, Dict

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from schemas.auth import UserResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/app-config", tags=["app-config"])

ADMIN_CONFIG_ROLES = {"admin", "super_admin"}
BUSINESS_DICT_CONFIG_ROLES = {"admin", "super_admin", "ops", "operations", "finance"}
SENSITIVE_CONFIG_KEYS = {"payroll_sheets_v1"}


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
                "/tasks",
                "/service-board",
                "/callbacks",
                "/employees",
                "/settings",
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
                "/tasks",
                "/service-board",
                "/callbacks",
                "/employees",
                "/settings",
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
            "pages": ["/sales-leads"],
            "buttons": [],
            "dataScope": "self",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "sales_manager": {
            "pages": ["/merchant-pool", "/sales-leads"],
            "buttons": [],
            "dataScope": "department",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": False},
        },
        "ops": {
            "pages": ["/", "/customers", "/tasks", "/service-board"],
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
            "pages": ["/", "/finance", "/customers", "/service-board"],
            "buttons": ["payment_create", "payment_edit", "customer_export"],
            "dataScope": "all",
            "sensitiveFields": {"viewPassword": False, "copyPassword": False, "viewFinance": True},
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


async def ensure_app_config_table(db: AsyncSession) -> None:
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


def get_default_config(key: str) -> Any:
    if key not in DEFAULT_APP_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    return DEFAULT_APP_CONFIGS[key]


def ensure_can_update_config(key: str, user: UserResponse) -> None:
    """Keep sensitive settings admin-only while allowing business teams to maintain dictionaries."""
    if user.role in ADMIN_CONFIG_ROLES:
        return

    if key == "dict_config" and user.role in BUSINESS_DICT_CONFIG_ROLES:
        return

    detail = "当前账号没有维护业务字典的权限" if key == "dict_config" else "Admin access required"
    raise HTTPException(status_code=403, detail=detail)


def ensure_can_read_config(key: str, user: UserResponse) -> None:
    if key in SENSITIVE_CONFIG_KEYS and user.role not in ADMIN_CONFIG_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")


async def read_config_value(db: AsyncSession, key: str) -> AppConfigValue:
    default_value = get_default_config(key)
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
    updated_at = row[1].isoformat() if row[1] is not None and hasattr(row[1], "isoformat") else None
    return AppConfigValue(key=key, value=value, updated_at=updated_at)


@router.get("")
async def get_all_app_configs(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_app_config_table(db)
    items = {}
    for key in DEFAULT_APP_CONFIGS:
        if key in SENSITIVE_CONFIG_KEYS and current_user.role not in ADMIN_CONFIG_ROLES:
            continue
        items[key] = (await read_config_value(db, key)).model_dump()
    return {"items": items}


@router.get("/{key}", response_model=AppConfigValue)
async def get_app_config(
    key: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    get_default_config(key)
    ensure_can_read_config(key, current_user)
    await ensure_app_config_table(db)
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
    await ensure_app_config_table(db)
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

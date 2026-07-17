import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.sales_knowledge_articles import SalesKnowledgeArticles, SalesKnowledgeQuestions
from schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/sales-knowledge", tags=["sales-knowledge"])

SALES_KNOWLEDGE_ROLES = {"sales", "sales_manager", "admin", "super_admin"}
KNOWLEDGE_MANAGE_ROLES = {"sales_manager", "admin", "super_admin"}


def _role(user: UserResponse) -> str:
    return str(user.role or "").strip().lower()


def _employee_id(user: UserResponse) -> int:
    try:
        return int(user.id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="当前账号未关联有效员工")


def _ensure_access(user: UserResponse) -> None:
    if _role(user) not in SALES_KNOWLEDGE_ROLES:
        raise HTTPException(status_code=403, detail="无权访问销售知识库")


def _ensure_manage(user: UserResponse) -> None:
    _ensure_access(user)
    if _role(user) not in KNOWLEDGE_MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="只有销售主管或管理员可以维护销售知识库")


def _list_json(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _article_data(article: SalesKnowledgeArticles) -> dict:
    return {
        "id": article.id,
        "category": article.category,
        "title": article.title,
        "customer_question": article.customer_question,
        "standard_answer": article.standard_answer,
        "action_steps": _list_json(article.action_steps),
        "related_links": _list_json(article.related_links),
        "escalation_rule": article.escalation_rule,
        "tags": _list_json(article.tags),
        "status": article.status,
        "is_sensitive": article.is_sensitive,
        "sort_order": article.sort_order,
        "created_by_name": article.created_by_name,
        "published_by_name": article.published_by_name,
        "published_at": article.published_at,
        "updated_at": article.updated_at,
    }


def _question_data(question: SalesKnowledgeQuestions) -> dict:
    return {
        "id": question.id,
        "question": question.question,
        "context": question.context,
        "status": question.status,
        "submitted_by_name": question.submitted_by_name,
        "resolved_article_id": question.resolved_article_id,
        "created_at": question.created_at,
        "resolved_at": question.resolved_at,
    }


class KnowledgeArticlePayload(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    customer_question: Optional[str] = Field(default=None, max_length=2000)
    standard_answer: str = Field(min_length=1, max_length=8000)
    action_steps: list[str] = Field(default_factory=list, max_length=12)
    related_links: list[str] = Field(default_factory=list, max_length=8)
    escalation_rule: Optional[str] = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    is_sensitive: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)

    @field_validator("category", "title", "standard_answer")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class KnowledgeQuestionPayload(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    context: Optional[str] = Field(default=None, max_length=2000)


class ResolveQuestionPayload(BaseModel):
    resolved_article_id: Optional[int] = None


SEED_ARTICLES = [
    {
        "category": "收款与付款",
        "title": "客户怎么付款？",
        "customer_question": "客户问可以用什么方式付款？",
        "standard_answer": "餐厅和美业系统可通过官网订阅页面付款。代运营服务由财务发送专属 Stripe 支付链接。也可按公司收款说明使用支票或 Zelle。销售负责发送说明和记录客户反馈，是否到账只能由财务确认。",
        "action_steps": ["确认客户购买的是系统、代运营或定制服务", "系统订阅引导客户进入官网订阅页面", "代运营或定制服务向财务申请专属付款链接", "记录付款方式、金额和客户承诺时间", "收到截图或支票信息后提交财务确认"],
        "escalation_rule": "客户要求拆分付款、改变收款主体、退款或自定义账期时，必须找主管或财务确认。",
        "tags": ["付款", "Stripe", "支票", "Zelle", "到账确认"],
        "is_sensitive": True,
        "sort_order": 10,
    },
    {
        "category": "收款与付款",
        "title": "支票写给谁？",
        "customer_question": "客户问支票抬头应该怎么写？",
        "standard_answer": "支票抬头请写 PIXELPATE INC。请客户在备注栏写明商家名称和购买的服务。开好后拍清晰正反面给销售或财务留档；销售不能自行确认到账。",
        "action_steps": ["确认支票抬头为 PIXELPATE INC", "提醒客户备注商家名称和服务项目", "收集清晰正反面照片并记录金额", "提交财务确认到账后再更新收款状态"],
        "escalation_rule": "支票金额、抬头、日期或签名异常时，不要让客户自行改写；请财务给出处理方式。",
        "tags": ["支票", "收款", "PIXELPATE INC"],
        "is_sensitive": True,
        "sort_order": 20,
    },
    {
        "category": "收款与付款",
        "title": "Zelle 如何付款？",
        "customer_question": "客户要 Zelle 收款信息，销售怎么回复？",
        "standard_answer": "Zelle 收款主体为 PIXELPATE INC，收款联系方式为 510-641-2566。请客户付款时备注商家名称和服务项目，并在完成后发送截图。销售只能协助收集截图，是否到账以财务确认结果为准。",
        "action_steps": ["发送公司 Zelle 收款说明", "提醒客户备注商家名称和服务项目", "收集付款截图和付款金额", "提交财务确认，勿直接向客户承诺已到账"],
        "escalation_rule": "客户要求支付给个人、变更收款联系方式或金额不一致时，立即停止指引并找财务确认。",
        "tags": ["Zelle", "收款", "付款截图", "到账确认"],
        "is_sensitive": True,
        "sort_order": 30,
    },
    {
        "category": "收款与付款",
        "title": "Stripe 链接在哪里？",
        "customer_question": "客户要付款链接，销售应该发哪个？",
        "standard_answer": "美业和餐厅系统使用官网订阅页面。代运营服务必须由财务按客户、金额和结算周期发送专属 Stripe 链接；销售不能自行创建、修改或复用其他客户的链接。",
        "action_steps": ["确认客户购买的服务和结算周期", "系统订阅发送官网订阅入口", "代运营向财务申请专属链接", "将链接和发送时间记录在销售跟进中"],
        "escalation_rule": "客户提出优惠、拆分付款、升级或跨币种付款时，先审批再让财务生成链接。",
        "tags": ["Stripe", "支付链接", "代运营", "官网订阅"],
        "is_sensitive": True,
        "sort_order": 40,
    },
    {
        "category": "套餐与报价",
        "title": "代运营套餐怎么选？",
        "customer_question": "客户问不同代运营套餐有什么区别，应该选哪个？",
        "standard_answer": "基础版：任选 2 个平台，每周 3 次内容、评论互动和月报，单月 $399，订阅 $198/月。进阶版：任选 3 个平台，每周 4 次内容、评论与差评处理及月度优化，单月 $499，订阅 $249/月。专业版：任选 4 个平台，每周 5 次内容和深度策略，单月 $699，年付 $329/月。旗舰版：6 平台托管、每日内容、深度报告和 VIP 服务，单月 $999，年付 $499/月。VIP 定制方案按实际工作量报价。",
        "action_steps": ["先问客户当前平台数量、更新频率和核心目标", "按需要托管的平台数匹配套餐", "明确单月与长期订阅的结算方式", "报价前确认广告投放和广告费不包含在社媒托管套餐内"],
        "escalation_rule": "客户需要超过套餐的平台、广告代投、官网定制、特殊内容频率或定制价格时，提交主管报价。",
        "tags": ["代运营", "基础版", "进阶版", "专业版", "旗舰版", "报价"],
        "sort_order": 50,
    },
    {
        "category": "套餐与报价",
        "title": "客户说太贵如何回复？",
        "customer_question": "客户觉得报价贵，销售怎么推进？",
        "standard_answer": "我理解您希望控制成本。我们先不只比较月费，想确认您更在意的是平台费用、人工时间、获客效果还是持续运营。系统是工具，代运营是团队持续执行；我们会按您真正需要的平台和目标推荐合适方案，而不是一开始就推最高套餐。",
        "action_steps": ["确认客户比较的成本项目", "回到客户已经确认的痛点", "匹配更适合的套餐或服务范围", "需要优惠时提交经理审批"],
        "escalation_rule": "未经书面批准，不能承诺折扣、免费服务、永久低价或额外平台。",
        "tags": ["太贵", "价格", "折扣", "异议处理"],
        "sort_order": 60,
    },
    {
        "category": "异议与合规",
        "title": "可以保证订单或 Google 排名吗？",
        "customer_question": "客户要求保证排名、订单或营业额，销售怎么回答？",
        "standard_answer": "我们不能保证自然 Google 排名、固定订单量或营业额。广告可以争取 Google 的付费广告展示位置，但仍受预算、竞价、质量、地区和平台政策影响。我们能承诺的是按约定完成搭建、运营和优化工作，并持续提供数据与建议。",
        "action_steps": ["区分自然排名与付费广告展示", "说明影响效果的客观因素", "回到可交付的服务范围和数据复盘", "记录客户是否要求效果承诺"],
        "escalation_rule": "客户要求业绩保底、排名保证或特殊赔付条款时，必须由负责人和合同流程确认。",
        "tags": ["Google", "广告", "排名", "订单", "合规"],
        "sort_order": 70,
    },
    {
        "category": "套餐与报价",
        "title": "客户已有系统如何回复？",
        "customer_question": "客户说已经有网站、点餐或预约系统。",
        "standard_answer": "很好，说明您已经在重视线上业务。我们不急着让您更换，想先了解您现在最满意和最不满意的地方是什么？例如顾客数据能否掌握、营销是否容易、平台费用、员工管理和运营支持是否够用。我们只比较是否更适合您的实际需求。",
        "action_steps": ["询问现有系统和使用时长", "找出客户最满意和最不满意的部分", "只展示对应痛点的功能或服务", "不要贬低竞品或承诺无风险迁移"],
        "escalation_rule": "涉及数据迁移、合同解约、硬件兼容或第三方接口时，先由产品或技术确认。",
        "tags": ["已有系统", "竞品", "迁移", "异议处理"],
        "sort_order": 80,
    },
    {
        "category": "套餐与报价",
        "title": "可以随时取消或先试用吗？",
        "customer_question": "客户问取消规则和试用规则。",
        "standard_answer": "系统可以按公司规则安排 Demo 或受控试用，代运营不提供免费试用。客户可以提出取消申请，但具体停止续费时间、当期费用和退款以签约套餐与书面规则为准，销售不会只做口头承诺。",
        "action_steps": ["确认客户问的是系统还是代运营", "说明可安排 Demo 或受控试用", "取消问题发送正式规则或请主管确认", "将客户的特殊要求写入跟进记录"],
        "escalation_rule": "任何退款、即时停止、免费试用延长或特殊取消条件均需主管书面确认。",
        "tags": ["取消", "试用", "退款", "订阅"],
        "sort_order": 90,
    },
    {
        "category": "成交与交接",
        "title": "成交后客户要提供哪些资料？",
        "customer_question": "客户付款后下一步怎么做？",
        "standard_answer": "成交后销售先完整记录套餐、价格、付款周期、特殊承诺、客户目标和关键联系人，然后建立运营对接群。运营负责后续资料收集、上线对接和日常服务；销售保留客户关系，并协助关键沟通。",
        "action_steps": ["在系统记录成交信息与特殊承诺", "建立客户、销售和运营的对接群", "把客户目标、当前系统和资料情况交给运营", "确认运营对接负责人和下一次沟通时间"],
        "escalation_rule": "客户要求未写入成交信息的功能、价格或上线时间时，必须先核对记录并由主管确认。",
        "tags": ["成交", "交接", "运营群", "资料收集"],
        "sort_order": 100,
    },
    {
        "category": "销售红线",
        "title": "哪些话销售绝对不能承诺？",
        "customer_question": "哪些情况必须先找主管？",
        "standard_answer": "销售不得保证自然 Google 排名、订单量、营业额或广告效果；不得承诺未上线功能、未经确认的接口、未经批准的折扣或退款；不得冒充平台官方、隐瞒费用或合同周期；不得私自收款、保存客户密码或确认财务到账。",
        "action_steps": ["遇到不确定的承诺先暂停回答", "说明需要主管、财务或技术确认", "在跟进记录写清客户问题和承诺风险", "得到书面确认后再回复客户"],
        "escalation_rule": "所有价格例外、退款、合同、技术定制、账号权限和效果保底问题都必须升级处理。",
        "tags": ["红线", "合规", "承诺", "审批"],
        "sort_order": 110,
    },
]


async def _ensure_seed_articles(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(SalesKnowledgeArticles))
    if count:
        return
    for item in SEED_ARTICLES:
        db.add(SalesKnowledgeArticles(
            category=item["category"],
            title=item["title"],
            customer_question=item.get("customer_question"),
            standard_answer=item["standard_answer"],
            action_steps=json.dumps(item.get("action_steps", []), ensure_ascii=False),
            related_links=json.dumps(item.get("related_links", []), ensure_ascii=False),
            escalation_rule=item.get("escalation_rule"),
            tags=json.dumps(item.get("tags", []), ensure_ascii=False),
            status="published",
            is_sensitive=item.get("is_sensitive", False),
            sort_order=item.get("sort_order", 0),
            created_by_name="T24 知识库初始资料",
            published_by_name="系统管理员",
            published_at=datetime.now(timezone.utc),
        ))
    await db.commit()


@router.get("/articles")
async def list_articles(
    query: str = Query(default="", max_length=200),
    category: Optional[str] = Query(default=None, max_length=80),
    include_all: bool = False,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_access(current_user)
    await _ensure_seed_articles(db)
    statement = select(SalesKnowledgeArticles)
    if not (include_all and _role(current_user) in KNOWLEDGE_MANAGE_ROLES):
        statement = statement.where(SalesKnowledgeArticles.status == "published")
    if category and category != "全部":
        statement = statement.where(SalesKnowledgeArticles.category == category)
    if query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(
            SalesKnowledgeArticles.title.ilike(pattern),
            SalesKnowledgeArticles.customer_question.ilike(pattern),
            SalesKnowledgeArticles.standard_answer.ilike(pattern),
            SalesKnowledgeArticles.tags.ilike(pattern),
        ))
    articles = (await db.scalars(statement.order_by(SalesKnowledgeArticles.sort_order, SalesKnowledgeArticles.id))).all()
    categories = (await db.scalars(
        select(SalesKnowledgeArticles.category)
        .where(SalesKnowledgeArticles.status == "published")
        .distinct()
        .order_by(SalesKnowledgeArticles.category)
    )).all()
    return {"items": [_article_data(article) for article in articles], "categories": categories}


@router.post("/articles", status_code=status.HTTP_201_CREATED)
async def create_article(
    payload: KnowledgeArticlePayload,
    publish_now: bool = False,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    now = datetime.now(timezone.utc)
    article = SalesKnowledgeArticles(
        category=payload.category,
        title=payload.title,
        customer_question=payload.customer_question,
        standard_answer=payload.standard_answer,
        action_steps=json.dumps(payload.action_steps, ensure_ascii=False),
        related_links=json.dumps(payload.related_links, ensure_ascii=False),
        escalation_rule=payload.escalation_rule,
        tags=json.dumps(payload.tags, ensure_ascii=False),
        is_sensitive=payload.is_sensitive,
        sort_order=payload.sort_order,
        status="published" if publish_now else "draft",
        created_by_id=_employee_id(current_user),
        created_by_name=current_user.name,
        published_by_id=_employee_id(current_user) if publish_now else None,
        published_by_name=current_user.name if publish_now else None,
        published_at=now if publish_now else None,
    )
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return _article_data(article)


@router.put("/articles/{article_id}")
async def update_article(
    article_id: int,
    payload: KnowledgeArticlePayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    article = await db.get(SalesKnowledgeArticles, article_id)
    if not article or article.status == "archived":
        raise HTTPException(status_code=404, detail="未找到该知识卡")
    article.category = payload.category
    article.title = payload.title
    article.customer_question = payload.customer_question
    article.standard_answer = payload.standard_answer
    article.action_steps = json.dumps(payload.action_steps, ensure_ascii=False)
    article.related_links = json.dumps(payload.related_links, ensure_ascii=False)
    article.escalation_rule = payload.escalation_rule
    article.tags = json.dumps(payload.tags, ensure_ascii=False)
    article.is_sensitive = payload.is_sensitive
    article.sort_order = payload.sort_order
    await db.commit()
    await db.refresh(article)
    return _article_data(article)


@router.post("/articles/{article_id}/publish")
async def publish_article(
    article_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    article = await db.get(SalesKnowledgeArticles, article_id)
    if not article or article.status == "archived":
        raise HTTPException(status_code=404, detail="未找到该知识卡")
    article.status = "published"
    article.published_by_id = _employee_id(current_user)
    article.published_by_name = current_user.name
    article.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(article)
    return _article_data(article)


@router.delete("/articles/{article_id}")
async def archive_article(
    article_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    article = await db.get(SalesKnowledgeArticles, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="未找到该知识卡")
    article.status = "archived"
    await db.commit()
    return {"message": "知识卡已归档"}


@router.get("/questions")
async def list_questions(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    questions = (await db.scalars(
        select(SalesKnowledgeQuestions).order_by(SalesKnowledgeQuestions.status, SalesKnowledgeQuestions.created_at.desc())
    )).all()
    return {"items": [_question_data(question) for question in questions]}


@router.post("/questions", status_code=status.HTTP_201_CREATED)
async def submit_question(
    payload: KnowledgeQuestionPayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_access(current_user)
    question = SalesKnowledgeQuestions(
        question=payload.question.strip(),
        context=(payload.context or "").strip() or None,
        submitted_by_id=_employee_id(current_user),
        submitted_by_name=current_user.name,
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return _question_data(question)


@router.post("/questions/{question_id}/resolve")
async def resolve_question(
    question_id: int,
    payload: ResolveQuestionPayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manage(current_user)
    question = await db.get(SalesKnowledgeQuestions, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="未找到该问题")
    if payload.resolved_article_id:
        article = await db.get(SalesKnowledgeArticles, payload.resolved_article_id)
        if not article or article.status != "published":
            raise HTTPException(status_code=400, detail="请关联已发布的知识卡")
    question.status = "resolved"
    question.resolved_article_id = payload.resolved_article_id
    question.resolved_by_id = _employee_id(current_user)
    question.resolved_by_name = current_user.name
    question.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "问题已标记为已处理"}

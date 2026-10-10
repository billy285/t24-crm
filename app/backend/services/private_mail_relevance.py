"""Explainable owner-mail rules using metadata only; mail is untrusted evidence.

No network calls, body decoding, identity verification, financial writes or AI.
User preferences can change relevance, but cannot hide concrete risk signals.
"""
import re
from email.utils import getaddresses


TOPICS = ("finance", "ads", "security", "business")
BUCKETS = ("urgent", "today", "digest", "low")
BUCKET_PRIORITY = {"urgent": "urgent", "today": "high", "digest": "normal", "low": "low"}
DEFAULT_GMAIL = {"topics": list(TOPICS), "watch_senders": [], "watch_keywords": [], "muted_senders": []}
_EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", re.I)
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", re.I)


def normalize_sender_rule(value):
    if not isinstance(value, str):
        raise ValueError("请填写完整邮箱或域名")
    value = value.strip().casefold()
    if len(value) > 254 or not (_EMAIL.fullmatch(value) or _DOMAIN.fullmatch(value)):
        raise ValueError("请填写完整邮箱或域名，不支持通配符")
    return value


def sender_address(value):
    if not isinstance(value, str) or len(value) > 1800 or any(c in value for c in "\r\n"):
        return None
    parsed = getaddresses([value])
    if len(parsed) != 1:
        return None
    address = parsed[0][1].strip().casefold()
    return address if len(address) <= 254 and _EMAIL.fullmatch(address) else None


def sender_matches(address, rules):
    if not address:
        return False
    domain = address.rsplit("@", 1)[-1]
    # Domain rules are exact: neither subdomains nor suffix lookalikes match.
    return any(address == rule or ("@" not in rule and domain == rule) for rule in rules)


def gmail_preferences(stored):
    gmail = stored.get("gmail", {}) if isinstance(stored, dict) else {}
    if not isinstance(gmail, dict):
        gmail = {}
    topics = gmail.get("topics", TOPICS)
    if not isinstance(topics, list) and not isinstance(topics, tuple):
        topics = TOPICS
    result = {"topics": list(dict.fromkeys(topic for topic in topics if topic in TOPICS))[:4]}
    for key in ("watch_senders", "muted_senders"):
        result[key] = []
        values = gmail.get(key, [])
        for value in values[:50] if isinstance(values, list) else []:
            try:
                value = normalize_sender_rule(value)
            except ValueError:
                continue
            if value not in result[key]:
                result[key].append(value)
    values = gmail.get("watch_keywords", [])
    result["watch_keywords"] = list(dict.fromkeys(value.strip().casefold() for value in values[:30]
        if isinstance(value, str) and 1 <= len(value.strip()) <= 80)) if isinstance(values, list) else []
    return result


def _has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def classify_mail(item, stored=None):
    preferences = gmail_preferences(stored)
    evidence = item.get("evidence") or {}
    evidence = evidence if isinstance(evidence, dict) else {}
    address = sender_address(evidence.get("from"))
    text = (str(item.get("title") or "")[:240] + "\n" + str(item.get("summary") or "")[:1800]).casefold()
    title = str(item.get("title") or "")[:240].casefold()
    labels = evidence.get("labels", [])
    labels = labels if isinstance(labels, list) else []
    feedbacks = stored.get("gmail_feedback", {}) if isinstance(stored, dict) else {}
    feedbacks = feedbacks if isinstance(feedbacks, dict) else {}
    item_choices = feedbacks.get("items", {})
    sender_choices = feedbacks.get("senders", {})
    item_choices = item_choices if isinstance(item_choices, dict) else {}
    sender_choices = sender_choices if isinstance(sender_choices, dict) else {}
    feedback = item_choices.get(str(item.get("id") or ""))
    feedback = feedback if isinstance(feedback, str) and feedback in {"important", "not_relevant"} else None
    sender_feedback = sender_choices.get(address) if address else None
    sender_feedback = sender_feedback if isinstance(sender_feedback, str) and sender_feedback in {"important", "not_relevant"} else None
    promotion = "CATEGORY_PROMOTIONS" in labels or _has(
        r"\b(newsletter|weekly digest|special offer|limited.time offer|sale ends|unsubscribe|security tips|protect yourself|best practices)\b|促销|优惠券|订阅周报|安全小贴士", text)
    finance = _has(r"\b(stripe|bank of america|bofa|payment|payout|invoice|receipt|refund|chargeback|dispute|transaction|balance)\b|收款|付款|银行|退款|账单|到账|争议", text)
    ads = _has(r"\b(google ads|adwords|advertising account|ad account|campaign|ad disapproved|ads disapproved)\b|广告账户|广告投放|投流|广告拒登", text)
    security = _has(r"\b(security|sign.in|log.in|password|two.factor|2fa|verification code|unauthorized|suspicious)\b|安全|登录|密码|验证码|异常访问", text)
    business = _has(r"\b(contract|proposal|quotation|quote|meeting|appointment|deadline|please reply|response required|action required|follow.up)\b|合同|合作|报价|预约|会议|请回复|截止|待确认", text)
    category = "finance" if finance else "ads" if ads else "security" if security else "business" if business else "promotion" if promotion else "general"
    concrete_finance_risk = _has(r"\b(payment|payout|transfer|withdrawal|transaction|charge|bank account)\b.{0,45}\b(failed|declined|blocked|rejected|unauthorized|suspicious|unrecognized|restricted|unsuccessful|returned)\b|\b(failed|declined|unauthorized|suspicious|unrecognized)\b.{0,35}\b(payment|payout|transfer|transaction|charge)\b|\bpayment\b.{0,25}\b(could not|couldn't|cannot|can't)\b.{0,15}\bprocessed\b|支付失败|付款失败|扣款失败|提现失败|转账失败|异常交易|未经授权.{0,12}(交易|扣款)|争议.{0,15}(回复|截止)|收到.{0,12}争议|new dispute|dispute (opened|created|received)|chargeback (received|opened)|\bdispute\b.{0,30}\b(requires? (your )?response|response required)\b|\brespond to (the |a )?dispute\b", text)
    concrete_ads_risk = ads and _has(r"\b(account|campaign|ad|ads)\b.{0,30}\b(suspended|disabled|disapproved|rejected)\b|\b(suspended|disabled|disapproved)\b.{0,25}\b(account|ad|ads)\b|广告.{0,15}(停用|封禁|拒登)|账户.{0,15}(停用|封禁)", text)
    concrete_security_risk = _has(r"\b(suspicious|unrecognized|unauthorized|unusual|new)\b.{0,30}\b(sign.in|log.in|login|access|device|activity)\b|\b(password|recovery email|two.factor authentication)\b.{0,30}\b(changed|reset|disabled)\b|new sign.in|异常登录|新设备登录|密码.{0,10}(已更改|被修改)", text) or _has(r"^\s*(security alert|安全警报)(\s*[:：–-]|\s+for\b|\s*$)", title)
    # Educational promotions must not impersonate an actual event. A concrete
    # event in the subject still wins, even when the message has a promo label.
    educational = promotion and _has(r"^\s*(?:(?:security\s+)?tips\b|how to\b|guide\b|learn\b|protect yourself\b|avoid\b|prevent\b|(?:安全|广告|投流|付款|支付)?(?:小贴士|指南)|如何|防范)", title)
    urgent_reason = ("疑似支付或资金异常，需核实来源" if concrete_finance_risk else
                     "疑似广告投放异常，需核实来源" if concrete_ads_risk else
                     "疑似账号安全事件，需核实来源" if concrete_security_risk else None)
    reasons = []
    if urgent_reason and not educational:
        bucket = "urgent"
        category = "finance" if concrete_finance_risk else "ads" if concrete_ads_risk else "security"
        reasons.append(urgent_reason)
        if feedback == "not_relevant" or sender_feedback == "not_relevant" or sender_matches(address, preferences["muted_senders"]):
            reasons.append("风险提醒优先，保留供你核实")
    elif feedback == "important":
        bucket = "today"; reasons.append("你已标记这封邮件重要")
    elif feedback == "not_relevant":
        bucket = "low"; reasons.append("你已标记这封邮件不相关")
    elif sender_feedback == "important":
        bucket = "today"; reasons.append("你关注的发件人")
    elif sender_feedback == "not_relevant" or sender_matches(address, preferences["muted_senders"]):
        bucket = "low"; reasons.append("你已降低该发件人的优先级")
    elif sender_matches(address, preferences["watch_senders"]):
        bucket = "today"; reasons.append("你关注的发件人")
    elif any(keyword in text for keyword in preferences["watch_keywords"]):
        bucket = "today"; reasons.append("命中你关注的关键词")
    elif "STARRED" in labels:
        bucket = "today"; reasons.append("你在 Gmail 中加了星标")
    elif promotion:
        bucket = "low"; category = "promotion"; reasons.append("疑似推广或订阅通知")
    elif category in preferences["topics"] and (business or _has(r"\b(action required|reply|respond|due|deadline|confirm|approval required)\b|请回复|需确认|待确认|截止|待审批", text)):
        bucket = "today"; reasons.append("关注主题中可能需要你处理的事项")
    else:
        bucket = "digest"
        reasons.append("关注主题的一般通知" if category in preferences["topics"] else "一般邮件，暂未命中个人关注规则")
        if "IMPORTANT" in labels:
            reasons.append("Gmail 标记为重要，未发现明确紧急事项")
    return {"bucket": bucket, "category": category, "reasons": reasons, "feedback": feedback,
            "sender_address": address, "sender_verification": "unverified"}

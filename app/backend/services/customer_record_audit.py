"""Server-authored, transaction-local history for customer business records."""
from datetime import date, datetime
from decimal import Decimal

from models.customer_record_audits import CustomerRecordAudit

SECRET_FIELDS = {"login_password", "password", "access_token", "refresh_token", "api_key"}


def _value(field, value):
    if field in SECRET_FIELDS or any(part in field.lower() for part in ("password", "secret", "token")):
        return "[redacted]" if value else None
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    return value


def record_customer_change(db, current_user, obj, module, *, changes=None, deleted=False):
    """Add only; the caller's commit/rollback includes both change and history."""
    if current_user is None:
        return
    field_names = list(obj.__table__.columns.keys()) if deleted else list(changes or {})
    before, after = {}, {}
    for field in field_names:
        if not hasattr(obj, field) or field in {"updated_at", "created_at"}:
            continue
        old = getattr(obj, field)
        new = None if deleted else changes[field]
        if not deleted and old == new:
            continue
        before[field] = _value(field, old)
        if not deleted:
            after[field] = _value(field, new)
    if not before:
        return
    db.add(CustomerRecordAudit(
        customer_id=obj.id if obj.__tablename__ == "customers" else obj.customer_id, module=module, entity_type=obj.__tablename__,
        entity_id=obj.id, actor_id=str(current_user.id),
        actor_name=str(getattr(current_user, "name", "") or getattr(current_user, "email", "") or current_user.id),
        action="delete" if deleted else "update", before=before, after=after,
    ))

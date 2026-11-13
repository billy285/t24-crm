"""Weekly delivery counts from publication receipts and completed internal reports."""
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_, select

from models.google_business import GoogleBusinessAction, GoogleBusinessBinding, GoogleBusinessConnection, GoogleBusinessGrant
from models.media_operations import MediaOperationTask
from models.meta_operations import MetaOperationsAction, MetaOperationsBinding
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from services.customer_scope import apply_customer_scope


BEIJING = timezone(timedelta(hours=8))


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _proof_link(value):
    if not value:
        return None
    try:
        url = urlsplit(value.strip())
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return None
        query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        return urlunsplit(("https", url.netloc.lower(), url.path.rstrip("/"), urlencode(query), ""))
    except ValueError:
        return None


def _platforms(value):
    if value and value.lstrip().startswith("["):
        try:
            items = json.loads(value)
            return {k.strip() for k in items if isinstance(k, str)} if isinstance(items, list) else set()
        except ValueError:
            return set()
    return {k.strip() for k in (value or "").split(",") if k.strip()}


def _completed_day(value):
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00"))).astimezone(BEIJING).date()
    except ValueError:
        return None


def _weekly_counts(receipts, projects, start, end):
    """Unify the same task, receipt, URL or screenshot before assigning a week/project."""
    groups = defaultdict(list)
    for customer, platform, project, stamp, identities in receipts:
        groups[(customer, platform)].append((project, stamp, identities))
    counts = defaultdict(Counter)
    unmapped = 0
    unresolved_projects = set()
    for (customer, platform), rows in groups.items():
        # A receipt can connect a task ID to a permalink already seen on another row.
        parents = {}
        def root(key):
            while key != parents.setdefault(key, key):
                parents[key] = parents[parents[key]]
                key = parents[key]
            return key
        for _, _, identities in rows:
            first = root(identities[0])
            for key in identities[1:]:
                parents[root(key)] = first
        clusters = defaultdict(list)
        for project_id, stamp, identities in rows:
            clusters[root(identities[0])].append((project_id, stamp))
        for entries in clusters.values():
            first_seen = min(stamp for _, stamp in entries)
            if not start <= first_seen < end:
                continue
            explicit = {pid for pid, _ in entries if pid is not None}
            if explicit:
                matched = [p for p in projects[customer] if p.id in explicit]
            else:
                # An unlinked post can only be assigned to an unambiguous contracted project.
                day = first_seen.astimezone(BEIJING).date().isoformat()
                matched = [p for p in projects[customer] if platform in _platforms(p.package_platforms)
                           and (p.service_stage not in {"ended", "paused"} or p.service_end_date)
                           and (not p.service_start_date or p.service_start_date[:10] <= day)
                           and (not p.service_end_date or p.service_end_date[:10] >= day)]
            if len(matched) == 1 and len(explicit) <= 1:
                counts[matched[0].id][platform] += 1
            else:
                unmapped += 1
                unresolved_projects.update(p.id for p in matched)
    return counts, unmapped, unresolved_projects


async def weekly_evidence(db, user, now=None):
    checked_at = _utc(now or datetime.now(timezone.utc))
    today = checked_at.astimezone(BEIJING).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, time.min, BEIJING).astimezone(timezone.utc)
    end = start + timedelta(days=7)
    projects = defaultdict(list)
    P = Service_progresses
    scope = apply_customer_scope(select(P.id, P.customer_id, P.package_platforms, P.service_stage, P.service_start_date,
                                       P.service_end_date), P, user)
    for row in await db.execute(scope):
        projects[row.customer_id].append(row)
    result = {"week_start": monday.isoformat(), "projects": {}, "unassigned": 0, "unresolved_projects": [], "scope": "owner" if user.role == "super_admin" else "assigned"}
    if not projects:
        return result
    # The aggregate exposes delivery counts only, never provider credentials, URLs or private material.
    customers = list(projects)
    owner = user.role == "super_admin"
    actor_id = int(user.id)
    receipts = []
    M, G, A, B = MediaOperationTask, GoogleBusinessAction, MetaOperationsAction, MetaOperationsBinding
    media = select(M.id, M.customer_id, M.platform, M.service_progress_id, M.completed_at, M.proof_url,
                   M.proof_material_id).where(M.customer_id.in_(customers), M.status == "completed", M.completed_at <= checked_at)
    if not owner:
        media = media.where(M.assignee_id == actor_id)
    for row in await db.execute(media):
        identities = [("url", url)] if (url := _proof_link(row.proof_url)) else []
        if row.proof_material_id:
            identities.append(("material", row.proof_material_id))
        if identities:
            receipts.append((row.customer_id, row.platform, row.service_progress_id, _utc(row.completed_at),
                             identities + [("task", row.id)]))
    google = select(G.customer_id, G.task_id, M.service_progress_id, G.provider_name, G.provider_url, G.confirmed_at).join(
        M, (G.task_id == M.id) & (G.customer_id == M.customer_id) & (M.platform == "google_business")).where(
        G.customer_id.in_(customers), G.kind == "post_publish", G.status == "succeeded", G.provider_state == "LIVE",
        G.provider_name.is_not(None), G.confirmed_at <= checked_at)
    google = google.join(GoogleBusinessBinding, (G.binding_id == GoogleBusinessBinding.id) &
                         (G.customer_id == GoogleBusinessBinding.customer_id))
    if owner:
        google = google.join(GoogleBusinessConnection, GoogleBusinessConnection.id == GoogleBusinessBinding.connection_id
                             ).where(GoogleBusinessConnection.owner_id == actor_id)
    else:
        google = google.join(GoogleBusinessGrant, GoogleBusinessGrant.binding_id == G.binding_id).where(
            M.assignee_id == actor_id, GoogleBusinessGrant.employee_id == actor_id,
            GoogleBusinessGrant.can_publish.is_(True), GoogleBusinessBinding.active.is_(True))
    for row in await db.execute(google):
        if row.provider_name:
            keys = [("google", row.provider_name), ("task", row.task_id)]
            if url := _proof_link(row.provider_url):
                keys.append(("url", url))
            receipts.append((row.customer_id, "google_business", row.service_progress_id, _utc(row.confirmed_at), keys))
    meta = select(B.customer_id, B.platform, A.provider_id, A.provider_url, A.updated_at).join_from(
        A, B, (A.binding_id == B.id) & (A.owner_id == B.owner_id)).where(
        B.customer_id.in_(customers), B.owner_id == actor_id, A.kind == "post", A.status == "succeeded", A.dispatch_stage == "complete",
        A.provider_id.is_not(None), A.updated_at <= checked_at)
    for row in await db.execute(meta) if owner else []:
        if row.provider_id:
            keys = [("meta", row.provider_id)]
            if url := _proof_link(row.provider_url):
                keys.append(("url", url))
            receipts.append((row.customer_id, row.platform, None, _utc(row.updated_at), keys))
    counts, result["unassigned"], unresolved_projects = _weekly_counts(receipts, projects, start, end)

    result["unresolved_projects"] = sorted(unresolved_projects)

    # Task timestamps are legacy ISO strings. Restrict the candidate set first, then
    # compare the exact Beijing calendar date (including UTC Sundays) in Python.
    T = Service_tasks
    # The historical submit_report type covers both weekly and monthly reports.
    weekly_report = (T.task_type == "submit_report") & or_(
        *[T.task_name.contains(word) for word in ("周报", "週報", "周总结", "周运营总结", "周汇报", "週總結", "週營運總結", "週匯報")],
        T.task_name.ilike("%weekly report%")) & ~or_(
        *[T.task_name.contains(word) for word in ("月报", "月報", "月度", "月总结")], T.task_name.ilike("%monthly%"))
    reports = select(T.service_progress_id, T.due_date, T.completed_at, T.completed_date).join(
        P, (P.id == T.service_progress_id) & (P.customer_id == T.customer_id)).where(
        T.customer_id.in_(customers), weekly_report, T.status == "completed",
        ((T.completed_at >= (monday - timedelta(days=1)).isoformat()) |
         (T.completed_date >= (monday - timedelta(days=1)).isoformat())))
    report_ids = set()
    for row in await db.execute(reports):
        day = _completed_day(row.completed_at or row.completed_date)
        due = _completed_day(row.due_date[:10]) if row.due_date else None
        if day and monday <= day <= today and (not row.due_date or due and monday <= due < monday + timedelta(days=7)):
            report_ids.add(row.service_progress_id)
    monday_key = monday.isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()
    reservations = select(T.service_progress_id, T.platform, T.task_type, T.status, func.count()).join(
        P, (P.id == T.service_progress_id) & (P.customer_id == T.customer_id)).where(
        T.customer_id.in_(customers), (T.task_type == "publish_content") | weekly_report, T.status != "cancelled",
        T.due_date >= monday_key, T.due_date < next_week).group_by(T.service_progress_id, T.platform, T.task_type, T.status)
    plans = defaultdict(lambda: {"scheduled": {}, "closed": {}, "report_scheduled": False})
    for pid, platform, kind, status, count in await db.execute(reservations):
        if kind == "submit_report":
            if status != "completed":
                plans[pid]["report_scheduled"] = True
        elif platform:
            slots = plans[pid]["closed" if status == "completed" else "scheduled"]
            slots[platform] = slots.get(platform, 0) + count
    result["projects"] = {pid: {"published": dict(counts[pid]), "internal_report": pid in report_ids, **plans[pid]}
                          for pid in counts.keys() | report_ids | plans.keys()}
    return result

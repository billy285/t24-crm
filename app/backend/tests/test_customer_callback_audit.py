from datetime import datetime, timezone

from backend.routers.customer_callbacks import _apply_completion_audit
from backend.schemas.auth import UserResponse


def _employee_user() -> UserResponse:
    return UserResponse(id="42", email="agent@example.com", name="Agent Li", role="operations")


def test_callback_create_audit_uses_authenticated_employee() -> None:
    audited = _apply_completion_audit(
        {
            "status": "pending",
            "created_by_employee_id": 999,
            "created_by_employee_name": "Forged User",
            "created_at": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2000, 1, 2, tzinfo=timezone.utc),
            "completed_by_employee_id": 999,
        },
        _employee_user(),
        creating=True,
    )

    assert audited["created_by_employee_id"] == 42
    assert audited["created_by_employee_name"] == "Agent Li"
    assert audited["created_at"] != datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert audited["updated_at"] == audited["created_at"]
    assert audited["completed_by_employee_id"] is None
    assert audited["completed_by_employee_name"] is None
    assert audited["completed_at"] is None


def test_callback_completion_audit_uses_authenticated_employee() -> None:
    audited = _apply_completion_audit(
        {
            "status": "completed",
            "completed_by_employee_id": 999,
            "completed_by_employee_name": "Forged User",
        },
        _employee_user(),
    )

    assert audited["completed_by_employee_id"] == 42
    assert audited["completed_by_employee_name"] == "Agent Li"
    assert audited["completed_at"] is not None


def test_callback_reopen_clears_completion_audit() -> None:
    audited = _apply_completion_audit({"status": "pending"}, _employee_user())

    assert audited["completed_by_employee_id"] is None
    assert audited["completed_by_employee_name"] is None
    assert audited["completed_at"] is None


def test_callback_partial_update_cannot_forge_completion_audit() -> None:
    audited = _apply_completion_audit(
        {
            "notes": "updated",
            "created_by_employee_id": 999,
            "created_by_employee_name": "Forged User",
            "created_at": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2000, 1, 2, tzinfo=timezone.utc),
            "completed_by_employee_id": 999,
        },
        _employee_user(),
    )

    assert audited["notes"] == "updated"
    assert audited["updated_at"] != datetime(2000, 1, 2, tzinfo=timezone.utc)
    assert "created_by_employee_id" not in audited
    assert "created_by_employee_name" not in audited
    assert "created_at" not in audited
    assert "completed_by_employee_id" not in audited

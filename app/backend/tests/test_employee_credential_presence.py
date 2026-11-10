"""Employee management exposes credential presence without exposing credentials."""
import pytest

from models.employees import Employees
from routers.employees import EmployeesResponse, EmployeeDirectoryResponse


@pytest.mark.parametrize("stored, expected", [(None, False), ("", False), ("   ", False), ("synthetic-hashed-credential", True)])
def test_management_response_exposes_presence_without_secret(stored, expected):
    employee = Employees(id=901, user_id="synthetic-user", name="Synthetic Employee", role="sales", password=stored)
    result = EmployeesResponse.model_validate(employee).model_dump()
    assert result["has_login_password"] is expected
    assert "password" not in result
    assert "synthetic-hashed-credential" not in str(result)


def test_directory_does_not_expose_credential_metadata():
    employee = Employees(id=901, user_id="synthetic-user", name="Synthetic Employee", role="sales", password="synthetic-hashed-credential")
    result = EmployeeDirectoryResponse.model_validate(employee).model_dump()
    assert "has_login_password" not in result and "password" not in result

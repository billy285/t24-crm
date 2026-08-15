from dependencies.auth import get_admin_user
from routers.storage import router


def test_every_generic_storage_route_requires_admin_dependency():
    """The shared OSS credential must never be exposed to ordinary staff."""
    protected_paths = {
        "/api/v1/storage/create-bucket",
        "/api/v1/storage/list-buckets",
        "/api/v1/storage/list-objects",
        "/api/v1/storage/get-object-info",
        "/api/v1/storage/rename-object",
        "/api/v1/storage/delete-object",
        "/api/v1/storage/upload-url",
        "/api/v1/storage/download-url",
    }

    routes = {route.path: route for route in router.routes if route.path in protected_paths}
    assert set(routes) == protected_paths
    for path, route in routes.items():
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert get_admin_user in dependency_calls, f"{path} must require an admin before using the shared OSS credential"

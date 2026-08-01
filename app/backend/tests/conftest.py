import os


# Most existing endpoint tests use signed fixture tokens without creating a
# matching employee row. Production keeps this enabled; focused auth tests
# explicitly turn it back on with monkeypatch.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENFORCE_EMPLOYEE_STATUS", "false")

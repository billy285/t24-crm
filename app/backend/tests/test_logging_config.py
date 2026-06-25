import logging

from backend import main


def _reset_logging_for_test():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_root_level = root.level
    saved_levels = {
        name: logging.getLogger(name).level
        for name in ("aiosqlite", "sqlalchemy.engine", "uvicorn", "fastapi")
    }

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    def restore():
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_root_level)
        for name, level in saved_levels.items():
            logging.getLogger(name).setLevel(level)

    return restore


def test_resolve_log_level_defaults_to_info_for_invalid_values():
    assert main._resolve_log_level(None) == logging.INFO
    assert main._resolve_log_level("not-a-level") == logging.INFO
    assert main._resolve_log_level("debug") == logging.DEBUG


def test_setup_logging_defaults_to_info_and_hides_sql_debug(monkeypatch, tmp_path):
    restore = _reset_logging_for_test()
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("ENABLE_SQL_DEBUG_LOGS", raising=False)

        main.setup_logging()

        assert logging.getLogger().level == logging.INFO
        assert logging.getLogger("aiosqlite").level == logging.WARNING
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
    finally:
        restore()


def test_setup_logging_allows_explicit_sql_debug(monkeypatch, tmp_path):
    restore = _reset_logging_for_test()
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("ENABLE_SQL_DEBUG_LOGS", "true")

        main.setup_logging()

        assert logging.getLogger().level == logging.DEBUG
        assert logging.getLogger("aiosqlite").level == logging.DEBUG
        assert logging.getLogger("sqlalchemy.engine").level == logging.DEBUG
    finally:
        restore()

import hashlib
import json
import sqlite3

import pytest

from scripts.scan_phone_numbers import main, scan_phone_numbers
from services.phone_numbers import normalize_phone_country, parse_phone_number, phone_match_key


@pytest.mark.parametrize("raw,country,e164,extension", [
    ("202-555-0123", "US", "+12025550123", None),
    ("1 (202) 555-0123", "美国", "+12025550123", None),
    ("+1 (202) 555-0123 ext. 009", None, "+12025550123", "009"),
    ("+1 202-555-0123 分机 9", None, "+12025550123", "9"),
    ("+1 202-555-0123;ext=9", None, "+12025550123", "9"),
    ("020 7946 0018", "UK", "+442079460018", None),
    ("+44 20 7946 0018", None, "+442079460018", None),
    ("+86 138 0013 8000", None, "+8613800138000", None),
    ("＋１（２０２）５５５－０１２３", None, "+12025550123", None),
])
def test_valid_phone_preserves_raw_and_international_identity(raw, country, e164, extension):
    result = parse_phone_number(raw, country)
    assert result.raw == raw
    assert result.is_valid
    assert result.e164 == e164
    assert result.extension == extension
    assert phone_match_key(raw, country) == e164


@pytest.mark.parametrize("raw,country,status", [
    ("2025550123", None, "needs_country"),
    ("12025550123", None, "needs_country"),
    ("2025550123", "unknown", "needs_country"),
    ("2025550123 / 2125550123", "US", "ambiguous"),
    ("+12025550123, +12125550123", None, "ambiguous"),
    ("+12025550123\n+12125550123", None, "ambiguous"),
    ("+12025550123 ext 9 ext 2", None, "invalid"),
    ("Call +12025550123", None, "invalid"),
    ("1.2025550123e10", "US", "invalid"),
    ("5550123", "US", "invalid"),
    ("+15552223333", None, "invalid"),
    ("", "US", "empty"),
])
def test_unsafe_phone_never_gets_matching_key(raw, country, status):
    result = parse_phone_number(raw, country)
    assert result.status == status
    assert result.reason
    assert result.e164 is None
    assert phone_match_key(raw, country) is None


def test_aliases_only_resolve_known_countries():
    assert normalize_phone_country("加拿大") == "CA"
    assert normalize_phone_country("ZZ") is None


def test_history_scan_has_no_writes_and_no_automatic_merges(tmp_path):
    database = tmp_path / "fixture.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, phone TEXT, country TEXT)")
    connection.executemany("INSERT INTO customers VALUES (?, ?, ?)", [
        (1, "202-555-0123 ext 9", "US"), (2, "+12025550123", "US"), (3, "invalid old number", None),
    ])
    connection.commit()
    connection.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    report = scan_phone_numbers(f"{database.as_uri()}?mode=ro")
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert report["read_only"] is True
    assert report["status_counts"] == {"valid": 2, "invalid": 1}
    assert report["same_number_candidates"] == [{"table": "customers", "e164": "+12025550123", "ids": [1, 2]}]
    with pytest.raises(ValueError):
        scan_phone_numbers(str(database))
    with pytest.raises(ValueError):
        scan_phone_numbers(f"{database.as_uri()}?mode=rw")
    with pytest.raises(ValueError):
        scan_phone_numbers("https://example.com/private.db?mode=ro")


def test_scan_cli_only_prints_aggregates_and_report_is_private(tmp_path, monkeypatch, capsys):
    database = tmp_path / "fixture.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, phone TEXT)")
    connection.execute("INSERT INTO employees VALUES (1, '+12025550123')")
    connection.commit()
    connection.close()
    report_file = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["scan", "--database-uri", f"{database.as_uri()}?mode=ro", "--output", str(report_file)])
    assert main() == 0
    output = capsys.readouterr()
    assert "+12025550123" not in output.out
    assert str(database) not in output.out
    assert json.loads(output.out)["record_count"] == 1
    assert report_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(report_file.read_text())["records"][0]["raw"] == "+12025550123"
    # Existing reports cannot be overwritten or followed as symlinks.
    original = report_file.read_bytes()
    assert main() == 1
    assert report_file.read_bytes() == original

"""Report-only local SQLite phone audit. Never changes records or associations.

Example: python scripts/scan_phone_numbers.py --database-uri
  'file:/absolute/path/to/copy.db?mode=ro' --output /private/path/phone-audit.json
The report contains personal data; stdout contains aggregate counts only.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.phone_numbers import parse_phone_number

PHONE_TABLES = {
    "merchant_pool": ("phone", "country"),
    "sales_leads": ("phone", "country"),
    "customers": ("phone", "country"),
    "customer_contacts": ("contact_phone", None),
    "employees": ("phone", None),
}


def scan_phone_numbers(database_uri: str) -> dict:
    uri = urlsplit(database_uri)
    query = parse_qs(uri.query)
    if uri.scheme != "file" or uri.netloc or not Path(unquote(uri.path)).is_absolute() or query.get("mode") != ["ro"]:
        raise ValueError("数据库必须使用绝对本地 file: URI，并明确指定 mode=ro")
    if set(query) - {"mode", "immutable"} or ("immutable" in query and query["immutable"] != ["1"]):
        raise ValueError("不支持的 SQLite URI 选项")
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    rows = []
    status_counts = Counter()
    candidates = defaultdict(list)
    try:
        connection.execute("PRAGMA query_only = ON")
        # A stable read transaction also avoids mixing two different snapshots.
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        customer_columns = {row[1] for row in connection.execute('PRAGMA table_info("customers")')} if "customers" in tables else set()
        for table, (phone_column, country_column) in PHONE_TABLES.items():
            if table not in tables:
                continue
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not {"id", phone_column} <= columns:
                continue
            if table == "customer_contacts" and {"customer_id"} <= columns and {"id", "country"} <= customer_columns:
                sql = 'SELECT t.id, t.contact_phone AS raw, c.country AS country FROM customer_contacts t LEFT JOIN customers c ON c.id=t.customer_id ORDER BY t.id'
            else:
                country = f'"{country_column}"' if country_column in columns else "NULL"
                sql = f'SELECT id, "{phone_column}" AS raw, {country} AS country FROM "{table}" ORDER BY id'
            for row in connection.execute(sql):
                parsed = parse_phone_number(row["raw"], row["country"])
                status_counts[parsed.status] += 1
                record = {
                    "table": table, "id": row["id"], "phone_field": phone_column,
                    "original_country": row["country"], **parsed.to_dict(),
                    "standard_value_differs": bool(parsed.e164 and parsed.raw != parsed.e164),
                }
                rows.append(record)
                if parsed.e164:
                    candidates[(table, parsed.e164)].append(row["id"])
        return {
            "read_only": True, "record_count": len(rows), "status_counts": dict(status_counts),
            "records": rows,
            "same_number_candidates": [{"table": table, "e164": key, "ids": ids}
                for (table, key), ids in candidates.items() if len(ids) > 1],
            "note": "同号仅供人工核对；不得据此自动修改、关联或合并记录。",
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="只读扫描本地 SQLite 副本的电话号码")
    parser.add_argument("--database-uri", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = scan_phone_numbers(args.database_uri)
        # O_EXCL prevents overwriting an existing report or following a symlink.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps({"read_only": True, "record_count": report["record_count"], "status_counts": report["status_counts"], "same_number_groups": len(report["same_number_candidates"])}, ensure_ascii=False))
        return 0
    except (ValueError, sqlite3.Error, OSError):
        # Do not accidentally echo private URI paths or record content.
        print("扫描未完成：请核对只读数据库 URI 和未使用的报告路径。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

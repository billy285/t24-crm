import hashlib
import json
import sqlite3
from backend.tests.test_alembic_fresh_bootstrap import _run_alembic

def snapshot(connection):
    tables=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','merchant_import_batches') ORDER BY name")]
    result={}
    for table in tables:
        schema=connection.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name",(table,)).fetchall()
        rows=connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        result[table]=hashlib.sha256(json.dumps([schema,rows],ensure_ascii=False,default=str).encode()).hexdigest()
    return result

def test_import_migration_preserves_all_historical_tables_amounts_and_phone_values(tmp_path):
    database=tmp_path/"historical.sqlite"
    _run_alembic(database,"upgrade","e9c7a3f2b106")
    with sqlite3.connect(database) as connection:
        # Fresh bootstrap imports current models. Removing only the new empty
        # table simulates the previous release without touching its existing data.
        connection.execute('DROP TABLE IF EXISTS merchant_import_batches')
        connection.execute("INSERT INTO customers (id,business_name,contact_name,phone,status) VALUES (9201,'历史客户','Owner',' +1 212-555-0123 ext. 9 ','已合作')")
        connection.execute("INSERT INTO deals (id,customer_id,product_type,deal_amount,is_paid) VALUES (9201,9201,'managed_service',198,1)")
        connection.execute("INSERT INTO payments (id,source_deal_id,customer_id,amount_due,amount_paid,currency,user_id) VALUES (9201,9201,9201,198,198,'USD','test')")
        connection.commit();before=snapshot(connection)
    _run_alembic(database,"upgrade","head")
    _run_alembic(database,"check")
    with sqlite3.connect(database) as connection:
        assert snapshot(connection) == before
        assert connection.execute("SELECT phone,status FROM customers WHERE id=9201").fetchone() == (' +1 212-555-0123 ext. 9 ','已合作')
        assert connection.execute("SELECT amount_paid FROM payments WHERE id=9201").fetchone() == (198,)
        assert connection.execute("SELECT count(*) FROM merchant_import_batches").fetchone() == (0,)

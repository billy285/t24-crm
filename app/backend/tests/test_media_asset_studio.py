"""Real-photo studio safety on isolated local SQLite; never public/provider I/O."""
import asyncio
import base64
import copy
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from models.customer_materials import Customer_materials as Material
from models.customer_record_audits import CustomerRecordAudit
from models.customers import Customers
from models.employees import Employees
from models.media_asset_studio import MediaAssetProfile as Profile, MediaAssetJob as Job, MediaAssetRequest as Request
from models.media_operations import MediaOperationTask as Task
from models.media_publication_images import MediaPublicationImage as Image, MediaPublicationImagePolicy as Policy, MediaPublicationImageDelivery as Delivery
from routers.media_asset_studio import router
from services import media_asset_studio as studio, media_asset_renderer as renderer, media_operations as media, media_publication_images as images
from test_media_publication_images import image_env, prepared as prepared_source, png
from test_google_business import gbp_env, OWNER, OPS, SECOND_OWNER

PREFIX = "/api/v1/media-asset-studio"


@pytest_asyncio.fixture
async def asset_env(image_env, monkeypatch):
    env = image_env; env.images._transport.app.include_router(router)
    env.version = await prepared_source(env)
    monkeypatch.setattr(studio, "_runtime", {"image":True, "video":False, "message":"synthetic no ffmpeg"})
    async def local_process(spec=None, *, probe=False):
        if probe: return b'{"image":true,"video":false}'
        width, height = (2, 2) if spec["recipe"]["kind"] == "enhance" else renderer.SIZES[spec["recipe"]["format"]]
        return json.dumps({"mime_type":"image/png", "width":width, "height":height, "duration_seconds":None}).encode()+b"\n"+png(width, height)
    monkeypatch.setattr(studio, "_process", local_process)
    env.render = local_process
    yield env


async def create(env, **changes):
    value = {"request_id":str(uuid4()), "profile_revision":0, "kind":"poster", "image_ids":[env.version["id"]],
        "title":"Real merchant", "subtitle":"", "format":"square", "exposure":0.0, "color":1.0, "sharpness":1.0, "rights_confirmed":True, **changes}
    response = await env.images.post(PREFIX+"/customers/10/jobs", json=value)
    assert response.status_code == 202, response.text
    return response.json()["job"], value


async def rendered(env):
    job, body = await create(env)
    tick = await studio.run_tick(sessions=env.sessions)
    assert tick["stage"] == "succeeded", tick
    response = await env.images.get(PREFIX+"/jobs/"+job["id"])
    return response.json(), body


async def counts(env):
    async with env.sessions() as db:
        return {model.__tablename__:await db.scalar(select(func.count()).select_from(model)) for model in (Job, Request, Material, Image, Task, Policy, Delivery, CustomerRecordAudit)}


@pytest.mark.asyncio
async def test_queue_is_immediate_idempotent_and_does_not_render_or_publish(asset_env, monkeypatch):
    env = asset_env
    async def forbidden(*a, **kw): pytest.fail("No rendering in the HTTP handler")
    monkeypatch.setattr(studio, "_process", forbidden)
    before = await counts(env); job, body = await create(env)
    assert job["status"] == "queued" and job["revision"] == 1 and job["output"] is None
    repeat = await env.images.post(PREFIX+"/customers/10/jobs", json=body)
    assert repeat.status_code == 202 and repeat.json()["job"] == job
    recovery = await env.images.get(PREFIX+"/requests/"+body["request_id"])
    assert recovery.json()["job"]["id"] == job["id"] and recovery.json()["kind"] == "create"
    after = await counts(env)
    assert after[Job.__tablename__] == before[Job.__tablename__]+1
    for model in (Material, Image, Task, Policy, Delivery): assert before[model.__tablename__] == after[model.__tablename__]
    assert not env.fake.writes and not env.fake.reads


@pytest.mark.asyncio
async def test_private_output_exact_hash_and_explicit_atomic_derivative_adoption(asset_env):
    env = asset_env; before = await counts(env); original = (env.root/"10/source.png").read_bytes()
    job, _ = await rendered(env)
    assert job["status"] == "succeeded" and job["can_adopt"] and job["revision"] == 3
    output = await env.images.get(job["output"]["preview_path"])
    assert output.status_code == 200 and output.headers["cache-control"] == "private, no-store"
    assert hashlib.sha256(output.content).hexdigest() == job["output"]["sha256"]
    assert (await env.images.get(job["output"]["download_path"])).headers["content-disposition"].startswith("attachment;")
    body = {"request_id":str(uuid4()), "expected_revision":job["revision"], "output_sha256":job["output"]["sha256"], "title":"New private poster", "derivative_confirmed":True}
    response = await env.images.post(PREFIX+"/jobs/"+job["id"]+"/adopt", json=body)
    assert response.status_code == 200, response.text
    adopted = response.json()["job"]; assert adopted["status"] == "adopted" and adopted["adoption"]["image_id"]
    repeat = await env.images.post(PREFIX+"/jobs/"+job["id"]+"/adopt", json=body)
    assert repeat.status_code == 200 and repeat.json()["job"] == adopted
    async with env.sessions() as db:
        material = await db.get(Material, adopted["adoption"]["material_id"])
        fixed = await db.get(Image, adopted["adoption"]["image_id"])
        assert material.visibility == "team" and material.approval_status == "pending" and material.copyright_status == "client_provided"
        assert fixed.material_id == material.id and fixed.source_sha256 == fixed.image_sha256 == job["output"]["sha256"]
        assert (await db.execute(text("SELECT amount,closing_state,commission_owner FROM financial_canary"))).one() == ("199.00", "closed", "original-owner")
        assert (await db.get(Material, 1001)).file_path == "10/source.png"
    after = await counts(env)
    assert after[Material.__tablename__] == before[Material.__tablename__]+1 and after[Image.__tablename__] == before[Image.__tablename__]+1
    for model in (Task, Policy, Delivery): assert before[model.__tablename__] == after[model.__tablename__]
    assert (env.root/"10/source.png").read_bytes() == original and not env.fake.writes


@pytest.mark.asyncio
async def test_failure_after_new_material_rolls_back_material_image_audit_receipt_and_job(asset_env, monkeypatch):
    env = asset_env; job, _ = await rendered(env); before = await counts(env)
    async def fail(*a, **kw): raise HTTPException(409, "Synthetic fixed-image failure")
    monkeypatch.setattr(images, "prepare_locked", fail)
    response = await env.images.post(PREFIX+"/jobs/"+job["id"]+"/adopt", json={"request_id":str(uuid4()), "expected_revision":job["revision"],
        "output_sha256":job["output"]["sha256"], "title":"New poster", "derivative_confirmed":True})
    assert response.status_code == 409 and await counts(env) == before
    assert (await env.images.get(PREFIX+"/jobs/"+job["id"])).json()["status"] == "succeeded"


@pytest.mark.asyncio
async def test_employee_owner_identity_and_customer_scope_rechecked(asset_env):
    env = asset_env; job, _ = await rendered(env)
    env.user = OPS
    for path in ("/customers/10/studio", "/jobs/"+job["id"], job["output"]["preview_path"].removeprefix(PREFIX)):
        assert (await env.images.get(PREFIX+path)).status_code == 403
    env.user = SECOND_OWNER
    assert (await env.images.get(PREFIX+"/jobs/"+job["id"])).status_code == 404
    env.user = OWNER
    async with env.sessions() as db:
        row = await db.get(Employees, 1); row.status = "inactive"; await db.commit()
    assert (await env.images.get(PREFIX+"/jobs/"+job["id"])).status_code == 403


@pytest.mark.asyncio
async def test_nonowner_denies_before_any_sql():
    class NoDb:
        def __getattr__(self, name): pytest.fail("Nonowner must never query "+name)
    for role in ("admin", "ops", "finance", "sales", "design"):
        with pytest.raises(HTTPException) as error: await studio.context(NoDb(), SimpleNamespace(id="2", role=role))
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_profile_cas_request_conflicts_and_current_receipt_recovery(asset_env):
    env = asset_env
    profile = {"request_id":str(uuid4()), "expected_revision":0, "preset":"clean", "brand_name":"Real Merchant", "primary_color":"#112233", "accent_color":"#FFAA22", "footer":"Real town"}
    response = await env.images.put(PREFIX+"/customers/10/profile", json=profile)
    assert response.status_code == 200 and response.json()["profile"]["revision"] == 1
    assert (await env.images.put(PREFIX+"/customers/10/profile", json=profile)).status_code == 200
    assert (await env.images.put(PREFIX+"/customers/10/profile", json={**profile, "footer":"Different"})).status_code == 409
    assert (await env.images.put(PREFIX+"/customers/10/profile", json={**profile, "request_id":str(uuid4())})).status_code == 409
    assert (await env.images.get(PREFIX+"/requests/"+profile["request_id"])).json()["profile"]["brand_name"] == "Real Merchant"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "source_bytes", "customer_stopped", "visibility", "profile"])
async def test_current_source_and_cooperation_changes_block_queue_processing_or_adoption(asset_env, change):
    env = asset_env; job, _ = await create(env)
    async with env.sessions() as db:
        if change == "revoked": (await db.get(Image, env.version["id"])).revoked_at = media.now()
        if change == "source_bytes": (env.root/"10/source.png").write_bytes(png(marker=b"\x60"))
        if change == "customer_stopped": (await db.get(Customers, 10)).status = "lost"
        if change == "visibility": (await db.get(Material, 1001)).visibility = "owner"
        if change == "profile": db.add(Profile(owner_id=1, customer_id=10, revision=1, settings={"preset":"clean", "brand_name":"Updated", "primary_color":"#000000", "accent_color":"#FF0000", "footer":""}, updated_at=media.now()))
        await db.commit()
    tick = await studio.run_tick(sessions=env.sessions)
    assert tick["stage"] == "failed"
    read = await env.images.get(PREFIX+"/jobs/"+job["id"])
    assert read.status_code == 200 and read.json()["source_stale"] and not read.json()["can_adopt"]
    if change == "customer_stopped":
        history = await env.images.get(PREFIX+"/customers/10/studio")
        assert history.status_code == 200 and not history.json()["capabilities"]["can_create"]


@pytest.mark.asyncio
async def test_worker_releases_sql_write_lock_and_uses_final_source_cas(asset_env, monkeypatch):
    env = asset_env; job, _ = await create(env); entered = asyncio.Event(); release = asyncio.Event()
    async def gated(*a, **kw): entered.set(); await release.wait(); return await env.render(*a, **kw)
    monkeypatch.setattr(studio, "_process", gated)
    tick = asyncio.create_task(studio.run_tick(sessions=env.sessions)); await asyncio.wait_for(entered.wait(), 3)
    async with env.sessions() as db:
        async with media._write(db): (await db.get(Image, env.version["id"])).revoked_at = media.now()
    busy = await studio.run_tick(sessions=env.sessions); assert busy["stage"] == "busy"
    release.set(); assert (await tick)["stage"] == "failed"
    assert (await env.images.get(PREFIX+"/jobs/"+job["id"])).json()["output"] is None


@pytest.mark.asyncio
async def test_interrupted_unknown_is_never_automatically_retried_and_explicit_retry_reuses_job(asset_env):
    env = asset_env; job, _ = await create(env)
    async with env.sessions() as db:
        row = await db.get(Job, job["id"]); row.status = "processing"; row.lease_at = media.now()-timedelta(minutes=5); row.lease_token = "a"*32; await db.commit()
    assert (await studio.run_tick(sessions=env.sessions))["stage"] == "idle"
    current = (await env.images.get(PREFIX+"/jobs/"+job["id"])).json()
    assert current["status"] == "unknown" and current["can_retry"]
    assert (await studio.run_tick(sessions=env.sessions))["stage"] == "idle"
    body = {"request_id":str(uuid4()), "expected_revision":current["revision"]}
    retry = await env.images.post(PREFIX+"/jobs/"+job["id"]+"/retry", json=body)
    assert retry.status_code == 200 and retry.json()["job"]["id"] == job["id"]
    assert (await env.images.post(PREFIX+"/jobs/"+job["id"]+"/retry", json=body)).status_code == 200
    assert (await studio.run_tick(sessions=env.sessions))["stage"] == "succeeded"
    assert (await counts(env))[Job.__tablename__] == 1


@pytest.mark.asyncio
async def test_private_artifact_tamper_symlink_and_cross_customer_sources_refused(asset_env):
    env = asset_env; job, _ = await rendered(env)
    async with env.sessions() as db: saved = dict((await db.get(Job, job["id"])).output)
    path = env.root/".asset-studio"/(saved["file_key"]+".png"); path.write_bytes(png(1080,1080,marker=b"\x77"))
    assert (await env.images.get(job["output"]["preview_path"])).status_code == 409
    path.unlink(); path.symlink_to(env.root/"10/source.png")
    assert (await env.images.get(job["output"]["preview_path"])).status_code in {404,422}
    response = await env.images.post(PREFIX+"/customers/20/jobs", json={"request_id":str(uuid4()), "profile_revision":0, "kind":"poster", "image_ids":[env.version["id"]], "rights_confirmed":True})
    assert response.status_code in {409,422}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"url":"https://example.test"}, {"image_ids":["../secret"]}, {"kind":"shell"}, {"rights_confirmed":False}, {"exposure":9}, {"color":float("nan")}, {"image_ids":["a"*32]*2}])
async def test_strict_payload_refuses_urls_paths_executables_unconfirmed_rights_and_unbounded_settings(asset_env, change):
    value = {"request_id":str(uuid4()), "profile_revision":0, "kind":"poster", "image_ids":[asset_env.version["id"]], "rights_confirmed":True, **change}
    if change.get("color") != change.get("color"):
        response = await asset_env.images.post(PREFIX+"/customers/10/jobs", content=json.dumps(value), headers={"content-type":"application/json"})
    else: response = await asset_env.images.post(PREFIX+"/customers/10/jobs", json=value)
    assert response.status_code == 422


def test_real_pillow_renderer_deterministic_real_pixels_no_metadata_and_bounded_text(monkeypatch):
    font = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if not font.exists(): font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.exists(): pytest.skip("Test-only redistributable/system font unavailable")
    monkeypatch.setattr(renderer, "FONTS", (str(font),))
    source = png(500,500,marker=b"\x50",metadata=True)
    spec = {"recipe":{"kind":"poster", "title":"Real food", "subtitle":"", "format":"square", "exposure":0, "color":1, "sharpness":1},
        "profile":{"preset":"clean", "brand_name":"Real shop", "primary_color":"#112233", "accent_color":"#F4AD31", "footer":""}, "images":[base64.b64encode(source).decode()]}
    meta, result = renderer.render(spec); assert renderer.render(spec) == (meta,result)
    canonical, width, height = images.canonical_png(result)
    assert (width,height) == (1080,1080) and b"EXIF SECRET" not in result
    from PIL import Image as PILImage
    with PILImage.open(io.BytesIO(result)) as out: assert out.getpixel((540,400)) == (80,80,80)
    spec["recipe"]["kind"] = "enhance"; spec["recipe"]["format"] = "original"; _, enhanced = renderer.render(spec)
    with PILImage.open(io.BytesIO(enhanced)) as out: assert out.getpixel((0,0)) == (80,80,80) and out.size == (500,500)
    spec["recipe"]["kind"] = "collage"; spec["recipe"]["format"] = "square"; spec["images"] *= 2
    assert renderer.render(spec)[0]["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_subprocess_uses_minimal_environment_and_reads_complete_chunked_output(tmp_path, monkeypatch):
    script = tmp_path/"synthetic_renderer.py"
    script.write_text("import os,sys,time\nassert 'SYNTHETIC_PROVIDER_SECRET' not in os.environ\nassert os.environ['OMP_NUM_THREADS']=='1'\nassert sys.flags.isolated==1\nsys.stdin.buffer.read()\nfor i in range(6):\n sys.stdout.buffer.write(b'x'*8192);sys.stdout.buffer.flush();time.sleep(.01)\n")
    monkeypatch.setenv("SYNTHETIC_PROVIDER_SECRET", "must-not-inherit")
    monkeypatch.setattr(studio, "RENDERER", script)
    kills = []; original_kill = studio.os.killpg
    def kill(pid, signal): kills.append((pid, signal)); return original_kill(pid, signal)
    monkeypatch.setattr(studio.os, "killpg", kill)
    assert await studio._process({"synthetic":True}) == b"x"*(6*8192)
    # A completed renderer can still have a local FFmpeg grandchild. The
    # parent always fences the session before deleting its temporary tree.
    import signal
    assert len(kills) == 1 and kills[0][0] > 0 and kills[0][1] == signal.SIGKILL


@pytest.mark.asyncio
async def test_runtime_probe_fails_closed_without_startup_error_or_new_tables(monkeypatch):
    monkeypatch.setattr(studio, "_runtime", None)
    async def fail(*a,**kw): raise RuntimeError("No actual engine")
    monkeypatch.setattr(studio, "_process", fail)
    assert (await studio.probe_runtime())["image"] is False
    assert (await studio.run_tick())["stage"] == "engine_unavailable"
    monkeypatch.setenv("APP_ENV", "test"); assert studio.start_worker() is None


@pytest.mark.asyncio
async def test_enhance_preserves_original_dimensions_and_formats_are_explicit(asset_env):
    env = asset_env
    body = {"request_id":str(uuid4()), "profile_revision":0, "kind":"enhance", "image_ids":[env.version["id"]], "rights_confirmed":True, "format":"square"}
    assert (await env.images.post(PREFIX+"/customers/10/jobs", json=body)).status_code == 422
    job, _ = await create(env, kind="enhance", format="original")
    assert (await studio.run_tick(sessions=env.sessions))["stage"] == "succeeded"
    current = (await env.images.get(PREFIX+"/jobs/"+job["id"])).json()
    assert (current["output"]["width"], current["output"]["height"]) == (2,2)


@pytest.mark.asyncio
async def test_output_revision_cas_does_not_overwrite_other_update(asset_env, monkeypatch):
    env = asset_env; job, _ = await create(env); enter = asyncio.Event(); release = asyncio.Event()
    async def gated(*a, **kw): enter.set(); await release.wait(); return await env.render(*a, **kw)
    monkeypatch.setattr(studio, "_process", gated)
    work = asyncio.create_task(studio.run_tick(sessions=env.sessions)); await asyncio.wait_for(enter.wait(), 3)
    async with env.sessions() as db:
        async with media._write(db):
            row = await db.get(Job, job["id"]); row.revision += 1; row.message = "Independent fenced update"
    release.set(); assert (await work)["stage"] == "superseded"
    current = (await env.images.get(PREFIX+"/jobs/"+job["id"])).json()
    assert current["message"] == "Independent fenced update" and current["output"] is None


@pytest.mark.asyncio
async def test_adopt_failure_after_image_creation_is_fully_atomic(asset_env, monkeypatch):
    env = asset_env; job, _ = await rendered(env); before = await counts(env); record = studio._record
    def fail(db, ctx, cid, request_id, kind, fingerprint, job_id=None):
        if kind == "adopt": raise HTTPException(409, "Synthetic receipt failure")
        return record(db, ctx, cid, request_id, kind, fingerprint, job_id)
    monkeypatch.setattr(studio, "_record", fail)
    response = await env.images.post(PREFIX+"/jobs/"+job["id"]+"/adopt", json={"request_id":str(uuid4()), "expected_revision":job["revision"],
        "output_sha256":job["output"]["sha256"], "title":"New poster", "derivative_confirmed":True})
    assert response.status_code == 409 and await counts(env) == before


def test_actual_asset_migration_is_additive_three_empty_tables_and_transaction_rollback(tmp_path, monkeypatch):
    import importlib.util
    import sqlite3
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1]/"alembic/versions/f21dc345d681_media_asset_studio.py"
    spec = importlib.util.spec_from_file_location("asset_migration_test", path); migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    source = path.read_bytes(); dbpath = tmp_path/"migration.db"
    con = sqlite3.connect(dbpath)
    con.execute("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)"); con.execute("INSERT INTO alembic_version VALUES('e10cb234c570')")
    for i in range(154):
        con.execute(f"CREATE TABLE legacy_{i:03}(id INTEGER PRIMARY KEY,value TEXT)"); con.execute(f"INSERT INTO legacy_{i:03} VALUES(1,'untouched')")
    con.commit(); con.close()
    def snapshot():
        con = sqlite3.connect(dbpath)
        try:
            objects = list(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
            rows = {name:list(con.execute('SELECT * FROM '+name)) for kind,name,_,_ in objects if kind == 'table'}
            return objects, rows
        finally: con.close()
    before = snapshot(); engine = sa.create_engine("sqlite:///"+str(dbpath))
    def apply():
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            with Operations.context(MigrationContext.configure(connection)): migration.upgrade()
            connection.exec_driver_sql("UPDATE alembic_version SET version_num='f21dc345d681'"); connection.commit()
    original = migration.op.create_table; counter = 0
    def fail(*a, **kw):
        nonlocal counter
        counter += 1
        if counter == 3: raise RuntimeError("Synthetic DDL failure")
        return original(*a, **kw)
    monkeypatch.setattr(migration.op, "create_table", fail)
    with pytest.raises(RuntimeError): apply()
    assert snapshot() == before
    monkeypatch.setattr(migration.op, "create_table", original); apply(); after = snapshot(); engine.dispose()
    assert len(before[1]) == 155 and len(after[1]) == 158 and set(after[1])-set(before[1]) == studio.TABLES
    assert all(row in after[0] for row in before[0])
    assert all(after[1][name] == rows for name, rows in before[1].items() if name != "alembic_version")
    assert after[1]["alembic_version"] == [("f21dc345d681",)] and all(after[1][name] == [] for name in studio.TABLES)
    assert path.read_bytes() == source


@pytest.mark.asyncio
async def test_suggested_public_copy_uses_verified_menu_or_brand_never_internal_material_label(asset_env):
    from models.customer_menu_items import Customer_menu_items as MenuItem
    env = asset_env
    first = (await env.images.get(PREFIX+"/customers/10/studio")).json()
    assert first["sources"][0]["suggested_title"] == first["profile"]["brand_name"]
    assert first["sources"][0]["suggested_title"] != first["sources"][0]["title"]
    async with env.sessions() as db:
        db.add(MenuItem(id=200, customer_id=10, user_id="1", name="Verified dumplings", status="active"))
        material = await db.get(Material, 1001); material.title = "INTERNAL OWNER ONLY ASSET LABEL"; material.linked_item_id = 200
        await db.commit()
    response = (await env.images.get(PREFIX+"/customers/10/studio")).json()
    assert response["sources"][0]["suggested_title"] == "Verified dumplings"
    async with env.sessions() as db:
        menu = await db.get(MenuItem, 200); menu.customer_id = 20; menu.name = "SECRET OTHER CUSTOMER MENU"; await db.commit()
    response = (await env.images.get(PREFIX+"/customers/10/studio")).json()
    assert response["sources"][0]["suggested_title"] == response["profile"]["brand_name"]
    assert "SECRET OTHER CUSTOMER MENU" not in str(response)


@pytest.mark.asyncio
async def test_unreadable_brand_text_color_is_rejected(asset_env):
    body = {"request_id":str(uuid4()), "expected_revision":0, "preset":"clean", "brand_name":"Real shop", "primary_color":"#FFFFFF", "accent_color":"#FFAA22", "footer":""}
    result = await asset_env.images.put(PREFIX+"/customers/10/profile", json=body)
    assert result.status_code == 422 and "深色" in result.text


def test_word_aware_wrapping_and_long_english_address_chinese_preserve_all_facts(monkeypatch):
    from PIL import Image as PILImage, ImageDraw, ImageFont
    latin = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    cjk = Path("/System/Library/Fonts/PingFang.ttc")
    if not latin.exists(): latin = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not cjk.exists(): cjk = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not latin.exists() or not cjk.exists(): pytest.skip("Local test fonts unavailable")
    draw = ImageDraw.Draw(PILImage.new("RGB", (1080,1080), "white")); font = ImageFont.truetype(str(latin), 42)
    value = "Northern Pasta offers real handmade specialties for local neighbors"
    lines = renderer.wrap_text(draw, value, font, 500)
    assert all(draw.textlength(x, font=font) <= 500 for x in lines)
    assert "".join(lines).replace(" ", "") == value.replace(" ", "")
    assert all(word in " ".join(lines).split() for word in value.split())
    monkeypatch.setattr(renderer, "FONTS", (str(cjk),))
    spec = {"recipe":{"kind":"poster", "title":"北方面食的真实餐品与手工面食欢迎周边顾客到店了解当天菜单"*2,
        "subtitle":"本页展示门店提供的真实照片具体菜品与当天供应情况请联系门店确认"*4, "format":"square", "exposure":0, "color":1, "sharpness":1},
        "profile":{"preset":"warm", "brand_name":"北方面食真实门店欢迎附近朋友来店品尝"*3, "primary_color":"#112233", "accent_color":"#F4AD31",
            "footer":"12345 Real Northern Street Suite 100, Beautiful Neighborhood, California 90000 - Visit our real local merchant today"},
        "images":[base64.b64encode(png(500,300)).decode()]}
    assert len(spec["recipe"]["title"]) <= 80 and len(spec["recipe"]["subtitle"]) <= 160
    for format in ("square", "portrait", "landscape"):
        spec["recipe"]["format"] = format
        metadata, body = renderer.render(spec)
        assert metadata["mime_type"] == "image/png" and body.startswith(images.PNG)


@pytest.mark.asyncio
async def test_empty_worker_poll_is_read_only_without_sqlite_writer_lock(asset_env):
    from sqlalchemy import event
    statements = []
    def before(connection, cursor, statement, parameters, context, executemany): statements.append(statement)
    event.listen(asset_env.engine.sync_engine, "before_cursor_execute", before)
    try: assert (await studio.run_tick(sessions=asset_env.sessions))["stage"] == "idle"
    finally: event.remove(asset_env.engine.sync_engine, "before_cursor_execute", before)
    assert statements and not any(s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "CREATE", "BEGIN IMMEDIATE")) for s in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("Synthetic failed renderer"), asyncio.CancelledError()])
async def test_parent_owns_and_cleans_private_process_temp_tree_even_when_child_cannot_cleanup(monkeypatch, error):
    saved = []
    async def interrupted(spec=None, *, probe=False, work_directory):
        root = Path(work_directory); saved.append(root)
        (root/"private-frames").mkdir(); (root/"private-frames"/"frame.png").write_bytes(b"SYNTHETIC PRIVATE FRAME")
        assert root.stat().st_mode & 0o077 == 0
        raise error
    monkeypatch.setattr(studio, "_process_in_directory", interrupted)
    with pytest.raises(type(error)): await studio._process({"synthetic":True})
    assert len(saved) == 1 and not saved[0].exists()

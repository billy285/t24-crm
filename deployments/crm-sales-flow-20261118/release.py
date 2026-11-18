"""Stage and switch the T24 CRM sales release, preserving data and rollback assets."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def local_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rt = local_module("runtime")
schema = local_module("schema")
m = json.loads((ROOT / "manifest.json").read_bytes())
rt.BASE_IMAGE = m["previous_image"]
s = m["source"]
old_public = Path(m["previous_root"])
new_public = old_public.parent / ("crm-sales-flow-" + s[:12] + "-20261118")
nginx = Path("/etc/nginx/sites-enabled/t24-crm").resolve()
retained = "t24-crm-before-sales-flow-" + s[:12]
old_id = m["previous_id"]
previous_revision = "k76cd890c136"
new_revision = "n18f9a3c0452"

def require(condition, name):
    if not condition:
        raise RuntimeError(name)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def run(args, timeout=120):
    proc = subprocess.run(list(map(str,args)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str,args[:3])))
    return proc.stdout

def write(path, data, mode=0o600):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def saved(name):
    return json.loads((ROOT/name).read_bytes())

def save(name, value):
    write(ROOT/name, json.dumps(value, sort_keys=True).encode())

def root_line(content, path):
    value = re.compile(rb"(?m)^([ \t]*root[ \t]+)" + re.escape(os.fsencode(path)) + rb"(;)")
    require(len(value.findall(content)) == 1, "unexpected active CRM web root")
    return value

def base():
    original = rt.inspect("t24-crm")
    require(original["Id"] == old_id and original["Image"] == rt.BASE_IMAGE and original["State"]["Running"], "baseline container changed")
    require((original["Config"].get("Labels") or {}).get("t24.release.source") == m["previous_source"], "baseline source label changed")
    require(json.loads((old_public/"app-version.json").read_bytes())["version"] == m["previous_version"], "baseline static version changed")
    root_line(nginx.read_bytes(), old_public)
    old = rt.inventory(old_id)
    require(all(old.get(name) == hash_ for name, hash_ in m["before"].items()), "production source differs from released baseline")
    return original, old

def prepare():
    original, old = base()
    if (ROOT/"prepared.json").exists():
        return saved("prepared.json")
    require(schema.preflight(original, ROOT)["revision"] == previous_revision, "previous database revision required")
    require(not original["HostConfig"].get("AutoRemove"), "old container cannot be retained")
    require(not any(any(("/app/backend/" + file + "/").startswith(mount["Destination"].rstrip("/") + "/")
                        for file in m["before"]) for mount in original["Mounts"]), "backend code shadowed by a mount")
    rt.validate_writable_layer(original, run(["docker","diff",old_id]).decode().splitlines())
    require(rt.cold_inventory(rt.BASE_IMAGE) == old, "base image differs from live backend source")
    require(digest((ROOT/"payload.tar.gz").read_bytes()) == m["payload_sha256"], "release payload digest")
    temp = Path(tempfile.mkdtemp(prefix="sales-flow-", dir=ROOT))
    static = temp / "static"
    patch = temp / "backend"
    with tarfile.open(ROOT/"payload.tar.gz", "r:gz") as archive:
        seen = set()
        for member in archive:
            name = member.name
            part = PurePosixPath(name)
            require(member.isfile() and name in m["files"] and name not in seen
                    and not part.is_absolute() and ".." not in part.parts and str(part) == name, "unrecognized payload member")
            seen.add(name)
            data = archive.extractfile(member).read()
            require(digest(data) == m["files"][name], "payload member digest")
            target = temp / name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        require(seen == set(m["files"]), "payload member missing")
    changes = {name: m["files"]["backend/"+name] for name in m["before"]}
    expected = {**old, **changes}
    migrations = {name: value for name, value in changes.items() if name.startswith("alembic/versions/")}
    require(set(migrations) == {
        "alembic/versions/m18f9a3c0451_sales_labels.py",
        "alembic/versions/n18f9a3c0452_sales_lead_markers.py",
    }, "exact sales migration files required")
    reference = "t24-crm:sales-flow-base-" + s[:12]
    run(["docker","tag",rt.BASE_IMAGE,reference])
    image = build_patch(reference, patch, "sales-flow", changes, expected)
    fallback_context = temp / "fallback"
    for name in migrations:
        dest = fallback_context / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(patch / name, dest)
    fallback_inventory = {**old, **migrations}
    fallback_image = build_patch(reference, fallback_context, "sales-flow-fallback", migrations, fallback_inventory)
    require(fallback_image != image, "fallback must omit sales feature code")
    probe_image(image, fallback=False)
    probe_image(fallback_image, fallback=True)
    migration_proof = schema.prepare(original, ROOT, image, fallback_image)
    for path in [static, *static.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    if not new_public.exists():
        candidate = Path(tempfile.mkdtemp(prefix=".sales-flow-release-", dir=old_public.parent))
        shutil.copytree(old_public, candidate, dirs_exist_ok=True)
        for path in (static / "assets").rglob("*"):
            target = candidate / path.relative_to(static)
            if path.is_file() and target.exists():
                require(digest(path.read_bytes()) == digest(target.read_bytes()), "hashed historical asset collision")
        shutil.copytree(static, candidate, dirs_exist_ok=True)
        candidate.chmod(0o755)
        candidate.rename(new_public)
    for name, hash_ in m["files"].items():
        if name.startswith("static/"):
            require(digest((new_public/name[7:]).read_bytes()) == hash_, "installed asset digest")
    require(json.loads((new_public/"app-version.json").read_bytes())["version"] == m["version"], "candidate static version")
    before_nginx = nginx.read_bytes()
    after_nginx = root_line(before_nginx,old_public).sub(lambda match:match.group(1)+os.fsencode(new_public)+match.group(2), before_nginx)
    write(ROOT/"nginx-before",before_nginx)
    write(ROOT/"nginx-after",after_nginx)
    save("baseline-inventory.json",old)
    value = {
        "source": s, "version": m["version"], "image": image, "old_id": old_id,
        "fallback_image": fallback_image, "fallback_inventory": inventory_digest(fallback_inventory),
        "expected_inventory": inventory_digest(expected), "migration_proof": migration_proof,
    }
    save("prepared.json",value)
    shutil.rmtree(temp)
    return value


def inventory_digest(inventory):
    return digest(json.dumps(inventory, sort_keys=True).encode())


def build_patch(reference, context, tag_prefix, changes, expected):
    tag = f"t24-crm:{tag_prefix}-{s[:12]}"
    (context/"Dockerfile").write_text("FROM "+reference+"\n"+"\n".join(
        f"COPY {name} /app/backend/{name}" for name in sorted(changes))+"\n")
    run(["docker", "build", "--network=none", "--pull=false", "-t", tag, context], timeout=360)
    image = run(["docker", "image", "inspect", "-f", "{{.Id}}", tag]).decode().strip()
    require(image != rt.BASE_IMAGE and rt.cold_inventory(image) == expected, "image backend inventory mismatch")
    return image


def probe_image(image, *, fallback):
    # No original environment, credentials, database or network.
    env = {"APP_ENV": "test", "ENVIRONMENT": "test", "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
           "JWT_SECRET_KEY": "t24-offline-synthetic-validation-only-010203040506",
           "SECRET_KEY": "t24-offline-synthetic-validation-only-010203040506"}
    script = """import sys
sys.path.insert(0, '/app/backend')
from services.database import _alembic_heads
assert _alembic_heads() == {REVISION}
from routers.sales_leads import router as lead_router
assert any(r.path.endswith('/industry-stock') for r in lead_router.routes)
if not FALLBACK:
 from routers import app_config, sales_labels
 assert any(r.path.endswith('/markers') and 'PUT' in r.methods for r in lead_router.routes)
 assert any(r.path.endswith('/sales-labels') for r in sales_labels.router.routes)
 assert any('quick-note' in r.path for r in app_config.router.routes)
"""
    script = f"REVISION={new_revision!r}; FALLBACK={fallback!r}\n" + script
    options = [arg for key, value in env.items() for arg in ("-e", key+"="+value)]
    run(["docker", "run", "--rm", "--network=none", "--read-only", "--tmpfs", "/tmp", "--tmpfs",
         "/app/backend/logs", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--entrypoint",
         "python", *options, image, "-I", "-B", "-c", script])

def nginx_switch(before, after):
    original = nginx.read_bytes()
    require(original in (before,after),"CRM nginx file changed externally")
    if original != after:
        write(nginx,after,nginx.stat().st_mode & 0o777)
    run(["nginx","-t"])
    run(["systemctl","reload","nginx"])

def web_version():
    return json.loads(run(["curl","-q","--noproxy","*","--resolve","t24-crm.com:443:127.0.0.1","-fsS","--max-time","5",
                           "-H","Cache-Control: no-cache","-H","Connection: close",
                           "https://t24-crm.com/app-version.json?release_check="+str(time.monotonic_ns())],timeout=8))["version"]

def wait_web_version(expected, timeout=30):
    deadline = time.monotonic() + timeout
    observed = "no response"
    while time.monotonic() < deadline:
        try:
            observed = web_version()
            if observed == expected:
                return observed
        except (RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
            observed = type(error).__name__
        time.sleep(0.5)
    raise RuntimeError(f"frontend version did not converge: expected {expected}, last observed {observed}")


def proxy_healthy():
    payload = json.loads(run(["curl", "-q", "--noproxy", "*", "--resolve", "t24-crm.com:443:127.0.0.1",
                              "-fsS", "--max-time", "8", "https://t24-crm.com/health"], timeout=10))
    require(payload.get("status") == "healthy" and payload.get("service") == "t24-crm",
            "CRM HTTPS proxy health check failed")

def receipt_schema(original):
    revision = schema.status(original, ROOT)["revision"]
    require(revision in {previous_revision, new_revision}, "unexpected database revision")
    return revision


def matches(container, image, source):
    return bool(container and container["Image"] == image
                and (container["Config"].get("Labels") or {}).get("t24.release.source") == source)


def guarded_stop(container):
    if container["State"]["Running"]:
        run(["docker", "stop", "--time=25", container["Id"]], timeout=55)


def rollback():
    original = rt.inspect(old_id)
    result = saved("prepared.json")
    revision = receipt_schema(original)
    current = rt.optional("t24-crm")
    fallback_active = matches(current, result["fallback_image"], m["previous_source"])
    if current and current["Id"] != old_id and not fallback_active:
        require(matches(current, result["image"], s), "a different deployment is active")
        guarded_stop(current)
        run(["docker", "rm", current["Id"]])
    if revision == new_revision:
        # Never restore a stale SQLite file or remove new data to roll back.
        # The old app only needs the two new scripts to recognize the new head.
        if original["Name"] == "/t24-crm":
            guarded_stop(original)
            run(["docker", "rename", old_id, retained])
        else:
            require(original["Name"] == "/"+retained, "unexpected original container name")
        ident = current["Id"] if fallback_active else rt.create_candidate(
            original, result["fallback_image"], m["previous_source"])
        config = rt.inspect(ident)
        rt.configuration_equal(config, original, result["fallback_image"], m["previous_source"])
        if not config["State"]["Running"]:
            run(["docker", "start", ident])
        rt.ready(ident, 120)
        require(inventory_digest(rt.inventory(ident)) == result["fallback_inventory"], "fallback runtime inventory mismatch")
    else:
        require(not fallback_active, "fallback image needs the new revision")
        if original["Name"] != "/t24-crm":
            require(original["Name"] == "/"+retained, "unexpected original container name")
            run(["docker", "rename", old_id, "t24-crm"])
        ident = old_id
        if not rt.inspect(ident)["State"]["Running"]:
            run(["docker", "start", ident])
        rt.ready(ident, 120)
    nginx_switch((ROOT/"nginx-after").read_bytes(), (ROOT/"nginx-before").read_bytes())
    wait_web_version(m["previous_version"])
    proxy_healthy()
    receipt = {"source": s, "restored": ident, "version": m["previous_version"], "schema_revision": revision}
    save("rollback.json", receipt)
    return receipt

def status(expected_frontend=None):
    active = rt.inspect("t24-crm")
    return {"container_id":active["Id"],"image":active["Image"],"running":active["State"]["Running"],
            "source":(active["Config"].get("Labels") or {}).get("t24.release.source"),
            "frontend_version":wait_web_version(expected_frontend) if expected_frontend else web_version(),
            "schema_revision": receipt_schema(active)}


def restricted_routes(ident):
    paths = ("/api/v1/sales-labels", "/api/v1/app-config/sales/quick-note-templates",
             "/api/v1/sales-leads/closing-queue")
    for path in paths:
        code = run(["docker", "exec", ident, "curl", "-q", "-sS", "--max-time", "8", "--noproxy", "*",
                    "--output", "/dev/null", "--write-out", "%{http_code}", "http://127.0.0.1:8000"+path])
        require(code in {b"401", b"403"}, f"Sales access boundary failed: {path}")

def activate():
    p = saved("prepared.json")
    cur = rt.inspect("t24-crm")
    if matches(cur, p["image"], s) and web_version() == m["version"]:
        rt.ready(cur["Id"])
        restricted_routes(cur["Id"])
        value = status()
        require(value["schema_revision"] == new_revision, "deployed schema differs")
        proxy_healthy()
        return value
    original, old = base()
    require(old == saved("baseline-inventory.json"),"baseline drifted after preparation")
    require(nginx.read_bytes() == (ROOT/"nginx-before").read_bytes(),"nginx drifted after preparation")
    require(rt.optional(retained) is None,"the retained container name is already used")
    require(receipt_schema(original) == previous_revision, "database schema drifted after preparation")
    try:
        guarded_stop(original)
        migrated = schema.migrate(original, ROOT, p["migration_proof"])
        require(receipt_schema(original) == new_revision, "additive migration did not finish")
        run(["docker","rename",old_id,retained])
        candidate = rt.create_candidate(original,p["image"],s)
        rt.configuration_equal(rt.inspect(candidate),original,p["image"],s)
        run(["docker","start",candidate])
        rt.ready(candidate,120)
        rt.configuration_equal(rt.inspect(candidate),original,p["image"],s)
        require(inventory_digest(rt.inventory(candidate)) == p["expected_inventory"],"activated source differs from candidate")
        restricted_routes(candidate)
        nginx_switch((ROOT/"nginx-before").read_bytes(),(ROOT/"nginx-after").read_bytes())
        value = status(m["version"])
        require(value["frontend_version"] == m["version"] and value["container_id"] == candidate
                and value["schema_revision"] == new_revision, "activated release is not live")
        proxy_healthy()
        value["migration"] = migrated
        save("deployed.json",value)
        return value
    except BaseException:
        rollback()
        raise

if __name__ == "__main__":
    os.umask(0o077)
    require(os.geteuid() == 0 and ROOT == Path("/opt/t24-crm/releases")/new_public.name, "wrong release target")
    with open("/opt/t24-crm/releases/.sales-flow.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        action = sys.argv[1]
        if action == "deploy":
            prepare()
            result = activate()
        else:
            result = {"prepare":prepare,"activate":activate,"rollback":rollback,"status":status}[action]()
        print(json.dumps(result,sort_keys=True))

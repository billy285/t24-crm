"""Stage and switch the T24 CRM calling-zone release; retain the prior container and assets."""
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
spec = importlib.util.spec_from_file_location("runtime", ROOT / "runtime.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)
m = json.loads((ROOT / "manifest.json").read_bytes())
s = m["source"]
old_public = Path(m["previous_root"])
new_public = old_public.parent / ("crm-timezone-claim-" + s[:12] + "-20261117")
nginx = Path("/etc/nginx/sites-enabled/t24-crm").resolve()
retained = "t24-crm-before-timezone-" + s[:12]
old_id = m["previous_id"]

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
    require(json.loads((old_public/"app-version.json").read_bytes())["version"] == m["previous_version"], "baseline static version changed")
    root_line(nginx.read_bytes(), old_public)
    old = rt.inventory(old_id)
    require(all(old.get(name) == hash_ for name, hash_ in m["before"].items()), "production source differs from released baseline")
    return original, old

def prepare():
    original, old = base()
    if (ROOT/"prepared.json").exists():
        return saved("prepared.json")
    require(not original["HostConfig"].get("AutoRemove"), "old container cannot be retained")
    require(not any(any(("/app/backend/" + file + "/").startswith(mount["Destination"].rstrip("/") + "/")
                        for file in m["before"]) for mount in original["Mounts"]), "backend code shadowed by a mount")
    rt.validate_writable_layer(original, run(["docker","diff",old_id]).decode().splitlines())
    require(rt.cold_inventory(rt.BASE_IMAGE) == old, "base image differs from live backend source")
    require(digest((ROOT/"payload.tar.gz").read_bytes()) == m["payload_sha256"], "release payload digest")
    temp = Path(tempfile.mkdtemp(prefix="timezone-claim-", dir=ROOT))
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
    expected = {**old, **{name:m["files"]["backend/"+name] for name in m["before"]}}
    reference = "t24-crm:timezone-base-" + s[:12]
    tag = "t24-crm:timezone-" + s[:12]
    run(["docker","tag",rt.BASE_IMAGE,reference])
    (patch/"Dockerfile").write_text("FROM "+reference+"\n"+"\n".join("COPY "+name+" /app/backend/"+name for name in sorted(m["before"]))+"\n")
    run(["docker","build","--network=none","--pull=false","-t",tag,patch],timeout=360)
    image = run(["docker","image","inspect","-f","{{.Id}}",tag]).decode().strip()
    require(image != rt.BASE_IMAGE and rt.cold_inventory(image) == expected,"candidate backend inventory mismatch")
    # No original container environment, provider credentials, or data mounts.
    env = {"APP_ENV":"test","ENVIRONMENT":"test","DATABASE_URL":"sqlite+aiosqlite:///:memory:",
           "JWT_SECRET_KEY":"t24-offline-synthetic-validation-only-010203040506","SECRET_KEY":"t24-offline-synthetic-validation-only-010203040506"}
    script = "import sys;sys.path.insert(0,'/app/backend');from routers.merchant_pool import IMPORT_OPTIONAL_HEADERS;from routers.sales_leads import router;assert IMPORT_OPTIONAL_HEADERS['IANA时区']=='source_timezone';assert any(r.path.endswith('/industry-stock') for r in router.routes)"
    opts=[a for k,v in env.items() for a in ("-e",k+"="+v)]
    run(["docker","run","--rm","--network=none","--read-only","--tmpfs","/tmp","--tmpfs","/app/backend/logs","--cap-drop=ALL","--security-opt=no-new-privileges","--entrypoint=python",*opts,image,"-I","-B","-c",script])
    for path in [static, *static.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    if not new_public.exists():
        candidate = Path(tempfile.mkdtemp(prefix=".timezone-release-", dir=old_public.parent))
        shutil.copytree(old_public, candidate, dirs_exist_ok=True)
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
    value = {"source":s,"version":m["version"],"image":image,"old_id":old_id,"expected_inventory":digest(json.dumps(expected,sort_keys=True).encode())}
    save("prepared.json",value)
    shutil.rmtree(temp)
    return value

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

def rollback():
    original = rt.inspect(old_id)
    current = rt.optional("t24-crm")
    p = saved("prepared.json")
    if current and current["Id"] != old_id:
        require(current["Image"] == p["image"] and current["Config"]["Labels"].get("t24.release.source") == s,
                "a different deployment is active")
        run(["docker","rm","-f",current["Id"]])
    if original["Name"] != "/t24-crm":
        require(original["Name"] == "/"+retained,"unexpected original container name")
        run(["docker","rename",old_id,"t24-crm"])
    if not rt.inspect(old_id)["State"]["Running"]:
        run(["docker","start",old_id])
    rt.ready(old_id,120)
    nginx_switch((ROOT/"nginx-after").read_bytes(),(ROOT/"nginx-before").read_bytes())
    wait_web_version(m["previous_version"])
    save("rollback.json",{"source":s,"restored":old_id,"version":m["previous_version"]})
    return saved("rollback.json")

def status(expected_frontend=None):
    active = rt.inspect("t24-crm")
    return {"container_id":active["Id"],"image":active["Image"],"running":active["State"]["Running"],
            "source":(active["Config"].get("Labels") or {}).get("t24.release.source"),
            "frontend_version":wait_web_version(expected_frontend) if expected_frontend else web_version()}

def activate():
    p = saved("prepared.json")
    cur = rt.inspect("t24-crm")
    if cur["Image"] == p["image"] and cur["Config"]["Labels"].get("t24.release.source") == s and web_version() == m["version"]:
        rt.ready(cur["Id"])
        return status()
    original, old = base()
    require(old == saved("baseline-inventory.json"),"baseline drifted after preparation")
    require(nginx.read_bytes() == (ROOT/"nginx-before").read_bytes(),"nginx drifted after preparation")
    require(rt.optional(retained) is None,"the retained container name is already used")
    try:
        run(["docker","stop","--time=25",old_id],timeout=55)
        run(["docker","rename",old_id,retained])
        candidate = rt.create_candidate(original,p["image"],s)
        rt.configuration_equal(rt.inspect(candidate),original,p["image"],s)
        run(["docker","start",candidate])
        rt.ready(candidate,120)
        rt.configuration_equal(rt.inspect(candidate),original,p["image"],s)
        require(digest(json.dumps(rt.inventory(candidate),sort_keys=True).encode()) == p["expected_inventory"],"activated source differs from candidate")
        nginx_switch((ROOT/"nginx-before").read_bytes(),(ROOT/"nginx-after").read_bytes())
        value = status(m["version"])
        require(value["frontend_version"] == m["version"] and value["container_id"] == candidate,"activated release is not live")
        save("deployed.json",value)
        return value
    except BaseException:
        rollback()
        raise

if __name__ == "__main__":
    os.umask(0o077)
    require(os.geteuid() == 0 and ROOT == Path("/opt/t24-crm/releases")/new_public.name, "wrong release target")
    with open("/opt/t24-crm/releases/.timezone-claim.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        action = sys.argv[1]
        if action == "deploy":
            prepare()
            result = activate()
        else:
            result = {"prepare":prepare,"activate":activate,"rollback":rollback,"status":status}[action]()
        print(json.dumps(result,sort_keys=True))

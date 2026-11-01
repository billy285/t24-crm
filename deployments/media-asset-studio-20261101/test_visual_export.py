"""Synthetic local-only checks for the prepared visual export reader."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import struct
import zlib
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("asset_visual_export_test",HERE/"make_visual_export.py")
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


def namespace():
    code=v.SERVER.replace("__ROOT__",repr("/synthetic-release")).replace("__RESULT__",repr("d"*64)).replace("__HOST__",repr("synthetic-host")).replace("__SOURCE__",repr("a"*40))
    tree=ast.parse(code);tree.body=[node for node in tree.body if not isinstance(node,ast.Try)]
    ns={};exec(compile(tree,"synthetic-visual-export","exec"),ns);return ns,code


def png(width=360,height=360):
    def chunk(kind,body):return struct.pack(">I",len(body))+kind+body+struct.pack(">I",zlib.crc32(kind+body)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress((b"\0"+b"\x20"*(width*3))*height))+chunk(b"IEND",b"")


def result():
    body=png();sha=hashlib.sha256(body).hexdigest();names=["chinese_long_poster","english_address_poster","original_rgba_enhance","whole_photo_collage_2","whole_photo_collage_3","whole_photo_collage_4","actual_h264_slideshow_2","actual_h264_slideshow_6"]
    cases=[{"name":name,"sha256":"c"*64,"byte_size":140000,"width":1080,"height":1080} for name in names]
    samples=[]
    for name,case in (("chinese-poster.png","chinese_long_poster"),("collage-four.png","whole_photo_collage_4")):
        samples.append({"file_name":name,"case":case,"synthetic_only":True,"mime_type":"image/png","sha256":sha,"byte_size":len(body),"width":360,"height":360,
            "original":{k:cases[0][k] for k in ("sha256","byte_size","width","height")}})
    return {"stage":"FINAL_ASSET_RENDERER_OFFLINE_VERIFIED","source_sha":"a"*40,"database_calls":0,"provider_calls":0,"business_writes":0,
        "process_launches":9,"synthetic_pixels_only":True,"all_private_temporary_trees_removed":True,"one_core_low_priority_minimal_environment":True,
        "cases":cases,"visual_samples":samples},body


def test_server_has_no_write_network_subprocess_database_or_dynamic_file_inputs():
    ns,code=namespace();ast.parse(code)
    assert "os.O_RDONLY|os.O_NOFOLLOW" in code and "s.st_uid==0" in code and "not s.st_mode&0o022" in code
    assert "before.st_nlink==1" in code and "stat.S_IMODE(before.st_mode)==0o600" in code and "fields(before)==fields(opened)==fields(after)==fields(path.lstat())" in code
    assert all(token not in code for token in ("O_WRONLY","O_CREAT","mkdir(","unlink(","subprocess","sqlite","urllib","requests","httpx","docker","restart"))
    value,_=result();assert ns["validate"](value)==value["visual_samples"]


@pytest.mark.parametrize("attack",["stage","source","db","provider","writes","false_zero","cases","launches","synthetic","traversal","duplicate","mime","sha","size","dimensions","original"])
def test_invalid_or_unverified_visual_proof_is_rejected(attack):
    ns,_=namespace();value,_=result();sample=value["visual_samples"][0]
    if attack=="stage":value["stage"]="UNKNOWN"
    if attack=="source":value["source_sha"]="b"*40
    if attack in {"db","provider","writes","false_zero"}:value[{"db":"database_calls","provider":"provider_calls","writes":"business_writes","false_zero":"database_calls"}[attack]]=False if attack=="false_zero" else 1
    if attack=="cases":value["cases"].pop()
    if attack=="launches":value["process_launches"]=8
    if attack=="synthetic":value["synthetic_pixels_only"]=False
    if attack=="traversal":sample["file_name"]="../private.png"
    if attack=="duplicate":value["visual_samples"][1]=copy.deepcopy(sample)
    if attack=="mime":sample["mime_type"]="text/html"
    if attack=="sha":sample["sha256"]="bad"
    if attack=="size":sample["byte_size"]=22529
    if attack=="dimensions":sample["width"]=361
    if attack=="original":sample["original"]["sha256"]="e"*64
    with pytest.raises(RuntimeError):ns["validate"](value)


def test_server_reads_only_result_and_fixed_two_pngs_and_prints_verified_bytes(monkeypatch,capsys):
    ns,_=namespace();value,body=result();proof=json.dumps(value).encode();reads=[]
    def read(path,maximum,sha=None):
        reads.append((str(path),maximum,sha))
        if path.name=="renderer-canary-result.json":return proof
        assert path.name in {"chinese-poster.png","collage-four.png"} and maximum==22528 and sha==hashlib.sha256(body).hexdigest();return body
    ns["read"]=read;ns["os"]=SimpleNamespace(geteuid=lambda:0);ns["socket"]=SimpleNamespace(gethostname=lambda:"synthetic-host")
    ns["resource"]=SimpleNamespace(RLIMIT_CORE=0,setrlimit=lambda *a:None)
    ns["main"]();output=json.loads(capsys.readouterr().out)
    assert len(reads)==3 and output["renderer_result"]==value and output["renderer_result_sha256"]=="d"*64
    assert len(output["previews"])==2 and all(base64.b64decode(x["base64"])==body for x in output["previews"])
    ns["read"]=lambda *a,**k:proof if a[0].name=="renderer-canary-result.json" else body[:16]+struct.pack(">II",359,360)+body[24:]
    with pytest.raises(RuntimeError,match="EXACT_PNG_HEADER_AND_DIMENSIONS_REQUIRED"):ns["main"]()


def test_read_rejects_symlink_hardlink_and_insecure_metadata_before_export(tmp_path):
    ns,_=namespace();target=tmp_path/"synthetic.png";target.write_bytes(png());target.chmod(0o600)
    link=tmp_path/"linked.png";link.symlink_to(target)
    with pytest.raises(RuntimeError,match="CANONICAL_FIXED_FILE_REQUIRED"):ns["read"](link,22528)
    # The real local owner/parent check also prevents treating this user's temp
    # files as server-root evidence. Production metadata predicates are exact.
    with pytest.raises(RuntimeError):ns["read"](target,22528)


def test_generator_requires_reviewed_canonical_prepared_and_emits_only_small_reader(monkeypatch):
    r=v.c.r;checked=[]
    monkeypatch.setattr(r,"pins_ready",lambda:None);monkeypatch.setattr(r,"SOURCE_SHA","a"*40)
    monkeypatch.setattr(r,"HOST","synthetic-host");monkeypatch.setattr(r,"ACTUAL_PREFLIGHT_SHA","b"*64)
    monkeypatch.setattr(r,"local_bytes",lambda *a,**kw:b"synthetic reviewed package")
    def validate(value,manifest,payload,preflight):
        assert preflight=="b"*64 and manifest==payload==hashlib.sha256(b"synthetic reviewed package").hexdigest()
        checked.append(value);assert value.get("approved") is True
    monkeypatch.setattr(r,"validate_prepared",validate)
    value={"approved":True,"renderer_canary_result_sha256":"d"*64};canonical=r.encoded(value)
    command,pins=v.generate(canonical)
    assert len(command.encode())<6144 and pins["executed"] is False and pins["prepared_sha256"]==hashlib.sha256(canonical).hexdigest()
    assert pins["renderer_result_sha256"]=="d"*64 and len(checked)==1
    ast.parse(command.split("<<'VISUAL'\n",1)[1].rsplit('\nVISUAL',1)[0])
    assert "--phase" not in command and "socket.gethostname" in command
    with pytest.raises(AssertionError):v.generate(r.encoded({"approved":False,"renderer_canary_result_sha256":"d"*64}))

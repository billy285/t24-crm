"""Local contract/attack tests for the release-only renderer proof, no server."""
import ast
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location("asset_final_renderer_canary_test",HERE/"renderer_canary.py")
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


def load_renderer():
    spec=importlib.util.spec_from_file_location("asset_frozen_renderer_local_test",ROOT/"app/backend/services/media_asset_renderer.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_exact_frozen_source_pins_and_no_database_or_provider_entrypoints():
    for name,sha in c.PINNED.items():assert hashlib.sha256((ROOT/"app/backend"/name).read_bytes()).hexdigest()==sha
    source=(HERE/"renderer_canary.py").read_text();ast.parse(source)
    assert "await studio._process(" in source and "sqlite3.connect=deny" in source and "studio.sessions_factory=deny" in source
    assert "signal.alarm(180)" in source and "one_core_low_priority_minimal_environment" in source
    assert not any(value in source for value in ("create_job(","run_tick(","adopt(","create_engine(","httpx.","requests.","urllib.","get_db("))


def test_complete_case_set_has_bounded_truthful_copy_and_synthetic_pixels_only():
    cases=c.cases();assert len(cases)==8
    assert [x["name"] for x in cases]==["chinese_long_poster","english_address_poster","original_rgba_enhance",
        "whole_photo_collage_2","whole_photo_collage_3","whole_photo_collage_4","actual_h264_slideshow_2","actual_h264_slideshow_6"]
    for item in cases:
        recipe=item["spec"]["recipe"];profile=item["spec"]["profile"]
        assert len(recipe["title"])<=80 and len(recipe["subtitle"])<=160 and len(profile["brand_name"])<=60 and len(profile["footer"])<=120
        assert 1<=len(item["spec"]["images"])<=6
        assert all(45<len(base64.b64decode(x))<8*1024*1024 for x in item["spec"]["images"])
        assert recipe["exposure"]==0 and recipe["color"]==recipe["sharpness"]==1


LIMITS="""Limit                     Soft Limit           Hard Limit           Units
Max cpu time              22                   22                   seconds
Max file size             25165824             25165824             bytes
Max core file size        0                    0                    bytes
Max open files            64                   64                   files
Max address space         805306368            805306368            bytes
"""


def test_effective_child_limits_must_match_real_production_bounds_exactly():
    assert c.expected_limits(LIMITS)=={"cpu_seconds":22,"memory_bytes":768*1024*1024,"file_bytes":24*1024*1024,"file_descriptors":64,"core_bytes":0}
    for text in (LIMITS.replace("22 ","unlimited "),LIMITS.replace("805306368","1610612736"),LIMITS.replace("64 ","1024 "),LIMITS.replace("Max core file size","Unrelated limit")):
        assert c.expected_limits(text) is None


def test_local_canary_png_alpha_and_corner_inspection_detects_crop_and_alpha_damage(monkeypatch):
    from PIL import Image
    renderer=load_renderer()
    font=Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if not font.exists():font=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.exists():pytest.skip("Local test font unavailable")
    monkeypatch.setattr(renderer,"FONTS",(str(font),))
    cases=c.cases();english=cases[1];alpha=cases[2]
    for case in (english,alpha):
        # Font text is only a local test fixture; the candidate always uses
        # its exact official Noto index2 and executes the isolated process.
        case=copy.deepcopy(case);case["spec"]["profile"]["brand_name"]="Offline test merchant"
        metadata,body=renderer.render(case["spec"])
        inspected=c.inspect_output(case,json.dumps(metadata).encode()+b"\n"+body)
        assert inspected["sha256"]==hashlib.sha256(body).hexdigest()
        with Image.open(io.BytesIO(body)) as image:
            broken=Image.new(image.mode,image.size,"white")
            if case["spec"]["recipe"]["kind"]=="enhance":broken.putalpha(255)
            mutated=c.image_bytes(broken)
        with pytest.raises(RuntimeError):c.inspect_output(case,json.dumps(metadata).encode()+b"\n"+mutated)


@pytest.mark.parametrize("change",["audio","codec","duration","dimensions","fps","format"])
def test_ffprobe_must_prove_complete_h264_duration_dimensions_no_audio(monkeypatch,change):
    case=c.cases()[-1];size=(1080,1350)
    row={"codec_type":"video","codec_name":"h264","width":size[0],"height":size[1],"pix_fmt":"yuv420p","r_frame_rate":"12/1"}
    data={"streams":[row],"format":{"duration":"18.000000","format_name":"mov,mp4,m4a,3gp,3g2,mj2"}}
    meta={"mime_type":"video/mp4","width":size[0],"height":size[1],"duration_seconds":18}
    body=b"\x00\x00\x00\x20ftyp"+b"SYNTHETIC-MP4-VALIDATION-ONLY"
    def probe(argv,**kw):
        assert argv[0]=="/usr/bin/ffprobe" and argv[-1]=="pipe:0" and kw["input"]==body and kw["timeout"]==5
        return SimpleNamespace(returncode=0,stdout=json.dumps(data).encode(),stderr=b"")
    monkeypatch.setattr(c.subprocess,"run",probe)
    assert c.inspect_output(case,json.dumps(meta).encode()+b"\n"+body)["ffprobe"]["duration_seconds"]==18
    if change=="audio":data["streams"].append({"codec_type":"audio"})
    if change=="codec":row["codec_name"]="mpeg4"
    if change=="duration":data["format"]["duration"]="3.0"
    if change=="dimensions":row["width"]=640
    if change=="fps":row["r_frame_rate"]="24/1"
    if change=="format":data["format"]["format_name"]="matroska,webm"
    with pytest.raises(RuntimeError):c.inspect_output(case,json.dumps(meta).encode()+b"\n"+body)


def test_synthetic_visual_files_compact_receipt_and_separate_exact_hash_export(tmp_path,monkeypatch):
    from PIL import Image
    parent=tmp_path/"logs";parent.mkdir(mode=0o700);monkeypatch.setattr(c,"VISUAL_ROOT",parent/"asset-studio-canary")
    photo,_=c.source_photo(0);photo=photo.resize((1080,1080));body=c.image_bytes(photo)
    metadata={"mime_type":"image/png","width":1080,"height":1080,"duration_seconds":None};rendered=json.dumps(metadata).encode()+b"\n"+body
    case={"name":"chinese_long_poster"};original={"sha256":hashlib.sha256(body).hexdigest(),"byte_size":len(body),"width":1080,"height":1080}
    sample=c.write_visual_sample(case,rendered,original)
    assert sample["width"]<=360 and sample["height"]<=360 and sample["byte_size"]<=22*1024 and "base64" not in sample
    assert sample["original"]==original and sample["synthetic_only"] is True
    assert c.write_visual_sample(case,rendered,original)==sample
    exported=c.export_thumbnail(sample["file_name"],sample["sha256"])
    assert len(exported["base64"])<=30*1024 and hashlib.sha256(base64.b64decode(exported["base64"])).hexdigest()==sample["sha256"]
    with pytest.raises(RuntimeError):c.export_thumbnail(sample["file_name"],"0"*64)
    with pytest.raises(RuntimeError):c.export_thumbnail("../secret",sample["sha256"])
    path=c.VISUAL_ROOT/sample["file_name"];path.unlink();path.symlink_to(parent/"unknown-private-data")
    with pytest.raises(OSError):c.export_thumbnail(sample["file_name"],sample["sha256"])

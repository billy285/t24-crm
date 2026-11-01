"""Offline execution proof for the exact frozen private renderer.

Run inside the final network-none candidate with all workers OFF and no
credentials. Uses only synthetic pixels/copy, never opens a CRM database or
creates a material/job/task/schedule. Every case goes through studio._process.
"""
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import time

SOURCE_SHA = "f595f3acfb5bfc4a28dadd3ec181b65f7c540fdd"
BACKEND = Path("/app/backend")
PINNED = {
    "services/media_asset_studio.py": "3655a9cc05786d879ad7b3afb4fb71c9f7280dcf748d7661bffbc1b89c22f16a",
    "services/media_asset_renderer.py": "a821f9767fec832687a45c7bf30ccfe25625b543893a938295a0df5e10c025bc",
    "services/media_publication_images.py": "a88ec25f09e91d1b754b5f15f24a17082e820b3af61744f3bec89c31f6ea1834",
}
FFPROBE = "/usr/bin/ffprobe"
MAX_OUTPUT = 24 * 1024 * 1024
VISUAL_ROOT = Path("/app/backend/logs/asset-studio-canary")
VISUAL_NAMES = {"chinese_long_poster":"chinese-poster.png", "whole_photo_collage_4":"collage-four.png"}
MAX_THUMBNAIL = 22 * 1024  # Both encoded previews together stay under60KiB.
MARKER = "EXACT_FINAL_ASSET_RENDERER_PNG_ALPHA_COLLAGE_H264_RESOURCE_CANARY"
H = lambda body: hashlib.sha256(body).hexdigest()


def need(value, code):
    if not value: raise RuntimeError(code)


def expected_limits(text):
    values = {}
    for label, field, unit, expected in (("Max cpu time", "cpu_seconds", "seconds", 22),
        ("Max address space", "memory_bytes", "bytes", 768*1024*1024),
        ("Max file size", "file_bytes", "bytes", MAX_OUTPUT),
        ("Max open files", "file_descriptors", "files", 64),
        ("Max core file size", "core_bytes", "bytes", 0)):
        match = re.search(r"^"+re.escape(label)+r"\s+(\S+)\s+(\S+)\s+"+unit+r"\s*$", text, re.M)
        if not match or match.groups() != (str(expected),str(expected)): return None
        values[field] = expected
    return values


def image_bytes(image, *, private_metadata=False):
    from PIL import PngImagePlugin
    metadata = PngImagePlugin.PngInfo()
    if private_metadata: metadata.add_text("private-canary", "CANARY-PRIVATE-METADATA-NOT-FOR-OUTPUT")
    buffer = io.BytesIO(); image.save(buffer, format="PNG", pnginfo=metadata, compress_level=6)
    return buffer.getvalue()


def source_photo(index):
    from PIL import Image, ImageDraw
    width, height = 640, 480
    image = Image.new("RGB", (width,height))
    # Real image pixels are transformed; no generated product is represented.
    image.putdata([((x+index*17)%200+25,(y+index*23)%180+30,(x//3+y//2+index*31)%190+20)
        for y in range(height) for x in range(width)])
    markers = ((245-index*7, 3+index, 7+index), (3+index,245-index*7,7+index),
               (3+index,7+index,245-index*7), (245-index*7,235-index*7,3+index))
    draw = ImageDraw.Draw(image); corner = 20
    for box,color in zip(((0,0,corner,corner),(width-corner-1,0,width-1,corner),
        (0,height-corner-1,corner,height-1),(width-corner-1,height-corner-1,width-1,height-1)), markers):
        draw.rectangle(box, fill=color)
    return image, markers


def source_alpha():
    from PIL import Image
    image = Image.new("RGBA", (91,137))
    image.putdata([((x*3)%256,(y*5)%256,(x+y)%256,(x*7+y*3)%256) for y in range(137) for x in range(91)])
    return image


def cases():
    photos = [source_photo(index) for index in range(6)]
    profile = {"revision":1, "preset":"warm", "brand_name":"离线真实照片版式验收商家",
        "primary_color":"#112233", "accent_color":"#F59E0B", "footer":""}
    base = {"kind":"poster", "title":"", "subtitle":"", "format":"square", "exposure":0, "color":1, "sharpness":1}
    def case(name, recipe, selected, profile_updates=None, alpha=None):
        return {"name":name, "spec":{"recipe":{**base,**recipe}, "profile":{**profile,**(profile_updates or {})},
            "images":[base64.b64encode(image_bytes(image,private_metadata=True)).decode() for image in selected]},
            "markers":[c for i,_ in enumerate(selected) for c in photos[i][1]] if alpha is None else [], "alpha":alpha}
    result = [case("chinese_long_poster", {"title":"真实门店照片展示与本店菜单信息请以门店当天实际供应为准欢迎周边朋友了解"*2,
        "subtitle":"本内容使用已提供的真实照片排版不虚构菜品不编造优惠具体服务与供应情况请联系门店确认"*3}, [photos[0][0]],
        {"brand_name":"真实商家名称与已确认门店资料用于离线模板检查"*2, "footer":"门店地址与联系信息均为离线版式检查内容请勿用于真实发布"*4}),
        case("english_address_poster", {"title":"Real Photos and Local Menu Information for Our Neighborhood Merchant",
            "subtitle":"Explore the merchant's own photos. Check current availability directly with the store before placing an order.", "format":"landscape"}, [photos[0][0]],
            {"brand_name":"Offline Real Photo Template Verification", "footer":"12345 Sample Avenue, Suite 100, Example City, CA 90000 | Offline template verification only"})]
    alpha = source_alpha()
    result.append(case("original_rgba_enhance", {"kind":"enhance", "format":"original"}, [alpha], alpha=alpha))
    for count in (2,3,4):
        result.append(case("whole_photo_collage_"+str(count), {"kind":"collage", "title":"真实照片完整展示", "format":"square"}, [x[0] for x in photos[:count]]))
    for count,format in ((2,"square"),(6,"portrait")):
        result.append(case("actual_h264_slideshow_"+str(count), {"kind":"video", "title":"真实照片轮播短片", "subtitle":"照片每张停留三秒，全片无声。", "format":format}, [x[0] for x in photos[:count]]))
    return result


def color_count(image, color):
    from PIL import ImageChops
    masks = [channel.point([255 if x == value else 0 for x in range(256)]) for channel,value in zip(image.convert("RGB").split(), color)]
    return ImageChops.multiply(ImageChops.multiply(masks[0],masks[1]),masks[2]).histogram()[255]


def inspect_output(case, rendered):
    from PIL import Image, ImageChops
    need(isinstance(rendered,bytes) and 0<len(rendered)<=MAX_OUTPUT+2048 and b"\n" in rendered, "BOUNDED_RENDERED_PROTOCOL_REQUIRED")
    header,body = rendered.split(b"\n",1); need(len(header)<2048, "BOUNDED_RENDER_HEADER_REQUIRED"); metadata = json.loads(header)
    need(set(metadata)=={"mime_type","width","height","duration_seconds"}, "EXACT_RENDER_METADATA_REQUIRED")
    recipe = case["spec"]["recipe"]; kind = recipe["kind"]
    size = case["alpha"].size if kind == "enhance" else {"square":(1080,1080),"portrait":(1080,1350),"landscape":(1200,900)}[recipe["format"]]
    need((metadata["width"],metadata["height"])==size, "EXACT_OUTPUT_DIMENSIONS_REQUIRED")
    result = {"name":case["name"], "kind":kind, "sha256":H(body), "byte_size":len(body), **metadata}
    if kind != "video":
        need(metadata["mime_type"]=="image/png" and metadata["duration_seconds"] is None and len(body)<=8*1024*1024,
            "EXACT_PRIVATE_PNG_OUTPUT_REQUIRED")
        need(b"CANARY-PRIVATE-METADATA" not in body, "PRIVATE_METADATA_MUST_BE_STRIPPED")
        with Image.open(io.BytesIO(body)) as image:
            image.load(); need(image.format=="PNG" and image.size==size and not image.info, "METADATA_FREE_PNG_REQUIRED")
            if kind == "enhance":
                need(image.mode=="RGBA" and image.getchannel("A").getextrema()==(0,255), "ORIGINAL_ALPHA_REQUIRED")
                difference = ImageChops.difference(image,case["alpha"])
                need(all(channel.getbbox() is None for channel in difference.split()), "ORIGINAL_RGBA_PIXELS_AND_SIZE_REQUIRED")
                result["original_alpha_pixels_preserved"] = True
            else:
                area = image.crop((48,155,size[0]-48,size[1]-310))
                counts = [color_count(area,color) for color in case["markers"]]
                need(all(n>=8 for n in counts), "ALL_REAL_PHOTO_CORNER_MARKERS_MUST_REMAIN_VISIBLE")
                result["whole_photo_corner_markers_verified"] = len(counts)
    else:
        count = len(case["spec"]["images"])
        need(metadata["mime_type"]=="video/mp4" and metadata["duration_seconds"]==3*count and body[4:8]==b"ftyp",
            "EXACT_PRIVATE_MP4_OUTPUT_REQUIRED")
        command = [FFPROBE,"-v","error","-protocol_whitelist","file,pipe","-show_entries",
            "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate:format=duration,format_name","-of","json","pipe:0"]
        probe = subprocess.run(command,input=body,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,check=False,
            env={"PATH":"/usr/bin:/bin","LANG":"C.UTF-8","OMP_NUM_THREADS":"1"})
        need(probe.returncode==0 and len(probe.stdout)<65536 and len(probe.stderr)<65536,"ACTUAL_FFPROBE_REQUIRED")
        data=json.loads(probe.stdout); streams=data["streams"]
        need(len(streams)==1 and streams[0]["codec_type"]=="video" and streams[0]["codec_name"]=="h264" and
            (streams[0]["width"],streams[0]["height"])==size and streams[0]["pix_fmt"]=="yuv420p" and streams[0]["r_frame_rate"]=="12/1",
            "H264_DIMENSIONS_PIXEL_FORMAT_AND_NO_AUDIO_REQUIRED")
        duration=float(data["format"]["duration"])
        need(abs(duration-count*3)<=0.1 and "mp4" in data["format"]["format_name"],"ACTUAL_COMPLETE_SLIDESHOW_DURATION_REQUIRED")
        result["ffprobe"]={"duration_seconds":duration,**streams[0]}
    return result


def write_visual_sample(case, rendered, original):
    """Only two synthetic, metadata-free, bounded previews in new probe logs."""
    from PIL import Image
    name=VISUAL_NAMES.get(case["name"])
    if name is None:return None
    _,body=rendered.split(b"\n",1)
    with Image.open(io.BytesIO(body)) as opened:
        image=opened.convert("RGB");image.thumbnail((360,360),Image.Resampling.LANCZOS)
    chosen=None
    for colors in (None,256,128,64):
        candidate=image if colors is None else image.quantize(colors=colors)
        buffer=io.BytesIO();candidate.save(buffer,format="PNG",compress_level=9,optimize=True);preview=buffer.getvalue()
        if len(preview)<=MAX_THUMBNAIL:chosen=preview;break
    need(chosen is not None,"BOUNDED_SYNTHETIC_VISUAL_PREVIEW_REQUIRED")
    parent=directory=fd=None
    try:
        parent=os.open(VISUAL_ROOT.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.mkdir(VISUAL_ROOT.name,mode=0o700,dir_fd=parent);os.fsync(parent)
        except FileExistsError:pass
        directory=os.open(VISUAL_ROOT.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        need(stat.S_IMODE(os.fstat(directory).st_mode)==0o700,"PRIVATE_SYNTHETIC_VISUAL_DIRECTORY_REQUIRED")
        try:
            fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        except FileExistsError:
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
            row=os.fstat(fd)
            need(stat.S_ISREG(row.st_mode) and row.st_nlink==1 and row.st_size==len(chosen),"EXACT_EXISTING_SYNTHETIC_PREVIEW_REQUIRED")
            need(os.read(fd,MAX_THUMBNAIL+1)==chosen,"SYNTHETIC_PREVIEW_MUST_NOT_BE_OVERWRITTEN")
        else:
            with os.fdopen(fd,"wb",closefd=False) as stream:stream.write(chosen);stream.flush();os.fsync(fd)
        os.fsync(directory)
    finally:
        if fd is not None:os.close(fd)
        if directory is not None:os.close(directory)
        if parent is not None:os.close(parent)
    return {"case":case["name"],"file_name":name,"mime_type":"image/png","sha256":H(chosen),"byte_size":len(chosen),
        "width":image.width,"height":image.height,"synthetic_only":True,
        "original":{"sha256":original["sha256"],"byte_size":original["byte_size"],"width":original["width"],"height":original["height"]}}


def export_thumbnail(name,expected):
    """Optional separate exact-hash read; never part of canonical receipt."""
    need(name in set(VISUAL_NAMES.values()) and re.fullmatch("[a-f0-9]{64}",expected or ""),"EXACT_THUMBNAIL_DESCRIPTOR_REQUIRED")
    directory=fd=None
    try:
        directory=os.open(VISUAL_ROOT,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory);before=os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and
            0<before.st_size<=MAX_THUMBNAIL,"PRIVATE_BOUNDED_THUMBNAIL_REQUIRED")
        body=os.read(fd,MAX_THUMBNAIL+1);after=os.fstat(fd)
        identity=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
        need(identity(before)==identity(after) and len(body)==before.st_size and H(body)==expected,"EXACT_SYNTHETIC_THUMBNAIL_HASH_REQUIRED")
    finally:
        if fd is not None:os.close(fd)
        if directory is not None:os.close(directory)
    return {"stage":"SYNTHETIC_RENDER_PREVIEW_EXPORTED","file_name":name,"sha256":expected,"byte_size":len(body),
        "mime_type":"image/png","base64":base64.b64encode(body).decode(),"synthetic_only":True}


async def run():
    need(sys.version_info[:2]==(3,10) and sys.platform=="linux","EXACT_CANDIDATE_PY310_LINUX_REQUIRED")
    need(os.getenv("T24_MEDIA_ASSET_WORKER_ENABLED")=="false","OFFLINE_ASSET_WORKER_OFF_REQUIRED")
    for name,sha in PINNED.items():
        path=BACKEND/name
        need(path.is_file() and not path.is_symlink() and H(path.read_bytes())==sha,"EXACT_FINAL_RENDER_SOURCE_REQUIRED")
    def deny(*a,**kw): raise RuntimeError("NO_DATABASE_OR_NETWORK_ALLOWED")
    socket.socket.connect=deny; socket.create_connection=deny; socket.getaddrinfo=deny; sqlite3.connect=deny
    sys.path.insert(0,str(BACKEND))
    from services import media_asset_studio as studio
    studio.sessions_factory=deny
    need(studio._worker is None,"NO_STUDIO_WORKER_MAY_START")
    spawn=asyncio.create_subprocess_exec; launches=[]
    async def observed(*args,**kwargs):
        need(args[:4]==(sys.executable,"-I","-B",str(BACKEND/"services/media_asset_renderer.py")) and
            list(args[4:]) in ([],["--probe"]),"EXACT_ISOLATED_RENDER_COMMAND_REQUIRED")
        env=kwargs.get("env",{})
        need(set(env)=={"PATH","LANG","OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","TMPDIR"} and
            all(env[x]=="1" for x in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS")) and
            kwargs.get("start_new_session") is True,"MINIMAL_ENVIRONMENT_AND_OWN_SESSION_REQUIRED")
        temp=Path(env["TMPDIR"])
        need(temp.parent==Path("/tmp") and temp.name.startswith("t24-asset-process-") and temp.is_dir() and
            not temp.is_symlink() and temp.stat().st_mode&0o077==0,"PARENT_OWNED_PRIVATE_TMPDIR_REQUIRED")
        process=await spawn(*args,**kwargs); measured=None; ready=False
        # Ordinary renderer invocations are now waiting for parent stdin, so
        # their effective limits can be inspected before any customer pixels.
        try:
            for _ in range(100):
                try:
                    measured=expected_limits((Path("/proc")/str(process.pid)/"limits").read_text())
                    ready=measured is not None and os.getpriority(os.PRIO_PROCESS,process.pid)>=10 and len(os.sched_getaffinity(process.pid))==1
                except OSError: pass
                if ready: break
                await asyncio.sleep(.01)
            need(measured is not None,"ACTUAL_CHILD_RESOURCE_LIMITS_REQUIRED")
            need(ready,"ONE_CORE_LOW_PRIORITY_RENDER_REQUIRED")
        except BaseException:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            await process.wait(); raise
        launches.append({"temporary_directory":temp,"limits":measured})
        return process
    asyncio.create_subprocess_exec=observed
    started=time.monotonic(); results=[];visuals=[]
    try:
        capability=json.loads(await studio._process(probe=True))
        need(capability=={"image":True,"video":True},"REAL_IMAGE_AND_VIDEO_ENGINE_PROBE_REQUIRED")
        need(all(not row["temporary_directory"].exists() for row in launches),"PROBE_TEMPORARY_TREE_CLEANUP_REQUIRED")
        for case in cases():
            began=time.monotonic(); rendered=await studio._process(case["spec"]); elapsed=time.monotonic()-began
            need(elapsed<35,"ACTUAL_RENDER_WITHIN_PRODUCTION_DEADLINE_REQUIRED")
            result=inspect_output(case,rendered);result["renderer_elapsed_seconds"]=round(elapsed,3);results.append(result)
            visual=write_visual_sample(case,rendered,result)
            if visual:visuals.append(visual)
            need(all(not row["temporary_directory"].exists() for row in launches),"ALL_PRIVATE_TEMPORARY_TREES_MUST_BE_REMOVED")
    finally: asyncio.create_subprocess_exec=spawn
    need(len(results)==8 and len(launches)==9,"ALL_RENDER_CASES_AND_ACTUAL_PROCESS_LAUNCHES_REQUIRED")
    need(len(visuals)==2 and sum((item["byte_size"]+2)//3*4 for item in visuals)<=60*1024,"BOUNDED_TWO_SYNTHETIC_VISUAL_PREVIEWS_REQUIRED")
    return {"stage":"FINAL_ASSET_RENDERER_OFFLINE_VERIFIED","source_sha":SOURCE_SHA,"source_hashes":PINNED,
        "cases":results,"visual_samples":visuals,"process_launches":len(launches),"effective_child_limits":launches[0]["limits"],
        "elapsed_seconds":round(time.monotonic()-started,3),"all_private_temporary_trees_removed":True,
        "one_core_low_priority_minimal_environment":True,"synthetic_pixels_only":True,"database_calls":0,"provider_calls":0,"business_writes":0}


def main():
    if len(sys.argv)==4 and sys.argv[1]=="--export-thumbnail":
        print(json.dumps(export_thumbnail(sys.argv[2],sys.argv[3]),sort_keys=True));return
    need(len(sys.argv)==1,"EXACT_OFFLINE_CANARY_COMMAND_REQUIRED")
    def deadline(*_): raise RuntimeError("OFFLINE_CANARY_DEADLINE_EXCEEDED")
    before=signal.signal(signal.SIGALRM,deadline)
    signal.alarm(180)
    try:
        result=asyncio.run(run()); print(json.dumps(result,sort_keys=True));print(MARKER)
    finally: signal.alarm(0);signal.signal(signal.SIGALRM,before)


if __name__=="__main__":
    try: main()
    except Exception as error:
        value=str(error);code=value if re.fullmatch("[A-Z][A-Z0-9_]{0,95}",value) else "OFFLINE_FINAL_RENDER_CANARY_FAILED"
        print(json.dumps({"stage":"FINAL_ASSET_RENDERER_OFFLINE_REJECTED","code":code},sort_keys=True));sys.exit(1)

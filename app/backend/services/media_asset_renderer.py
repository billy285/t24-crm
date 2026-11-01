"""Standalone, bounded real-photo renderer. Input/output are private pipe bytes.

No provider client, network retrieval, generated food, template download or CRM
imports belong in this process. The parent supplies already verified fixed PNGs.
"""
import base64
import io
import json
import os
from pathlib import Path
import re
import resource
import socket
import subprocess
import sys
import tempfile
import warnings

SIZES = {"square": (1080, 1080), "portrait": (1080, 1350), "landscape": (1200, 900)}
FONTS = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/app/backend/assets/media-asset-studio/NotoSansSC-Regular.ttf")
FFMPEG = "/usr/bin/ffmpeg"
MAX_INPUT = 72 * 1024 * 1024
MAX_OUTPUT = 24 * 1024 * 1024


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (22, 22))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    os.nice(10)
    if hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
        available = os.sched_getaffinity(0)
        if available: os.sched_setaffinity(0, {min(available)})
    os.umask(0o077)
    def deny(*a, **kw): raise ValueError("NETWORK_DISABLED")
    socket.socket.connect = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny


def _font_path():
    return next((p for p in FONTS if Path(p).is_file() and not Path(p).is_symlink()), None)


def wrap_text(draw, value, font, max_width):
    """Keep ordinary Latin words intact; CJK wraps at glyph boundaries."""
    tokens = re.findall(r"[A-Za-z0-9]+(?:['’/-][A-Za-z0-9]+)*|\s+|.", value)
    lines = []; current = ""
    for token in tokens:
        if draw.textlength(current+token, font=font) <= max_width:
            current += token; continue
        if current.strip(): lines.append(current.rstrip()); current = ""
        token = token.lstrip()
        if not token: continue
        if draw.textlength(token, font=font) <= max_width:
            current = token; continue
        # A single exceptionally long word/address token is broken only when
        # it cannot fit an empty line. No characters or facts are omitted.
        for char in token:
            if current and draw.textlength(current+char, font=font) > max_width:
                lines.append(current); current = char
            else: current += char
    if current.strip(): lines.append(current.rstrip())
    return lines


def render(spec):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
    Image.MAX_IMAGE_PIXELS = 2048 * 2048
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    recipe, profile = spec["recipe"], spec["profile"]
    kind = recipe["kind"]
    count = len(spec["images"])
    if not ((kind in {"poster", "enhance"} and count == 1) or (kind == "collage" and 2 <= count <= 4) or (kind == "video" and 2 <= count <= 6)):
        raise ValueError("INVALID_SOURCE_COUNT")
    if (kind == "enhance") != (recipe["format"] == "original"): raise ValueError("INVALID_FORMAT")
    size = None if kind == "enhance" else SIZES[recipe["format"]]
    font_path = _font_path()
    if not font_path: raise ValueError("FONT_UNAVAILABLE")
    def font(px): return ImageFont.truetype(font_path, px, index=2 if font_path.endswith(".ttc") else 0, layout_engine=ImageFont.Layout.BASIC)
    check_font = font(30)
    missing = bytes(check_font.getmask(chr(0x10FFFF)))
    for value in (recipe["title"], recipe["subtitle"], profile["brand_name"], profile["footer"]):
        if any(ord(c) < 32 for c in value): raise ValueError("INVALID_TEXT")
        if any(not c.isspace() and bytes(check_font.getmask(c)) == missing for c in value): raise ValueError("UNSUPPORTED_GLYPH")
    photos = []
    for encoded in spec["images"]:
        body = base64.b64decode(encoded, validate=True)
        if not 45 <= len(body) <= 8 * 1024 * 1024: raise ValueError("INVALID_PNG")
        with Image.open(io.BytesIO(body)) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1 or image.mode not in {"RGB", "RGBA"} or max(image.size) > 2048:
                raise ValueError("INVALID_PNG")
            image.load()
            alpha = image.getchannel("A").copy() if kind == "enhance" and image.mode == "RGBA" else None
            if kind == "enhance": result = image.convert("RGB")
            else:
                result = Image.new("RGB", image.size, "white")
                result.paste(image, mask=image.getchannel("A") if image.mode == "RGBA" else None)
        result = ImageEnhance.Brightness(result).enhance(1 + recipe["exposure"])
        result = ImageEnhance.Color(result).enhance(recipe["color"])
        result = ImageEnhance.Sharpness(result).enhance(recipe["sharpness"])
        if alpha is not None: result.putalpha(alpha)
        photos.append(result)
    if kind == "enhance": size = photos[0].size
    primary, accent = profile["primary_color"], profile["accent_color"]
    bg = "#F6F3EC" if profile["preset"] == "warm" else "#F8FAFC" if profile["preset"] == "clean" else "#FFFFFF"
    def text(draw, value, xy, px, minimum, color, max_width, max_height, max_lines):
        if not value: return
        for points in range(px, minimum-1, -1):
            f = font(points); lines = wrap_text(draw, value, f, max_width); step = int(points*1.3)
            if len(lines) <= max_lines and len(lines)*step <= max_height:
                for i, line in enumerate(lines): draw.text((xy[0], xy[1]+i*step), line, font=f, fill=color, anchor="lt")
                return
        raise ValueError("TEXT_DOES_NOT_FIT")
    def frame(photo):
        canvas = Image.new("RGB", size, bg); draw = ImageDraw.Draw(canvas); w, h = size
        if kind == "enhance": return photo.copy()
        draw.rectangle((0, 0, w, 12), fill=accent)
        text(draw, profile["brand_name"], (48, 35), 32, 22, primary, w-96, 110, 3)
        top, bottom = 155, h-310
        if bottom <= top: raise ValueError("INVALID_LAYOUT")
        if kind == "collage":
            n = len(photos); gap = 12; cols = 2; rows = 1 if n == 2 else 2
            cell = ((w-96-gap)//2, (bottom-top-gap*(rows-1))//rows)
            for i, p in enumerate(photos):
                x, y = 48+(i%cols)*(cell[0]+gap), top+(i//cols)*(cell[1]+gap)
                canvas.paste(ImageOps.pad(p, cell, method=Image.Resampling.LANCZOS, color=bg), (x, y))
        else: canvas.paste(ImageOps.pad(photo, (w-96, bottom-top), method=Image.Resampling.LANCZOS, color=bg), (48, top))
        text(draw, recipe["title"], (48, bottom+18), 42, 26, primary, w-96, 120, 3)
        text(draw, recipe["subtitle"], (48, bottom+146), 24, 18, primary, w-96, 82, 3)
        text(draw, profile["footer"], (48, h-60), 20, 14, primary, w-96, 50, 2)
        return canvas
    if kind == "video":
        if not Path(FFMPEG).is_file() or Path(FFMPEG).is_symlink(): raise ValueError("VIDEO_UNAVAILABLE")
        # No remote inputs, audio, demuxed source or caller-controlled command.
        with tempfile.TemporaryDirectory(prefix="t24-private-render-") as folder:
            for i, photo in enumerate(photos): frame(photo).save(Path(folder)/(str(i).zfill(2)+".png"), format="PNG", compress_level=6)
            target = Path(folder)/"result.mp4"
            command = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", "-filter_threads", "1",
                "-protocol_whitelist", "file,pipe", "-framerate", "1/3", "-i", folder+"/%02d.png", "-an", "-c:v", "libx264", "-threads", "1",
                "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p", "-r", "12", "-movflags", "+faststart", "-map_metadata", "-1", "-t", str(3*count), "-y", str(target)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=False,
                env={"PATH":"/usr/bin:/bin", "LANG":"C.UTF-8", "OMP_NUM_THREADS":"1", "OPENBLAS_NUM_THREADS":"1"})
            if result.returncode != 0 or not target.is_file() or not 1 <= target.stat().st_size <= MAX_OUTPUT: raise ValueError("VIDEO_RENDER_FAILED")
            body = target.read_bytes()
        return {"mime_type":"video/mp4", "width":size[0], "height":size[1], "duration_seconds":3*count}, body
    output = io.BytesIO(); frame(photos[0]).save(output, format="PNG", compress_level=6)
    body = output.getvalue()
    if not 45 <= len(body) <= 8*1024*1024: raise ValueError("OUTPUT_TOO_LARGE")
    return {"mime_type":"image/png", "width":size[0], "height":size[1], "duration_seconds":None}, body


def main():
    limits()
    if sys.argv[1:] == ["--probe"]:
        from PIL import Image, ImageFont
        path = _font_path()
        if not path: raise ValueError("FONT_UNAVAILABLE")
        f = ImageFont.truetype(path, 24, index=2 if path.endswith(".ttc") else 0, layout_engine=ImageFont.Layout.BASIC)
        missing = bytes(f.getmask(chr(0x10FFFF)))
        if any(bytes(f.getmask(c)) == missing for c in "真实照片Northern"): raise ValueError("FONT_UNAVAILABLE")
        video = False
        if Path(FFMPEG).is_file() and not Path(FFMPEG).is_symlink():
            # Encode an actual synthetic black frame, never customer media.
            # Listing an installed encoder is not proof it can execute.
            result = subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", "-filter_threads", "1",
                "-protocol_whitelist", "file,pipe", "-f", "lavfi", "-i", "color=c=black:s=32x32:r=1:d=1", "-frames:v", "1", "-an",
                "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "frag_keyframe+empty_moov",
                "-f", "mp4", "pipe:1"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4,
                env={"PATH":"/usr/bin:/bin", "OMP_NUM_THREADS":"1"})
            video = result.returncode == 0 and 32 < len(result.stdout) < 65536 and result.stdout[4:8] == b"ftyp"
        sys.stdout.write(json.dumps({"image":True, "video":video})); return
    raw = sys.stdin.buffer.read(MAX_INPUT+1)
    if len(raw) > MAX_INPUT: raise ValueError("INPUT_TOO_LARGE")
    metadata, body = render(json.loads(raw))
    sys.stdout.buffer.write(json.dumps(metadata, sort_keys=True).encode()+b"\n"+body)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try: main()
    except Exception as error:
        # Never print private photo pixels, copy, filesystem paths or subprocess
        # stderr. The authenticated parent maps this generic code to guidance.
        code = str(error)
        if not code.isascii() or not code.replace("_", "").isalpha() or not code.isupper() or len(code) > 40: code = "LOCAL_RENDER_FAILED"
        sys.stderr.write(code+"\n"); sys.exit(1)

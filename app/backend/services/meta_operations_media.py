"""Bounded private JPEG versions. Uploading never grants public access."""
import asyncio
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import warnings
import weakref

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent / "data" / "materials"
MAX_BYTES = 8 * 1024 * 1024
MAX_DIMENSION = 2048
IDENTITY = re.compile(r"[a-f0-9]{32}")
_slots = weakref.WeakKeyDictionary()
_working = set()


def _invalid(message="请上传不超过8MB、最长边2048像素的真实 JPEG 图片"):
    raise HTTPException(422, message)


def canonical_jpeg(body):
    if not isinstance(body, bytes) or not 4 <= len(body) <= MAX_BYTES or not body.startswith(b"\xff\xd8"):
        _invalid()
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise HTTPException(503, "图片处理组件尚未就绪，请稍后上传") from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as original:
                if original.format != "JPEG" or getattr(original, "n_frames", 1) != 1:
                    _invalid()
                if not all(1 <= value <= MAX_DIMENSION for value in original.size): _invalid()
                original.load()
                oriented = ImageOps.exif_transpose(original).convert("RGB")
                pixels = Image.new("RGB", oriented.size)
                pixels.paste(oriented)
                output = io.BytesIO()
                pixels.save(output, "JPEG", quality=92, optimize=False, progressive=False, exif=b"", icc_profile=None)
                canonical = output.getvalue()
                if len(canonical) > MAX_BYTES: _invalid("处理后的 JPEG 超过8MB，请缩小图片")
                return canonical, pixels.width, pixels.height
    except HTTPException: raise
    except Exception:
        _invalid("JPEG 像素无法完整读取，请重新导出图片后上传")


async def prepare_pixels(body):
    loop = asyncio.get_running_loop()
    slot = _slots.setdefault(loop, asyncio.Semaphore(2))
    await slot.acquire()
    try: work = asyncio.create_task(asyncio.to_thread(canonical_jpeg, body))
    except BaseException:
        slot.release(); raise
    _working.add(work)
    def complete(task):
        _working.discard(task)
        try: task.exception()
        except asyncio.CancelledError: pass
        slot.release()
    work.add_done_callback(complete)
    return await asyncio.shield(work)


def _stat(row):
    return [row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns, row.st_nlink]


def write_image(identity, body):
    if not IDENTITY.fullmatch(identity): _invalid()
    parent = directory = fd = None
    try:
        parent = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.mkdir(".meta-publication-images", mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError: pass
        directory = os.open(".meta-publication-images", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        directory_stat = os.fstat(directory)
        if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_IMODE(directory_stat.st_mode) != 0o700:
            raise HTTPException(503, "图片保存目录权限待核对")
        fd = os.open(identity + ".jpg", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(body); stream.flush(); os.fsync(fd)
        os.fsync(directory)
        return _stat(os.fstat(fd))
    except HTTPException: raise
    except OSError:
        raise HTTPException(503, "图片副本暂未保存，请保留请求编号核对原结果") from None
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)
        if parent is not None: os.close(parent)


def read_image(row):
    identity = str(row.id)
    if not IDENTITY.fullmatch(identity): _invalid()
    parent = directory = fd = None
    try:
        parent = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.open(".meta-publication-images", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        fd = os.open(identity + ".jpg", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or _stat(before) != list(row.file_stat):
            _invalid("图片副本已发生变化，请重新上传并确认")
        if not 0 < before.st_size <= MAX_BYTES or before.st_size != row.byte_size: _invalid()
        with os.fdopen(fd, "rb", closefd=False) as stream: body = stream.read(MAX_BYTES + 1)
        if _stat(os.fstat(fd)) != _stat(before) or len(body) != row.byte_size or hashlib.sha256(body).hexdigest() != row.sha256:
            _invalid("图片副本校验失败，请重新上传并确认")
        return body
    except HTTPException: raise
    except OSError:
        _invalid("图片副本不可读取，请重新上传并确认")
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)
        if parent is not None: os.close(parent)

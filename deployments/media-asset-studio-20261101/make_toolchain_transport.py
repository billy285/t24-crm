"""Split the unchanged reviewed command into ordered protected local chunks."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
H = lambda body: hashlib.sha256(body).hexdigest()

GUARD = '''import base64,hashlib,json,os,re,resource,socket,stat,sys,zlib
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
 if not ok:raise RuntimeError(code)
sys.dont_write_bytecode=True;os.umask(0o077);resource.setrlimit(resource.RLIMIT_CORE,(0,0))
need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED')
def secure(path,mode=None):
 for parent in (path,*path.parents):
  row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_TRANSPORT_PARENT_REQUIRED')
 if mode is not None:need(stat.S_IMODE(path.lstat().st_mode)==mode,'EXACT_TRANSPORT_DIRECTORY_MODE_REQUIRED')
def read(path,size,sha):
 row=path.lstat();need(path.resolve()==path and stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600 and row.st_size==size,'EXACT_TRANSPORT_FILE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno());body=f.read(size+1)
 after=path.lstat();fields=lambda r:(r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_uid,r.st_mode,r.st_nlink)
 need(fields(row)==fields(opened)==fields(after) and len(body)==size and H(body)==sha,'TRANSPORT_HASH_OR_IDENTITY_DRIFT');return body
def write(path,body):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)
'''


def wrapper(code):
    body = '#!/bin/bash\nset -eu\nsudo python3 -I -S -B - <<\'ASSET_TOOLCHAIN_PROTECTED_TRANSPORT\'\n' + GUARD + code + '\nASSET_TOOLCHAIN_PROTECTED_TRANSPORT\n'
    if len(body.encode()) >= 14000: raise RuntimeError('CONSOLE_SAFE_TRANSPORT_LIMIT_REQUIRED')
    return body


def generate(source):
    need = lambda ok: ok or (_ for _ in ()).throw(RuntimeError('EXACT_REVIEWED_TOOLCHAIN_COMMAND_REQUIRED'))
    pins = json.loads((HERE / 'toolchain-freeze.json').read_bytes())
    need(len(source) == pins['command_bytes'] and H(source) == pins['command_sha256'])
    packed = zlib.compress(source, 9); parts = [packed[i:i+6000] for i in range(0, len(packed), 6000)]
    need(1 <= len(parts) <= 4)
    stage = '/opt/t24-crm/releases/media-asset-toolchain-transport-' + H(source)[:12] + '-20261101'
    rows = [(f'part-{i:02d}.bin', len(body), H(body)) for i, body in enumerate(parts)]
    commands = {}
    for i, body in enumerate(parts):
        code = f'''root=Path({stage!r});secure(root.parent)
if not root.exists():
 need({i}==0 and not root.is_symlink(),'ORDERED_TRANSPORT_STAGING_REQUIRED');root.mkdir(mode=0o700)
secure(root,0o700);prior={rows[:i]!r};current={rows[i]!r};expected={{name for name,_,_ in prior}};actual={{p.name for p in root.iterdir()}}
need(actual in (expected,expected|{{current[0]}}),'ORDERED_APPEND_ONLY_TRANSPORT_REQUIRED')
for name,size,sha in prior:read(root/name,size,sha)
body=base64.b64decode({base64.b64encode(body).decode()!r},validate=True)
need(len(body)==current[1] and H(body)==current[2],'EXACT_TRANSPORT_CHUNK_REQUIRED')
if current[0] in actual:read(root/current[0],current[1],current[2])
else:write(root/current[0],body)
need({{p.name for p in root.iterdir()}}==expected|{{current[0]}},'EXACT_TRANSPORT_MEMBER_SET_REQUIRED')
print(json.dumps({{'stage':'ASSET_TOOLCHAIN_CHUNK_STAGED','chunk':{i},'chunk_sha256':current[2],'next_chunk':{i+1},'toolchain_executed':False}}))'''
        commands[f'stage-{i:02d}-command.sh'] = wrapper(code)
    code = f'''root=Path({stage!r});secure(root,0o700);rows={rows!r}
need({{p.name for p in root.iterdir()}}=={{name for name,_,_ in rows}},'FRESH_COMPLETE_TRANSPORT_REQUIRED')
packed=b''.join(read(root/name,size,sha) for name,size,sha in rows)
need(len(packed)=={len(packed)} and H(packed)=={H(packed)!r},'EXACT_COMPLETE_PACKED_TRANSPORT_REQUIRED')
body=zlib.decompress(packed)
need(len(body)=={len(source)} and H(body)=={H(source)!r},'EXACT_REVIEWED_TOOLCHAIN_COMMAND_REQUIRED')
script=root/'toolchain-reviewed.sh';write(script,body)
write(root/'execution-started.json',(json.dumps({{'command_sha256':{H(source)!r},'toolchain_sha256':{pins['toolchain_sha256']!r}}},sort_keys=True,indent=2)+'\\n').encode())
os.execve('/bin/bash',['/bin/bash',str(script)],{{'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}})'''
    commands['execute-command.sh'] = wrapper(code)
    return commands, {'stage': 'APPEND_ONLY_TOOLCHAIN_TRANSPORT_PREPARED', 'source_command_sha256': H(source), 'source_command_bytes': len(source),
        'toolchain_sha256': pins['toolchain_sha256'], 'directory': stage, 'packed_sha256': H(packed), 'packed_bytes': len(packed), 'chunks': rows,
        'commands': {name: {'sha256': H(body.encode()), 'bytes': len(body.encode())} for name, body in commands.items()}, 'executed': False}


def main():
    commands, pins = generate((HERE / 'toolchain-command.sh').read_bytes())
    out = HERE / 'toolchain-transport'; out.mkdir(mode=0o700)
    for name, body in {**commands, 'transport-pins.json': json.dumps(pins, sort_keys=True, indent=2) + '\n'}.items():
        fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(body); f.flush(); os.fsync(f.fileno())
    print(json.dumps(pins, sort_keys=True))


if __name__ == '__main__': main()

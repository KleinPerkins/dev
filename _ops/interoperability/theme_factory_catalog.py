"""Closed local catalog transport; no model turn or account method.

The original unreaped child remains the sole signal target through actual pipe
EOF. A work or observation expiry never creates another child or adopts a PID.
The native child is OS-denied fork, network, unrelated home reads and writes.
This is a short local parser, not general descendant or abrupt-parent-loss proof.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import threading
import time
import uuid

CLI=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
CLI_SHA='58a91f6ea19bea477ae3a2ec48d619f0039afe75d3476260747e11d201fa7cea'
PROTOCOL={'work_seconds':8.0,'term_seconds':10.0,'kill_seconds':11.0,'hard_seconds':12.0,
          'stdout_bytes':16*1024*1024,'stderr_bytes':128*1024,
          'methods':['initialize','initialized','skills/list'],'process_count':1,
          'network_and_fork_denied':True,'model_worker_count':0,
          'private_runtime_storage':{'sqlite_home':'catalog-operation/state','log_dir':'catalog-operation/logs'}}
_OWNED_CHILDREN=[]


class _Child:
    # A birth returned by our one spawn, never a discovered/borrowed PID. There
    # is no convenience poll/destructor that can reap or invent an exit status.
    def __init__(self):self.pid=None;self.stdin=None;self.stdout=None;self.stderr=None


def _spawn_owned(command,env):
    if _OWNED_CHILDREN:raise ValueError('an original catalog owner remains retained; no new child permitted')
    if threading.current_thread() is not threading.main_thread() or threading.active_count()!=1:
        raise ValueError('native catalog requires one main-thread child owner')
    child=_Child();fds=[];error=None
    blocked={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
    previous=signal.pthread_sigmask(signal.SIG_BLOCK,blocked)
    try:
        for descriptor in (0,1,2):os.fstat(descriptor)
        input_read,input_write=os.pipe();fds += [input_read,input_write]
        output_read,output_write=os.pipe();fds += [output_read,output_write]
        error_read,error_write=os.pipe();fds += [error_read,error_write]
        child.stdin,child.stdout,child.stderr=input_write,output_read,error_read
        for descriptor in (input_write,output_read,error_read):os.set_blocking(descriptor,False)
        # Python-owned descriptors are close-on-exec. Also close every observed
        # inheritable non-stdio descriptor; no thread may change this fd table.
        close=set(fds)
        for name in os.listdir('/dev/fd'):
            if not name.isdigit() or int(name)<3:continue
            try:
                if os.get_inheritable(int(name)):close.add(int(name))
            except OSError:pass  # the directory enumeration's own fd is gone
        actions=[(os.POSIX_SPAWN_DUP2,input_read,0),(os.POSIX_SPAWN_DUP2,output_write,1),
                 (os.POSIX_SPAWN_DUP2,error_write,2)]
        actions += [(os.POSIX_SPAWN_CLOSE,fd) for fd in sorted(close)]
        _OWNED_CHILDREN.append(child)
        child.pid=os.posix_spawn(command[0],command,env,file_actions=actions,setpgroup=0,
            setsigmask=previous,setsigdef=(signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGPIPE))
        for fd in (input_read,output_write,error_write):os.close(fd);fds.remove(fd)
    except BaseException as failure:error=failure
    finally:
        try:signal.pthread_sigmask(signal.SIG_SETMASK,previous)
        except BaseException as failure:error=failure
    if child.pid is None:
        for fd in fds:
            try:os.close(fd)
            except OSError:pass
        if child in _OWNED_CHILDREN:_OWNED_CHILDREN.remove(child)
        raise error or ValueError('native spawn did not return an original child')
    # Capture and registry admission precede signal-mask restoration. Any
    # deferred interruption returns the same owner for mandatory cleanup.
    for fd in fds:
        if fd not in (child.stdin,child.stdout,child.stderr):
            try:os.close(fd)
            except OSError:pass
    return child,error


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def write_once(path,raw,mode=0o600):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)


def cli_proof():
    info=CLI.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise ValueError('qualified bundled CLI identity changed')
    digest=hashlib.sha256(CLI.read_bytes()).hexdigest()
    if digest!=CLI_SHA:raise ValueError('qualified bundled CLI changed')
    return {'path':str(CLI),'sha256':digest,'device':info.st_dev,'inode':info.st_ino,
            'mode':stat.S_IMODE(info.st_mode),'size':info.st_size}


class CatalogFailure(ValueError):
    def __init__(self,message,evidence):
        super().__init__(message);self.evidence=evidence


def _strict_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate native response field')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict):raise ValueError('native response must be an object')
    return value


def _exchange(command,operation,home,cwd,executables,action):
    """Private transport seam. Public run supplies only the fixed qualified CLI."""
    operation.mkdir(mode=0o700)
    if operation.is_symlink() or stat.S_IMODE(operation.stat().st_mode)!=0o700:
        raise ValueError('private catalog operation required')
    quote=lambda p:json.dumps(str(p))
    profile=['(version 1)','(allow default)','(deny network*)','(deny appleevent-send)',
        '(deny process-fork)','(deny process-exec)',
        '(allow process-exec '+ ' '.join('(literal '+quote(p)+')' for p in executables)+')',
        '(deny file-read* (subpath '+quote(home)+'))',
        '(allow file-read* '+ ' '.join('(subpath '+quote(p)+')' for p in
            (home/'.codex',home/'dev/capabilities/skills',cwd,operation))+')',
        '(deny file-write*)','(allow file-write* (subpath '+quote(operation)+') (literal "/dev/null"))']
    write_once(operation/'catalog.sb',('\n'.join(profile)+'\n').encode(),0o400)
    inherited={k:(k in os.environ,os.environ.get(k)) for k in ('HOME','CODEX_HOME')}
    env=dict(os.environ,TMPDIR=str(operation))
    assert inherited=={k:(k in env,env.get(k)) for k in inherited}
    started=time.monotonic()
    process,spawn_interruption=_spawn_owned(['/usr/bin/sandbox-exec','-f',str(operation/'catalog.sb')]+command,env)
    streams={'stdout':process.stdout,'stderr':process.stderr}
    settled={k:False for k in streams};eof={k:False for k in streams}
    counts={k:0 for k in streams};digests={k:hashlib.sha256() for k in streams}
    pending=b'';outgoing=canonical({'id':1,'method':'initialize','params':{
        'clientInfo':{'name':'theme_factory_retained_verify','version':'1.0'},
        'capabilities':{'experimentalApi':True}}})+b'\n'
    phase=1;response=None;failure=None;shutting=False;sent=[];signals=[];overrun=False
    reaped=False;custody_lost=False;code=None

    def refuse(message):
        nonlocal failure,shutting,outgoing
        if failure is None:failure=message
        shutting=True;outgoing=b''

    def close_input():
        if process.stdin is not None:
            try:os.close(process.stdin)
            except OSError:pass
            process.stdin=None

    if spawn_interruption:refuse('native catalog interrupted during original-child capture')

    while True:
        try:
            now=time.monotonic();elapsed=now-started
            if elapsed>=PROTOCOL['work_seconds'] and not shutting:refuse('native catalog work deadline exceeded')
            if shutting:close_input()
            # No poll, wait or convenience send_signal occurs before stream
            # settlement: the original child cannot be reaped/reused before a signal.
            for name,limit,sig in [('TERM',PROTOCOL['term_seconds'],signal.SIGTERM),
                                   ('KILL',PROTOCOL['kill_seconds'],signal.SIGKILL)]:
                if shutting and elapsed>=limit and name not in signals:
                    try:os.kill(process.pid,sig)
                    except ProcessLookupError:pass
                    signals.append(name)
            if elapsed>=PROTOCOL['hard_seconds']:
                overrun=True;refuse('native catalog actual hard deadline exceeded')
            if all(settled.values()):
                try:observed,status=os.waitpid(process.pid,os.WNOHANG)
                except ChildProcessError:
                    custody_lost=True;refuse('native catalog exclusive child custody lost; no status invented');break
                if observed:
                    if observed!=process.pid:raise ValueError('unexpected native child status')
                    code=os.waitstatus_to_exitcode(status)
                    reaped=True;_OWNED_CHILDREN.remove(process);break
            reads=[stream for name,stream in streams.items() if not settled[name]]
            writes=[process.stdin] if outgoing and process.stdin is not None else []
            ready,writable,_=select.select(reads,writes,[],0.05)
            if writable:
                try:
                    used=os.write(process.stdin,outgoing);outgoing=outgoing[used:]
                except BlockingIOError:pass
                except OSError:refuse('native catalog input closed before request')
            for name,stream in streams.items():
                if stream not in ready:continue
                try:chunk=os.read(stream,65536)
                except BlockingIOError:continue
                except OSError:
                    settled[name]=True;refuse('native catalog stream unavailable before EOF');continue
                if not chunk:
                    settled[name]=eof[name]=True
                    if not shutting:refuse('native catalog closed before response')
                    continue
                counts[name]+=len(chunk);digests[name].update(chunk)
                if counts[name]>PROTOCOL[name+'_bytes']:
                    refuse('native catalog output exceeded bound');continue
                if name!='stdout' or shutting:continue
                pending+=chunk
                while b'\n' in pending and not shutting:
                    line,pending=pending.split(b'\n',1)
                    message=_strict_json(line)
                    if 'id' not in message:continue
                    if type(message['id']) is not int or message['id']!=phase:
                        refuse('native catalog response sequence changed');break
                    if 'error' in message or not isinstance(message.get('result'),dict):
                        refuse('native catalog request refused');break
                    if phase==1:
                        sent.append('initialize');phase=2
                        outgoing+=canonical({'method':'initialized','params':{}})+b'\n'
                        outgoing+=canonical({'id':2,'method':'skills/list','params':{'cwds':[str(cwd)],'forceReload':True}})+b'\n'
                    else:
                        sent+=['initialized','skills/list'];response=message['result'];shutting=True
                        outgoing=b'';close_input()
        except BaseException as error:
            # Ordinary cancellation and parser/observation failures retain this
            # same child and drain it through the shutdown path. No restart.
            refuse('native catalog parent interruption or malformed response: '+type(error).__name__)
    ended=time.monotonic();close_input()
    for stream in streams.values():os.close(stream)
    try:os.killpg(process.pid,0);group_absent=False
    except ProcessLookupError:group_absent=True
    unchanged=inherited=={k:(k in os.environ,os.environ.get(k)) for k in inherited}
    proof={'schema':'interoperability/theme-factory-catalog-process/v1','action_sha256':action,
        'duration_ms':math.ceil((ended-started)*1000),'exit_code':code,
        'methods':sent,'original_child_reaped':reaped,'exclusive_child_custody_lost':custody_lost,
        'unknown_owner_handle_retained_without_signalling':custody_lost,'actual_stdout_EOF':eof['stdout'],
        'actual_stderr_EOF':eof['stderr'],'process_group_absent_at_observation':group_absent,
        'signals_to_original_unreaped_child':signals,'stream_bytes':counts,
        'stream_sha256':{k:v.hexdigest() for k,v in digests.items()},
        'strict_actual_hard_deadline_passed':not overrun and ended-started<PROTOCOL['hard_seconds'],
        'actual_HOME_CODEX_HOME_preserved':unchanged,'OS_network_and_fork_denied':True,
        'original_birth_captured_before_parent_signal_restore':True,'single_main_thread_owner':True,
        'actual_process_cwd_inherited_without_chdir':True,
        'new_model_workers_conversation_threads_or_token_refresh_methods':0,
        'general_descendant_or_abrupt_parent_death_qualification':False}
    if not failure and (overrun or ended-started>=PROTOCOL['hard_seconds']):
        failure='native catalog actual hard deadline exceeded at terminal observation'
    if not failure and (code!=0 or not reaped or not all(eof.values()) or not group_absent or not unchanged
                        or response is None or sent!=PROTOCOL['methods']):failure='native catalog terminal or identity postcondition failed'
    proof['success']=failure is None
    write_once(operation/'process-result.json',canonical(proof)+b'\n')
    if failure:raise CatalogFailure(failure,proof)
    return response,proof


def run(plan):
    if cli_proof()!=plan['native_cli']:raise ValueError('qualified bundled CLI changed')
    home=Path(plan['home']);cwd=Path(plan['native_cwd'])
    if home!=Path.home().absolute() or cwd!=home/'Codex':raise ValueError('native catalog root escaped its fixed scope')
    operation=Path(plan['operation_dir'])/('catalog-'+str(uuid.uuid4()))
    command=[str(CLI),'-c','sqlite_home='+json.dumps(str(operation/'state')),
        '-c','log_dir='+json.dumps(str(operation/'logs')),'app-server','--stdio']
    response,proof=_exchange(command,operation,home,cwd,
        [CLI.resolve()],plan['action_sha256'])
    if cli_proof()!=plan['native_cli']:raise ValueError('bundled CLI changed during native catalog')
    return response,{'operation':str(operation),'process':proof}

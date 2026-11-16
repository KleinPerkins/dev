"""Synthetic stdio peer for the private transport tests; never a native substitute."""
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import sys
import time

kind=sys.argv[1];operation=Path(sys.argv[2])
assert os.environ['HOME']==pwd.getpwuid(os.getuid()).pw_dir
# The real home directory always exists; a machine-private file may not, in
# which case ENOENT would test fixture setup instead of the OS read fence.
try:os.listdir(os.environ['HOME'])
except PermissionError:pass
else:raise AssertionError('real home read was permitted')
try:(operation.parent/'outside-write-must-not-exist').write_text('wrong')
except PermissionError:pass
else:raise AssertionError('outside write was permitted')
try:
    with socket.socket() as s:s.connect(('127.0.0.1',9))
except PermissionError:pass
else:raise AssertionError('network was permitted')
try:pid=os.fork()
except PermissionError:pass
else:
    if pid==0:os._exit(91)
    os.waitpid(pid,0);raise AssertionError('fork was permitted')
if kind=='early':raise SystemExit(0)
if kind=='work-timeout':
    while True:time.sleep(.01)
def send(value):print(json.dumps(value),flush=True)
first=sys.stdin.readline()
if not first:raise SystemExit(0)
assert json.loads(first)['method']=='initialize'
if kind=='duplicate':
    print('{"id":1,"id":1,"result":{}}',flush=True)
    sys.stdin.read();raise SystemExit(0)
if kind=='partial':
    sys.stdout.write('{"id":1');sys.stdout.flush();raise SystemExit(0)
if kind=='stderr-overflow':sys.stderr.write('X'*200000);sys.stderr.flush()
send({'id':1,'result':{}})
initialized=sys.stdin.readline()
if not initialized:raise SystemExit(0)
assert json.loads(initialized)['method']=='initialized'
request=sys.stdin.readline()
if not request:raise SystemExit(0)
assert json.loads(request)['method']=='skills/list'
if kind=='ignore-eof':signal.signal(signal.SIGTERM,signal.SIG_IGN)
if kind=='unknown-id':send({'id':3,'result':{}})
else:send({'id':2,'result':{'data':[]}})
if kind=='ignore-eof':
    while True:time.sleep(.01)
sys.stdin.read()
sys.stderr.write('synthetic peer reached input EOF\n');sys.stderr.flush()
if kind=='nonzero':raise SystemExit(3)

import errno,json,os,socket,sys,unittest
from pathlib import Path
op=Path(__file__).parent;source=Path(sys.argv[1]);version=sys.argv[2];home=Path(os.environ['HOME']).resolve()
before={k:(k in os.environ,os.environ.get(k)) for k in ('HOME','CODEX_HOME')}
spawns=0
approved_paths=set()
def canonical(path):return Path(os.fsdecode(path)).resolve()
def private(path):
 p=canonical(path)
 return p==op or p.is_relative_to(op)
def deny():raise PermissionError(errno.EACCES,'private fixture audit denied access')
def audit(event,args):
 global spawns
 if event=='open':
  path,mode,flags=args
  if isinstance(path,int):
   info=os.fstat(path);accepted=False
   for allowed in tuple(approved_paths):
    try:
     current=allowed.stat()
     if private(allowed) and (info.st_dev,info.st_ino)==(current.st_dev,current.st_ino):accepted=True;break
    except OSError:pass
   if not accepted:deny()
   return
  p=canonical(path);writing=bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if p==home or p.is_relative_to(home):deny()
  if writing and not private(p):deny()
  if private(p):approved_paths.add(p)
 if event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.chown','os.truncate','os.utime','os.chdir'):
  if not isinstance(args[0],(str,bytes,os.PathLike)) or not private(args[0]):deny()
 if event in ('os.rename','os.link','os.symlink'):
  if event=='os.symlink':
   if not private(args[1]):deny()
  elif not private(args[0]) or not private(args[1]):deny()
 if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.exec','os.fork','os.forkpty'):deny()
 if event=='os.posix_spawn':
  executable,argv,env=args
  if executable!='/usr/bin/sandbox-exec' or len(argv)!=9 or argv[1]!='-f' or not private(argv[2]) or argv[3]!=sys.executable or argv[4:6]!=['-I','-B'] or Path(argv[6])!=source/'_ops/interoperability/fixtures/theme-factory-retained/catalog_peer.py' or argv[7] not in ('success','early','work-timeout','duplicate','partial','stderr-overflow','unknown-id','ignore-eof','nonzero') or not private(argv[8]):deny()
  if before!={k:(k in env,env.get(k)) for k in before}:deny()
  spawns+=1
 if event=='os.kill':
  pid,sig=args
  module=sys.modules.get('theme_factory_catalog')
  if sig not in (15,9) or not module or not any(c.pid==pid for c in module._OWNED_CHILDREN):deny()
 if event=='os.killpg' and args[1]!=0:deny()
sys.addaudithook(audit)
guards={}
for name,path in [('home_read',home/'.local/share/personal-portability/bootstrap-17e962df/manifest.json'),('outside_write',op.parent/(op.name+'-outside'))]:
 try:
  if name=='home_read':path.read_bytes()
  else:path.write_text('wrong')
 except PermissionError:guards[name]=True
 else:guards[name]=False
try:
 with socket.socket() as s:s.connect(('127.0.0.1',9))
except PermissionError:guards['network']=True
else:guards['network']=False
try:os.posix_spawn('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',['codex'],dict(os.environ))
except PermissionError:guards['native_CLI_launch']=True
else:guards['native_CLI_launch']=False
assert all(guards.values()),guards
sys.path.insert(0,str(source/'_ops/interoperability'))
suite=unittest.defaultTestLoader.loadTestsFromName('test_theme_factory_retained.Transport')
result=unittest.TextTestRunner(verbosity=2).run(suite)
value={'tests_run':result.testsRun,'success':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'skipped':[(str(t),r) for t,r in result.skipped],'parent_audit_guards':guards,'synthetic_peer_spawns':spawns,'actual_native_CLI_processes':0,'actual_HOME_CODEX_HOME_preserved':before=={k:(k in os.environ,os.environ.get(k)) for k in before},'parent_OS_fenced':False,'each_synthetic_child_OS_fenced':True}
Path(os.environ['TMPDIR']).joinpath('result.json').write_text(json.dumps(value,indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() else 2)

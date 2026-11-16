#!/usr/bin/env python3
"""Mandatory separate Mac synthetic-transport qualification; no native CLI.

The twenty lifecycle/identity methods run in normal owner verification. macOS
refuses nested sandbox application, so these eight methods use the closed audited
parent fixture and independently OS-fenced synthetic peers. Retain every attempt.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parents[2]
FILES=('theme_factory_canary.py','selected_skill_canary.py','isokit_migration.py','skill_migration.py','inventory.py',
    'fixtures/theme-factory-canary/fixture.py','fixtures/theme-factory-canary/source-notes.json',
    'fixtures/theme-factory-canary/workload.json','theme_factory_catalog.py','theme_factory_retained.py',
    'test_theme_factory_canary.py','test_theme_factory_retained.py',
    'fixtures/theme-factory-retained/catalog_peer.py','fixtures/theme-factory-retained/transport_driver.py')


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p,raw,mode=0o400):
    p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)


def main():
    if len(sys.argv)!=1 or sys.platform!='darwin' or sys.version_info<(3,11):
        raise ValueError('this closed source fixture requires macOS and Python3.11+; no selectors')
    before={k:(k in os.environ,os.environ.get(k)) for k in ('HOME','CODEX_HOME')}
    operation=Path(tempfile.mkdtemp(prefix='theme-factory-transport-owner-',dir='/private/tmp')).resolve()
    source=operation/'source';source.mkdir(mode=0o700)
    temporary=operation/'temporary';temporary.mkdir(mode=0o700)
    inventory=[]
    for name in FILES:
        p=HERE/name;info=p.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():
            raise ValueError('same-source test fixture identity changed')
        raw=p.read_bytes();target=source/'_ops/interoperability'/name;write(target,raw)
        inventory.append({'path':'_ops/interoperability/'+name,'sha256':digest(target)})
    driver=operation/'driver.py'
    write(driver,(source/'_ops/interoperability/fixtures/theme-factory-retained/transport_driver.py').read_bytes())
    write(operation/'source-inventory.json',(json.dumps(inventory,indent=2)+'\n').encode())
    env={**os.environ,'TMPDIR':str(temporary),'THEME_RETAINED_TEST_EVIDENCE':str(temporary/'peer-evidence'),
        'PYTHONDONTWRITEBYTECODE':'1'}
    assert before=={k:(k in env,env.get(k)) for k in before}
    log=operation/'tests.log'
    with log.open('xb') as stream:
        child=subprocess.Popen([sys.executable,'-I','-B',str(driver),str(source),platform.python_version()],
            env=env,cwd=operation,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        expiries=0
        while True:
            try:code=child.wait(timeout=10);break
            except subprocess.TimeoutExpired:
                expiries+=1
                print(json.dumps({'original_parent_handle_retained':True,'observation_expiries':expiries,'restart_or_signal':False}),flush=True)
    try:os.killpg(child.pid,0);absent=False
    except ProcessLookupError:absent=True
    result_path=temporary/'result.json'
    result=json.loads(result_path.read_bytes()) if result_path.is_file() else None
    records=[]
    for p in sorted((temporary/'peer-evidence').glob('*/process-result.json')):
        proof=json.loads(p.read_bytes());records.append({'path':str(p),'sha256':digest(p),'process':proof})
    good=bool(code==0 and absent and result and result['success'] and result['tests_run']==8
        and result['synthetic_peer_spawns']==12 and len(records)==12 and not result['skipped'])
    if good:
        for r in records:
            proof=r['process']
            assert proof['actual_stdout_EOF'] and proof['actual_stderr_EOF'] and proof['process_group_absent_at_observation']
            if not proof['original_child_reaped']:
                observer=json.loads((Path(r['path']).parent/'custody-observer.json').read_bytes())
                assert proof['exclusive_child_custody_lost'] and proof['exit_code'] is None and not proof['success']
                assert observer['actual_exclusive_wait_completed'] and observer['actual_original_status']==0
                assert observer['test_scope_retired_only_the_observed_terminal_handle']
        assert sum(not r['process']['original_child_reaped'] for r in records)==1
        assert all(digest(source/r['path'])==r['sha256'] for r in inventory)
    assert before=={k:(k in os.environ,os.environ.get(k)) for k in before}
    receipt={'schema':'interoperability/theme-factory-source-transport-qualification/v1',
        'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'operation':str(operation),
        'source_inventory':inventory,'qualifier_sha256':digest(Path(__file__)),
        'python':platform.python_version(),'interpreter':sys.executable,'interpreter_sha256':digest(Path(sys.executable)),
        'exit_code':code,'original_parent_reaped':True,'original_parent_group_absent_at_observation':absent,
        'observation_expiries':expiries,'result':result,'synthetic_peer_records':records,
        'test_log_sha256':digest(log),'all_expected_outcomes':good,'actual_HOME_CODEX_HOME_preserved':True,
        'actual_native_CLI_model_workers_links_services_or_Affirm_access':0,
        'limits':'Exact14-file source fixture, closed audited parent, actual child OS fences. No general parent OS-isolation, abrupt-parent-death/descendant qualification, ownerLinux/native catalog, source acceptance or retained installation.'}
    write(operation/'qualification.json',(json.dumps(receipt,indent=2)+'\n').encode())
    print(json.dumps({'qualification':str(operation/'qualification.json'),'python':receipt['python'],
        'tests':result['tests_run'] if result else None,'synthetic_peers':len(records),'all_expected_outcomes':good}),flush=True)
    return 0 if good else 2


if __name__=='__main__':raise SystemExit(main())

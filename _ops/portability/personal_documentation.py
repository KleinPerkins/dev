"""Bounded primary-only documentation structural observations.

The current doctor's legacy `check` route, including its read-only v2 ADR
validator, is projected over eligible personal primaries. This neither imports
legacy state nor qualifies the separate active-v2 documentation capability.
Run with Python -I -B. No repair, worker, network or native publication route.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).absolute().parent
DEPENDENCIES={
    'personal_baseline.py':'48a1e661077b889e9c0e959dfbad4466fd500f7aa546218e86bdcdda68ded4ce',
    'personal_doc_v2_contract.py':'4357e4e94887a607ce9e0ad0a5315606c3126d8f1b1e20f5fff5c99be6625fdd',
    'personal_doc_yaml.py':'4dfb643a7f4ad166bc39b77cc59b00196ad8195210d38b4105fbcb788d6aa558',
}
for name,digest in DEPENDENCIES.items():
    path=HERE/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('personal documentation dependency changed')
if not sys.dont_write_bytecode:raise ValueError('personal documentation requires Python -B')
sys.path.insert(0,str(HERE))
import personal_baseline as b
import personal_doc_v2_contract as v2
import personal_doc_yaml as yaml
for name in DEPENDENCIES:
    if Path(sys.modules[Path(name).stem].__file__).absolute()!=HERE/name:
        raise ValueError('documentation dependency imported from another root')
c,g,w,s=b.c,b.g,b.w,b.s
OWNER_REF='2b41485359c1d64129003535ae919c7caf817459'
OWNER_LIBRARY_BLOB='29d734d52270c0a03e9924ef9781c3a42ec5d9b3'
DOCTOR_BLOB='7e8aed3984be06ad970366313e43e1eebea8d40d'
SCHEMA_SOURCE_SHA256='ddfd5e8d7eb52f5b77e80428f9eaf5dea81277bc4e1bcc8fd216db56cf8b72cd'
TRIGGERS_SHA256='c9c33479c4b6918c1e37267d1103f59f82ad7ebc9aa74d15c42c05beba849282'
LEVELS=('CONFORMANT','MISSING','NEEDS_AUTHORING','DRIFTED','NEEDS_OPERATOR','CONTRADICTORY')
SPACE=r'[\t\v\f\r ]'
RECEIPTS='_ops/doc-warden/state/v2/receipts'
EVENTS='_ops/doc-warden/state/v2/events'
MAX_ENTRIES=4096
MAX_BYTES=16*1024*1024
MAX_SECONDS=12
MAX_INPUT=24*1024*1024
MAX_RECEIPTS=128
OID=re.compile(r'[0-9a-f]{40}')


class UnavailableEvidence(RuntimeError):
    """Owner validators must not reinterpret a held observation as drift."""


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise g.Refusal('documentation-duplicate-json-key')
            result[key]=value
        return result
    def invalid(value):raise g.Refusal('documentation-nonfinite-json')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def relative(value,*,root=False):
    if (not isinstance(value,str) or not value or value.startswith(('/','~'))
            or any(ord(ch)<32 or ord(ch)==127 for ch in value)):
        raise g.Refusal('documentation-relative-path-held')
    parts=tuple(part for part in value.split('/') if part not in ('','.'))
    if (not parts and not root) or any(part=='..' for part in parts):
        raise g.Refusal('documentation-relative-path-held')
    if any(part.casefold() in w.HELD_NAMES|{'.git','agent-learnings.md'} for part in parts):
        raise g.Refusal('documentation-unclassified-path-held')
    return parts


class DocReader:
    """Descriptor-only reads, membership/type/byte fences, no aliases or memory.

    Existing non-file slots can be structurally missing. Symlinks, special files,
    foreign owners and shared regular files are unavailable, never missing.
    """
    def __init__(self,tree):
        self.tree,self.repo=tree,tree.repo
        self.nodes={};self.directories={};self.cache={};self.total=0
        self.deadline=time.monotonic()+MAX_SECONDS

    def bound(self):
        if time.monotonic()>self.deadline:raise g.Refusal('documentation-time-bound')
        if len(self.nodes)>MAX_ENTRIES or self.total>MAX_BYTES:raise g.Refusal('documentation-input-bound')

    def members(self,fd,path):
        self.bound();names=[]
        with os.scandir(fd) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names)>MAX_ENTRIES:raise g.Refusal('documentation-directory-bound')
                self.bound()
        if path and any(name.casefold()=='.git' for name in names):
            raise g.Refusal('documentation-nested-root-held')
        return names

    def directory_fact(self,fd,path):
        info=os.fstat(fd)
        if info.st_uid!=os.getuid():raise g.Refusal('documentation-directory-owner-held')
        names=self.members(fd,path)
        current={**w.fact(info),'members_sha256':w.digest(sorted(names))}
        if path in self.directories and self.directories[path]!=current:
            raise g.Refusal('documentation-directory-changed')
        self.directories[path]=current
        return names

    def node(self,path):
        parts=relative(path,root=True);fd=os.dup(self.repo._fd);prefix=[]
        try:
            self.directory_fact(fd,'')
            for index,name in enumerate(parts):
                self.bound()
                try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                except FileNotFoundError:return None,None
                mode=stat.S_IFMT(info.st_mode)
                if info.st_uid!=os.getuid() or mode not in {stat.S_IFREG,stat.S_IFDIR} or (mode==stat.S_IFREG and info.st_nlink!=1):
                    raise g.Refusal('documentation-type-or-owner-held')
                if index==len(parts)-1:return w.fact(info),os.dup(fd)
                if mode!=stat.S_IFDIR:return None,None
                child=os.open(name,s.DIR_FLAGS,dir_fd=fd)
                if w.fact(os.fstat(child))!=w.fact(info):
                    os.close(child);raise g.Refusal('documentation-parent-changed')
                os.close(fd);fd=child;prefix.append(name)
                self.directory_fact(fd,'/'.join(prefix))
            return w.fact(os.fstat(fd)),os.dup(fd)
        finally:os.close(fd)

    def state(self,path):
        normalized='/'.join(relative(path,root=True));value,fd=self.node(normalized or '.')
        if fd is not None:os.close(fd)
        if normalized in self.nodes and self.nodes[normalized]!=value:
            raise g.Refusal('documentation-node-changed')
        self.nodes[normalized]=value;self.bound();return value

    def directory(self,path):
        parts=relative(path,root=True);normalized='/'.join(parts);value=self.state(path)
        if value is None or value['type']!=stat.S_IFDIR:return None
        fd=s.child_directory(self.repo._fd,parts)
        try:return self.directory_fact(fd,normalized)
        finally:os.close(fd)

    def read(self,path):
        normalized='/'.join(relative(path));before=self.state(path)
        if before is None or before['type']!=stat.S_IFREG:return None
        parent=s.child_directory(self.repo._fd,relative(path)[:-1])
        try:raw=s.read_regular(parent,relative(path)[-1])
        finally:os.close(parent)
        if self.state(path)!=before:raise g.Refusal('documentation-file-changed')
        if b'\0' in raw:raise g.Refusal('documentation-binary-text-held')
        try:raw.decode('utf-8')
        except UnicodeError:raise g.Refusal('documentation-non-utf8-text-held') from None
        if normalized in self.cache:
            if self.cache[normalized]!=raw:raise g.Refusal('documentation-bytes-changed')
        else:self.total+=len(raw);self.cache[normalized]=raw
        self.bound();return raw

    def text(self,path):
        raw=self.read(path);return None if raw is None else raw.decode('utf-8')

    def shallow(self,path,suffix,*,hidden=True):
        names=self.directory(path)
        return [] if names is None else sorted(n for n in names if n.endswith(suffix) and (hidden or not n.startswith('.')))

    def check(self):
        for path,old in list(self.nodes.items()):
            if self.state(path or '.')!=old:raise g.Refusal('documentation-node-changed')
        for path in list(self.directories):self.directory(path or '.')
        for path in list(self.cache):self.read(path)

    def digest(self):
        return w.digest({'nodes':self.nodes,'directories':self.directories,
                         'bytes':{path:g.sha(raw) for path,raw in self.cache.items()}})


class Authority:
    def __init__(self):
        self.root=HERE/'doc_v2_schemas'
        self.files={}
        fd=s.absolute_directory(self.root)
        try:
            raw=s.read_regular(fd,'SOURCE.json')
            if g.sha(raw)!=SCHEMA_SOURCE_SHA256:raise g.Refusal('documentation-schema-authority-changed')
            source=strict_json(raw)
            expected={'SOURCE.json'}|{row['name'] for row in source['files']}
            if len(expected)!=10 or set(os.listdir(fd))!=expected:raise g.Refusal('documentation-schema-members-held')
            self.files[self.root/'SOURCE.json']=raw
            for row in source['files']:
                name=row['name']
                if re.fullmatch(r'[a-z-]+\.schema\.json',name) is None:raise g.Refusal('documentation-schema-name-held')
                data=s.read_regular(fd,name)
                if g.sha(data)!=row['sha256']:raise g.Refusal('documentation-schema-bytes-changed')
                self.files[self.root/name]=data
        finally:os.close(fd)
        fd=s.absolute_directory(HERE/'doc_authority')
        try:self.triggers=s.read_regular(fd,'triggers.yml')
        finally:os.close(fd)
        if g.sha(self.triggers)!=TRIGGERS_SHA256:raise g.Refusal('documentation-trigger-authority-changed')
        self.files[HERE/'doc_authority/triggers.yml']=self.triggers
        yaml.verified_parser()
        parsed=yaml.safe_receipt_document(self.triggers)
        if not isinstance(parsed,dict) or not isinstance(parsed.get('triggers'),list):raise g.Refusal('documentation-trigger-shape-held')
        self.trigger_ids={str(row['id']) for row in parsed['triggers'] if isinstance(row,dict) and 'id' in row}

    def check(self):
        for path,raw in self.files.items():
            fd=s.absolute_directory(path.parent)
            try:current=s.read_regular(fd,path.name)
            finally:os.close(fd)
            if current!=raw:raise g.Refusal('documentation-authority-changed')
        if set(os.listdir(self.root))!={p.name for p in self.files if p.parent==self.root}:
            raise g.Refusal('documentation-schema-members-changed')
        yaml.verified_parser()


class LegacyReceipts:
    """Explicit staged personal observations; no old/global state directory read.

    Supplied bytes prove neither personal/work classification nor import consent.
    Missing, malformed or unqualified namespaces never mean known-empty state.
    """
    def __init__(self,value=None,selected=None):
        self.rows={};selected=s.selected_ids(selected)
        if value is None:return
        if (not isinstance(value,dict) or set(value)!={'schema','repositories'}
                or value['schema']!='personal-doc-receipt-observations/v1' or not isinstance(value['repositories'],list)
                or len(value['repositories'])>len(selected)):
            raise g.Refusal('documentation-receipt-input-held')
        total=0
        for row in value['repositories']:
            if (not isinstance(row,dict) or set(row)!={'repository','namespace','files'} or row['repository'] not in selected
                    or row['repository'] in self.rows or row['namespace']!=Path(s.PROJECTS[row['repository']][0]).name
                    or not isinstance(row['files'],list) or len(row['files'])>MAX_RECEIPTS):
                raise g.Refusal('documentation-receipt-namespace-held')
            files={}
            for item in row['files']:
                if (not isinstance(item,dict) or set(item)!={'name','raw_base64','sha256'}
                        or not isinstance(item['name'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.yml',item['name'])
                        or item['name'].startswith('.') or item['name'] in files or not isinstance(item['raw_base64'],str)):
                    raise g.Refusal('documentation-receipt-file-held')
                try:raw=base64.b64decode(item['raw_base64'],validate=True)
                except (ValueError,TypeError):raise g.Refusal('documentation-receipt-encoding-held') from None
                total+=len(raw)
                if len(raw)>yaml.MAX_YAML_BYTES or total>MAX_BYTES or g.sha(raw)!=item['sha256']:
                    raise g.Refusal('documentation-receipt-hash-or-bound-held')
                files[item['name']]=raw
            self.rows[row['repository']]=files

    def digest(self,repository,path):
        if repository not in self.rows:raise g.Refusal('legacy-personal-receipt-namespace-unavailable')
        for name,raw in sorted(self.rows[repository].items(),reverse=True):
            try:
                value=yaml.safe_receipt_document(raw) or {}
                if not isinstance(value,dict):raise ValueError()
                actions=value.get('approved_actions') or []
                if not isinstance(actions,list):raise ValueError()
                for action in actions:
                    if not isinstance(action,dict):raise ValueError()
                    if action.get('path')!=path:continue
                    digest=action.get('content_digest','')
                    if digest and digest not in ('n/a','index_row'):
                        if not isinstance(digest,str):raise ValueError()
                        return digest
            except (ValueError,TypeError,KeyError,RecursionError):
                raise g.Refusal('legacy-personal-receipt-parse-unavailable') from None
        return None


def match(pattern,text,flags=0):
    # The owner's grep operates on LF records. In particular, \s must never
    # consume the LF between an empty metadata field and the next record.
    return any(re.search(pattern,line,re.ASCII|flags) is not None for line in text.split('\n'))


def override(raw,key,default):
    if raw is None:return default
    for line in raw.split('\n'):
        if line.startswith(key+':'):
            value=re.sub('^'+key+':'+SPACE+'*','',line).replace('"','').replace("'",'')
            if not value or value.startswith('/') or '..' in value:return default
            relative(value,root=True);return value
    return default


def convention(readme):
    return readme is not None and match(r'(## The convention|The convention \(already|planning-document convention)',readme)


def policy_drifts(readme):
    if readme is None:return []
    result=[]
    if all(value in readme for value in ('now frozen historical','superseded file','**Status:**')):result.append('status_bullet_exception')
    if match(r'(no index/README of its own yet|has the same gap|lacks an index)',readme):result.append('stale_adr_index_crossref')
    return result


def readme_class(raw,kind,local=False):
    if raw is None:return 'MISSING'
    header=r'\|\s*(Plan|File)\s*\|' if local else r'\|\s*'+kind+r'\s*\|'
    good=match(header,raw)
    if local:good=good and match(r'^\|[-\s|]+\|',raw) and not policy_drifts(raw)
    return 'CONFORMANT' if good else 'DRIFTED'


def agents_class(raw,plans,local=False):
    if raw is None:return 'MISSING'
    if local and plans+'/README.md' in raw and match(r'(Planning documents|planning-document|execution/design plan)',raw):return 'CONFORMANT'
    begin=[i for i,line in enumerate(raw.split('\n')) if '<!-- doc-warden:begin -->' in line]
    end=[i for i,line in enumerate(raw.split('\n')) if '<!-- doc-warden:end -->' in line]
    if len(begin)>1 or len(end)>1:return 'CONTRADICTORY'
    if len(begin)==len(end)==1:return 'CONTRADICTORY' if end[0]<=begin[0] else 'CONFORMANT'
    return 'DRIFTED'


def author_todo(raw,adr=False):
    accepted=(r'^Status:'+SPACE+r'*accepted('+SPACE+r'|$|-)' if adr
              else r'^\*\*Status:\*\*'+SPACE+r'*ACCEPTED('+SPACE+r'|$|-)')
    if match(accepted,raw,re.I if adr else 0):return False
    return match(r'(^|\s)<!-- TODO: author|^\*\*[^*]+\*\*:\s*<!-- TODO: author|^# TODO: author',raw)


def plan_shape(name,raw):
    if raw is None:return 'MISSING'
    if re.fullmatch(r'[a-z0-9-]+-v[0-9]+\.md',name) is None:return 'DRIFTED'
    if author_todo(raw):return 'NEEDS_AUTHORING'
    header=[]
    for line in raw.split('\n'):
        if line.startswith('## '):break
        header.append(line)
    header='\n'.join(header).rstrip('\n')
    if not match(r'^\*\*Status:\*\*|^\*\*Date:\*\*|^\*\*Owning repository:\*\*',header):return 'DRIFTED'
    accepted=match(r'^\*\*Status:\*\*\s*ACCEPTED(\s|$|-)',header)
    standard=match(r'^\*\*Plan-type:\*\*\s*standard(\s|$)',header)
    agentic=not standard and match(r'^\*\*Plan-type:\*\*\s*agentic-execution(\s|$)',header)
    if not (standard or agentic) and (match(r'^\*\*Plan-type:\*\*',header) or not accepted):return 'DRIFTED'
    if agentic:
        section=[];active=False
        for line in raw.split('\n'):
            if match(r'^## +([0-9]+\.? *)?[Ww]ork [Ii]tems',line):active=True;continue
            if line.startswith('## '):active=False
            if active:section.append(line)
        block='\n'.join(section)
        if not all(match(pattern,block) for pattern in (r'^\s*\*\*Files:\*\*',r'^\s*\*\*Interfaces:\*\*',r'^\s*- \[[ xX]\](\s|$)')):return 'DRIFTED'
    return None


class PrivateGit:
    def __init__(self,tree,reader,snapshot):self.tree,self.reader,self.snapshot=tree,reader,snapshot;self.count=0

    def run(self,args,*,literal=True):
        self.count+=1
        if self.count>128:raise UnavailableEvidence('documentation-Git-process-bound')
        if self.tree.git._active_gitdir is None:raise UnavailableEvidence('documentation-private-Git-required')
        self.reader.bound();self.tree.unchanged();self.tree.tool.assert_current()
        argv=[str(self.tree.tool.path),*g.FLAGS,'--literal-pathspecs' if literal else '--no-literal-pathspecs']
        for setting in g.OVERRIDES:argv.extend(['-c',setting])
        quote=g.git_bool(g.last(self.tree.git.config,'core.quotepath','true'))
        argv.extend(['-c','core.quotePath='+str(quote).lower(),'--git-dir='+str(self.tree.git._active_gitdir),
                     '--work-tree='+str(self.snapshot),*args])
        try:code,out,err=g.bounded_process(argv,self.snapshot)
        except (ValueError,OSError):raise UnavailableEvidence('documentation-private-Git-unavailable') from None
        self.tree.tool.assert_current();self.tree.unchanged();self.reader.bound()
        if err:raise UnavailableEvidence('documentation-private-Git-stderr-held')
        return subprocess.CompletedProcess(args,code,out,err)

    def __call__(self,repo,*args,literal_pathspecs=False):
        if repo!=self.snapshot:raise UnavailableEvidence('documentation-Git-root-held')
        if args==('rev-parse','--show-toplevel'):pass
        elif len(args)==3 and args[:2] in (('cat-file','-t'),('cat-file','blob')) and OID.fullmatch(args[2]):pass
        elif len(args)==6 and args[:3]==('ls-tree','-z','--full-tree') and OID.fullmatch(args[3]) and args[4]=='--' and literal_pathspecs:
            # The original provenance validator examines the working path's
            # ancestors. Fence real metadata, without reading the asset body.
            try:
                parts=relative(args[5])
                for index in range(1,len(parts)+1):
                    state=self.reader.state('/'.join(parts[:index]))
                    if state is not None and state['type']!=(stat.S_IFREG if index==len(parts) else stat.S_IFDIR):
                        raise g.Refusal('documentation-asset-path-type-held')
            except (g.Refusal,OSError):raise UnavailableEvidence('documentation-asset-path-unavailable') from None
        else:raise UnavailableEvidence('documentation-Git-verb-held')
        return self.run(list(args))

    def plans(self,rawdir):
        result=self.run(['ls-files','--',rawdir],literal=False)
        if result.returncode:raise UnavailableEvidence('documentation-plan-inventory-unavailable')
        # Use the owner's actual fixed awk selection over Git's C-quoted LF
        # names. Never decode/approximate core.quotePath or pathspec semantics.
        script=r'index($0,prefix)==1 { rel=substr($0,length(prefix)+1); if(rel!~/\// && rel~/\.md$/ && rel!="README.md") print rel }'
        code,out,err=g.bounded_process(['/usr/bin/awk','-v','prefix='+rawdir+'/',script],self.snapshot,result.stdout)
        if code or err:raise UnavailableEvidence('documentation-plan-selection-unavailable')
        try:names=out.decode('utf-8').splitlines()
        except UnicodeError:raise UnavailableEvidence('documentation-plan-names-held') from None
        if len(names)>MAX_ENTRIES:raise UnavailableEvidence('documentation-plan-count-bound')
        return sorted(names)


class V2Snapshot:
    def __init__(self,reader,private,authority):
        self.reader,self.private,self.authority=reader,private,authority
        self.root=private.snapshot;self.contract=v2.observation_contract(authority.root,private)
        self.ready=False

    def copy(self,path):
        raw=self.reader.read(path)
        if raw is not None:
            destination=self.root.joinpath(*relative(path));destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if destination.exists() and destination.read_bytes()!=raw:raise UnavailableEvidence('documentation-snapshot-collision')
            destination.write_bytes(raw);destination.chmod(0o600)

    def directory(self,path):
        state=self.reader.state(path)
        if state is None:return False
        if state['type']!=stat.S_IFDIR:raise UnavailableEvidence('documentation-v2-directory-type-held')
        self.reader.directory(path)
        self.root.joinpath(*relative(path)).mkdir(parents=True,exist_ok=True,mode=0o700)
        return True

    def prepare(self):
        if self.ready:return
        for path in ('.doc-warden.yml','.planning/doc-warden.json'):self.copy(path)
        # Resolve the v2 override using the exact read-only owner function.
        owner=self.contract['adr_directory'](self.root)
        relative(owner)
        for path in ('.planning/artifacts',owner):
            if self.directory(path):
                for name in self.reader.shallow(path,'.md'):
                    state=self.reader.state(path+'/'+name)
                    if state is not None and state['type']!=stat.S_IFREG:
                        raise UnavailableEvidence('documentation-v2-artifact-type-held')
                    self.copy(path+'/'+name)
        if self.directory(RECEIPTS):
            for name in self.reader.shallow(RECEIPTS,'.json'):
                self.copy(RECEIPTS+'/'+name)
                raw=self.reader.cache.get(RECEIPTS+'/'+name)
                if raw is None:raise UnavailableEvidence('documentation-v2-receipt-type-held')
                # Preserve lazy owner validation: a later invalid receipt must
                # not override an earlier matching freeze. Parsing here only
                # stages closed event pointers; the owner checks their order.
                try:
                    receipt=self.contract['parse_json_object'](raw)
                    self.contract['require_valid']('receipt',receipt)
                except ValueError:continue
                if self.contract['frozen_semantic_postimages'](receipt):
                    event_id=receipt['event_id']
                    # The schema validates UUID shape; no arbitrary input path.
                    if re.fullmatch(r'[0-9a-f-]{36}',event_id) is None:raise ValueError('event identifier invalid')
                    self.copy(EVENTS+'/'+event_id+'.json')
        self.ready=True

    def validate(self,path):
        self.prepare();self.copy(path)
        # Local provenance path metadata is checked on the original root by
        # the closed Git callback, before any immutable source blob is read.
        # Working asset bodies are never copied or read.
        return self.contract['validate_adr_record'](self.root,self.root.joinpath(*relative(path)))


class Structural:
    def __init__(self,tree,reader,authority,receipts,private):
        self.tree,self.reader,self.authority,self.receipts=tree,reader,authority,receipts
        self.private=private;self.v2=V2Snapshot(reader,private,authority);self.items=[]

    def item(self,path,operation):
        try:
            classification=operation()
            if classification not in LEVELS:raise g.Refusal('documentation-classification-held')
            row={'path':path,'classification':classification,'available':True}
        except (g.Refusal,UnavailableEvidence,OSError,UnicodeError,RecursionError):
            row={'path':path,'classification':'UNAVAILABLE','available':False}
        self.items.append(row)

    def receipt_class(self,path,raw):
        digest=self.receipts.digest(self.tree.repo.row['id'],path)
        return 'DRIFTED' if digest is not None and g.sha(raw.encode())!=digest else 'CONFORMANT'

    def plan(self,directory,name):
        path=directory+'/'+name;raw=self.reader.text(path);value=plan_shape(name,raw)
        return value if value is not None else self.receipt_class(path,raw)

    def adr(self,directory,name):
        path=directory+'/'+name;raw=self.reader.text(path)
        if raw is None:return 'MISSING'
        if re.fullmatch(r'[0-9]{4}-[a-z0-9-]+\.md',name) is None:return 'DRIFTED'
        if author_todo(raw,True):return 'NEEDS_AUTHORING'
        state=self.reader.state(RECEIPTS)
        if (state is not None and state['type']==stat.S_IFDIR) or raw.split('\n',1)[0].startswith('---') or 'doc-warden/artifact/' in raw:
            try:
                if self.v2.validate(path):return 'CONFORMANT'
            except (g.Refusal,UnavailableEvidence):raise
            except (ValueError,OSError,KeyError,TypeError):return 'DRIFTED'
        if not all(match('^## '+section,raw) for section in ('Decision','Why','Consequences')):return 'DRIFTED'
        return self.receipt_class(path,raw)

    def collect(self):
        config=self.reader.text('.doc-warden.yml')
        plans=override(config,'plans_dir','docs/plans');adr=override(config,'adr_dir','docs/adr')
        plans_readme=self.reader.text(plans+'/README.md');agents=self.reader.text('AGENTS.md')
        local=convention(plans_readme)
        self.item(plans,lambda:'CONFORMANT' if self.reader.directory(plans) is not None else 'MISSING')
        self.item(plans+'/README.md',lambda:readme_class(plans_readme,'Plan',local))
        self.item(adr,lambda:'CONFORMANT' if self.reader.directory(adr) is not None else 'MISSING')
        self.item(adr+'/README.md',lambda:readme_class(self.reader.text(adr+'/README.md'),'ADR'))
        self.item('AGENTS.md',lambda:agents_class(agents,plans,local))
        if local:
            for drift in policy_drifts(plans_readme):self.item('policy:'+drift,lambda:'DRIFTED')
        else:
            try:
                names=self.private.plans(plans) if self.reader.directory(plans) is not None else []
                for name in names:self.item(plans+'/'+name,lambda name=name:self.plan(plans,name))
            except (g.Refusal,UnavailableEvidence,OSError):self.item(plans+' inventory',lambda:(_ for _ in ()).throw(g.Refusal('held')))
            try:
                superseded=set()
                for name in self.reader.shallow(plans,'.md',hidden=False):
                    if name=='README.md':continue
                    text=self.reader.text(plans+'/'+name)
                    if text is not None:superseded.update(re.findall(r'\*\*Supersedes:\*\*\s*`?([a-z0-9-]+-v[0-9]+\.md)`?',text,re.I|re.ASCII))
                for name in sorted(superseded):
                    state=self.reader.state(plans+'/'+name)
                    if state is not None and state['type']==stat.S_IFREG and ((plans_readme is not None and name in plans_readme and '|' in plans_readme) or (agents is not None and name in agents)):
                        self.item('superseded_plan:'+plans+'/'+name,lambda:'DRIFTED')
            except (g.Refusal,OSError):self.item('superseded_plans',lambda:(_ for _ in ()).throw(g.Refusal('held')))
            for name in self.reader.shallow(adr,'.md'):
                if re.fullmatch(r'[0-9]{4}-.*\.md',name):self.item(adr+'/'+name,lambda name=name:self.adr(adr,name))
        incident='docs/incidents' if plans.startswith('docs/') and adr.startswith('docs/') else '_ops/incidents'
        for directory,trigger,label,exclude in ((adr,'1','adr',False),('docs/runbooks','3','runbook',False),(incident,'4','incident',True)):
            names=self.reader.shallow(directory,'.md')
            if label=='adr':names=[name for name in names if re.fullmatch(r'[0-9]{4}-.*\.md',name)]
            if exclude:names=[name for name in names if name!='README.md']
            if names and trigger not in self.authority.trigger_ids:self.item(label+'_trigger_unknown',lambda:'NEEDS_OPERATOR')
        glossary=self.reader.state('docs/GLOSSARY.md')
        if glossary is not None and glossary['type']==stat.S_IFREG and '7' not in self.authority.trigger_ids:self.item('glossary_trigger_unknown',lambda:'NEEDS_OPERATOR')
        if self.reader.shallow('docs/decisions','.md'):self.item('decisions_directory_unknown',lambda:'NEEDS_OPERATOR')
        return self.summary()

    def summary(self):
        known=[row['classification'] for row in self.items if row['available']]
        available=all(row['available'] for row in self.items)
        worst=max(known,key=LEVELS.index) if known else None
        return {'available':available,'classification':worst if available else 'UNAVAILABLE','worst_known_classification':worst,
                'items':self.items,
                'canonical_check_exit':(0 if worst=='CONFORMANT' else 3 if worst in LEVELS[-2:] else 1) if available else None}

    def observe(self):
        try:return self.collect()
        except (g.Refusal,UnavailableEvidence,OSError,UnicodeError,RecursionError):
            # Keep independently observed operator/contradictory facts visible
            # when a later directory or input cannot be safely classified.
            self.items.append({'path':'remaining_structural_scope','classification':'UNAVAILABLE','available':False})
            return self.summary()


def stable(value):
    return {key:value[key] for key in ('head','branch','config_sha256','worktree_config_sha256','worktree_fence','clean_under_personal_policy')}


def inspect_repository(repo,tool,authority,receipts):
    tree=w.PersonalWorktree(repo,tool);before=tree.observe();applicability=b.eligibility(before)
    value={'id':repo.row['id'],'head':before['head'],'pin_matches':before['pin_matches'],'eligibility':applicability}
    if applicability['classification']!='ELIGIBLE':
        return {**value,'available':True,'classification':'NOT_APPLICABLE','documentation_bodies_read':False,
                'reason':applicability['reason'],'conformance_claimed':False}
    reader=DocReader(tree)
    parent='/private/tmp' if sys.platform=='darwin' else '/tmp'
    with tree.git.private_gitdir(worktree_controls=True),tempfile.TemporaryDirectory(prefix='personal-doc-observation-',dir=parent) as temp:
        private=PrivateGit(tree,reader,Path(temp))
        result=Structural(tree,reader,authority,receipts,private).observe()
        reader.check();tree.git.finish();tree.unchanged();authority.check()
        after=w.PersonalWorktree(repo,tool).observe()
        if stable(before)!=stable(after):raise g.Refusal('documentation-primary-worktree-or-eligibility-changed')
        reader.check();tree.git.finish();authority.check()
        return {**value,**result,'documentation_bodies_read':bool(reader.cache),
                'document_evidence_sha256':reader.digest(),'legacy_state_imported':False,
                'legacy_receipt_observation_supplied':repo.row['id'] in receipts.rows}


def inspect(scope,tool,authority,receipts):
    rows=[];authority.check()
    for target in scope.targets():
        try:
            with scope.repository(target['id']) as repo:row=inspect_repository(repo,tool,authority,receipts)
        except (ValueError,OSError,UnicodeError,UnavailableEvidence,RecursionError):
            row={'id':target['id'],'available':False,'classification':'UNAVAILABLE','conformance_claimed':False}
        rows.append(row)
    authority.check()
    return {'schema':'personal-portability/personal-documentation-structural/v1','owner_ref':OWNER_REF,
            'owner_library_blob':OWNER_LIBRARY_BLOB,'canonical_doctor_blob':DOCTOR_BLOB,'rows':rows,
            'scope':'canonical eligible personal primaries only; no linked-root admission',
            'network_requests':0,'source_or_configuration_writes':False,'new_model_workers':0,'new_shared_links':0,
            'generated_memory_contents_read':False,'legacy_state_imported':False,
            'supplied_receipts_are_not_classification_import_or_human_consent':True,
            'active_v2_documentation_or_full_doctor_or_native_or_migration_acceptance':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['inspect']);parser.add_argument('--repository',action='append')
    parser.add_argument('--receipts-stdin',action='store_true');args=parser.parse_args(argv)
    try:
        selected=s.selected_ids(args.repository);authority=Authority();value=None
        if args.receipts_stdin:
            raw=sys.stdin.buffer.read(MAX_INPUT+1)
            if len(raw)>MAX_INPUT:raise g.Refusal('documentation-receipt-input-bound')
            value=strict_json(raw)
        receipts=LegacyReceipts(value,selected)
        result=inspect(s.PersonalScope(repositories=selected),g.GitTool(),authority,receipts)
        print(json.dumps(result,sort_keys=True))
        if any(not row['available'] for row in result['rows']):return 2
        known=[row.get('canonical_check_exit',0) for row in result['rows']]
        return max(known,default=0)
    except (ValueError,OSError,UnicodeError,TypeError,KeyError,UnavailableEvidence,RecursionError):
        print(json.dumps({'status':'refused','reason':'personal-documentation-authority-scope-or-input-unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())

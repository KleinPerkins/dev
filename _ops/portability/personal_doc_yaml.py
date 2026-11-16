"""Hash-bound pure PyYAML reader for legacy receipt data only."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

HERE=Path(__file__).absolute().parent
SOURCE_SHA256='e3059a7dcf56997bda13ef896dba3d62d8fadd361b673f48f1b71e616474d7c7'
ALIAS='_personal_doc_yaml603'
MAX_YAML_BYTES=1024*1024
MAX_YAML_NODES=50000
MAX_YAML_DEPTH=64

def verified_parser():
    if not sys.dont_write_bytecode:raise ValueError('frozen YAML reader requires a no-bytecode process')
    root=HERE/'_vendor/pyyaml_603'
    for path in (HERE/'_vendor',root,root/'yaml'):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('YAML source directory held')
    source=root/'SOURCE.json';info=source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():raise ValueError('YAML source manifest held')
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256:raise ValueError('YAML source manifest changed')
    metadata=json.loads(raw);expected={row['path']:row for row in metadata['files']}
    if set(p.name for p in root.iterdir())!={'yaml','LICENSE','SOURCE.json'}:raise ValueError('foreign YAML source member held')
    names={str(p.relative_to(root)) for p in (root/'yaml').iterdir()}
    if names!={name for name in expected if name.startswith('yaml/')}:raise ValueError('foreign YAML module or cache held')
    for name,row in expected.items():
        path=root/name;info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                or info.st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']):
            raise ValueError('YAML source member changed')
    allowed={ALIAS:root/'yaml/__init__.py'}
    allowed.update({ALIAS+'.'+Path(name).stem:root/name for name in names if Path(name).name!='__init__.py'})
    for name,module in list(sys.modules.items()):
        if name==ALIAS or name.startswith(ALIAS+'.'):
            if name not in allowed or Path(getattr(module,'__file__','')).absolute()!=allowed[name]:raise ValueError('foreign YAML import held')
    module=sys.modules.get(ALIAS)
    if module is None:
        spec=importlib.util.spec_from_file_location(ALIAS,root/'yaml/__init__.py',submodule_search_locations=[str(root/'yaml')])
        module=importlib.util.module_from_spec(spec);sys.modules[ALIAS]=module
        try:spec.loader.exec_module(module)
        except BaseException:
            for name in list(sys.modules):
                if name==ALIAS or name.startswith(ALIAS+'.'):sys.modules.pop(name,None)
            raise
    if module.__version__!='6.0.3' or module.__with_libyaml__:raise ValueError('unexpected YAML implementation held')
    return module

def safe_receipt_document(raw):
    if not isinstance(raw,bytes) or len(raw)>MAX_YAML_BYTES:raise ValueError('receipt YAML byte bound')
    parser=verified_parser()
    class BoundedSafeLoader(parser.SafeLoader):
        def __init__(self,source):
            self.observed_nodes=0;self.observed_depth=0;super().__init__(source)
        def compose_node(self,parent,index):
            self.observed_nodes+=1;self.observed_depth+=1
            try:
                if self.observed_nodes>MAX_YAML_NODES or self.observed_depth>MAX_YAML_DEPTH:raise ValueError('receipt YAML structure bound')
                return super().compose_node(parent,index)
            finally:self.observed_depth-=1
    loader=BoundedSafeLoader(raw)
    try:return loader.get_single_data()
    except parser.YAMLError as error:raise ValueError('receipt YAML parse unavailable') from error
    finally:loader.dispose()

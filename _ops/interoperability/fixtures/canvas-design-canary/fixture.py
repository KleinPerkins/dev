#!/usr/bin/env python3
"""Bounded saved-artifact inspection; never grants native or retained acceptance."""
from __future__ import annotations
import argparse,hashlib,io,json,os,re,stat,uuid
from pathlib import Path

OUTPUTS=('philosophy.md','artwork.pdf','worker-notes.md')
FONT_DIGESTS={
 'InstrumentSans-Regular.ttf':'a22cb26e48fd79bcb01bf2fc92d36785474dce36d9c544ab0a8868c2657c4a87',
 'InstrumentSans-OFL.txt':'bf4dc6d13a8cccd4807133c77a1ee9619a16b92cb23322258725ab6731c2f6e5',
 'GeistMono-Regular.ttf':'a55c1b51cda4afeab9e471e7947b85a20f7c8831d7e6b1470c1b7fbdc0f0f15e',
 'GeistMono-OFL.txt':'6a873c900f584109b13ae0aaf81d6e3cf0a68751a216b03f7b6c68d547057bb4'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def identity(s):return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def regular(path,limit=65536):
 p=Path(path);before=p.lstat()
 if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_size>limit:
  raise ValueError('private bounded unshared fixture file required')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  opened=os.fstat(fd)
  if identity(before)!=identity(opened):raise ValueError('fixture file identity changed before read')
  data=bytearray()
  while block:=os.read(fd,min(65536,limit+1-len(data))):
   data.extend(block)
   if len(data)>limit:raise ValueError('fixture file exceeded bound')
  if identity(opened)!=identity(os.fstat(fd)) or identity(opened)!=identity(p.lstat()) or len(data)!=opened.st_size:
   raise ValueError('fixture file changed during read')
  return bytes(data)
 finally:os.close(fd)
def unique(pairs):
 result={}
 for k,v in pairs:
  if k in result:raise ValueError('duplicate fixture key')
  result[k]=v
 return result
def directory(path):
 p=Path(path);s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o700:
  raise ValueError('private operator-owned fixture directory required')
 return identity(s)
def root_proof(root,operation_id,action):
 root=Path(root).absolute()
 if str(root)!=os.path.normpath(str(root)) or any(p.is_symlink() for p in (root,*root.parents)):
  raise ValueError('normalized unlinked fixture root required')
 root_id=directory(root)
 if str(uuid.UUID(operation_id))!=operation_id or not re.fullmatch('[0-9a-f]{64}',action):raise ValueError('exact operation binding required')
 marker=json.loads(regular(root/'fixture-owner.json'),object_pairs_hook=unique)
 if marker!={'schema':'interoperability/canvas-design-fixture/v1','operation_id':operation_id,'action_sha256':action}:
  raise ValueError('fixture owner marker changed')
 if set(os.listdir(root))!=set(OUTPUTS)|{'fixture-owner.json','source-notes.json','fonts'}:raise ValueError('fixture output set changed')
 fonts=root/'fonts';font_id=directory(fonts)
 if set(os.listdir(fonts))!=set(FONT_DIGESTS):raise ValueError('font or license inventory changed')
 paths=[root/n for n in (*OUTPUTS,'fixture-owner.json','source-notes.json')]+[fonts/n for n in FONT_DIGESTS]
 states={str(p.relative_to(root)):identity(p.lstat()) for p in paths}
 return root,{'root':root_id,'fonts':font_id,'files':states}
def check_texts(philosophy,notes):
 blocks=[x.strip() for x in re.split(r'\n\s*\n',philosophy.strip()) if x.strip()]
 title=blocks[0].lstrip('#').strip() if blocks else ''
 if not 1<=len(title.split())<=2 or not 5<=len(blocks)<=7 or any(len(p.split())<35 for p in blocks[1:]):
  raise ValueError('movement name and four to six substantial philosophy paragraphs required')
 if not 1<=len(notes.split())<=180 or any(s not in notes for s in ('SKILL.md','Instrument','Geist')):
  raise ValueError('bounded notes must identify actual source and two fonts')
 return ['movement name and complete philosophy paragraph shape','bounded source/font notes']
def inspect_pdf(raw):
 from pypdf.errors import PyPdfError
 try:return _inspect_pdf(raw)
 except (PyPdfError,RecursionError,TypeError,KeyError,OverflowError) as error:
  raise ValueError("bounded PDF parser refused artifact: "+type(error).__name__) from error
def _inspect_pdf(raw):
 from pypdf import PdfReader
 from pypdf.generic import DictionaryObject,ArrayObject,IndirectObject,StreamObject
 reader=PdfReader(io.BytesIO(raw),strict=True)
 if reader.is_encrypted or len(reader.pages)!=1:raise ValueError('one unencrypted static PDF page required')
 page=reader.pages[0]
 if tuple(float(x) for x in page.mediabox)!=(0.,0.,600.,800.) or tuple(float(x) for x in page.cropbox)!=(0.,0.,600.,800.) or page.get('/Rotate',0)!=0:
  raise ValueError('exact unrotated 600x800 page and crop box required')
 denied={'/OpenAction','/AA','/A','/AcroForm','/Annots','/EmbeddedFiles','/JavaScript','/JS','/XFA','/Encrypt','/URI','/EF','/RichMedia','/Launch','/SubmitForm','/GoToR','/Movie','/Sound'}
 seen=set();stack=[reader.trailer];objects=0
 while stack:
  obj=stack.pop()
  if isinstance(obj,IndirectObject):
   key=(obj.idnum,obj.generation)
   if key in seen:continue
   seen.add(key);obj=obj.get_object()
  elif isinstance(obj,(dict,list)):
   key=('direct',id(obj))
   if key in seen:continue
   seen.add(key)
  objects+=1
  if objects>50000:raise ValueError('PDF object graph exceeds bound')
  if isinstance(obj,DictionaryObject):
   if denied.intersection(map(str,obj)) or str(obj.get('/Type','')) in {'/Action','/Filespec','/Annot'}:
    raise ValueError('active, external, attached or interactive PDF feature refused')
   stack.extend(obj.values())
  elif isinstance(obj,ArrayObject):stack.extend(obj)
 used={};parts=[]
 def text(content,cm,tm,font,size):
  if content.strip():
   if font is None:raise ValueError('unresolved text font')
   name=str(font.get('/BaseFont',''));descriptor=font.get('/FontDescriptor')
   if descriptor is None:raise ValueError('used font is not embedded')
   descriptor=descriptor.get_object()
   streams=[descriptor.get(k) for k in ('/FontFile','/FontFile2','/FontFile3') if descriptor.get(k) is not None]
   if len(streams)!=1 or not isinstance(streams[0].get_object(),StreamObject) or not streams[0].get_object().get_data():raise ValueError('used font stream missing')
   family=name.split('+')[-1].lstrip('/')
   if family not in {'InstrumentSans-Regular','GeistMono-Regular'}:raise ValueError('unexpected used font')
   used[family]=True;parts.append(content)
 page.extract_text(visitor_text=text)
 visible=' '.join(parts)
 if set(used)!={'InstrumentSans-Regular','GeistMono-Regular'} or 'SEED EXCHANGE' not in visible or 'Save a seed. Share a season.' not in visible:
  raise ValueError('supplied text and both embedded fonts must be used')
 return {'page_count':1,'page_points':[600,800],'used_embedded_fonts':sorted(used),'static_object_graph_checked':True,'visual_layout_or_native_qualified':False}
def inspect(root,operation_id,action):
 root,before=root_proof(root,operation_id,action)
 fixture=Path(__file__).absolute().parent
 notes=regular(root/'source-notes.json')
 if notes!=(fixture/'source-notes.json').read_bytes():raise ValueError('synthetic source notes changed')
 data={}
 for n in OUTPUTS:data[n]=regular(root/n,2*1024*1024 if n.endswith('.pdf') else 65536)
 for n,digest in FONT_DIGESTS.items():
  if sha(regular(root/'fonts'/n,1024*1024))!=digest:raise ValueError('original font or full license changed')
 checks=check_texts(data['philosophy.md'].decode('utf-8'),data['worker-notes.md'].decode('utf-8'))
 pdf=inspect_pdf(data['artwork.pdf'])
 _,after=root_proof(root,operation_id,action)
 if before!=after:raise ValueError('fixture identity changed during inspection')
 return {'schema':'interoperability/canvas-design-artifact-observation/v1','checks':checks,'PDF':pdf,'output_sha256':{n:sha(v) for n,v in data.items()},'operation_id':operation_id,'action_sha256':action,'semantic_and_render_review_still_required':True,'native_or_retained_acceptance':False}
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--operation-id',required=True);p.add_argument('--action-sha256',required=True);a=p.parse_args(argv)
 try:result=inspect(a.root,a.operation_id,a.action_sha256)
 except (ValueError,OSError,UnicodeError,ImportError) as e:print(json.dumps({'status':'held','reason':str(e)}));return 2
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

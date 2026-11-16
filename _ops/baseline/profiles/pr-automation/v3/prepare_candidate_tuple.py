#!/usr/bin/env python3
"""Prepare an unqualified forward/fallback tuple in a fresh private directory.

This command cannot publish, activate, retain a qualified release, or run a Linux
candidate. Its only subprocess is the explicitly hash-bound native lock compiler.
"""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,json,os,re,subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("candidate_owner_profile",HERE/"profile.py")
assert spec and spec.loader
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
class Refused(ValueError):pass
def closed(v,keys,label):
 if not isinstance(v,dict) or set(v)!=set(keys.split()):raise Refused(label+": closed shape required")
def digest(data):return hashlib.sha256(data).hexdigest()
def json_bytes(value):return (json.dumps(value,indent=2,sort_keys=True)+"\n").encode()
def read_bound(record,label):
 closed(record,"path sha256",label)
 p=Path(record["path"])
 if not p.is_absolute() or p.is_symlink() or not p.is_file():raise Refused(label+": absolute regular file required")
 data=p.read_bytes()
 if digest(data)!=record["sha256"]:raise Refused(label+": digest mismatch")
 return data
def blob(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def sha40(v):return isinstance(v,str) and re.fullmatch(r"[0-9a-f]{40}",v)
def release_digest(v):
 if not isinstance(v,str) or not re.fullmatch(r"sha256:[0-9a-f]{64}",v):raise Refused("invalid candidate release digest")
 return v
def candidate_policy(original,*,controller_digest,generation,assignments,fleet,controller):
 # Validate every original invariant with the unchanged qualified-owner validator.
 P.validate_policy(original,"observed policy",assignments=assignments,fleet=fleet,controller=controller)
 if type(generation) is not int or generation<controller["release"]["activation_generation"]:raise Refused("generation downgrade")
 result=copy.deepcopy(original)
 result["controller_release_digest"]=release_digest(controller_digest)
 result["activation_generation"]=generation
 return result
def validate_linux_provenance(c,evidence):
 joined=evidence["candidates"][c["name"]]
 if joined.get("commit")!=c["commit"] or joined.get("tree")!=c["tree"] or joined.get("source_gate")!="PASS":raise Refused("candidate source/tree/gate mismatch")
 for key in ("source_manifest","source_packet","catalog"):read_bound(joined[key],"joined "+key)
 if joined["catalog"]["sha256"]!=c["catalog_sha256"]:raise Refused("joined catalog mismatch")
 releases=joined.get("build_artifacts",{}).get("release_executables",[])
 if len(releases)!=2 or {x.get("target") for x in releases}!={"pr-automation-controller","lock-compiler"}:raise Refused("complete release build artifact pair required")
 for field,target in (("controller","pr-automation-controller"),("linux_compiler","lock-compiler")):
  item=next(x for x in releases if x["target"]==target)
  read_bound({"path":item["path"],"sha256":item["sha256"]},"joined Linux artifact")
  if item["sha256"]!=c[field]["sha256"]:raise Refused("Linux artifact belongs to another source record")

def validate_request(request):
 closed(request,"schema lifecycle_state activation_generation live_config preimages candidate_evidence candidates profile_change","request")
 if request["schema"]!="pr-automation-private-candidate-request/v1" or request["lifecycle_state"]!="unqualified":raise Refused("unqualified private request required")
 if type(request["activation_generation"]) is not int or not 1<=request["activation_generation"]<2**64:raise Refused("invalid generation")
 closed(request["profile_change"],"repo from_profile to_profile","profile change")
 if request["profile_change"]!={"repo":"KleinPerkins/ecosystem-orchestrator","from_profile":"stdlib-shell.v1","to_profile":"stdlib-shell-gvisor-headroom.v1"}:raise Refused("only the accepted Orchestrator profile correction is supported")
 if not isinstance(request["candidates"],list) or {x.get("name") for x in request["candidates"] if isinstance(x,dict)}!={"forward","fallback"} or len(request["candidates"])!=2:raise Refused("exact forward/fallback pair required")
 if [c["name"] for c in request["candidates"]]!=["forward","fallback"]:raise Refused("forward then fallback order required")
 evidence=json.loads(read_bound(request["candidate_evidence"],"candidate source evidence"))
 if evidence.get("schema")!="f3-final-candidate-source-gate-join/v1" or set(evidence.get("candidates",{}))!={"forward","fallback"}:raise Refused("exact final candidate source record required")
 for c in request["candidates"]:
  closed(c,"name commit tree version controller linux_compiler host_compiler build_evidence catalog_sha256","candidate")
  if not sha40(c["commit"]) or not sha40(c["tree"]) or not isinstance(c["version"],str) or not re.fullmatch(r"v?\d+\.\d+\.\d+",c["version"]):raise Refused("candidate source identity")
  for field in ("controller","linux_compiler","host_compiler","build_evidence"):read_bound(c[field],field)
  validate_linux_provenance(c,evidence)
  for field in ("controller","linux_compiler"):
   b=read_bound(c[field],field)
   if len(b)<20 or b[:5]!=b"\x7fELF\x02" or b[5]!=1 or b[18:20]!=b"\x3e\x00":raise Refused("Linux x86_64 artifact required; never executed here")
  host=read_bound(c["host_compiler"],"host compiler")
  if sys.platform!="darwin" or host[:4] not in (b"\xcf\xfa\xed\xfe",b"\xfe\xed\xfa\xcf"):raise Refused("only the explicitly supported native macOS preparation compiler may execute")
  build=json.loads(read_bound(c["build_evidence"],"build evidence"))
  e=build.get("candidates",{}).get(c["name"],{})
  if not e.get("success") or not e.get("temporary_removed") or e.get("source")!=c["commit"] or e.get("tree")!=c["tree"] or e.get("binary",{}).get("sha256")!=c["host_compiler"]["sha256"] or e.get("source_files",{}).get("catalog/execution-catalog.v1.json")!=c["catalog_sha256"]:raise Refused("host build evidence does not bind candidate source/compiler/catalog")
 return request
def safe_output(out):
 if out!=out.resolve():raise Refused("canonical absolute output path required")
 if not out.is_absolute() or out.exists() or out.is_symlink() or not out.parent.is_dir():raise Refused("fresh absolute private output directory required")
 for ancestor in (out,*out.parents):
  if ancestor.is_symlink() or (ancestor/".git").exists():raise Refused("private output must be outside Git worktrees and symlink ancestry")
 home=Path.home()
 for forbidden in (home/".config",home/".local",Path("/etc"),Path("/usr"),Path("/var/lib")):
  canonical_forbidden=forbidden.resolve()
  if out==canonical_forbidden or canonical_forbidden in out.parents:raise Refused("installed-state output is forbidden")
def prepare(request,out):
 validate_request(request);safe_output(out)
 fleet=P.load_json(HERE/"fleet.json");original=P.load_json(HERE/"coverage-assignments.json");controller=P.load_json(HERE/"controller.json")
 P.validate_json_schema_instance(P.load_json(HERE/"fleet.schema.json"),fleet,source="fleet")
 P.validate_json_schema_instance(P.load_json(HERE/"controller.schema.json"),controller,source="controller")
 P.validate_json_schema_instance(P.load_json(HERE/"coverage-assignments.schema.json"),original,source="assignments")
 if controller["release"]["digest"]!=P.RELEASE_DIGEST or controller["release"]["lock_compiler_digest"]!=P.LOCK_COMPILER_DIGEST:raise Refused("owner source pins disagree")
 generation=request["activation_generation"]
 if generation<controller["release"]["activation_generation"]:raise Refused("generation downgrade")
 live_raw=read_bound(request["live_config"],"observed config")
 current_projection=P.project_live_config(live_raw,original,fleet,controller)
 if current_projection.changed:raise Refused("observed config differs from current owner assignment authority")
 live=json.loads(live_raw)
 if live["controller_release_digest"]!=controller["release"]["digest"]:raise Refused("observed config release differs from owner authority")
 inventory=json.loads(read_bound(request["preimages"],"preimage inventory"))
 if inventory.get("schema")!="f3-fleet-preimages/v1":raise Refused("unsupported preimage inventory")
 rows=inventory.get("files",[])
 by={}
 for r in rows:
  key=(r["repo"],r["path"])
  if key in by:raise Refused("duplicate preimage")
  by[key]=r
 repos={t["repo"]:t for t in fleet["targets"]}
 if set(r["repo"] for r in rows)!=set(repos) or any(r.endswith("/chaos-scheduler") for r in repos):raise Refused("exact eligible fleet required")
 required={".github/pr-recipe.json",".github/pr-automation.lock.json",".github/pr-automation.json",".github/pr-verification.json"}
 if set(by)!={(repo,path) for repo in repos for path in required}:raise Refused("complete four-file preimage per eligible repository required")
 input_bytes={}
 for (repo,path),r in by.items():
  b=read_bound({"path":r["retained_path"],"sha256":r["sha256"]},repo+path)
  if not sha40(r["ref"]) or blob(b)!=r["blob_sha"]:raise Refused("invalid observed Git binding")
  input_bytes[(repo,path)]=b
 for repo,target in repos.items():
  if len({r["ref"] for r in rows if r["repo"]==repo})!=1:raise Refused("mixed repository preimage refs")
  policy=json.loads(input_bytes[(repo,P.POLICY)])
  if policy["repository_id"]!=target["repository_id"] or policy["activation_generation"]!=controller["release"]["activation_generation"]:raise Refused("policy identity/generation mismatch")
  P.validate_policy(policy,repo,assignments=original,fleet=fleet,controller=controller)
  P.validate_manifest(json.loads(input_bytes[(repo,P.MANIFEST)]),repo)
 assignment=copy.deepcopy(original)
 outputs={};records=[];catalogs=set()
 out.mkdir(mode=0o700)
 def write(rel,data):
  p=out/rel;p.parent.mkdir(parents=True,exist_ok=True)
  fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,"wb") as f:f.write(data)
  outputs[rel]={"sha256":digest(data),"size":len(data)}
 try:
  for c in request["candidates"]:
   role=c["name"];host=Path(c["host_compiler"]["path"])
   inspect=P._run_checked([str(host),"inspect","--json"])
   observed=json.loads(inspect.stdout);catalogs.add(observed["catalog_digest"])
   build=json.loads(read_bound(c["build_evidence"],"build evidence"))["candidates"][role]
   if observed!=build["inspection"]:raise Refused("compiler embedded catalog inspection drift")
   candidate_controller=copy.deepcopy(controller)
   candidate_controller["release"].update(version=c["version"],commit=c["commit"],digest="sha256:"+c["controller"]["sha256"],lock_compiler_digest="sha256:"+c["linux_compiler"]["sha256"],activation_generation=generation)
   # Host compiler substitution is scoped to validation data only, not candidate release authority.
   native_context=copy.deepcopy(candidate_controller);native_context["release"]["lock_compiler_digest"]="sha256:"+c["host_compiler"]["sha256"]
   for repo in sorted(repos):
    name=repo.split("/")[1];a=next(x for x in original["assignments"] if x["repo"]==repo)
    selected=request["profile_change"]["to_profile"] if repo==request["profile_change"]["repo"] else a["profile_ref"]["id"]
    if repo==request["profile_change"]["repo"] and a["profile_ref"]["id"]!=request["profile_change"]["from_profile"]:raise Refused("assignment preimage changed")
    ri=by[(repo,P.RECIPE)];recipe=Path(ri["retained_path"])
    lockrel=role+"/repositories/"+name+"/pr-automation.lock.json"
    lockpath=out/lockrel;lockpath.parent.mkdir(parents=True,exist_ok=True)
    argv=[str(host),"compile","--recipe",str(recipe),"--repository-id",name,"--activation-generation",str(generation),"--profile-id",selected,"--recipe-base-sha",ri["ref"],"--recipe-blob-sha",ri["blob_sha"],"--out-lock",str(lockpath)]
    run=P._run_checked(argv)
    lockbytes=lockpath.read_bytes();lockpath.chmod(0o600);lock=json.loads(lockbytes);pd=lock["payload"]["profile_digest"]
    validation=P.validate_artifact_bytes(input_bytes[(repo,P.RECIPE)],lockbytes,host,native_context,repo=repo,profile_id=selected,profile_digest=pd)
    if lock["payload"]["catalog_digest"]!=observed["catalog_digest"]:raise Refused("lock catalog differs from inspected compiler")
    if repo!=request["profile_change"]["repo"] and pd!=a["profile_ref"]["digest"]:raise Refused("unapproved profile object change")
    if repo==request["profile_change"]["repo"]:
     proposed=P.propose_assignment(original,fleet,controller,repo=repo,coverage_mode=a["coverage_mode"],profile_id=selected,profile_digest=pd,artifacts_validated=True)
     if role=="forward":assignment=proposed
     elif assignment!=proposed:raise Refused("pair assignment mismatch")
    outputs[lockrel]={"sha256":digest(lockbytes),"size":len(lockbytes)}
    policy=candidate_policy(json.loads(input_bytes[(repo,P.POLICY)]),controller_digest=candidate_controller["release"]["digest"],generation=generation,assignments=original,fleet=fleet,controller=controller)
    write(role+"/repositories/"+name+"/pr-automation.json",json_bytes(policy))
    records.append({"candidate":role,"repo":repo,"recipe_ref":ri["ref"],"recipe_blob_sha":ri["blob_sha"],"profile_id":selected,"profile_digest":pd,"lock_digest":lock["lock_digest"],"validation":validation,"compiler_argv":argv})
   projected=P.project_live_config(live_raw,assignment,fleet,controller)
   config=json.loads(projected.candidate);config["controller_release_digest"]=candidate_controller["release"]["digest"];config["activation_generation"]=generation
   write(role+"/config.json",json_bytes(config))
   write(role+"/controller.json",json_bytes(candidate_controller))
   write(role+"/release-inputs.json",json_bytes({"schema":"pr-automation-unqualified-release-inputs/v1","lifecycle_state":"unqualified","candidate":c,"catalog_digest":observed["catalog_digest"],"linux_executed":False}))
  if len(catalogs)!=1:raise Refused("candidate catalog mismatch")
  for repo in repos:
   name=repo.split("/")[1]
   if outputs["forward/repositories/"+name+"/pr-automation.lock.json"]!=outputs["fallback/repositories/"+name+"/pr-automation.lock.json"]:raise Refused("pair lock bytes differ")
  write("coverage-assignments.json",json_bytes(assignment))
  # Recheck all bound inputs before marking the private preparation complete.
  for r in rows:read_bound({"path":r["retained_path"],"sha256":r["sha256"]},"preimage")
  read_bound(request["live_config"],"config")
  validate_request(request)
  result={"schema":"pr-automation-private-candidate-tuple/v1","lifecycle_state":"unqualified","phase":"private-preparation","applied":False,"qualified":False,"runtime_executed":False,"activation_generation":generation,"catalog_digest":next(iter(catalogs)),"request_sha256":digest(json_bytes(request)),"owner_source_digests":{n:digest((HERE/n).read_bytes()) for n in ("profile.py","fleet.json","controller.json","coverage-assignments.json","prepare_candidate_tuple.py")},"records":records,"outputs":outputs.copy(),"restoration":{"from":"forward","to":"fallback","same_assignment":"coverage-assignments.json","mapping":[{"forward":key,"fallback":"fallback/"+key[len("forward/"):],"forward_sha256":value["sha256"],"fallback_sha256":outputs["fallback/"+key[len("forward/"):]]["sha256"]} for key,value in outputs.items() if key.startswith("forward/")],"journal":"advance only; journal is never an output or restoration asset"},"not_proven":["source delivery","Linux compiler consumption","candidate runtime validity and qualification","timed restoration rehearsal","active owner publication"],"owner_delivery":"private source proposal until owner review and normal merge"}
  write("PREPARATION.json",json_bytes(result))
  return result
 except BaseException as exc:
  # Preserve partial private output for diagnosis; never emit a completion manifest.
  (out/"FAILED.json").write_bytes(json_bytes({"schema":"pr-automation-private-preparation-failure/v1","lifecycle_state":"unqualified","error":type(exc).__name__,"completion":False}))
  raise
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--input",type=Path,required=True);parser.add_argument("--out",type=Path,required=True);a=parser.parse_args()
 result=prepare(json.loads(a.input.read_text()),a.out)
 print(json.dumps({"lifecycle_state":result["lifecycle_state"],"locks":len(result["records"]),"outputs":len(result["outputs"]),"applied":False,"qualified":False}))
if __name__=="__main__":main()

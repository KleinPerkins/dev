"""Safety and authority checks for private unqualified tuple preparation."""
import copy,hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parent
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
T=module('candidate_tuple_test',HERE/'prepare_candidate_tuple.py')
F=module('existing_profile_test_fixtures',HERE/'test_profile.py')
class PrivateTupleTest(unittest.TestCase):
 def policy(self):
  c=F.controller();a=F.assignment();f=F.fleet()
  return F.repository_policy('KleinPerkins/awa',policy_digest=T.P.RELEASE_DIGEST,policy_generation=3),a,f,c
 def test_candidate_policy_changes_only_release_and_generation(self):
  p,a,f,c=self.policy();before=copy.deepcopy(p)
  new=T.candidate_policy(p,controller_digest='sha256:'+'a'*64,generation=4,assignments=a,fleet=f,controller=c)
  self.assertEqual(p,before)
  self.assertEqual({k for k in p if p[k]!=new[k]},{'controller_release_digest','activation_generation'})
  with self.assertRaises(SystemExit):T.P.validate_policy(new,'candidate must remain unqualified',assignments=a,fleet=f,controller=c)
 def test_invalid_policy_still_refused(self):
  for field,value in [('verifier_app_id',1),('protected_paths',[]),('max_changed_files',999),('unexpected','x')]:
   p,a,f,c=self.policy();p[field]=value
   with self.assertRaises(SystemExit):T.candidate_policy(p,controller_digest='sha256:'+'a'*64,generation=3,assignments=a,fleet=f,controller=c)
 def test_generation_downgrade_refused(self):
  p,a,f,c=self.policy()
  with self.assertRaises(T.Refused):T.candidate_policy(p,controller_digest='sha256:'+'a'*64,generation=2,assignments=a,fleet=f,controller=c)
 def test_invalid_candidate_digest_refused(self):
  p,a,f,c=self.policy()
  with self.assertRaises(T.Refused):T.candidate_policy(p,controller_digest='qualified',generation=3,assignments=a,fleet=f,controller=c)
 def test_bound_bytes_reject_stale_and_symlink(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'input';p.write_bytes(b'fixture');r={'path':str(p),'sha256':hashlib.sha256(b'fixture').hexdigest()}
   self.assertEqual(T.read_bound(r,'fixture'),b'fixture')
   p.write_bytes(b'changed')
   with self.assertRaises(T.Refused):T.read_bound(r,'fixture')
   link=Path(temp)/'link';link.symlink_to(p)
   with self.assertRaises(T.Refused):T.read_bound({'path':str(link),'sha256':hashlib.sha256(b'changed').hexdigest()},'link')
 def test_output_cannot_overwrite_or_use_git_worktree(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();out=root/'fresh';T.safe_output(out)
   out.mkdir()
   with self.assertRaises(T.Refused):T.safe_output(out)
   (root/'.git').mkdir()
   with self.assertRaises(T.Refused):T.safe_output(root/'other')
 def test_installed_output_rejected(self):
  with self.assertRaises(T.Refused):T.safe_output(Path('/etc/new-private-tuple'))
 def test_closed_request_rejected_before_subprocess(self):
  with mock.patch.object(T.P,'_run_checked',side_effect=AssertionError('subprocess not permitted')):
   for bad in ({},{'schema':'pr-automation-qualified-release/v1'}, {'schema':'pr-automation-private-candidate-request/v1','lifecycle_state':'qualified'}):
    with self.assertRaises(T.Refused):T.validate_request(bad)
class ProvenanceAndConfinementTest(unittest.TestCase):
 def bound_fixture(self):
  c={'name':'forward','commit':'a'*40,'tree':'b'*40,'catalog_sha256':'c'*64,'controller':{'sha256':'d'*64},'linux_compiler':{'sha256':'e'*64}}
  ref={'path':'/synthetic/source','sha256':'f'*64}
  e={'candidates':{'forward':{'commit':c['commit'],'tree':c['tree'],'source_gate':'PASS','source_manifest':ref,'source_packet':ref,'catalog':{'path':'/synthetic/catalog','sha256':c['catalog_sha256']},'build_artifacts':{'release_executables':[{'target':'pr-automation-controller','path':'/synthetic/controller','sha256':'d'*64},{'target':'lock-compiler','path':'/synthetic/compiler','sha256':'e'*64}]}}}}
  return c,e
 def test_linux_source_provenance_accepts_bound_pair(self):
  c,e=self.bound_fixture()
  with mock.patch.object(T,'read_bound',return_value=b'synthetic'):T.validate_linux_provenance(c,e)
 def test_linux_target_swap_refused(self):
  c,e=self.bound_fixture();c['controller'],c['linux_compiler']=c['linux_compiler'],c['controller']
  with mock.patch.object(T,'read_bound',return_value=b'synthetic'):
   with self.assertRaises(T.Refused):T.validate_linux_provenance(c,e)
 def test_stale_source_and_missing_gate_refused(self):
  for field,value in [('commit','0'*40),('tree','0'*40),('source_gate','PENDING')]:
   c,e=self.bound_fixture();e['candidates']['forward'][field]=value
   with mock.patch.object(T,'read_bound',return_value=b'synthetic'):
    with self.assertRaises(T.Refused):T.validate_linux_provenance(c,e)
 def test_single_target_digest_mismatch_refused(self):
  c,e=self.bound_fixture();c['linux_compiler']['sha256']='0'*64
  with mock.patch.object(T,'read_bound',return_value=b'synthetic'):
   with self.assertRaises(T.Refused):T.validate_linux_provenance(c,e)
 def test_noncanonical_private_output_refused(self):
  for forbidden in (Path.home()/'.config',Path.home()/'.local',Path('/etc'),Path('/usr'),Path('/var/lib')):
   path=forbidden.parent/'traversal'/ '..'/forbidden.name/'not-created'
   with self.assertRaises(T.Refused):T.safe_output(path)
class CanonicalForbiddenRootTest(unittest.TestCase):
 def test_canonical_alias_of_each_excluded_root_refused(self):
  for forbidden in (Path.home()/'.config',Path.home()/'.local',Path('/etc'),Path('/usr'),Path('/var/lib')):
   with self.assertRaises(T.Refused):T.safe_output(forbidden.resolve()/'f3-test-never-created')
 def test_mocked_macos_system_aliases_refused(self):
  original_resolve=Path.resolve
  def resolved(path,*args,**kwargs):
   if path==Path('/etc'):return Path('/private/etc')
   if path==Path('/var/lib'):return Path('/private/var/lib')
   return path
  with mock.patch.object(Path,'resolve',resolved),mock.patch.object(Path,'is_dir',return_value=True),mock.patch.object(Path,'exists',return_value=False),mock.patch.object(Path,'is_symlink',return_value=False):
   for path in (Path('/private/etc/f3-test-never-created'),Path('/private/var/lib/f3-test-never-created')):
    with self.assertRaises(T.Refused):T.safe_output(path)
if __name__=='__main__':unittest.main()

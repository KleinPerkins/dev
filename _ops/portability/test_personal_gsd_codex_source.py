"""Offline source-boundary regressions; no download, installer or native worker."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import personal_gsd_codex_source as m


def archive(entries):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as output:
        for name,kind,size in entries:
            item = tarfile.TarInfo(name);item.type=kind;item.size=size
            if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):item.linkname='outside'
            output.addfile(item,io.BytesIO(b'x'*size) if kind==tarfile.REGTYPE else None)
    raw.seek(0)
    return tarfile.open(fileobj=raw,mode='r:')


def conversion():
    contract = copy.deepcopy(m.load_contract())
    rows = []
    for skill in m.SKILLS:
        body = 'synthetic conversion for '+skill
        contract['descriptors'][skill]['converted_sha256']=m.digest(body.encode())
        rows.append({'id':skill,'command_sha256':contract['descriptors'][skill]['command_sha256'],
                     'converted_sha256':m.digest(body.encode()),'body':body})
    result = {'descriptors':rows,'loaded_modules':['gsd-core/bin/lib/example.cjs'],
        'imported_builtins':['crypto','fs','os','path'],'denied_operation_imports':['child_process'],
        'HOME':os.environ.get('HOME'),'CODEX_HOME':os.environ.get('CODEX_HOME'),
        'installer_invoked':False,'node_version':'24.22.2',
        'guard_probes':dict.fromkeys(('outside_read_denied','writes_denied','child_calls_denied','network_import_denied'),True)}
    return result,contract


class SourceContractTests(unittest.TestCase):
    def test_duplicate_keys_refuse_at_every_object_level(self):
        for raw in (b'{"schema":"one","schema":"two"}',b'{"nested":{"x":1,"x":2}}'):
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'duplicate_json_key'):
                m.strict_json(raw)

    def test_floating_nonfinite_and_non_utf8_json_refuse(self):
        for raw in (b'{"x":1.0}',b'{"x":1e2}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":"\xff"}'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,UnicodeError)):
                m.strict_json(raw)

    def test_exact_source_contract_and_owner_pin(self):
        value=m.load_contract()
        self.assertEqual(value['scope'],'raw_codex_text_only_not_native_installation')
        self.assertEqual(set(value['descriptors']),set(m.SKILLS))
        self.assertEqual(value['npm_integrity'],m.INTEGRITY)

    def mutate_contract(self,change):
        value=m.load_contract();change(value);read=m.regular_bytes
        def changed(path,limit):
            return json.dumps(value).encode() if path.name==m.CONTRACT_NAME else read(path,limit)
        with patch.object(m,'regular_bytes',side_effect=changed),self.assertRaises(ValueError):m.load_contract()

    def test_unknown_contract_field_refuses(self):
        self.mutate_contract(lambda d:d.update(native_authorized=True))

    def test_wrong_pin_refuses(self):
        self.mutate_contract(lambda d:d.update(git_commit='0'*40))

    def test_excluded_skill_refuses(self):
        self.mutate_contract(lambda d:d['descriptors'].update({'gsd-ship':{}}))

    def test_wrong_descriptor_shape_refuses(self):
        self.mutate_contract(lambda d:d['descriptors'].update({'gsd-new-project':[]}))

    def test_wrong_descriptor_digest_refuses(self):
        self.mutate_contract(lambda d:d['descriptors']['gsd-plan-phase'].update(converted_sha256='not-a-digest'))

    def test_harness_drift_refuses(self):
        self.mutate_contract(lambda d:d.update(harness_sha256='0'*64))

    def test_owner_interface_drift_refuses(self):
        self.mutate_contract(lambda d:d.update(owner_interface_sha256='0'*64))

    def test_package_change_refuses_before_archive_interpretation(self):
        with self.assertRaisesRegex(ValueError,'gsd_package_integrity'):
            m.verified_package(b'not a package',m.load_contract())

    def test_compressed_limit_precedes_hashing(self):
        with patch.object(m,'MAX_COMPRESSED',2),self.assertRaisesRegex(ValueError,'compressed_limit'):
            m.verified_package(b'abc',m.load_contract())

    def test_regular_read_preserves_content_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'reference';path.write_bytes(b'preserve');before=path.stat()
            self.assertEqual(m.regular_bytes(path,32),b'preserve');after=path.stat()
            self.assertEqual((before.st_ino,before.st_mode,before.st_mtime_ns,before.st_ctime_ns),
                             (after.st_ino,after.st_mode,after.st_mtime_ns,after.st_ctime_ns))

    def test_symlink_and_shared_files_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'reference';path.write_bytes(b'x');link=root/'alias';link.symlink_to(path)
            with self.assertRaises(OSError):m.regular_bytes(link,32)
            os.link(path,root/'shared')
            with self.assertRaisesRegex(ValueError,'unavailable'):m.regular_bytes(path,32)

    def test_oversized_regular_file_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'reference';path.write_bytes(b'xx')
            with self.assertRaisesRegex(ValueError,'unavailable'):m.regular_bytes(path,1)

    def test_clean_environment_preserves_actual_roots_and_removes_execution_options(self):
        # Synthetic positive identity pair: CI may give its process a HOME that
        # differs from the container account database. Never replace HOME itself.
        with patch.dict(os.environ,{'NODE_OPTIONS':'--require attacker','HTTPS_PROXY':'secret'}), \
                patch.object(m.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=os.environ['HOME'])):
            env=m.child_environment()
            self.assertEqual(env['HOME'],os.environ['HOME'])
            self.assertEqual(env.get('CODEX_HOME'),os.environ.get('CODEX_HOME'))
            self.assertNotIn('NODE_OPTIONS',env);self.assertNotIn('HTTPS_PROXY',env)

    def test_repurposed_home_refuses(self):
        with patch.object(m.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/different-identity')),self.assertRaisesRegex(ValueError,'real_home'):
            m.child_environment()

    def test_bounded_runner_keeps_default_data_argument_and_environment(self):
        runner=m.bounded_runner()
        with patch.object(m.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=os.environ['HOME'])):
            code,out,err=runner([sys.executable,'-I','-B','-c','import os;print(os.environ["HOME"])'],m.HERE)
        self.assertEqual((code,err),(0,b''));self.assertEqual(out.decode().strip(),os.environ['HOME'])


class ArchiveBoundaryTests(unittest.TestCase):
    def check(self,entries,count=None):
        with archive(entries) as value:return m.validated_members(value,len(entries) if count is None else count)

    def test_regular_package_members_allowed(self):
        self.assertEqual(len(self.check([('package/commands/a.md',tarfile.REGTYPE,1)])),1)

    def test_paths_outside_closed_package_refuse(self):
        for name in ('/package/a','package/../outside','package/./a','package//a','other/a','package/a\\b','package'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'member_invalid'):
                self.check([(name,tarfile.REGTYPE,1)])

    def test_links_directories_and_special_members_refuse(self):
        for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE,tarfile.CHRTYPE,tarfile.DIRTYPE):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'member_invalid'):
                self.check([('package/reference',kind,0)])

    def test_duplicate_and_ancestor_collision_refuse(self):
        for names in (('package/a','package/a'),('package/a','package/a/b')):
            with self.subTest(names=names),self.assertRaises(ValueError):
                self.check([(n,tarfile.REGTYPE,1) for n in names])

    def test_entry_and_expanded_limits_refuse(self):
        entries=[('package/a',tarfile.REGTYPE,2)]
        with self.assertRaisesRegex(ValueError,'entry_count'):self.check(entries,2)
        with patch.object(m,'MAX_EXPANDED',1),self.assertRaisesRegex(ValueError,'expanded_limit'):self.check(entries)
        with patch.object(m,'MAX_MEMBER',1),self.assertRaisesRegex(ValueError,'member_invalid'):self.check(entries)


class ConversionBoundaryTests(unittest.TestCase):
    def test_saved_projection_omits_environment_values_and_source_bodies(self):
        result,contract=conversion();result['descriptors'][0]['body']='SYNTHETIC_SOURCE_BODY_NEVER_PERSIST'
        # Distinctive values exercise data omission without assuming the ambient
        # HOME is a distinctive substring (a sandbox may legitimately use '/').
        result['HOME']='SYNTHETIC_HOME_VALUE_NEVER_PERSIST'
        result['CODEX_HOME']='SYNTHETIC_CODEX_HOME_VALUE_NEVER_PERSIST'
        projection=m.conversion_projection(result)
        encoded=json.dumps(projection)
        self.assertNotIn('SYNTHETIC_SOURCE_BODY_NEVER_PERSIST',encoded)
        self.assertNotIn('HOME',projection);self.assertNotIn('CODEX_HOME',projection)
        self.assertNotIn(result['HOME'],encoded);self.assertNotIn(result['CODEX_HOME'],encoded)
        self.assertTrue(projection['HOME_preserved']);self.assertTrue(projection['CODEX_HOME_preserved'])
        self.assertEqual(set(projection['descriptors'][0]),{'id','command_sha256','converted_sha256'})
        self.assertEqual(result['descriptors'][0]['body'],'SYNTHETIC_SOURCE_BODY_NEVER_PERSIST')

    def test_root_home_value_is_omitted_without_banning_module_path_separators(self):
        result,contract=conversion();result['HOME']='/'
        projection=m.conversion_projection(result)
        self.assertNotIn('HOME',projection);self.assertNotIn('CODEX_HOME',projection)
        self.assertEqual(projection['loaded_modules'],['gsd-core/bin/lib/example.cjs'])
        self.assertTrue(projection['HOME_preserved'])

    def test_synthetic_validation_has_no_publication_authority(self):
        result,contract=conversion();m.validate_conversion(result,contract)
        self.assertFalse(result['installer_invoked'])

    def test_changed_descriptor_bytes_refuse_even_matching_claimed_hash(self):
        result,contract=conversion();result['descriptors'][0]['body']+='changed'
        with self.assertRaisesRegex(ValueError,'descriptor_changed'):m.validate_conversion(result,contract)

    def test_duplicate_or_extra_skills_refuse(self):
        for kind in ('duplicate','extra','invalid'):
            result,contract=conversion()
            if kind=='duplicate':result['descriptors'][1]=result['descriptors'][0]
            elif kind=='extra':result['descriptors'].append({'id':'gsd-execute-phase'})
            else:result['descriptors'][0]=None
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'skill_set_changed'):m.validate_conversion(result,contract)

    def test_failed_or_integer_guard_is_not_true(self):
        for value in (False,1,'true'):
            result,contract=conversion();result['guard_probes']['writes_denied']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'guards_unproven'):m.validate_conversion(result,contract)

    def test_changed_home_or_more_builtins_refuse(self):
        for field,value in (('HOME','/changed'),('CODEX_HOME','/changed'),('imported_builtins',['fs','https'])):
            result,contract=conversion();result[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate_conversion(result,contract)

    def test_installer_claim_unknown_authority_or_old_node_refuse(self):
        for field,value in (('installer_invoked',True),('native_authorized',True),('node_version','22.0.0'),('node_version',None)):
            result,contract=conversion();result[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate_conversion(result,contract)


if __name__=='__main__':
    unittest.main()

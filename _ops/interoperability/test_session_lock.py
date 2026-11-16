"""LCK-01: real processes and disposable repositories; no installed hooks changed."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HOOK = Path(os.environ.get('SESSION_LOCK_UNDER_TEST', Path(__file__).parents[1] / 'hooks/session-lock')).resolve()


class WriterIsolation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='int011-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.lock = self.repo / '.git/cursor-session.lock'
        self.children = []
        self.addCleanup(self.stop_children)

    def stop_children(self):
        for process in self.children:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)

    def start(self, session='one', command='check', repo=None, extra=None):
        env = dict(os.environ, DEV_SESSION_TOOL='fixture')
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'DEV_SESSION_ID', 'DEV_SESSION_LOCK'):
            env.pop(key, None)
        if session is not None:
            env['DEV_SESSION_ID'] = session
        env.update(extra or {})
        process = subprocess.Popen(['bash', str(HOOK), command], cwd=repo or self.repo,
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        self.children.append(process)
        return process

    def call(self, session='one', command='check', **kwargs):
        process = self.start(session, command, **kwargs)
        out, err = process.communicate(timeout=15)
        return process.returncode, out, err

    def seed(self, token='env:another', pid=None, timestamp=None):
        self.lock.write_text(f'token={token}\npid={pid or os.getpid()}\ntty=?\nts={timestamp or int(time.time())}\nhost=fixture\ntool=fixture\n')

    def test_distinct_explicit_ids_do_not_inherit_ancestor_ownership(self):
        # A live parent is shared by both child checks, reproducing the old bypass.
        self.seed(token='env:one')
        before = self.lock.read_bytes()
        code, _, err = self.call('two')
        self.assertEqual(code, 1, err)
        self.assertIn('BLOCKED', err)
        self.assertEqual(self.lock.read_bytes(), before)
        self.assertEqual(self.call('one')[0], 0)

    def test_acquire_and_release_cannot_silently_steal(self):
        self.seed()
        before = self.lock.read_bytes()
        for command in ('acquire', 'release'):
            self.assertEqual(self.call('other', command)[0], 1)
            self.assertEqual(self.lock.read_bytes(), before)

    def test_absent_identity_retains_documented_ancestor_fallback(self):
        self.seed(token='pid:legacy')
        self.assertEqual(self.call(None)[0], 0)

    def test_dead_pid_and_expired_ttl_recover(self):
        self.seed(pid=2147483647)
        self.assertEqual(self.call('new')[0], 0)
        self.assertIn('token=env:new', self.lock.read_text())
        self.seed(timestamp=int(time.time()) - 40000)
        self.assertEqual(self.call('new')[0], 0)

    def test_concurrent_acquisition_has_exactly_one_owner(self):
        processes = [self.start(f'writer-{i}') for i in range(12)]
        codes = []
        for process in processes:
            process.communicate(timeout=20)
            codes.append(process.returncode)
        self.assertEqual(codes.count(0), 1, codes)
        self.assertEqual(codes.count(1), 11, codes)
        text = self.lock.read_text()
        self.assertEqual(len(text.splitlines()), 6)
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o600)

    def test_separate_linked_trees_have_independent_locks(self):
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
        second = self.root / 'linked'
        subprocess.run(['git', '-C', str(self.repo), 'worktree', 'add', '-q', '--detach', str(second)], check=True)
        self.assertEqual(self.call('one')[0], 0)
        self.assertEqual(self.call('two', repo=second)[0], 0)

    def test_mutex_wait_is_bounded_and_does_not_claim_ownership(self):
        guard_path = Path(str(self.lock) + '.guard')
        with guard_path.open('w') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            started = time.monotonic()
            code, _, err = self.call('one')
        self.assertEqual(code, 0)
        self.assertIn('ownership unverified (fail-open)', err)
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(self.lock.exists())

    def test_interpreter_failure_is_visible_and_fail_open(self):
        interpreter = self.root / 'broken-python'
        interpreter.write_text('#!/bin/sh\nexit 42\n'); interpreter.chmod(0o755)
        fixture_hook = self.root / 'hook'
        # Fault injection in a disposable exact source copy; live source and
        # inherited shell policy stay intact.
        fixture_hook.write_text(HOOK.read_text().replace('python3 - "$CMD"', '"' + str(interpreter) + '" - "$CMD"'))
        with mock.patch(__name__ + '.HOOK', fixture_hook):
            code, _, err = self.call('one')
        self.assertEqual(code, 0)
        self.assertIn('runtime failure; ownership unverified (fail-open)', err)
        self.assertFalse(self.lock.exists())

    def test_status_is_read_only(self):
        self.assertEqual(self.call('one', 'status')[0], 0)
        self.assertFalse(self.lock.exists())
        self.assertFalse(Path(str(self.lock) + '.guard').exists())

    def test_interrupted_replace_preserves_previous_complete_record(self):
        self.seed(token='env:one')
        before = self.lock.read_bytes()
        sentinel = self.root / 'ready'
        # Execute the exact embedded transaction code in a real process, injecting
        # a pause at replacement without adding any production test switch.
        source = HOOK.read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        injection = ('import os,time\nfrom pathlib import Path\n' +
                     'def pause_replace(*args):\n    Path(' + repr(str(sentinel)) + ').touch()\n    time.sleep(30)\n' +
                     'os.replace=pause_replace\n')
        process = subprocess.Popen([sys.executable, '-c', injection + source, 'check',
                                    str(self.lock.parent), 'env:one', str(os.getpid()), '?', str(os.getpid())],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        self.children.append(process)
        deadline = time.monotonic() + 10
        while not sentinel.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not sentinel.exists():
            out, err = process.communicate(timeout=5)
            self.fail(f'writer did not reach replacement boundary: {process.returncode}: {out} {err}')
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(self.lock.read_bytes(), before)
        self.assertEqual(list(self.lock.parent.glob('.session-lock-*')), [])
        self.assertEqual(self.call('one')[0], 0, 'kernel must release mutex after interruption')


if __name__ == '__main__':
    unittest.main()

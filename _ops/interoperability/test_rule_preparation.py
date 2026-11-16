import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('renderer', Path(__file__).with_name('render_rules.py'))
renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)


class SourcePreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='int007a-source-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.dev, self.skills, self.awa = [root / name for name in ('dev', 'skills', 'awa')]
        def write(root, name, body):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(body)
        write(self.dev, '_ops/rules/agent-context.md', '# Shared policy\n- Preserve dirty work.\n- For Codex, inspect native attachments and create/attach the appropriate worktree; verify the returned root, branch, Git directories and writer before mutation. A printed helper path is not native attachment or AWA protection. Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks). Preserve owner exclusions and separate indexes.\n')
        for name in ('terse-output', 'worktree-default'):
            write(self.dev, f'_ops/rules/global/{name}.mdc', f'---\nalwaysApply: true\n---\n{name} original owner instruction\n')
        for name in renderer.SERVICES:
            write(self.dev, f'_ops/rules/global/{name}-mcp-safety.mdc', f'---\ndescription: only for {name}\nalwaysApply: false\n---\n{name} schema and payload approval required\n')
        write(self.skills, 'global/rules/subagent-orchestration/subagent-orchestration.mdc', '---\nalwaysApply: true\n---\nOriginal Cursor resolver\n')
        write(self.awa, 'consumer/operator-skill.md', 'Exact Close remains required.\n')

    def render(self, host):
        return renderer.prepare(self.dev, self.skills, self.awa, host)

    def test_no_installed_host_dependency_and_deterministic(self):
        for host in ('cursor', 'codex', 'claude'):
            self.assertEqual(self.render(host), self.render(host))
            self.assertEqual(self.render(host)['activation'], 'withheld-INT-007B')
        self.assertFalse((Path(self.temp.name) / '.cursor').exists())

    def test_conditional_policy_and_owner_bytes_preserved(self):
        for host in ('cursor', 'codex', 'claude'):
            blocks = self.render(host)['blocks']
            for name in renderer.SERVICES:
                self.assertIn(f'**Apply only when:** only for {name}', blocks[renderer.MARKERS[2]])
                self.assertIn(f'{name} schema and payload approval required', blocks[renderer.MARKERS[2]])
            self.assertIn('Exact Close remains required.', blocks[renderer.MARKERS[1]])
            self.assertEqual(blocks[renderer.MARKERS[1]].count('### awa-operator'), 1)

    def test_cursor_claude_keep_source_routing_codex_withholds_it(self):
        for host in ('cursor', 'claude'):
            blocks = self.render(host)['blocks']
            self.assertIn('Original Cursor resolver', blocks[renderer.MARKERS[1]])
            self.assertIn('worktree-default original owner instruction', blocks[renderer.MARKERS[1]])
        codex = self.render('codex')
        text = ''.join(codex['blocks'].values())
        self.assertNotIn('Original Cursor resolver', text)
        self.assertNotIn('Cursor **Agents Window**', text)
        self.assertIn('Preserve dirty work.', text)
        self.assertIn('Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks).', text)
        self.assertEqual(len(codex['pending']), 2)

    def test_pure_preview_preserves_unmanaged_bytes_and_is_idempotent(self):
        original = 'User text  \n\n'
        blocks = self.render('cursor')['blocks']
        projected = renderer.project(original, blocks)
        self.assertTrue(projected.startswith(original))
        self.assertEqual(renderer.project(projected, blocks), projected)
        for name in renderer.MARKERS:
            self.assertEqual(projected.count(f'<!-- BEGIN {name} '), 1)

    def test_entry_preimage_drift_duplicate_missing_and_legacy_refuse(self):
        path = self.dev / '_ops/rules/agent-context.md'
        original = path.read_text()
        entry = next(line for line in original.splitlines() if line.startswith('- For Codex, '))
        cases = {
            'unknown-entry': original.replace('inspect native attachments', 'trust a printed helper'),
            'missing-entry': original.replace(entry + '\n', ''),
            'duplicate-entry': original + entry + '\n',
            'conflicting-entry': original + '- For Codex, use an unknown entry.\n',
            'missing-exclusions': original.replace(' Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks).', ''),
            'drifted-exclusions': original.replace('`affirm/vendor/*`', '`affirm/src/*`'),
            'legacy-entry': original.replace(entry, '- Start governed repo mutation from the Cursor **Agents Window**. Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks).'),
            'mixed-legacy-entry': original + '- Start governed repo mutation from the Cursor **Agents Window**.\n',
        }
        for label, text in cases.items():
            path.write_text(text)
            for native in (False, True):
                with self.subTest(case=label, native=native):
                    with self.assertRaisesRegex(ValueError, 'host entry source preimage changed'):
                        renderer.prepare(self.dev, self.skills, self.awa, 'codex', native_codex=native)
        path.write_text(original)

    def test_other_hosts_preserve_context_without_codex_slot_rewriting(self):
        path = self.dev / '_ops/rules/agent-context.md'
        for context in (path.read_text(), '# A different owner host policy.\n'):
            path.write_text(context)
            for host in ('cursor', 'claude'):
                with self.subTest(host=host, context=context):
                    result = self.render(host)
                    self.assertIn(context, result['blocks'][renderer.MARKERS[0]])
                    self.assertIn('Original Cursor resolver', result['blocks'][renderer.MARKERS[1]])
                    self.assertIn('worktree-default original owner instruction', result['blocks'][renderer.MARKERS[1]])
                    self.assertEqual(result['pending'], [])
                    with self.assertRaisesRegex(ValueError, 'Codex-only'):
                        renderer.prepare(self.dev, self.skills, self.awa, host, native_codex=True)

    def test_ambiguous_projection_or_changed_entry_refuses(self):
        blocks = self.render('cursor')['blocks']
        with self.assertRaises(ValueError):
            renderer.project(blocks[renderer.MARKERS[0]] * 2, blocks)
        outer, inner = renderer.MARKERS[:2]
        nested = blocks[outer].replace(f'<!-- END {outer} -->', blocks[inner] + f'<!-- END {outer} -->')
        with self.assertRaises(ValueError):
            renderer.project(nested, blocks)
        reversed_markers = f'<!-- END {outer} -->\n<!-- BEGIN {outer} (managed by KleinPerkins/dev) -->'
        with self.assertRaises(ValueError):
            renderer.project(reversed_markers, blocks)
        (self.dev / '_ops/rules/agent-context.md').write_text('changed entry policy\n')
        with self.assertRaises(ValueError):
            self.render('codex')


if __name__ == '__main__':
    unittest.main()

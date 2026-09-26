"""Installer regression tests. Every external command and home directory is fake."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install


def completed(value):
    return subprocess.CompletedProcess([], 0, json.dumps(value), '')


class InstallerReadinessTests(unittest.TestCase):
    def test_menu_install_reinstall_uninstall_preserves_unrelated_content(self):
        original = '{\r\n  // Keep my shortcuts\r\n  "notes": {"label":"Notes", "action":"open https://example.org/a,b"},\r\n}\r\n'
        executable = Path('/home/test user/.local/bin/gardener')
        installed = install.menu_text(original, executable)
        self.assertEqual(install.jsonc(installed)['notes'], install.jsonc(original)['notes'])
        self.assertEqual(install.menu_text(installed, executable), installed)
        self.assertEqual(install.menu_text(installed, executable, uninstall=True), original)

    def test_menu_collision_refuses_to_replace_existing_user_entries(self):
        for original in ('{"gardener": {"label":"My garden"}}',
                         '{"personal": {"aliases":["gardener"]}}'):
            with self.assertRaisesRegex(ValueError, 'conflicts with Gardener'):
                install.menu_text(original, Path('/tmp/gardener'))

    def test_waits_for_delayed_discovery(self):
        responses = [completed([]), completed([{'id': 'other'}]),
                     completed([{'id': install.PLUGIN_ID}])]
        with patch.object(install.subprocess, 'run', side_effect=responses) as run, \
                patch.object(install.time, 'sleep'):
            install.wait_registered()
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], ('omarchy', 'plugin', 'list', '--json'))
            self.assertTrue(call.kwargs['capture_output'])
            self.assertTrue(call.kwargs['check'])
            self.assertGreater(call.kwargs['timeout'], 0)
            self.assertLessEqual(call.kwargs['timeout'], 3)

    def test_waits_for_service_to_load_and_clear_error(self):
        responses = [subprocess.CalledProcessError(1, ['omarchy-shell']),
                     subprocess.CompletedProcess([], 0, 'service loading', ''),
                     completed({'ready': False}),
                     completed({'ready': True, 'error': 'initializing'}),
                     completed({'ready': True, 'error': ''})]
        with patch.object(install.subprocess, 'run', side_effect=responses) as run, \
                patch.object(install.time, 'sleep'):
            install.wait_ready()
        self.assertEqual(run.call_count, 5)
        self.assertEqual(run.call_args.args[0], ('omarchy-shell', 'gardener', 'status'))

    def test_wait_has_total_deadline_including_command_timeout(self):
        clock = [0.0]

        def timeout_command(*args, **kwargs):
            clock[0] += kwargs['timeout']
            raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

        with patch.object(install.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(install.time, 'sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)), \
                patch.object(install.subprocess, 'run', side_effect=timeout_command) as run:
            with self.assertRaisesRegex(ValueError, 'Timed out waiting for test service'):
                install.wait_for_json(('fake',), lambda value: False, 'test service', timeout=1)
        self.assertEqual(clock[0], 1)
        self.assertEqual(run.call_count, 1)

    def test_mutating_commands_also_have_timeout(self):
        with patch.object(install.subprocess, 'run') as run:
            install.run('omarchy', 'plugin', 'enable', install.PLUGIN_ID)
        self.assertEqual(run.call_args.kwargs['timeout'], 15)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_installer_announces_success_only_after_discovery_and_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            repo.mkdir()
            for name in ('manifest.json', 'Service.qml', 'Model.js', 'gardener.py'):
                (repo / name).write_text('fixture')
            (repo / 'gardener.py').chmod(0o755)
            home = root / 'home'
            home.mkdir()
            events = []
            discoveries = iter([[], [{'id': install.PLUGIN_ID}]])
            statuses = iter([{'ready': False}, {'ready': True}])
            output = io.StringIO()

            def fake_run(command, **kwargs):
                events.append(command)
                self.assertNotIn('Gardener installed.', output.getvalue())
                if command == ('omarchy', 'plugin', 'list', '--json'):
                    return completed(next(discoveries))
                if command == ('omarchy-shell', 'gardener', 'status'):
                    return completed(next(statuses))
                return completed('ok')

            with patch.object(install, '__file__', str(repo / 'install.py')), \
                    patch.object(install.Path, 'home', return_value=home), \
                    patch.dict(os.environ, {'XDG_CONFIG_HOME': '', 'XDG_DATA_HOME': ''}), \
                    patch.object(install.shutil, 'which', return_value='/fake/omarchy'), \
                    patch.object(install.subprocess, 'run', side_effect=fake_run), \
                    patch.object(install.time, 'sleep'), contextlib.redirect_stdout(output):
                self.assertEqual(install.main([]), 0)
            self.assertEqual(events, [
                ('omarchy-shell', 'shell', 'rescanPlugins'),
                ('omarchy', 'plugin', 'list', '--json'),
                ('omarchy', 'plugin', 'list', '--json'),
                ('omarchy', 'plugin', 'enable', install.PLUGIN_ID),
                ('omarchy-shell', 'gardener', 'status'),
                ('omarchy-shell', 'gardener', 'status'),
            ])
            self.assertIn('Gardener installed.', output.getvalue())


if __name__ == '__main__':
    unittest.main()

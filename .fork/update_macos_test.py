import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

import update_macos as updater


class UpdaterTests(unittest.TestCase):
    def test_release_requires_complete_fork_assets_and_selects_newest(self):
        def release(version, assets=True):
            names = [f'T3-Code-{version}-arm64.dmg', 'SHA256SUMS', 'fork-build.json']
            return {'tag_name': 'fork-v' + version, 'draft': False,
                    'assets': [{'name': name} for name in names] if assets else []}
        old = release('0.0.41-nightly.20260912.100003')
        newer = release('0.0.41-nightly.20260913.100004')
        incomplete = release('0.0.41-nightly.20260914.100005', False)
        self.assertEqual(updater.select_release([old, incomplete, newer]), newer)
        self.assertIsNone(updater.select_release([incomplete, {'tag_name': 'v9.9.9'}]))

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = pathlib.Path(directory) / 'app.dmg'
            file.write_bytes(b'actual')
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                updater.verify_digest(file, hashlib.sha256(b'expected').hexdigest())

    def test_busy_uses_active_sessions_and_recent_requests_not_stale_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            db = pathlib.Path(directory) / 'state.sqlite'
            with sqlite3.connect(db) as connection:
                connection.executescript('''
                    CREATE TABLE projection_thread_sessions (status TEXT, active_turn_id TEXT);
                    CREATE TABLE projection_turns (state TEXT, turn_id TEXT, requested_at TEXT);
                    INSERT INTO projection_thread_sessions VALUES ('ready', NULL);
                    INSERT INTO projection_turns VALUES ('pending', NULL, '2000-01-01T00:00:00Z');
                ''')
            self.assertFalse(updater.is_busy(db))
            with sqlite3.connect(db) as connection:
                connection.execute("UPDATE projection_thread_sessions SET status = 'running'")
            self.assertTrue(updater.is_busy(db))
            with sqlite3.connect(db) as connection:
                connection.execute("UPDATE projection_thread_sessions SET status = 'ready'")
                connection.execute("UPDATE projection_turns SET requested_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
            self.assertTrue(updater.is_busy(db))
            with self.assertRaises(sqlite3.OperationalError):
                updater.is_busy(pathlib.Path(directory) / 'missing.sqlite')

    def test_failed_start_restores_previous_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            app, candidate, backup = [root / name for name in ['app', 'candidate', 'backup']]
            for path, value in [(app, 'old'), (candidate, 'new')]:
                path.mkdir()
                (path / 'version').write_text(value)
            def launch(path, expected):
                if expected == 'new':
                    raise RuntimeError('new backend failed')
                self.assertEqual((path / 'version').read_text(), 'old')
            with mock.patch.object(updater, 'launch_and_verify', side_effect=launch), \
                 mock.patch.object(updater, 'quit_app'):
                with self.assertRaisesRegex(RuntimeError, 'new backend failed'):
                    updater.replace_app(app, candidate, backup, 'new', 'old', True)
            self.assertEqual((app / 'version').read_text(), 'old')
            self.assertEqual((candidate / 'version').read_text(), 'new')

    def test_busy_install_does_not_quit_or_replace(self):
        with mock.patch.object(updater, 'app_pids', return_value=[123]), \
             mock.patch.object(updater, 'is_busy', return_value=True), \
             mock.patch.object(updater, 'quit_app') as quit_app, \
             mock.patch.object(updater, 'replace_app') as replace:
            self.assertFalse(updater.wait_until_quiet(pathlib.Path('/app'), pathlib.Path('/data')))
            quit_app.assert_not_called()
            replace.assert_not_called()

    def test_repeated_quiet_check_catches_new_turn(self):
        with mock.patch.object(updater, 'app_pids', return_value=[123]), \
             mock.patch.object(updater, 'is_busy', side_effect=[False, True]), \
             mock.patch.object(updater.time, 'sleep'):
            self.assertFalse(updater.wait_until_quiet(pathlib.Path('/app'), pathlib.Path('/data')))

    def test_current_release_does_not_prepare_or_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            (state / 'config.json').write_text(json.dumps({'app': '/app'}))
            (state / 'installed.json').write_text(json.dumps({'fingerprint': ['known']}))
            version = '0.0.41-nightly.20260912.100003'
            with mock.patch.object(updater, 'fingerprint', return_value=['known']), \
                 mock.patch.object(updater, 'version_of', return_value=version), \
                 mock.patch.object(updater, 'latest_release', return_value={'tag_name': 'fork-v' + version}), \
                 mock.patch.object(updater, 'prepare_candidate') as prepare, \
                 mock.patch.object(updater, 'quit_app') as quit_app:
                updater.run_update(state)
                prepare.assert_not_called()
                quit_app.assert_not_called()
            self.assertEqual(json.loads((state / 'status.json').read_text())['status'], 'current')

    def test_external_app_replacement_pauses_updater(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            (state / 'config.json').write_text(json.dumps({'app': '/app'}))
            (state / 'installed.json').write_text(json.dumps({'fingerprint': ['fork']}))
            with mock.patch.object(updater, 'fingerprint', return_value=['official']), \
                 mock.patch.object(updater, 'latest_release') as latest:
                updater.run_update(state)
                latest.assert_not_called()
            self.assertEqual(json.loads((state / 'status.json').read_text())['status'], 'paused')


if __name__ == '__main__':
    unittest.main()

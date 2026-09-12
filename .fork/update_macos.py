#!/usr/bin/env python3
"""Install verified personal fork Nightlies when the desktop is idle (macOS/Python 3.9)."""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import plistlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

from smoke import verify_app

REPOSITORY = 'Jefferson-Butler1/t3code'
VERSION = re.compile(r'^fork-v(\d+\.\d+\.\d+-nightly\.\d{8}\.\d+)$')
DEFAULT_STATE = pathlib.Path.home() / 'Library/Application Support/T3 Fork Updater'
APP_NAME = 'T3 Code (Nightly).app'
LABEL = 'com.jeff.t3-fork-updater'


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def report(state, status, **details):
    value = dict(status=status, time=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **details)
    write_json(state / 'status.json', value)
    print(json.dumps(value), flush=True)


def version_of(app):
    return plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def fingerprint(app):
    return [digest(app / name) for name in ['Contents/Info.plist', 'Contents/Resources/app.asar']]


def verify_digest(path, expected):
    if digest(path) != expected:
        raise RuntimeError('Download checksum mismatch: ' + path.name)


def version_key(version):
    return tuple(int(part) for part in re.findall(r'\d+', version))


def select_release(releases):
    complete = []
    for release in releases:
        match = VERSION.fullmatch(release['tag_name'])
        if not match or release.get('draft'):
            continue
        required = {f'T3-Code-{match[1]}-arm64.dmg', 'SHA256SUMS', 'fork-build.json'}
        if required.issubset({asset['name'] for asset in release['assets']}):
            complete.append(release)
    return max(complete, key=lambda r: version_key(r['tag_name']), default=None)


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'Jeff-T3-Fork-Updater', 'Accept': 'application/vnd.github+json',
    }), timeout=60)


def latest_release():
    with request(f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=30') as response:
        release = select_release(json.load(response))
    if release is None:
        raise RuntimeError('No complete fork Nightly release is available')
    return release


def download(asset, destination):
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/'
    if not asset['browser_download_url'].startswith(expected_url):
        raise RuntimeError('Unexpected release download origin')
    with request(asset['browser_download_url']) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)
    if destination.stat().st_size != asset['size']:
        raise RuntimeError('Incomplete download: ' + destination.name)
    if asset.get('digest', '').startswith('sha256:'):
        verify_digest(destination, asset['digest'].split(':', 1)[1])


def prepare_candidate(release, app, state):
    version = VERSION.fullmatch(release['tag_name'])[1]
    candidate = app.parent / ('.t3-fork-staged-' + version + '.app')
    receipt = state / 'candidate.json'
    previous = read_json(receipt, {})
    if (previous.get('version') == version and candidate.exists()
            and previous.get('fingerprint') == fingerprint(candidate)):
        return candidate
    with tempfile.TemporaryDirectory(prefix='download-', dir=state) as directory:
        temp = pathlib.Path(directory)
        names = [f'T3-Code-{version}-arm64.dmg', 'SHA256SUMS', 'fork-build.json']
        assets = {asset['name']: asset for asset in release['assets']}
        for name in names:
            download(assets[name], temp / name)
        sums = dict((name.lstrip('*'), sha) for sha, name in
                    (line.split(maxsplit=1) for line in (temp / 'SHA256SUMS').read_text().splitlines()))
        for name in [names[0], 'fork-build.json']:
            verify_digest(temp / name, sums[name])
        manifest = read_json(temp / 'fork-build.json')
        if manifest['version'] != version:
            raise RuntimeError('Release manifest version mismatch')
        mount = temp / 'mounted'
        mount.mkdir()
        subprocess.run(['/usr/bin/hdiutil', 'attach', str(temp / names[0]), '-readonly',
                        '-nobrowse', '-mountpoint', str(mount), '-quiet'], check=True)
        try:
            if candidate.exists():
                shutil.rmtree(candidate)
            subprocess.run(['/usr/bin/ditto', str(mount / APP_NAME), str(candidate)], check=True)
        finally:
            subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount), '-quiet'], check=True)
        verify_app(candidate, version, temp)
        write_json(receipt, dict(version=version, fingerprint=fingerprint(candidate), manifest=manifest))
    return candidate


def app_pids(app, action='status'):
    result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript',
                             str(pathlib.Path(__file__).with_name('app_lifecycle.js')),
                             action, str(app)], check=True, capture_output=True, text=True, timeout=20)
    return json.loads(result.stdout)


def is_busy(database):
    # Never open the live T3 database for writes. A missing/changed schema defers installation.
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2) as connection:
        connection.execute('PRAGMA query_only=ON')
        return bool(connection.execute('''
            SELECT EXISTS(SELECT 1 FROM projection_thread_sessions
                WHERE status IN ('starting', 'running') OR active_turn_id IS NOT NULL)
            OR EXISTS(SELECT 1 FROM projection_turns
                WHERE state = 'pending' AND turn_id IS NULL
                  AND julianday(requested_at) > julianday('now', '-2 minutes'))
        ''').fetchone()[0])


def wait_until_quiet(app, data):
    for attempt in range(3):
        if app_pids(app) and is_busy(data / 'state.sqlite'):
            return False
        if attempt < 2:
            time.sleep(5)
    return True


def quit_app(app):
    app_pids(app, 'quit')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        # Also wait for the desktop-managed backend and native helpers to stop.
        processes = subprocess.check_output(['/bin/ps', '-axo', 'command='], text=True)
        if not app_pids(app) and not any(line.startswith(str(app) + '/Contents/')
                                       for line in processes.splitlines()):
            return
        time.sleep(1)
    raise RuntimeError('T3 did not quit normally; application was not replaced')


def launch_and_verify(app, version):
    runtime_path = pathlib.Path.home() / '.t3/userdata/server-runtime.json'
    previous = read_json(runtime_path, {})
    subprocess.run(['/usr/bin/open', '-g', '-a', str(app)], check=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            runtime = read_json(runtime_path, {})
            if runtime.get('pid') and (runtime.get('pid'), runtime.get('startedAt')) != (
                    previous.get('pid'), previous.get('startedAt')) and app_pids(app):
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{int(runtime['port'])}/.well-known/t3/environment", timeout=2) as response:
                    if json.load(response)['serverVersion'] == version:
                        return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(1)
    raise RuntimeError('Restarted T3 backend did not become ready at version ' + version)


def replace_app(app, candidate, backup, version, old_version, launch):
    app.rename(backup)
    try:
        candidate.rename(app)
        if launch:
            launch_and_verify(app, version)
    except Exception:
        if app.exists():
            quit_app(app)
            app.rename(candidate)
        backup.rename(app)
        if launch:
            launch_and_verify(app, old_version)
        raise


def run_update(state, stage_only=False):
    config = read_json(state / 'config.json')
    app = pathlib.Path(config['app'])
    installed = read_json(state / 'installed.json')
    if fingerprint(app) != installed['fingerprint']:
        report(state, 'paused', reason='Installed app changed outside this updater; re-enroll explicitly')
        return
    release = latest_release()
    version = VERSION.fullmatch(release['tag_name'])[1]
    current = version_of(app)
    if version_key(version) <= version_key(current):
        report(state, 'current', version=current)
        return
    if read_json(state / 'failed.json', {}).get('version') == version:
        report(state, 'paused', reason='This release failed activation; waiting for a newer release', version=version)
        return
    report(state, 'preparing', version=version, installed_version=current)
    candidate = prepare_candidate(release, app, state)
    if stage_only:
        report(state, 'staged', version=version, installed_version=current)
        return
    if not wait_until_quiet(app, pathlib.Path(config['data'])):
        report(state, 'waiting-for-idle', version=version, installed_version=current)
        return
    if fingerprint(app) != installed['fingerprint']:
        raise RuntimeError('Installed app changed while preparing the update')
    was_running = bool(app_pids(app))
    if was_running:
        quit_app(app)
    backup = app.parent / ('.t3-fork-backup-' + current + '-' + str(time.time_ns()) + '.app')
    launch = was_running or config.get('launch_after_first_install', False)
    report(state, 'installing', version=version, backup=str(backup))
    try:
        replace_app(app, candidate, backup, version, current, launch)
    except Exception:
        write_json(state / 'failed.json', dict(version=version))
        raise
    previous_backup = installed.get('backup')
    write_json(state / 'installed.json', dict(version=version, fingerprint=fingerprint(app),
                                             backup=str(backup), manifest=read_json(state / 'candidate.json')['manifest']))
    config['launch_after_first_install'] = False
    write_json(state / 'config.json', config)
    if previous_backup:
        previous_path = pathlib.Path(previous_backup)
        if previous_path.parent == app.parent and previous_path.name.startswith('.t3-fork-backup-'):
            shutil.rmtree(previous_path, ignore_errors=True)
    report(state, 'installed', version=version, backend_verified=launch, backup=str(backup))


def install_agent(source, state, app):
    state.mkdir(parents=True, exist_ok=True)
    for name in ['update_macos.py', 'app_lifecycle.js', 'smoke.py']:
        target = state / name
        if (source / name).resolve() != target.resolve():
            shutil.copy2(source / name, target)
    if not (state / 'config.json').exists():
        write_json(state / 'config.json', dict(app=str(app), data=str(pathlib.Path.home() / '.t3/userdata'),
                                               launch_after_first_install=True))
        write_json(state / 'installed.json', dict(version=version_of(app), fingerprint=fingerprint(app)))
    plist = pathlib.Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(state / 'update_macos.py'), '--state', str(state)],
        'RunAtLoad': True, 'StartInterval': 900, 'ProcessType': 'Background',
        'StandardOutPath': str(state / 'updater.log'), 'StandardErrorPath': str(state / 'updater-error.log'),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
    }))
    print('Installed updater and LaunchAgent:', plist)
    print('Load with: launchctl bootstrap gui/' + str(os.getuid()) + ' ' + str(plist))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument('--install-agent', action='store_true')
    parser.add_argument('--app', type=pathlib.Path, default=pathlib.Path('/Applications') / APP_NAME)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if args.install_agent:
        install_agent(pathlib.Path(__file__).parent, args.state, args.app)
        return
    args.state.mkdir(parents=True, exist_ok=True)
    with (args.state / 'updater.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            run_update(args.state, args.stage_only)
        except Exception as error:
            report(args.state, 'error', error=str(error))
            raise


if __name__ == '__main__':
    main()

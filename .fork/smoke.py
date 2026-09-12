#!/usr/bin/env python3
"""Verify the downloadable DMG without opening a window or using installed T3 data."""
import argparse
import os
import pathlib
import plistlib
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def verify_app(app, version, temp):
    resources = app / 'Contents/Resources'
    assert not (resources / 'app-update.yml').exists(), 'An implicit native update feed was bundled'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleShortVersionString'] == version
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('T3CODE_', 'CODEX_', 'OPENAI_', 'VITE_', 'OTEL_'))}
    env.update(T3CODE_HOME=str(temp / 'data'), ELECTRON_RUN_AS_NODE='1', T3CODE_NO_BROWSER='true')
    log = temp / 'startup.log'
    with log.open('w') as output:
        process = subprocess.Popen([
            str(app / 'Contents/MacOS/T3 Code (Nightly)'),
            str(resources / 'app.asar/apps/server/dist/bin.mjs'),
            '--base-dir', str(temp / 'data'), '--host', '127.0.0.1', '--port', str(port), '--no-browser',
        ], env=env, cwd=temp, stdout=output, stderr=output)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Packaged server exited ({process.returncode}): {log.read_text()[-3000:]}')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1) as response:
                        assert response.status == 200 and b'<html' in response.read().lower()
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(.25)
            else:
                raise TimeoutError(f'Packaged server did not start: {log.read_text()[-3000:]}')
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=pathlib.Path)
    parser.add_argument('version')
    args = parser.parse_args()
    dmgs = list(args.release.resolve().glob('*-arm64.dmg'))
    assert len(dmgs) == 1, f'Expected one Apple Silicon DMG; found {dmgs}'
    with tempfile.TemporaryDirectory(prefix='t3-fork-smoke-') as directory:
        temp = pathlib.Path(directory)
        mount = temp / 'mounted'
        mount.mkdir()
        subprocess.run(['hdiutil', 'attach', str(dmgs[0]), '-readonly', '-nobrowse',
                        '-mountpoint', str(mount), '-quiet'], check=True)
        try:
            apps = list(mount.glob('T3 Code (Nightly).app'))
            assert len(apps) == 1, f'Expected one app in the DMG; found {apps}'
            verify_app(apps[0], args.version, temp)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount), '-quiet'], check=True)
    print('Verified DMG version, absent native updater feed, and isolated server/UI startup.')


if __name__ == '__main__':
    main()

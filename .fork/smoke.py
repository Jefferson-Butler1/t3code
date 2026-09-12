#!/usr/bin/env python3
"""Verify the built app without opening a window or touching an installed T3 home."""
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('release', type=pathlib.Path)
parser.add_argument('version')
args = parser.parse_args()
apps = list(args.release.resolve().glob('mac*/T3 Code (Nightly).app'))
assert len(apps) == 1, f'Expected one packaged app; found {apps}'
app = apps[0]
resources = app / 'Contents/Resources'
assert not (resources / 'app-update.yml').exists(), 'An implicit native update feed was bundled'
info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
assert info['CFBundleShortVersionString'] == args.version
with tempfile.TemporaryDirectory(prefix='t3-fork-smoke-') as temp:
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('T3CODE_', 'CODEX_', 'OPENAI_', 'VITE_', 'OTEL_'))}
    env.update(T3CODE_HOME=temp, ELECTRON_RUN_AS_NODE='1', T3CODE_NO_BROWSER='true')
    log = pathlib.Path(temp) / 'startup.log'
    with log.open('w') as output:
        process = subprocess.Popen([
            str(app / 'Contents/MacOS/T3 Code (Nightly)'),
            str(resources / 'app.asar/apps/server/dist/bin.mjs'),
            '--base-dir', temp, '--host', '127.0.0.1', '--port', str(port), '--no-browser',
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
print('Verified packaged version, absent native updater feed, and isolated server/UI startup.')

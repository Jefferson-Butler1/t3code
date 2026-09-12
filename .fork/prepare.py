#!/usr/bin/env python3
"""Assemble a disposable nightly checkout; never update a published branch here."""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess

CONTROL = pathlib.Path(__file__).resolve().parent.parent
UPSTREAM = 'pingdotgg/t3code'
BRANCH = 'patched-nightly'
NIGHTLY = re.compile(r'^v(\d+\.\d+\.\d+)-nightly\.\d{8}\.\d+$')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def apply_patches(repo, patches):
    applied = []
    for patch in patches:
        reverse = subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', '--check', str(patch)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if reverse.returncode == 0:
            applied.append({'patch': patch.name, 'status': 'already-upstream'})
            continue
        try:
            git(repo, '-c', 'core.hooksPath=/dev/null', 'am', '--3way', str(patch))
        except subprocess.CalledProcessError:
            git(repo, 'am', '--abort')
            raise
        applied.append({'patch': patch.name, 'status': 'applied'})
    return applied


def release_is_complete(repo, version):
    result = subprocess.run(['gh', 'api', f'repos/{repo}/releases/tags/fork-v{version}'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return False
    release = json.loads(result.stdout)
    assets = {asset['name'] for asset in release['assets']}
    return (not release['draft'] and 'SHA256SUMS' in assets and 'fork-build.json' in assets
            and any(name.endswith('-arm64.dmg') for name in assets))


def outputs(values):
    text = ''.join(f'{key}={value}\n' for key, value in values.items())
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a') as output:
            output.write(text)
    print(text, end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=pathlib.Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--run-number', type=int, required=True)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.source.exists():
        parser.error('--source must be a new, disposable path')
    if args.run_number < 1:
        parser.error('--run-number must be positive')
    releases = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{UPSTREAM}/releases?per_page=100'], text=True))
    nightly = max((r for r in releases if not r['draft'] and r['prerelease'] and NIGHTLY.fullmatch(r['tag_name'])),
                  key=lambda r: r['published_at'])
    tag = nightly['tag_name']
    git(CONTROL, 'fetch', '--no-tags', f'https://github.com/{UPSTREAM}.git', f'refs/tags/{tag}')
    upstream_commit = git(CONTROL, 'rev-parse', 'FETCH_HEAD^{commit}')
    control_commit = git(CONTROL, 'rev-parse', 'HEAD')
    remote = git(CONTROL, 'ls-remote', 'origin', f'refs/heads/{BRANCH}')
    previous_commit = remote.split()[0] if remote else ''
    if previous_commit:
        git(CONTROL, 'fetch', '--no-tags', 'origin', f'refs/heads/{BRANCH}')
        previous = json.loads(git(CONTROL, 'show', f'{previous_commit}:.fork-build.json'))
        if (not args.force and previous['upstream_commit'] == upstream_commit
                and previous['control_commit'] == control_commit
                and release_is_complete(args.repository, previous['version'])):
            outputs({'changed': 'false'})
            return
    source = args.source.resolve()
    git(CONTROL, 'worktree', 'add', '--detach', str(source), upstream_commit)
    patch_names = [line.strip() for line in (CONTROL / '.fork/series').read_text().splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
    patches = []
    for name in patch_names:
        if pathlib.Path(name).name != name or not name.endswith('.patch'):
            raise ValueError(f'Invalid patch name in series: {name}')
        patches.append(CONTROL / '.fork/patches' / name)
    applied = apply_patches(source, patches)
    date = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')
    version = f'{NIGHTLY.fullmatch(tag).group(1)}-nightly.{date}.{100000 + args.run_number}'
    manifest = {'upstream_tag': tag, 'upstream_commit': upstream_commit,
                'control_commit': control_commit, 'version': version, 'patches': applied}
    (source / '.fork-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    git(source, 'add', '.fork-build.json')
    git(source, '-c', 'core.hooksPath=/dev/null', 'commit', '-m', f'chore(fork): record nightly build {version}')
    outputs({'changed': 'true', 'version': version, 'source_commit': git(source, 'rev-parse', 'HEAD'),
             'previous_commit': previous_commit, 'upstream_tag': tag})


if __name__ == '__main__':
    main()

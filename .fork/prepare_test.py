import pathlib
import subprocess
import tempfile
import unittest

from prepare import apply_patches, preserve_workflows


class PatchReplayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = pathlib.Path(self.temp.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fork test')
        self.git('config', 'user.email', 'fork-test@example.invalid')
        (self.repo / 'file.txt').write_text('original\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'upstream base')
        self.base = self.git('rev-parse', 'HEAD')
        (self.repo / 'file.txt').write_text('patched\n')
        self.git('commit', '-qam', 'local fix')
        self.patch = pathlib.Path(self.temp.name) / 'fix.patch'
        self.patch.write_text(self.git('format-patch', '-1', '--stdout') + '\n')
        self.git('reset', '--hard', self.base)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def test_replays_onto_new_upstream_without_merge_commit(self):
        (self.repo / 'new-upstream.txt').write_text('new upstream work\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'new upstream')
        upstream = self.git('rev-parse', 'HEAD')
        self.assertEqual(apply_patches(self.repo, [self.patch]), [{'patch': 'fix.patch', 'status': 'applied'}])
        self.assertEqual((self.repo / 'file.txt').read_text(), 'patched\n')
        self.assertEqual(self.git('rev-parse', 'HEAD^'), upstream)
        self.assertEqual(len(self.git('rev-list', '--parents', '-n', '1', 'HEAD').split()), 2)

    def test_conflict_aborts_without_changing_the_published_branch(self):
        self.git('branch', 'patched-nightly')
        published = self.git('rev-parse', 'patched-nightly')
        (self.repo / 'file.txt').write_text('incompatible upstream rewrite\n')
        self.git('commit', '-qam', 'conflicting upstream')
        upstream = self.git('rev-parse', 'HEAD')
        with self.assertRaises(subprocess.CalledProcessError):
            apply_patches(self.repo, [self.patch])
        self.assertEqual(self.git('rev-parse', 'HEAD'), upstream)
        self.assertEqual(self.git('rev-parse', 'patched-nightly'), published)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_exact_upstreamed_patch_is_detected_without_duplicate_commit(self):
        self.git('am', str(self.patch))
        upstream = self.git('rev-parse', 'HEAD')
        self.assertEqual(apply_patches(self.repo, [self.patch]), [{'patch': 'fix.patch', 'status': 'already-upstream'}])
        self.assertEqual(self.git('rev-parse', 'HEAD'), upstream)

    def test_publication_keeps_existing_workflows_while_updating_application_source(self):
        workflows = self.repo / '.github/workflows'
        workflows.mkdir(parents=True)
        (workflows / 'release.yml').write_text('existing release workflow\n')
        (workflows / 'retained.yml').write_text('retained workflow\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'previously published workflows')
        published = self.git('rev-parse', 'HEAD')
        (workflows / 'release.yml').write_text('changed upstream release workflow\n')
        (workflows / 'retained.yml').unlink()
        (workflows / 'new.yml').write_text('new upstream workflow\n')
        (self.repo / 'file.txt').write_text('updated upstream application\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'latest upstream')
        preserve_workflows(self.repo, published)
        self.assertEqual(self.git('diff', '--cached', published, '--', '.github/workflows'), '')
        self.assertEqual((self.repo / 'file.txt').read_text(), 'updated upstream application\n')
        self.assertFalse((workflows / 'new.yml').exists())

    def test_preserving_unchanged_workflows_does_not_stage_changes(self):
        workflows = self.repo / '.github/workflows'
        workflows.mkdir(parents=True)
        (workflows / 'release.yml').write_text('existing release workflow\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'published workflows')
        preserve_workflows(self.repo, 'HEAD')
        self.assertEqual(self.git('status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()

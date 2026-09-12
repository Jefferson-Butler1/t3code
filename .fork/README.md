# Jeff's maintained T3 fork

This fork checks the latest **published upstream Nightly** at **09:17 UTC daily**. When upstream or the patch series changes, it applies the patches, runs the focused server tests, typecheck and lint, and builds an Apple Silicon macOS DMG. A failed patch or build leaves the previous release available.

- **[Downloads](https://github.com/Jefferson-Butler1/t3code/releases):** successful patched Nightlies, checksums and source provenance.
- **[Workflow](https://github.com/Jefferson-Butler1/t3code/actions/workflows/fork-nightly.yml):** daily runs; **Run workflow** also supports a forced rebuild.
- **`fork-maintenance` (default):** this automation and the small patch series. Edit this branch.
- **`patched-nightly`:** generated application source, replayed onto the latest published upstream tag. Do not edit it directly; successful builds replace it using an explicit force-with-lease. Its `.fork-build.json` records the upstream tag, source commit, maintenance commit and patch disposition.

The upstream `main` branch is retained separately. Upstream's own release, deployment and notification workflows are disabled in this fork.

## Patch lifecycle

`series` lists patches in application order. Each file under `patches/` is an ordinary `git format-patch` mailbox. To change a patch, generate a replacement from a clean upstream checkout and update this branch. The daily job uses `git am --3way`; conflicts stop the build. If a patch applies exactly in reverse, it is already present upstream and is skipped without making a duplicate commit. Equivalent upstream implementations still need human review.

The current patch fixes Codex's paginated-history revert and restores current files when provider rollback fails. Tracking: [issue #8958](https://github.com/pingdotgg/t3code/issues/8958), [recovery PR #9069](https://github.com/pingdotgg/t3code/pull/9069), and [newer orchestration PR #9169](https://github.com/pingdotgg/t3code/pull/9169).

The separate `explicit-update-feed.patch` sets the build publisher to `null` unless explicitly configured. This prevents electron-builder from inferring an upstream update feed for an unsigned fork. It is independent of the Codex fix.

When upstream covers the behavior, remove `codex-paginated-revert.patch` from `series` and delete the patch file. Run the workflow; it will publish upstream behavior with only the fork distribution configuration. To leave the fork entirely, install an official T3 Nightly. Fork installation/removal does not require deleting T3 data.

## macOS installation and signing

The downloadable build targets Apple Silicon Macs. It is unsigned, matching upstream's macOS preview build process. Download the DMG from this fork's release, verify it against `SHA256SUMS`, quit T3 normally, and replace the application. Keep the previous app if you want a local rollback.

These builds are published daily but are **not installed automatically**. Native macOS automatic updates require a Developer ID signing identity; the unsigned fork does not configure a native update feed. No Apple certificate, notarization secret, private relay key or npm token is needed to build it. Public T3 Connect configuration comes from upstream `.env.example`.

Unsigned builds may require macOS permission approval, and native passkey support requires proper signing and associated-domain entitlements. Use the official build when those capabilities are required. Adding signed distribution later should use this fork's update repository, never upstream's feed.

Each machine has its own installed app and backend. A client connected to a remote environment executes server code there; installing only the local client does not patch the remote backend. The GitHub DMG replaces a desktop-managed backend with its app. Upstream's separate headless `t3` service updates through npm and is not covered by these desktop releases.

## Maintainer checks

```sh
python3 -m unittest discover -s .fork -p '*_test.py'
```

The workflow tests patch replay, exact upstream detection, and conflict behavior, then validates the actual patched server before building. Unchanged inputs skip rebuilding only if the matching release has its DMG, checksums and provenance. No automatic PRs or comments are created.

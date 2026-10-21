# Repair the fork's patch series

You are repairing this fork's patch series after the Fork Nightly build failed. Work unattended: nobody will answer questions. Finish with a working series or a clear explanation of why you could not.

## Layout

- `$CONTROL` is a checkout of the `fork-maintenance` branch. Its `.fork/series` lists the patches in order. Each one is a `git format-patch` mailbox in `.fork/patches/`. `.fork/README.md` explains what each patch is for.
- `$UPSTREAM_TAG` is the upstream nightly tag the build failed on. It is fetched into `$CONTROL`.
- `$FAILED_RUN_LOG` holds the failed run's log, trimmed to its failing steps. Read it first.

Create your own scratch checkout of the tag, for example `git -C "$CONTROL" worktree add --detach "$RUNNER_TEMP/source" "$UPSTREAM_TAG"`. Then install with `vp -C "$RUNNER_TEMP/source" install --frozen-lockfile` and apply the series one patch at a time with `git am --3way`.

Your shell is limited to `git` and `vp` commands. Use `git -C <dir>` and `vp -C <dir>` instead of `cd`. Don't use pipes or redirects. Read, search and edit files with your file tools.

## Goal

Every patch in the series must apply to `$UPSTREAM_TAG` with plain `git am`, without `--3way`, in series order. The patched tree must also pass the checks below. CI fetches upstream shallowly and has no blobs for a 3-way merge, so any conflict fails the build.

For each patch that does not apply:

1. **Check whether upstream already covers it.** Compare what the patch is for (its commit message and README paragraph) with what upstream's new commits did, using `git log` between the previous tag and `$UPSTREAM_TAG`. If upstream now has equivalent behavior, drop the patch: remove it from `series`, delete the file, and replace its README paragraph with one sentence naming the upstream PR that superseded it. Equivalent means the user-visible behavior the patch provides, not merely similar code. When in doubt, keep the patch.
2. **Otherwise, port it.** Resolve every conflict so the patched behavior is preserved on top of upstream's new code. Prefer upstream's structure and conventions, and re-express the patch's change inside them. Don't drop upstream changes or revert upstream refactors. When a whole file conflicts heavily, it is usually cleaner to take upstream's version and re-apply the patch's intent by hand.
3. **Watch for silent duplicates.** A patch can apply cleanly and still break, when upstream added the same import, constant or field the patch adds. Compiler errors such as "has already been declared" or "Duplicate identifier" mean you should delete the patch's copy.
4. **Commit and regenerate.** Commit the result as that patch's single commit, keeping its original message. Regenerate the file with `git format-patch -1 <commit> --output="$CONTROL/.fork/patches/<name>.patch"`. Later patches must be replayed on top of your repaired commits.

Upstream lint rules apply to code the patch adds. Fix violations in the lines a patch adds, but don't restyle code you aren't otherwise touching.

## Checks

Run all of these on the fully patched tree. All must pass. Paths are relative to your scratch checkout, so prefix them with it (for example `vp -C "$RUNNER_TEMP/source/apps/web" run typecheck`).

- `vp -C apps/web run typecheck`
- `vp -C apps/desktop run typecheck`
- `vp -C apps/mobile run typecheck`
- `vp -C packages/contracts run typecheck`
- `vp -C apps/desktop run build`
- `vp lint apps/web/src/components/ChatView.tsx scripts/build-desktop-artifact.ts`
- `vp fmt --check` on every file the series changes
- `vp -C <app> test run <files>` for the test files next to every source file you edited during conflict resolution, with paths relative to that app.

The server typecheck (`vp -C apps/server run typecheck`) has a known artifact. `home-agent.patch` adds enough WebSocket RPCs that the Effect checker reports TS377030 ("any in the requirements channel") in `src/server.ts` and `src/ws.test.ts` even when the types are correct. Those diagnostics can hide real missing-service errors in tests, so:

- Any server error other than TS377030 in those two files must be fixed.
- If upstream added a test that builds `layerWsRpc` or the MCP toolkit layers, make sure it provides `notHomeLayer` from `apps/server/src/home/HomeTestkit.ts`, as the existing tests do.
- To see the masked errors, temporarily remove three Home RPCs (`WsHomeEnableRpc`, `WsHomeDisableRpc`, `WsHomeStartFreshRpc`) from the RPC group in `packages/contracts/src/rpc.ts` and their handlers in `apps/server/src/ws.ts`. Typecheck, then restore them.

Finally, prove the series replays: apply every patch from `$CONTROL/.fork/patches` in `series` order to a fresh checkout of `$UPSTREAM_TAG` with plain `git am`. Confirm the result is the tree you checked.

## Boundaries

- Only change `$CONTROL/.fork/series`, `$CONTROL/.fork/patches/`, and `$CONTROL/.fork/README.md`. Don't edit any other file in `$CONTROL`. Don't commit or push in `$CONTROL`; the workflow does that after re-verifying.
- Don't add new features or patches. Don't widen a patch beyond what it takes to keep its behavior on the new upstream.
- Never add AI attribution: no Co-authored-by trailers, no "Generated with" lines.

## Report

Write a Markdown summary to `$REPAIR_SUMMARY`. Its first line must be a commit subject of the form `fix(fork): refresh patches for <tag>`. Then add a blank line, then plain prose that a maintainer can review in a minute:

- which patches you dropped and the upstream PR that superseded each;
- which patches you ported, and for each conflict what upstream changed and how the patch's behavior was kept;
- which checks you ran and their results.

If you could not produce a series that passes every check, leave `$CONTROL/.fork` unchanged (`git -C "$CONTROL" checkout -- .fork` and `git -C "$CONTROL" clean -fd .fork`). Write `$REPAIR_SUMMARY` starting with the line `REPAIR FAILED`, followed by what blocks it.

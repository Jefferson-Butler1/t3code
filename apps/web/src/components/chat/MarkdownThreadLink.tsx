import { scopeProjectRef, scopeThreadRef } from "@t3tools/client-runtime/environment";
import type { EnvironmentId, ThreadId } from "@t3tools/contracts";
import { formatThreadLink, percentDecodedThreadLinkId } from "@t3tools/shared/threadLinks";
import { Link } from "@tanstack/react-router";
import { MessageSquareTextIcon } from "lucide-react";

import { useProject, useThreadShell, useThreadShells } from "../../state/entities";
import { ProjectFavicon } from "../ProjectFavicon";

/**
 * A `t3-thread://` link in chat. It shows the thread's current title, so a rename
 * reaches every message that links to it, and leads with the thread's project icon
 * the way a web link leads with its favicon. `label` is what the message wrote,
 * shown only when this client cannot see the thread. Opens the thread in the app.
 * A thread missing from the message's environment is looked up in every connected
 * one, so links Home writes to threads on other machines still open.
 */
export function MarkdownThreadLink(props: {
  readonly environmentId: EnvironmentId;
  readonly threadId: ThreadId;
  readonly label: string;
}) {
  const decodedId = percentDecodedThreadLinkId(props.threadId);
  const written = useThreadShell(scopeThreadRef(props.environmentId, props.threadId));
  const decoded = useThreadShell(
    written === null && decodedId !== null ? scopeThreadRef(props.environmentId, decodedId) : null,
  );
  const local = written ?? decoded;
  // Only an unresolved link subscribes to the full shell list.
  const allShells = useThreadShells(local === null);
  const thread =
    local ??
    allShells.find((shell) => shell.id === props.threadId) ??
    (decodedId === null ? undefined : allShells.find((shell) => shell.id === decodedId)) ??
    null;
  const threadId = thread?.id ?? props.threadId;
  const environmentId = thread?.environmentId ?? props.environmentId;
  const project = useProject(
    thread === null ? null : scopeProjectRef(environmentId, thread.projectId),
  );
  const title = thread?.title.trim() || props.label;
  return (
    <Link
      to="/$environmentId/$threadId"
      params={{ environmentId, threadId }}
      // Like an attached thread chip: archived threads are not in the index but still open.
      title={thread === null ? "Thread no longer available" : project?.title}
      data-markdown-copy={formatThreadLink(threadId, title)}
    >
      <span
        className="ms-[0.25em] me-[0.2em] inline-flex size-[14px] [vertical-align:-0.125em]"
        aria-hidden
      >
        {project === null ? (
          <MessageSquareTextIcon className="block size-full shrink-0" />
        ) : (
          <ProjectFavicon project={project} className="size-full" />
        )}
      </span>
      {title}
    </Link>
  );
}

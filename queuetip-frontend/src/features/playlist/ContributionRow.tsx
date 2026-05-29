import { useMutation } from "@apollo/client";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { toast } from "sonner";

import {
  CastVoteDocument,
  ClearVoteDocument,
  RemoveContributionDocument,
} from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";
import { PlatformLinks } from "./PlatformLinks";

type Vote = { account: { id: string }; value: number };
type Contribution = {
  id: string;
  netScore: number;
  song: {
    id: string;
    title: string;
    artist: string;
    spotifyGid?: string | null;
    deezerId?: string | null;
    durationSeconds?: number | null;
  };
  duplicateKind?: string;
  duplicateWithTitles?: string[];
  contributedBy: { id: string; displayName: string };
  votes: Vote[];
};

type Props = {
  contribution: Contribution;
  currentAccountId: string;
  isOwner: boolean;
  onRemoved: () => void;
};

export function ContributionRow({ contribution, currentAccountId, isOwner, onRemoved }: Props) {
  const myVote = contribution.votes.find((v) => v.account.id === currentAccountId)?.value ?? 0;

  const [castVote] = useMutation(CastVoteDocument);
  const [clearVote] = useMutation(ClearVoteDocument);
  const [removeContribution] = useMutation(RemoveContributionDocument, {
    update(cache) {
      cache.evict({ id: cache.identify({ __typename: "ContributionType", id: contribution.id }) });
      cache.gc();
    },
  });

  async function vote(value: 1 | -1) {
    if (myVote === value) {
      await clearVote({
        variables: { contributionId: contribution.id },
        optimisticResponse: {
          clearVote: {
            __typename: "ContributionType",
            id: contribution.id,
            netScore: contribution.netScore - value,
            votes: contribution.votes.filter((v) => v.account.id !== currentAccountId),
          },
        },
      });
      return;
    }
    const newVotes = [
      ...contribution.votes.filter((v) => v.account.id !== currentAccountId),
      { __typename: "VoteType" as const, account: { __typename: "AccountType" as const, id: currentAccountId }, value },
    ];
    const newNet = newVotes.reduce((sum, v) => sum + v.value, 0);
    await castVote({
      variables: { contributionId: contribution.id, value },
      optimisticResponse: {
        castVote: {
          __typename: "ContributionType",
          id: contribution.id,
          netScore: newNet,
          votes: newVotes,
        },
      },
    });
  }

  const canRemove = isOwner || contribution.contributedBy.id === currentAccountId;
  const duplicateKind = contribution.duplicateKind ?? "none";
  const duplicateWithTitles = contribution.duplicateWithTitles ?? [];
  const hasDuplicates = duplicateKind !== "none";
  const duplicateLabel =
    duplicateKind === "exact"
      ? "Exact duplicate"
      : duplicateKind === "alt_version"
        ? "Alt version"
        : "Duplicate";
  const duration = formatDuration(contribution.song.durationSeconds);

  async function handleRemove() {
    if (!confirm(`Remove "${contribution.song.title}"?`)) return;
    try {
      await removeContribution({ variables: { id: contribution.id } });
      toast.success("Contribution removed.");
      onRemoved();
    } catch {
      toast.error("Could not remove contribution.");
    }
  }

  return (
    <div
      className={`flex min-w-0 items-center justify-between gap-3 border-b py-2 last:border-b-0 ${
        hasDuplicates ? "bg-amber-50/40 dark:bg-amber-900/10" : ""
      }`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <div className="flex flex-col items-center gap-1">
          <Button
            variant={myVote === 1 ? "default" : "ghost"}
            size="icon"
            onClick={() => vote(1)}
            aria-label="Upvote"
          >
            <ChevronUp className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium tabular-nums w-8 text-center">
            {contribution.netScore > 0 ? "+" : ""}
            {contribution.netScore}
          </span>
          <Button
            variant={myVote === -1 ? "default" : "ghost"}
            size="icon"
            onClick={() => vote(-1)}
            aria-label="Downvote"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <div className="truncate font-medium">{contribution.song.title}</div>
            {hasDuplicates ? (
              <span className="shrink-0 rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-200">
                {duplicateLabel}
              </span>
            ) : null}
          </div>
          <div className="flex min-w-0 flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:items-center sm:gap-2">
            <span className="min-w-0 truncate">
              {contribution.song.artist} • added by {contribution.contributedBy.displayName}
              {duration ? ` • ${duration}` : ""}
            </span>
            <PlatformLinks
              title={contribution.song.title}
              artist={contribution.song.artist}
              spotifyGid={contribution.song.spotifyGid}
              deezerId={contribution.song.deezerId}
            />
          </div>
          {hasDuplicates && duplicateWithTitles.length > 0 ? (
            <p className="truncate pt-1 text-xs text-amber-800 dark:text-amber-200">
              Also on playlist: {duplicateWithTitles.join(", ")}
            </p>
          ) : null}
        </div>
      </div>
      {canRemove ? (
        <Button
          variant="ghost"
          size="icon"
          className="shrink-0"
          onClick={handleRemove}
          aria-label="Remove"
        >
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
}

function formatDuration(durationSeconds?: number | null): string | null {
  if (durationSeconds == null || durationSeconds <= 0) return null;
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

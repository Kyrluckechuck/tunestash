import { useMutation } from "@apollo/client";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { toast } from "sonner";

import {
  CastVoteDocument,
  ClearVoteDocument,
  RemoveContributionDocument,
} from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";

type Vote = { account: { id: string }; value: number };
type Contribution = {
  id: string;
  netScore: number;
  song: { id: string; title: string; artist: string };
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
    <div className="flex items-center justify-between gap-3 py-2 border-b last:border-b-0">
      <div className="flex items-center gap-2">
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
        <div>
          <div className="font-medium">{contribution.song.title}</div>
          <div className="text-sm text-muted-foreground">
            {contribution.song.artist} • added by {contribution.contributedBy.displayName}
          </div>
        </div>
      </div>
      {canRemove ? (
        <Button variant="ghost" size="icon" onClick={handleRemove} aria-label="Remove">
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
}

import * as React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@apollo/client";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { PlaylistDetailDocument } from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { RequireAuth } from "@/components/RequireAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ContributionRow } from "@/features/playlist/ContributionRow";
import { MemberList } from "@/features/playlist/MemberList";
import { BulkImportDialog } from "@/features/playlist/BulkImportDialog";
import { ContributeDialog } from "@/features/playlist/ContributeDialog";

function PlaylistDetailContent({ id }: { id: string }) {
  const { account } = useMe();
  const { data, loading, refetch } = useQuery(PlaylistDetailDocument, {
    variables: { id },
  });
  const [contributeOpen, setContributeOpen] = React.useState(false);
  const [bulkImportOpen, setBulkImportOpen] = React.useState(false);

  if (loading || !data) return <p className="container py-8 text-muted-foreground">Loading…</p>;
  if (!data.playlist) {
    return <p className="container py-8">Playlist not found.</p>;
  }

  const playlist = data.playlist;
  const contributions = data.playlistContributions;
  const myMembership = playlist.members.find((m) => m.account.id === account!.id);
  const isOwner = myMembership?.role === "owner";

  function copyInvite() {
    const url = `${window.location.origin}/join/${playlist.inviteToken}`;
    navigator.clipboard.writeText(url);
    toast.success("Invite link copied.");
  }

  return (
    <div className="container py-8 grid lg:grid-cols-[1fr_280px] gap-6">
      <div>
        <header className="mb-4">
          <h1 className="text-2xl font-bold">{playlist.name}</h1>
          {playlist.description ? (
            <p className="text-muted-foreground mt-1">{playlist.description}</p>
          ) : null}
        </header>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Contributions</CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setBulkImportOpen(true)}>
                Bulk import
              </Button>
              <Button size="sm" onClick={() => setContributeOpen(true)}>
                Contribute
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {contributions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No songs yet. Click "Contribute" to add the first one.
              </p>
            ) : (
              contributions.map((c) => (
                <ContributionRow
                  key={c.id}
                  contribution={c}
                  currentAccountId={account!.id}
                  isOwner={!!isOwner}
                  onRemoved={() => refetch()}
                />
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Members</CardTitle>
          </CardHeader>
          <CardContent>
            <MemberList members={playlist.members} currentAccountId={account!.id} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Invite</CardTitle>
          </CardHeader>
          <CardContent>
            <Button variant="outline" size="sm" className="w-full" onClick={copyInvite}>
              <Copy className="h-4 w-4 mr-2" /> Copy invite link
            </Button>
          </CardContent>
        </Card>
      </aside>

      <BulkImportDialog
        playlistId={id}
        open={bulkImportOpen}
        onOpenChange={setBulkImportOpen}
      />
      <ContributeDialog
        playlistId={id}
        open={contributeOpen}
        onOpenChange={setContributeOpen}
      />
    </div>
  );
}

export function PlaylistDetail() {
  const { id } = Route.useParams();
  return (
    <RequireAuth>
      <PlaylistDetailContent id={id} />
    </RequireAuth>
  );
}

export const Route = createFileRoute("/playlists/$id")({
  component: PlaylistDetail,
});

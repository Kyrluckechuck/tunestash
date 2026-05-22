import * as React from "react";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery } from "@apollo/client";
import { Copy, Settings, Trash2, LogOut, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import {
  DeletePlaylistDocument,
  KickMemberDocument,
  LeavePlaylistDocument,
  PlaylistDetailDocument,
  PromoteMemberDocument,
  RegenerateInviteTokenDocument,
} from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { RequireAuth } from "@/components/RequireAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ContributionRow } from "@/features/playlist/ContributionRow";
import { MemberList } from "@/features/playlist/MemberList";
import { BulkImportDialog } from "@/features/playlist/BulkImportDialog";
import { ContributeDialog } from "@/features/playlist/ContributeDialog";
import { EditSettingsDialog } from "@/features/playlist/EditSettingsDialog";
import { SendToSubsonicCard } from "@/features/playlist/SendToSubsonicCard";
import { SendToSpotifyCard } from "@/features/playlist/SendToSpotifyCard";

function PlaylistDetailContent({ id }: { id: string }) {
  const { account } = useMe();
  const router = useRouter();
  const { data, loading, refetch } = useQuery(PlaylistDetailDocument, {
    variables: { id },
  });
  const [contributeOpen, setContributeOpen] = React.useState(false);
  const [bulkImportOpen, setBulkImportOpen] = React.useState(false);
  const [settingsOpen, setSettingsOpen] = React.useState(false);

  const [regenerate] = useMutation(RegenerateInviteTokenDocument, {
    refetchQueries: [{ query: PlaylistDetailDocument, variables: { id } }],
  });
  const [deletePlaylist] = useMutation(DeletePlaylistDocument);
  const [leave] = useMutation(LeavePlaylistDocument);
  const [kick] = useMutation(KickMemberDocument, {
    refetchQueries: [{ query: PlaylistDetailDocument, variables: { id } }],
  });
  const [promote] = useMutation(PromoteMemberDocument, {
    refetchQueries: [{ query: PlaylistDetailDocument, variables: { id } }],
  });

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

  async function handleRegenerate() {
    if (!confirm("Regenerate the invite link? The current link will stop working.")) return;
    try {
      await regenerate({ variables: { id } });
      toast.success("Invite link regenerated.");
    } catch {
      toast.error("Failed.");
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${playlist.name}"? This cannot be undone.`)) return;
    try {
      await deletePlaylist({ variables: { id } });
      toast.success("Playlist deleted.");
      await router.navigate({ to: "/playlists" });
    } catch {
      toast.error("Failed.");
    }
  }

  async function handleLeave() {
    if (!confirm("Leave this playlist?")) return;
    try {
      await leave({ variables: { id } });
      toast.success("Left the playlist.");
      await router.navigate({ to: "/playlists" });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Could not leave.";
      toast.error(message);
    }
  }

  async function handleKick(accountId: string, displayName: string) {
    if (!confirm(`Kick ${displayName}?`)) return;
    try {
      await kick({ variables: { playlistId: id, accountId } });
      toast.success("Kicked.");
    } catch {
      toast.error("Failed.");
    }
  }

  async function handlePromote(accountId: string, displayName: string) {
    if (!confirm(`Promote ${displayName} to owner?`)) return;
    try {
      await promote({ variables: { playlistId: id, accountId } });
      toast.success("Promoted.");
    } catch {
      toast.error("Failed.");
    }
  }

  return (
    <div className="container py-8 space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{playlist.name}</h1>
          {playlist.description ? (
            <p className="text-muted-foreground mt-1">{playlist.description}</p>
          ) : null}
        </div>
        {isOwner ? (
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
              <Settings className="h-4 w-4 mr-1" />
              Settings
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={handleDelete}
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" className="shrink-0" onClick={handleLeave}>
            <LogOut className="h-4 w-4 mr-1" />
            Leave
          </Button>
        )}
      </header>

      <div className="grid lg:grid-cols-[1fr_320px] gap-6">
        <div>
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-2">
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

        <aside className="space-y-4 order-first lg:order-none">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Members</CardTitle>
            </CardHeader>
            <CardContent>
              <MemberList
                members={playlist.members}
                currentAccountId={account!.id}
                isOwner={!!isOwner}
                onKick={isOwner ? handleKick : undefined}
                onPromote={isOwner ? handlePromote : undefined}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Invite</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Button variant="outline" size="sm" className="w-full" onClick={copyInvite}>
                <Copy className="h-4 w-4 mr-2" /> Copy invite link
              </Button>
              {isOwner ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-muted-foreground"
                  onClick={handleRegenerate}
                >
                  <RefreshCw className="h-4 w-4 mr-2" /> Regenerate link
                </Button>
              ) : null}
            </CardContent>
          </Card>

          <SendToSpotifyCard playlistId={id} />
          <SendToSubsonicCard playlistId={id} />
        </aside>
      </div>

      <BulkImportDialog playlistId={id} open={bulkImportOpen} onOpenChange={setBulkImportOpen} />
      <ContributeDialog playlistId={id} open={contributeOpen} onOpenChange={setContributeOpen} />
      {isOwner ? (
        <EditSettingsDialog
          playlist={{
            id: playlist.id,
            name: playlist.name,
            description: playlist.description,
          }}
          initialKnobs={{
            minSize: playlist.engineSettings.minSize,
            maxSize: playlist.engineSettings.maxSize ?? null,
            tHigh: playlist.engineSettings.tHigh,
            tLow: playlist.engineSettings.tLow,
            base: playlist.engineSettings.base,
            pFloor: playlist.engineSettings.pFloor,
          }}
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
        />
      ) : null}
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

import * as React from "react";
import { useMutation, useQuery } from "@apollo/client";
import { AlertCircle, CheckCircle2, Loader2, Music, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import {
  CreateSpotifyExportTargetDocument,
  MyPlaylistSyncTargetsDocument,
  RecreateSyncTargetRemoteDocument,
  RemoveSyncTargetDocument,
  SyncTargetNowDocument,
} from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * "Reshuffle & push to Spotify" panel — appears on the playlist page when
 * the user has linked their Spotify account. Mirrors SendToSubsonicCard:
 * each push runs a fresh selection roll and replaces the Spotify playlist's
 * tracks. No background auto-sync.
 */
type Props = {
  playlistId: string;
};

export function SendToSpotifyCard({ playlistId }: Props) {
  const { account } = useMe();
  const spotifyLinked =
    account?.externalServices.some((l) => l.service === "spotify") ?? false;

  const { data: targetsData, refetch } = useQuery(MyPlaylistSyncTargetsDocument, {
    variables: { playlistId },
    fetchPolicy: "cache-and-network",
  });
  const target =
    targetsData?.myPlaylistSyncTargets.find(
      (t) => t.destinationType === "spotify",
    ) ?? null;

  const [createTarget, { loading: creating }] = useMutation(
    CreateSpotifyExportTargetDocument,
    { onCompleted: () => refetch() },
  );
  const [pushNow, { loading: pushing }] = useMutation(SyncTargetNowDocument, {
    onCompleted: () => refetch(),
  });
  const [recreateRemote, { loading: recreating }] = useMutation(
    RecreateSyncTargetRemoteDocument,
    { onCompleted: () => refetch() },
  );
  const [removeTarget, { loading: removing }] = useMutation(
    RemoveSyncTargetDocument,
    { onCompleted: () => refetch() },
  );

  if (!spotifyLinked) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Music className="h-4 w-4" /> Spotify
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-muted-foreground">Not linked.</span>
            <Link to="/settings">
              <Button variant="outline" size="sm">
                Link Spotify
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  async function handleReshufflePush() {
    try {
      let targetId = target?.id;
      if (!targetId) {
        const created = await createTarget({ variables: { playlistId } });
        targetId = created.data?.createSpotifyExportTarget.id;
      }
      if (!targetId) {
        toast.error("Could not set up the Spotify target.");
        return;
      }
      await pushNow({ variables: { id: targetId } });
      toast.success("Reshuffled & pushed to Spotify.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Push failed.");
    }
  }

  async function handleRecreate() {
    if (!target) return;
    try {
      await recreateRemote({ variables: { id: target.id } });
      toast.success("Re-created on Spotify.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Recreate failed.");
    }
  }

  async function handleRemove() {
    if (!target) return;
    if (
      !window.confirm(
        "Stop pushing this playlist to Spotify? The Spotify playlist is left as-is.",
      )
    ) {
      return;
    }
    try {
      await removeTarget({ variables: { id: target.id, deleteRemote: false } });
      toast.success("Removed.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Remove failed.");
    }
  }

  const busy = creating || pushing;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Music className="h-4 w-4" /> Spotify
          {target ? <SyncStatusBadge status={target.lastSyncStatus} /> : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {target && target.lastSyncStatus === "remote_deleted" ? (
          <div className="space-y-2">
            <Alert variant="destructive">
              <AlertDescription>
                The Spotify playlist was deleted. Recreate to start over.
              </AlertDescription>
            </Alert>
            <div className="flex gap-2">
              <Button onClick={handleRecreate} disabled={recreating}>
                <RefreshCw className="h-4 w-4 mr-2" />
                {recreating ? "Recreating…" : "Recreate on Spotify"}
              </Button>
              <Button variant="ghost" onClick={handleRemove} disabled={removing}>
                Stop pushing
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {target && target.lastSyncedAt ? (
              <div className="text-sm text-muted-foreground">
                Last pushed {new Date(target.lastSyncedAt).toLocaleString()} ·{" "}
                {target.matchedTrackCount} of {target.totalTrackCount} tracks added
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                Not pushed yet. Each push picks a fresh random selection and
                replaces the Spotify playlist.
              </div>
            )}
            {target && target.unmatchedTrackTitles.length > 0 ? (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  {target.unmatchedTrackTitles.length} track
                  {target.unmatchedTrackTitles.length === 1 ? "" : "s"} skipped
                </summary>
                <ul className="mt-2 list-disc pl-5 space-y-1">
                  {target.unmatchedTrackTitles.map((t, idx) => (
                    <li key={idx}>{t}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <div className="flex gap-2">
              <Button onClick={handleReshufflePush} disabled={busy}>
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Pushing…
                  </>
                ) : (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2" /> Reshuffle &amp; push
                  </>
                )}
              </Button>
              {target ? (
                <Button variant="ghost" size="sm" onClick={handleRemove} disabled={removing}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SyncStatusBadge({ status }: { status: string }) {
  if (status === "ok") {
    return (
      <Badge variant="default" className="gap-1 ml-auto">
        <CheckCircle2 className="h-3 w-3" /> Pushed
      </Badge>
    );
  }
  if (status === "partial") {
    return (
      <Badge variant="secondary" className="gap-1 ml-auto">
        <AlertCircle className="h-3 w-3" /> Partial
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1 ml-auto">
        <AlertCircle className="h-3 w-3" /> Failed
      </Badge>
    );
  }
  if (status === "remote_deleted") {
    return (
      <Badge variant="destructive" className="gap-1 ml-auto">
        <AlertCircle className="h-3 w-3" /> Deleted on Spotify
      </Badge>
    );
  }
  return null;
}

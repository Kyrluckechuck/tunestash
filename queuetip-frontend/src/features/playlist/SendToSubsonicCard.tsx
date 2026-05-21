import * as React from "react";
import { useMutation, useQuery } from "@apollo/client";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Server,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import {
  CreateSubsonicSyncTargetDocument,
  MyPlaylistSyncTargetsDocument,
  MySubsonicConnectionDocument,
  RecreateSyncTargetRemoteDocument,
  RemoveSyncTargetDocument,
  SyncTargetNowDocument,
  UpdateSyncTargetModeDocument,
} from "@/types/generated/graphql";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

/**
 * "Send to Subsonic" panel — appears on the playlist detail page when the
 * user has a Subsonic connection configured.
 *
 * - No target yet → "Sync to <connection label>" creates one and runs the
 *   first sync (creates a fresh playlist on the user's Navidrome).
 * - Target exists → status badge + sync-now button + auto-sync toggle +
 *   remove. Unmatched track titles surface in an expandable list.
 * - Target in REMOTE_DELETED → red badge + "Recreate on Subsonic" button.
 */
type Props = {
  playlistId: string;
};

export function SendToSubsonicCard({ playlistId }: Props) {
  const { data: connData } = useQuery(MySubsonicConnectionDocument, {
    fetchPolicy: "cache-and-network",
  });
  const connection = connData?.mySubsonicConnection ?? null;

  const { data: targetsData, refetch } = useQuery(
    MyPlaylistSyncTargetsDocument,
    {
      variables: { playlistId },
      fetchPolicy: "cache-and-network",
    },
  );
  const subsonicTarget =
    targetsData?.myPlaylistSyncTargets.find(
      (t) => t.destinationType === "subsonic",
    ) ?? null;

  const [createTarget, { loading: creating }] = useMutation(
    CreateSubsonicSyncTargetDocument,
    { onCompleted: () => refetch() },
  );
  const [syncNow, { loading: syncing }] = useMutation(SyncTargetNowDocument, {
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
  const [updateMode, { loading: updatingMode }] = useMutation(
    UpdateSyncTargetModeDocument,
    { onCompleted: () => refetch() },
  );

  if (!connection) {
    // Don't render at all when no Subsonic connection — settings page is
    // where the user adds one, surfacing it here would clutter the playlist.
    return null;
  }

  async function handleFirstSync() {
    try {
      const created = await createTarget({
        variables: {
          playlistId,
          connectionId: connection!.id,
          syncMode: "manual",
        },
      });
      const newId = created.data?.createSubsonicSyncTarget.id;
      if (newId) {
        await syncNow({ variables: { id: newId } });
        toast.success("Synced to Subsonic.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sync failed.");
    }
  }

  async function handleSyncNow() {
    if (!subsonicTarget) return;
    try {
      await syncNow({ variables: { id: subsonicTarget.id } });
      toast.success("Synced to Subsonic.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sync failed.");
    }
  }

  async function handleRecreate() {
    if (!subsonicTarget) return;
    try {
      await recreateRemote({ variables: { id: subsonicTarget.id } });
      toast.success("Re-created on Subsonic.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Recreate failed.");
    }
  }

  async function handleRemove() {
    if (!subsonicTarget) return;
    if (
      !window.confirm(
        "Stop syncing this playlist to Subsonic? The playlist on your server will not be touched.",
      )
    ) {
      return;
    }
    try {
      await removeTarget({
        variables: { id: subsonicTarget.id, deleteRemote: false },
      });
      toast.success("Sync target removed.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Remove failed.");
    }
  }

  async function handleToggleAutoSync(checked: boolean) {
    if (!subsonicTarget) return;
    try {
      await updateMode({
        variables: {
          id: subsonicTarget.id,
          syncMode: checked ? "on_change" : "manual",
        },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Server className="h-4 w-4" />
          Send to {connection.label}
          {subsonicTarget ? (
            <SyncStatusBadge status={subsonicTarget.lastSyncStatus} />
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!subsonicTarget ? (
          <Button onClick={handleFirstSync} disabled={creating || syncing}>
            {creating || syncing ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Syncing…
              </>
            ) : (
              "Sync to Subsonic"
            )}
          </Button>
        ) : subsonicTarget.lastSyncStatus === "remote_deleted" ? (
          <div className="space-y-2">
            <Alert variant="destructive">
              <AlertDescription>
                The Subsonic playlist was deleted. Recreate to start over.
              </AlertDescription>
            </Alert>
            <div className="flex gap-2">
              <Button onClick={handleRecreate} disabled={recreating}>
                <RefreshCw className="h-4 w-4 mr-2" />
                {recreating ? "Recreating…" : "Recreate on Subsonic"}
              </Button>
              <Button variant="ghost" onClick={handleRemove} disabled={removing}>
                Stop syncing
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground">
              {subsonicTarget.matchedTrackCount} of{" "}
              {subsonicTarget.totalTrackCount} tracks matched
              {subsonicTarget.lastSyncedAt
                ? ` · synced ${new Date(subsonicTarget.lastSyncedAt).toLocaleString()}`
                : ""}
            </div>
            {subsonicTarget.unmatchedTrackTitles.length > 0 ? (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  {subsonicTarget.unmatchedTrackTitles.length} track
                  {subsonicTarget.unmatchedTrackTitles.length === 1 ? "" : "s"}{" "}
                  couldn&apos;t be matched on your server
                </summary>
                <ul className="mt-2 list-disc pl-5 space-y-1">
                  {subsonicTarget.unmatchedTrackTitles.map((title, idx) => (
                    <li key={idx}>{title}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-muted-foreground">
                  TuneStash has been asked to download these. Re-sync after
                  they appear in your library, or turn on auto-sync below.
                </p>
              </details>
            ) : null}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Switch
                  checked={subsonicTarget.syncMode === "on_change"}
                  onCheckedChange={handleToggleAutoSync}
                  disabled={updatingMode}
                  id={`auto-sync-${subsonicTarget.id}`}
                />
                <label
                  htmlFor={`auto-sync-${subsonicTarget.id}`}
                  className="text-sm cursor-pointer select-none"
                >
                  Auto-sync on changes
                </label>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSyncNow}
                  disabled={syncing}
                >
                  <RefreshCw className="h-4 w-4 mr-1" />
                  {syncing ? "Syncing…" : "Sync now"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRemove}
                  disabled={removing}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
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
        <CheckCircle2 className="h-3 w-3" /> Synced
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
        <AlertCircle className="h-3 w-3" /> Deleted on server
      </Badge>
    );
  }
  return null;
}

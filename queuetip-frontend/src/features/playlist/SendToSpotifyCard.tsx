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
  UpdateSyncTargetPreferencesDocument,
} from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

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
  const [updatePreferences, { loading: savingPreferences }] = useMutation(
    UpdateSyncTargetPreferencesDocument,
    { onCompleted: () => refetch() },
  );
  const [excludeMyDownvotes, setExcludeMyDownvotes] = React.useState(false);
  const [uniqueVersionsOnly, setUniqueVersionsOnly] = React.useState(false);
  const [minScoreThreshold, setMinScoreThreshold] = React.useState("");
  const [targetSizeOverride, setTargetSizeOverride] = React.useState("");

  React.useEffect(() => {
    setExcludeMyDownvotes(target?.excludeMyDownvotes ?? false);
    setUniqueVersionsOnly(target?.uniqueVersionsOnly ?? false);
    setMinScoreThreshold(
      target?.minScoreThreshold != null ? String(target.minScoreThreshold) : "",
    );
    setTargetSizeOverride(
      target?.targetSizeOverride != null ? String(target.targetSizeOverride) : "",
    );
  }, [target]);

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

  async function handleSavePreferences() {
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

      const parsedTargetSize =
        targetSizeOverride.trim() === "" ? null : Number(targetSizeOverride.trim());
      if (parsedTargetSize !== null && (!Number.isInteger(parsedTargetSize) || parsedTargetSize < 1)) {
        toast.error("Target size must be a whole number of at least 1.");
        return;
      }

      const parsedMinScore =
        minScoreThreshold.trim() === "" ? null : Number(minScoreThreshold.trim());
      if (parsedMinScore !== null && (!Number.isInteger(parsedMinScore) || parsedMinScore < -99)) {
        toast.error("Minimum score must be a whole number.");
        return;
      }

      await updatePreferences({
        variables: {
          id: targetId,
          excludeMyDownvotes,
          uniqueVersionsOnly,
          minScoreThreshold: parsedMinScore,
          targetSizeOverride: parsedTargetSize,
        },
      });
      toast.success("Export preferences saved.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save preferences.");
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

  // Any in-flight mutation disables all action buttons so a push can't race a
  // remove/recreate (which create vs delete the same target). The push button's
  // spinner label still keys off the push action specifically.
  const pushBusy = creating || pushing;
  const busy = pushBusy || removing || recreating;

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
              <Button onClick={handleRecreate} disabled={busy}>
                <RefreshCw className="h-4 w-4 mr-2" />
                {recreating ? "Recreating…" : "Recreate on Spotify"}
              </Button>
              <Button variant="ghost" onClick={handleRemove} disabled={busy}>
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
            <div className="space-y-3 rounded-md border p-3">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="spotify-exclude-downvotes" className="text-sm">
                  Exclude my downvotes
                </Label>
                <Switch
                  id="spotify-exclude-downvotes"
                  checked={excludeMyDownvotes}
                  onCheckedChange={setExcludeMyDownvotes}
                />
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="spotify-min-score" className="text-xs text-muted-foreground">
                    Minimum score
                  </Label>
                  <Input
                    id="spotify-min-score"
                    inputMode="numeric"
                    value={minScoreThreshold}
                    onChange={(event) => setMinScoreThreshold(event.target.value)}
                    placeholder="No minimum"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="spotify-target-size" className="text-xs text-muted-foreground">
                    Target size override
                  </Label>
                  <Input
                    id="spotify-target-size"
                    inputMode="numeric"
                    value={targetSizeOverride}
                    onChange={(event) => setTargetSizeOverride(event.target.value)}
                    placeholder="Use playlist settings"
                  />
                </div>
              </div>
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="spotify-unique-versions" className="text-sm">
                  Only include one version per song
                </Label>
                <Switch
                  id="spotify-unique-versions"
                  checked={uniqueVersionsOnly}
                  onCheckedChange={setUniqueVersionsOnly}
                />
              </div>
              <div className="flex justify-end">
                <Button size="sm" variant="outline" onClick={handleSavePreferences} disabled={busy || savingPreferences}>
                  Save preferences
                </Button>
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={handleReshufflePush} disabled={busy}>
                {pushBusy ? (
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
                <Button variant="ghost" size="sm" onClick={handleRemove} disabled={busy}>
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

import * as React from "react";
import { useApolloClient, useMutation, useQuery } from "@apollo/client";
import { Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";

import {
  BulkImportJobDocument,
  BulkImportPlaylistDocument,
  PlaylistDetailDocument,
} from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  playlistId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);

export function BulkImportDialog({ playlistId, open, onOpenChange }: Props) {
  const apollo = useApolloClient();
  const [url, setUrl] = React.useState("");
  const [jobId, setJobId] = React.useState<string | null>(null);
  // No refetchQueries here: the mutation returns when the job is QUEUED, not
  // when it completes, so a refetch at this point would show an unchanged
  // playlist. We refetch in the effect below once status hits a terminal state.
  const [bulkImport, { loading: starting }] = useMutation(BulkImportPlaylistDocument);

  const { data: jobData, stopPolling, startPolling } = useQuery(BulkImportJobDocument, {
    variables: { id: jobId ?? "" },
    skip: !jobId,
    pollInterval: jobId ? 2000 : 0,
  });

  // Stop polling once the job reaches a terminal state, and refetch the
  // parent playlist so the newly-added contributions render without a manual
  // refresh. Re-fetching here (not on mutation resolution) ensures we see
  // the real post-import state, not the empty queued-but-not-run state.
  React.useEffect(() => {
    if (!jobId || !jobData) return;
    const status = jobData.bulkImportJob.status;
    if (!TERMINAL_STATUSES.has(status)) return;
    stopPolling();
    if (status === "succeeded") {
      apollo.refetchQueries({ include: [PlaylistDetailDocument] });
    }
  }, [jobId, jobData, stopPolling, apollo]);

  // Resume polling if the dialog reopens with the same job still running.
  React.useEffect(() => {
    if (open && jobId && jobData && !TERMINAL_STATUSES.has(jobData.bulkImportJob.status)) {
      startPolling(2000);
    }
  }, [open, jobId, jobData, startPolling]);

  function reset() {
    setUrl("");
    setJobId(null);
  }

  function handleClose() {
    reset();
    onOpenChange(false);
  }

  async function handleStart() {
    if (!url.trim()) return;
    try {
      const { data } = await bulkImport({
        variables: { playlistId, url: url.trim() },
      });
      const job = data?.bulkImportPlaylist;
      if (!job) {
        toast.error("Could not start the import.");
        return;
      }
      setJobId(job.id);
    } catch {
      toast.error("Could not start the import.");
    }
  }

  const job = jobData?.bulkImportJob;
  const status = job?.status ?? null;
  const isRunning = status !== null && !TERMINAL_STATUSES.has(status);
  const isSucceeded = status === "succeeded";
  const isFailed = status === "failed";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Bulk import a playlist</DialogTitle>
        <DialogDescription>
          Paste a public Spotify or Apple Music playlist URL. We&apos;ll add every
          resolvable track to this playlist.
        </DialogDescription>
      </DialogHeader>
      <DialogContent>
        {!jobId ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="bi-url">Playlist URL</Label>
              <Input
                id="bi-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://open.spotify.com/playlist/…"
                autoFocus
              />
            </div>
          </div>
        ) : isRunning && job ? (
          <div className="space-y-2 py-4">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              <span className="text-sm">
                {status === "pending"
                  ? "Queued for import…"
                  : job.totalTracks
                    ? `Importing tracks… ${
                        job.addedCount + job.skippedCount + job.unresolvedCount
                      } / ${job.totalTracks}`
                    : "Importing tracks…"}
              </span>
            </div>
            {job.totalTracks && status === "running" ? (
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
                aria-label="Import progress"
              >
                <div
                  className="h-full bg-primary transition-all"
                  style={{
                    width: `${Math.min(
                      100,
                      ((job.addedCount + job.skippedCount + job.unresolvedCount) /
                        Math.max(1, job.totalTracks)) *
                        100,
                    )}%`,
                  }}
                />
              </div>
            ) : null}
          </div>
        ) : isSucceeded && job ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-600" />
              <span className="font-medium">Import complete</span>
            </div>
            <ul className="text-sm space-y-1">
              <li>Added: {job.addedCount}</li>
              <li>Already present: {job.skippedCount}</li>
              <li>Unresolved: {job.unresolvedCount}</li>
            </ul>
            {job.unresolvedTitles.length > 0 ? (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  Show unresolved tracks
                </summary>
                <ul className="mt-2 list-disc pl-5 space-y-1">
                  {job.unresolvedTitles.map((title, idx) => (
                    <li key={idx}>{title}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : isFailed && job ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-destructive" />
              <span className="font-medium">Import failed</span>
            </div>
            <p className="text-sm text-muted-foreground">{job.error}</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground py-4">Loading…</p>
        )}
      </DialogContent>
      <DialogFooter>
        {!jobId ? (
          <>
            <Button variant="ghost" onClick={handleClose}>
              Cancel
            </Button>
            <Button onClick={handleStart} disabled={!url.trim() || starting}>
              {starting ? "Starting…" : "Start import"}
            </Button>
          </>
        ) : (
          <Button onClick={handleClose} variant={isRunning ? "ghost" : "default"}>
            {isRunning ? "Close (keeps running)" : "Done"}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}

import * as React from "react";
import { useApolloClient, useLazyQuery, useMutation, useQuery } from "@apollo/client";
import { AlertCircle, CheckCircle2, Loader2, Search } from "lucide-react";
import { toast } from "sonner";

import {
  BulkImportJobDocument,
  BulkImportPlaylistDocument,
  CastVoteDocument,
  CatalogSearchDocument,
  ContributeFromLinkDocument,
  ContributeFromSearchDocument,
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
import { classifyContentInput } from "@/features/playlist/content-input";

type Props = {
  playlistId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

type DuplicateState = {
  contributionId: string;
  songLabel: string;
};

const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);

export function ContributeDialog({ playlistId, open, onOpenChange }: Props) {
  const apollo = useApolloClient();
  const [input, setInput] = React.useState("");
  const [duplicate, setDuplicate] = React.useState<DuplicateState | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const content = React.useMemo(() => classifyContentInput(input), [input]);

  const [search, { data: searchData, loading: searching }] = useLazyQuery(CatalogSearchDocument);
  const [contributeFromSearch, { loading: contributingSearch }] = useMutation(
    ContributeFromSearchDocument,
    { refetchQueries: [{ query: PlaylistDetailDocument, variables: { id: playlistId } }] }
  );
  const [contributeFromLink, { loading: contributingLink }] = useMutation(
    ContributeFromLinkDocument,
    { refetchQueries: [{ query: PlaylistDetailDocument, variables: { id: playlistId } }] }
  );
  // The import mutation only queues work; refetch after the worker reaches a terminal state.
  const [bulkImport, { loading: startingImport }] = useMutation(BulkImportPlaylistDocument);
  const [castVote] = useMutation(CastVoteDocument);
  const {
    data: jobData,
    stopPolling,
    startPolling,
  } = useQuery(BulkImportJobDocument, {
    variables: { id: jobId ?? "" },
    skip: !jobId,
    pollInterval: jobId ? 2000 : 0,
  });

  React.useEffect(() => {
    if (content.kind !== "search" || !input.trim()) return;
    const id = window.setTimeout(() => {
      void search({ variables: { query: input.trim(), limit: 10 } });
    }, 300);
    return () => window.clearTimeout(id);
  }, [input, content.kind, search]);

  // Keep the displayed playlist in sync only after all imported contributions are written.
  React.useEffect(() => {
    if (!jobId || !jobData) return;
    const status = jobData.bulkImportJob.status;
    if (!TERMINAL_STATUSES.has(status)) return;
    stopPolling();
    if (status === "succeeded") {
      void apollo.refetchQueries({ include: [PlaylistDetailDocument] });
    }
  }, [jobId, jobData, stopPolling, apollo]);

  // Continue showing progress if an open dialog still has an in-flight job.
  React.useEffect(() => {
    if (open && jobId && jobData && !TERMINAL_STATUSES.has(jobData.bulkImportJob.status)) {
      startPolling(2000);
    }
  }, [open, jobId, jobData, startPolling]);

  function reset() {
    setInput("");
    setDuplicate(null);
    setJobId(null);
  }

  function handleClose() {
    reset();
    onOpenChange(false);
  }

  async function addFromSearch(deezerId: string, songLabel: string) {
    try {
      const { data } = await contributeFromSearch({
        variables: { playlistId, deezerTrackId: deezerId },
      });
      const payload = data?.contributeFromSearch;
      if (!payload) return;
      if (payload.alreadyPresent) {
        setDuplicate({ contributionId: payload.contribution.id, songLabel });
      } else {
        toast.success("Added to playlist.");
        handleClose();
      }
    } catch {
      toast.error("Could not add the song.");
    }
  }

  async function addTrack() {
    if (content.kind !== "track") return;
    try {
      const { data } = await contributeFromLink({
        variables: { playlistId, url: input.trim() },
      });
      const payload = data?.contributeFromLink;
      if (!payload) return;
      const label = `${payload.contribution.song.artist} - ${payload.contribution.song.title}`;
      if (payload.alreadyPresent) {
        setDuplicate({ contributionId: payload.contribution.id, songLabel: label });
      } else {
        toast.success("Added to playlist.");
        handleClose();
      }
    } catch {
      toast.error("Could not add from that link.");
    }
  }

  async function startImport() {
    if (content.kind !== "collection") return;
    try {
      const { data } = await bulkImport({ variables: { playlistId, url: input.trim() } });
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

  async function upvoteExisting() {
    if (!duplicate) return;
    try {
      await castVote({ variables: { contributionId: duplicate.contributionId, value: 1 } });
      toast.success("Upvoted.");
      handleClose();
    } catch {
      toast.error("Could not upvote.");
    }
  }

  const job = jobData?.bulkImportJob;
  const status = job?.status ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Add songs</DialogTitle>
        <DialogDescription>Search or add from Spotify, Apple Music, or Deezer.</DialogDescription>
      </DialogHeader>
      <DialogContent>
        {duplicate ? (
          <div className="space-y-4">
            <p>
              <span className="font-medium">{duplicate.songLabel}</span> is already in this
              playlist. Upvote it instead?
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={handleClose}>
                Dismiss
              </Button>
              <Button onClick={upvoteExisting}>Upvote</Button>
            </div>
          </div>
        ) : jobId ? (
          <ImportStatus job={job} status={status} onClose={handleClose} />
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="add-songs-input">Search or paste a link</Label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="add-songs-input"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="Song name or music link"
                  className="pl-9"
                  autoFocus
                />
              </div>
            </div>
            {content.kind === "search" ? (
              <SearchResults
                data={searchData?.catalogSearch}
                searching={searching}
                contributing={contributingSearch}
                onAdd={addFromSearch}
              />
            ) : content.kind === "unsupported-url" ? (
              <p className="text-sm text-destructive">
                Unsupported link. Use a Spotify, Apple Music, or Deezer track, album, or playlist
                link.
              </p>
            ) : content.kind === "track" ? (
              <div className="flex justify-end">
                <Button onClick={addTrack} disabled={contributingLink}>
                  {contributingLink ? "Adding..." : "Add track"}
                </Button>
              </div>
            ) : (
              <div className="flex justify-end">
                <Button onClick={startImport} disabled={startingImport}>
                  {startingImport
                    ? "Starting..."
                    : `Import ${content.resource === "album" ? "album" : "playlist"}`}
                </Button>
              </div>
            )}
          </div>
        )}
      </DialogContent>
      {!duplicate && !jobId ? (
        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            Close
          </Button>
        </DialogFooter>
      ) : null}
    </Dialog>
  );
}

type SearchResultsProps = {
  data: Array<{ deezerId: string; title: string; artist: string; inLibrary: boolean }> | undefined;
  searching: boolean;
  contributing: boolean;
  onAdd: (deezerId: string, songLabel: string) => void;
};

function SearchResults({ data, searching, contributing, onAdd }: SearchResultsProps) {
  return (
    <div className="max-h-72 divide-y overflow-y-auto">
      {searching ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Searching...</p>
      ) : !data ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Start typing to search.</p>
      ) : data.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">No matches.</p>
      ) : (
        data.map((hit) => (
          <div key={hit.deezerId} className="flex items-center justify-between py-2">
            <div className="min-w-0">
              <div className="truncate font-medium">{hit.title}</div>
              <div className="truncate text-sm text-muted-foreground">
                {hit.artist}
                {hit.inLibrary ? " - already in your library" : ""}
              </div>
            </div>
            <Button
              size="sm"
              disabled={contributing}
              onClick={() => onAdd(hit.deezerId, `${hit.artist} - ${hit.title}`)}
            >
              Add
            </Button>
          </div>
        ))
      )}
    </div>
  );
}

type ImportStatusProps = {
  job:
    | {
        status: string;
        totalTracks?: number | null;
        addedCount: number;
        skippedCount: number;
        unresolvedCount: number;
        unresolvedTitles: string[];
        error: string;
      }
    | undefined;
  status: string | null;
  onClose: () => void;
};

function ImportStatus({ job, status, onClose }: ImportStatusProps) {
  if (!job || (status !== "succeeded" && status !== "failed")) {
    return (
      <div className="space-y-4 py-4">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="text-sm">
            {status === "running" && job?.totalTracks
              ? `Importing tracks... ${
                  job.addedCount + job.skippedCount + job.unresolvedCount
                } / ${job.totalTracks}`
              : "Queued for import..."}
          </span>
        </div>
        {status === "running" && job?.totalTracks ? (
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
                    100
                )}%`,
              }}
            />
          </div>
        ) : null}
        <div className="flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            Close (keeps running)
          </Button>
        </div>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-destructive" />
          <span className="font-medium">Import failed</span>
        </div>
        <p className="text-sm text-muted-foreground">{job.error}</p>
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-5 w-5 text-green-600" />
        <span className="font-medium">Import complete</span>
      </div>
      <ul className="space-y-1 text-sm">
        <li>Added: {job.addedCount}</li>
        <li>Already present: {job.skippedCount}</li>
        <li>Unresolved: {job.unresolvedCount}</li>
      </ul>
      {job.unresolvedTitles.length > 0 ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">Show unresolved tracks</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {job.unresolvedTitles.map((title, index) => (
              <li key={`${index}-${title}`}>{title}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className="flex justify-end">
        <Button onClick={onClose}>Done</Button>
      </div>
    </div>
  );
}

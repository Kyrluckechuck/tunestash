import * as React from "react";
import { useMutation, useLazyQuery } from "@apollo/client";
import { Search } from "lucide-react";
import { toast } from "sonner";

import {
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Props = {
  playlistId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

type DuplicateState = {
  contributionId: string;
  songLabel: string;
};

export function ContributeDialog({ playlistId, open, onOpenChange }: Props) {
  const [tab, setTab] = React.useState<"search" | "link">("search");
  const [query, setQuery] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [duplicate, setDuplicate] = React.useState<DuplicateState | null>(null);

  const [search, { data: searchData, loading: searching }] = useLazyQuery(
    CatalogSearchDocument,
  );
  const [contributeFromSearch, { loading: contributingSearch }] = useMutation(
    ContributeFromSearchDocument,
    { refetchQueries: [{ query: PlaylistDetailDocument, variables: { id: playlistId } }] },
  );
  const [contributeFromLink, { loading: contributingLink }] = useMutation(
    ContributeFromLinkDocument,
    { refetchQueries: [{ query: PlaylistDetailDocument, variables: { id: playlistId } }] },
  );
  const [castVote] = useMutation(CastVoteDocument);

  React.useEffect(() => {
    if (!query.trim() || tab !== "search") return;
    const id = window.setTimeout(() => {
      void search({ variables: { query: query.trim(), limit: 10 } });
    }, 300);
    return () => window.clearTimeout(id);
  }, [query, tab, search]);

  function reset() {
    setQuery("");
    setUrl("");
    setDuplicate(null);
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

  async function addFromLink() {
    if (!url.trim()) return;
    try {
      const { data } = await contributeFromLink({
        variables: { playlistId, url: url.trim() },
      });
      const payload = data?.contributeFromLink;
      if (!payload) return;
      const label = `${payload.contribution.song.artist} – ${payload.contribution.song.title}`;
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

  async function upvoteExisting() {
    if (!duplicate) return;
    try {
      await castVote({
        variables: { contributionId: duplicate.contributionId, value: 1 },
      });
      toast.success("Upvoted.");
      handleClose();
    } catch {
      toast.error("Could not upvote.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Contribute a song</DialogTitle>
        <DialogDescription>
          Search the catalog or paste a Spotify / Apple / Deezer track link.
        </DialogDescription>
      </DialogHeader>
      <DialogContent>
        {duplicate ? (
          <div className="space-y-4">
            <p>
              <span className="font-medium">{duplicate.songLabel}</span> is already in
              this playlist. Upvote it instead?
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={handleClose}>
                Dismiss
              </Button>
              <Button onClick={upvoteExisting}>Upvote</Button>
            </div>
          </div>
        ) : (
          <Tabs value={tab} onValueChange={(v) => setTab(v as "search" | "link")}>
            <TabsList>
              <TabsTrigger value="search">Search</TabsTrigger>
              <TabsTrigger value="link">Paste link</TabsTrigger>
            </TabsList>

            <TabsContent value="search" className="mt-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Song name, artist, anything…"
                  className="pl-9"
                  autoFocus
                />
              </div>
              <div className="mt-3 max-h-72 overflow-y-auto divide-y">
                {searching ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    Searching…
                  </p>
                ) : !searchData ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    Start typing to search the catalog.
                  </p>
                ) : searchData.catalogSearch.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No matches.
                  </p>
                ) : (
                  searchData.catalogSearch.map((hit) => (
                    <div
                      key={hit.deezerId}
                      className="flex items-center justify-between py-2"
                    >
                      <div className="min-w-0">
                        <div className="font-medium truncate">{hit.title}</div>
                        <div className="text-sm text-muted-foreground truncate">
                          {hit.artist}
                          {hit.inLibrary ? " • already in your library" : ""}
                        </div>
                      </div>
                      <Button
                        size="sm"
                        disabled={contributingSearch}
                        onClick={() =>
                          addFromSearch(hit.deezerId, `${hit.artist} – ${hit.title}`)
                        }
                      >
                        Add
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </TabsContent>

            <TabsContent value="link" className="mt-4 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ct-url">Track URL</Label>
                <Input
                  id="ct-url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://open.spotify.com/track/…"
                />
                <p className="text-xs text-muted-foreground">
                  Spotify, Apple Music, or Deezer track URLs are supported.
                </p>
              </div>
              <div className="flex justify-end">
                <Button
                  onClick={addFromLink}
                  disabled={!url.trim() || contributingLink}
                >
                  {contributingLink ? "Adding…" : "Add"}
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
      {!duplicate ? (
        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            Close
          </Button>
        </DialogFooter>
      ) : null}
    </Dialog>
  );
}

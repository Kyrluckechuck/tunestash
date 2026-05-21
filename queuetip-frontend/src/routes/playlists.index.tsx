import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@apollo/client";
import { Plus } from "lucide-react";

import { MyPlaylistsDocument } from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NewPlaylistDialog } from "@/features/playlists/NewPlaylistDialog";
import { RequireAuth } from "@/components/RequireAuth";

export function PlaylistsIndex() {
  return (
    <RequireAuth>
      <PlaylistsIndexContent />
    </RequireAuth>
  );
}

function PlaylistsIndexContent() {
  const { data, loading } = useQuery(MyPlaylistsDocument);
  const [open, setOpen] = React.useState(false);

  const playlists = data?.myPlaylists ?? [];

  return (
    <div className="container py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Your playlists</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4 mr-1" /> New playlist
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : playlists.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No playlists yet. Create one to start contributing.
          </CardContent>
        </Card>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {playlists.map((p) => (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle>{p.name}</CardTitle>
                {p.description ? <CardDescription>{p.description}</CardDescription> : null}
              </CardHeader>
              <CardContent className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">
                  {p.members.length} member{p.members.length === 1 ? "" : "s"}
                </span>
                <Link
                  to="/playlists/$id"
                  params={{ id: p.id }}
                  className="text-sm underline-offset-4 hover:underline"
                >
                  Open →
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <NewPlaylistDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}

export const Route = createFileRoute("/playlists/")({
  component: PlaylistsIndex,
});

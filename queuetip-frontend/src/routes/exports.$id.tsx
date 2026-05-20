import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@apollo/client";
import { AlertTriangle, Download } from "lucide-react";

import { ExportDocument } from "@/types/generated/graphql";
import { RequireAuth } from "@/components/RequireAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

function ExportPageContent({ id }: { id: string }) {
  const { data, loading } = useQuery(ExportDocument, { variables: { id } });

  if (loading || !data) {
    return <p className="container py-8 text-muted-foreground">Loading…</p>;
  }

  const snapshot = data.export;

  return (
    <div className="container py-8 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{snapshot.playlist.name} — export</h1>
          <p className="text-sm text-muted-foreground">
            Created by {snapshot.requestedBy.displayName}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/playlists/$id" params={{ id: snapshot.playlist.id }}>
            <Button variant="outline">Back to playlist</Button>
          </Link>
          <a href={snapshot.m3uUrl} target="_blank" rel="noopener noreferrer">
            <Button>
              <Download className="h-4 w-4 mr-2" /> Download m3u
            </Button>
          </a>
        </div>
      </div>

      {snapshot.warningMessage ? (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Heads up</AlertTitle>
          <AlertDescription>{snapshot.warningMessage}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Tracks ({snapshot.tracks.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {snapshot.tracks.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              No tracks made the cut — the playlist may have been empty or all songs
              filtered out.
            </p>
          ) : (
            <ol className="space-y-2">
              {snapshot.tracks.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3">
                  <div className="flex items-baseline gap-3 min-w-0">
                    <span className="text-sm text-muted-foreground tabular-nums w-6 text-right">
                      {t.position + 1}.
                    </span>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{t.song.title}</div>
                      <div className="text-sm text-muted-foreground truncate">
                        {t.song.artist}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge
                      variant={
                        t.inclusionReason === "guaranteed"
                          ? "default"
                          : t.inclusionReason === "topped_up"
                            ? "outline"
                            : "secondary"
                      }
                    >
                      {t.inclusionReason}
                    </Badge>
                    <span className="text-xs text-muted-foreground tabular-nums w-12 text-right">
                      {(t.rollProbability * 100).toFixed(0)}%
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function ExportPage() {
  const { id } = Route.useParams();
  return (
    <RequireAuth>
      <ExportPageContent id={id} />
    </RequireAuth>
  );
}

export const Route = createFileRoute("/exports/$id")({
  component: ExportPage,
});

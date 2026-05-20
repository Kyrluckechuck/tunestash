import { createFileRoute } from "@tanstack/react-router";
import { ExternalLink, Music } from "lucide-react";

import { RequireAuth } from "@/components/RequireAuth";
import { useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function SettingsPageContent() {
  const { account } = useMe();
  const spotifyLink = account?.externalServices.find((l) => l.service === "spotify");

  function handleLinkSpotify() {
    const base = (
      import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "http://localhost:5050/graphql"
    ).replace(/\/graphql\/?$/, "");
    window.location.assign(`${base}/auth/spotify/start`);
  }

  return (
    <div className="container max-w-2xl py-8 space-y-4">
      <h1 className="text-2xl font-bold">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Music className="h-5 w-5" /> Spotify
          </CardTitle>
          <CardDescription>
            Link your Spotify account to export Queuetip playlists directly.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {spotifyLink ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Linked ✓</div>
                <div className="text-sm text-muted-foreground">
                  As: {spotifyLink.serviceUserId}
                </div>
              </div>
              <Button variant="outline" disabled>
                Linked
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">Not linked.</div>
              <Button onClick={handleLinkSpotify}>
                <ExternalLink className="h-4 w-4 mr-2" /> Link Spotify
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function SettingsPage() {
  return (
    <RequireAuth>
      <SettingsPageContent />
    </RequireAuth>
  );
}

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

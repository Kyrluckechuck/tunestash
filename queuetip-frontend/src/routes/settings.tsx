import { useNavigate, createFileRoute } from "@tanstack/react-router";
import { ExternalLink, LogOut, Music } from "lucide-react";
import { useMutation } from "@apollo/client";

import { RequireAuth } from "@/components/RequireAuth";
import { signOut, useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SignOutEverywhereDocument } from "@/types/generated/graphql";
import { SubsonicConnectionSection } from "@/features/settings/SubsonicConnectionSection";

function SettingsPageContent() {
  const { account } = useMe();
  const navigate = useNavigate();
  const spotifyLink = account?.externalServices.find((l) => l.service === "spotify");
  const [signOutEverywhere, { loading: signingOut }] = useMutation(
    SignOutEverywhereDocument,
  );

  function handleLinkSpotify() {
    // Same-origin: Vite dev proxy (or nginx in prod) forwards /auth to backend.
    // Browser navigation to /auth/spotify/start lands here, gets proxied to the
    // backend, which 302s the user to accounts.spotify.com with a redirect_uri
    // built from X-Forwarded-Host — so it matches whatever origin the user is on.
    const base = (
      import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "/graphql"
    ).replace(/\/graphql\/?$/, "");
    window.location.assign(`${base}/auth/spotify/start`);
  }

  async function handleSignOutEverywhere() {
    await signOutEverywhere();
    await signOut();
    navigate({ to: "/sign-in" });
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

      <SubsonicConnectionSection />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LogOut className="h-5 w-5" /> Session Security
          </CardTitle>
          <CardDescription>
            Sign out of all devices and browsers at once. Your current session
            will also end.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            onClick={handleSignOutEverywhere}
            disabled={signingOut}
          >
            <LogOut className="h-4 w-4 mr-2" /> Sign out everywhere
          </Button>
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

import { useNavigate, createFileRoute } from "@tanstack/react-router";
import { ExternalLink, LogOut, Music } from "lucide-react";
import * as React from "react";
import { useMutation } from "@apollo/client";

import { RequireAuth } from "@/components/RequireAuth";
import { signOut, useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SignOutEverywhereDocument } from "@/types/generated/graphql";
import { SubsonicConnectionSection } from "@/features/settings/SubsonicConnectionSection";
import {
  useOpenAppleLinksInApp,
  useOpenDeezerLinksInApp,
  useOpenSpotifyLinksInApp,
} from "@/lib/link-preferences";
import { isExpiredSpotifyLink } from "@/lib/spotify";

function SettingsPageContent() {
  const { account } = useMe();
  const navigate = useNavigate();
  const [openSpotifyLinksInApp, setOpenSpotifyLinksInApp] = useOpenSpotifyLinksInApp();
  const [openAppleLinksInApp, setOpenAppleLinksInApp] = useOpenAppleLinksInApp();
  const [openDeezerLinksInApp, setOpenDeezerLinksInApp] = useOpenDeezerLinksInApp();
  const spotifyLink = account?.externalServices.find((l) => l.service === "spotify");
  const spotifyExpired = isExpiredSpotifyLink(spotifyLink);
  const [signOutEverywhere, { loading: signingOut }] = useMutation(SignOutEverywhereDocument);
  const [currentPassword, setCurrentPassword] = React.useState("");
  const [newPassword, setNewPassword] = React.useState("");
  const [confirmPassword, setConfirmPassword] = React.useState("");
  const [passwordMessage, setPasswordMessage] = React.useState<string | null>(null);
  const [passwordError, setPasswordError] = React.useState<string | null>(null);
  const [savingPassword, setSavingPassword] = React.useState(false);

  function handleLinkSpotify() {
    // Same-origin: Vite dev proxy (or nginx in prod) forwards /auth to backend.
    // Browser navigation to /auth/spotify/start lands here, gets proxied to the
    // backend, which 302s the user to accounts.spotify.com with a redirect_uri
    // built from X-Forwarded-Host — so it matches whatever origin the user is on.
    const base = (import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "/graphql").replace(
      /\/graphql\/?$/,
      ""
    );
    window.location.assign(`${base}/auth/spotify/start`);
  }

  async function handleSignOutEverywhere() {
    await signOutEverywhere();
    await signOut();
    navigate({ to: "/sign-in" });
  }

  async function handleSetPassword(event: React.FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    setPasswordMessage(null);
    if (newPassword !== confirmPassword) {
      setPasswordError("Passwords do not match.");
      return;
    }
    setSavingPassword(true);
    try {
      const res = await fetch("/auth/password/set", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      if (!res.ok) {
        setPasswordError((await res.text()) || "Could not update password.");
        return;
      }
      setPasswordMessage("Password updated.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } finally {
      setSavingPassword(false);
    }
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
        <CardContent className="space-y-4">
          {spotifyLink && !spotifyExpired ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Linked ✓</div>
                <div className="text-sm text-muted-foreground">As: {spotifyLink.serviceUserId}</div>
              </div>
              <Button variant="outline" disabled>
                Linked
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                {spotifyExpired ? "Authorization expired." : "Not linked."}
              </div>
              <Button onClick={handleLinkSpotify}>
                <ExternalLink className="h-4 w-4 mr-2" /> Link Spotify
              </Button>
            </div>
          )}
          <div className="flex items-center justify-between gap-4 border-t pt-4">
            <label className="text-sm font-medium" htmlFor="open-spotify-links-in-app">
              Open Spotify songs in desktop app
            </label>
            <Switch
              id="open-spotify-links-in-app"
              checked={openSpotifyLinksInApp}
              onCheckedChange={setOpenSpotifyLinksInApp}
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm font-medium" htmlFor="open-apple-links-in-app">
              Open Apple Music links in app
            </label>
            <Switch
              id="open-apple-links-in-app"
              checked={openAppleLinksInApp}
              onCheckedChange={setOpenAppleLinksInApp}
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm font-medium" htmlFor="open-deezer-links-in-app">
              Open Deezer links in app
            </label>
            <Switch
              id="open-deezer-links-in-app"
              checked={openDeezerLinksInApp}
              onCheckedChange={setOpenDeezerLinksInApp}
            />
          </div>
        </CardContent>
      </Card>

      <SubsonicConnectionSection />

      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>
            Set a password for email/password sign-in. Magic links still work.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSetPassword} className="space-y-3">
            <Input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="Current password (if already set)"
            />
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="New password"
              required
            />
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="Confirm new password"
              required
            />
            {passwordError ? <p className="text-sm text-destructive">{passwordError}</p> : null}
            {passwordMessage ? (
              <p className="text-sm text-muted-foreground">{passwordMessage}</p>
            ) : null}
            <Button type="submit" disabled={savingPassword || !newPassword || !confirmPassword}>
              {savingPassword ? "Saving..." : "Update password"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LogOut className="h-5 w-5" /> Session Security
          </CardTitle>
          <CardDescription>
            Sign out of all devices and browsers at once. Your current session will also end.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={handleSignOutEverywhere} disabled={signingOut}>
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

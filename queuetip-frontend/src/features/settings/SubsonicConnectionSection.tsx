import * as React from "react";
import { useMutation, useQuery } from "@apollo/client";
import { CheckCircle2, AlertCircle, Server, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  AddSubsonicConnectionDocument,
  MySubsonicConnectionDocument,
  RemoveSubsonicConnectionDocument,
  TestSubsonicConnectionDocument,
  UpdateSubsonicConnectionDocument,
} from "@/types/generated/graphql";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Subsonic connection management. Users add their own Navidrome/Subsonic
 * server credentials so queuetip can push collaborative playlists into the
 * Subsonic clients they already use (Symfonium, Amperfy, play:Sub, etc).
 *
 * MVP: one connection per account. Adding a second hard-replaces — the
 * backend enforces this via unique_together, and the form below adapts to
 * "edit existing" mode when a connection already exists.
 */
export function SubsonicConnectionSection() {
  const { data, refetch } = useQuery(MySubsonicConnectionDocument, {
    fetchPolicy: "cache-and-network",
  });
  const existing = data?.mySubsonicConnection ?? null;

  const [showForm, setShowForm] = React.useState(false);
  const [label, setLabel] = React.useState("");
  const [serverUrl, setServerUrl] = React.useState("");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");

  const [addConn, { loading: adding }] = useMutation(
    AddSubsonicConnectionDocument,
    { onCompleted: () => refetch() },
  );
  const [updateConn, { loading: updating }] = useMutation(
    UpdateSubsonicConnectionDocument,
    { onCompleted: () => refetch() },
  );
  const [removeConn, { loading: removing }] = useMutation(
    RemoveSubsonicConnectionDocument,
    { onCompleted: () => refetch() },
  );
  const [testConn, { loading: testing }] = useMutation(
    TestSubsonicConnectionDocument,
    { onCompleted: () => refetch() },
  );

  function resetForm() {
    setLabel("");
    setServerUrl("");
    setUsername("");
    setPassword("");
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      if (existing) {
        await updateConn({
          variables: {
            id: existing.id,
            label: label || existing.label,
            serverUrl: serverUrl || existing.serverUrl,
            username: username || existing.username,
            // Only send password when the user typed one; null leaves the
            // stored Fernet-encrypted credential untouched.
            password: password || null,
          },
        });
        toast.success("Subsonic connection updated.");
      } else {
        await addConn({
          variables: {
            label: label || "My Subsonic Server",
            serverUrl,
            username,
            password,
          },
        });
        toast.success("Subsonic connection added.");
      }
      resetForm();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Save failed.";
      toast.error(msg);
    }
  }

  async function handleRemove() {
    if (!existing) return;
    if (!window.confirm("Disconnect this Subsonic server? Existing synced playlists will stop updating.")) return;
    try {
      await removeConn({ variables: { id: existing.id } });
      toast.success("Connection removed.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not remove.";
      toast.error(msg);
    }
  }

  async function handleTest() {
    if (!existing) return;
    try {
      await testConn({ variables: { id: existing.id } });
      toast.success("Connection re-tested.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Test failed.";
      toast.error(msg);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Server className="h-5 w-5" /> Subsonic / Navidrome
        </CardTitle>
        <CardDescription>
          Push your collaborative playlists into your own Subsonic-compatible
          server so they appear in your existing client (Symfonium, Amperfy,
          play:Sub, etc).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {existing && !showForm ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium truncate">{existing.label}</div>
                <div className="text-sm text-muted-foreground truncate">
                  {existing.serverUrl} · {existing.username}
                </div>
              </div>
              <ConnectionStatusBadge
                status={existing.verificationStatus}
                error={existing.verificationError ?? null}
              />
            </div>
            {existing.opensubsonicExtensions.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                OpenSubsonic detected · {existing.opensubsonicExtensions.length}{" "}
                extension{existing.opensubsonicExtensions.length === 1 ? "" : "s"}{" "}
                advertised (better track matching available).
              </p>
            ) : null}
            {existing.verificationError ? (
              <Alert variant="destructive">
                <AlertDescription>{existing.verificationError}</AlertDescription>
              </Alert>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={handleTest}
                disabled={testing}
                size="sm"
              >
                {testing ? "Testing…" : "Test connection"}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setLabel(existing.label);
                  setServerUrl(existing.serverUrl);
                  setUsername(existing.username);
                  setPassword("");
                  setShowForm(true);
                }}
                size="sm"
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                onClick={handleRemove}
                disabled={removing}
                size="sm"
              >
                <Trash2 className="h-4 w-4 mr-1" /> Remove
              </Button>
            </div>
          </div>
        ) : showForm ? (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="sub-label">Label</Label>
              <Input
                id="sub-label"
                placeholder="Home Navidrome"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sub-url">Server URL</Label>
              <Input
                id="sub-url"
                type="url"
                placeholder="https://navidrome.example.com"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                required={!existing}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sub-user">Username</Label>
              <Input
                id="sub-user"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required={!existing}
                autoComplete="username"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sub-pass">
                Password{existing ? " (leave blank to keep current)" : ""}
              </Label>
              <Input
                id="sub-pass"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required={!existing}
                autoComplete="current-password"
              />
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={adding || updating}>
                {existing
                  ? updating
                    ? "Saving…"
                    : "Save"
                  : adding
                    ? "Adding…"
                    : "Add connection"}
              </Button>
              <Button type="button" variant="ghost" onClick={resetForm}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button onClick={() => setShowForm(true)}>
            <Server className="h-4 w-4 mr-2" /> Add Subsonic connection
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function ConnectionStatusBadge({
  status,
  error,
}: {
  status: string;
  error: string | null;
}) {
  if (status === "ok") {
    return (
      <Badge variant="default" className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> Verified
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1" title={error ?? undefined}>
        <AlertCircle className="h-3 w-3" /> Failed
      </Badge>
    );
  }
  return <Badge variant="secondary">Not verified</Badge>;
}

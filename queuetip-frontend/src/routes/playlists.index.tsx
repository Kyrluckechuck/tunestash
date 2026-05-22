import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@apollo/client";
import { Plus, UserPlus } from "lucide-react";
import { toast } from "sonner";

import {
  InviteToQueuetipDocument,
  MyInviteesDocument,
  MyPlaylistsDocument,
  RemoveQueuetipInviteDocument,
} from "@/types/generated/graphql";
import { X } from "lucide-react";
import { useMe } from "@/lib/auth";
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

      <AdminInviteCard />

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

function AdminInviteCard() {
  const { account } = useMe();
  const [email, setEmail] = React.useState("");
  const refetchInvitees = { refetchQueries: [{ query: MyInviteesDocument }] };
  const [invite, { loading }] = useMutation(InviteToQueuetipDocument, refetchInvitees);
  const [remove] = useMutation(RemoveQueuetipInviteDocument, refetchInvitees);
  const { data } = useQuery(MyInviteesDocument, {
    skip: !account?.isAdmin,
  });

  if (!account?.isAdmin) return null;

  async function handleInvite() {
    try {
      const r = await invite({ variables: { email } });
      const res = r.data?.inviteToQueuetip;
      if (res?.sent) {
        toast.success(res.message);
        setEmail("");
      } else {
        toast.error(res?.message ?? "Could not invite.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not invite.");
    }
  }

  async function handleRemove(targetEmail: string) {
    if (!confirm(`Remove ${targetEmail} from the allowlist?`)) return;
    try {
      const r = await remove({ variables: { email: targetEmail } });
      const res = r.data?.removeQueuetipInvite;
      if (res?.sent) toast.success(res.message);
      else toast.error(res?.message ?? "Could not remove.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove.");
    }
  }

  const invitees = data?.myInvitees ?? [];

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <UserPlus className="h-4 w-4" /> Invite someone to Queuetip
        </CardTitle>
        <CardDescription>Allowlists the email and sends them a sign-up invite.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="friend@example.com"
            className="flex-1 px-3 py-1.5 text-sm bg-background border border-input rounded-md"
          />
          <Button onClick={handleInvite} disabled={loading || !email.trim()}>
            {loading ? "Inviting…" : "Send invite"}
          </Button>
        </div>
        {invitees.length > 0 ? (
          <ul className="divide-y divide-border border border-border rounded-md">
            {invitees.map((iv) => (
              <li
                key={iv.email}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <span className="truncate">
                  <span className="font-mono">{iv.email}</span>
                  <span
                    className={`ml-2 text-xs ${
                      iv.hasSignedUp ? "text-green-500" : "text-muted-foreground"
                    }`}
                  >
                    {iv.hasSignedUp ? "Joined" : "Pending"}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemove(iv.email)}
                  aria-label={`Remove ${iv.email}`}
                  title="Remove from allowlist"
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

export const Route = createFileRoute("/playlists/")({
  component: PlaylistsIndex,
});

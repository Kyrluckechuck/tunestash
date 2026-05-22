import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery } from "@apollo/client";
import { toast } from "sonner";

import {
  JoinPlaylistDocument,
  PlaylistByInviteTokenDocument,
} from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MemberList } from "@/features/playlist/MemberList";

export function JoinPage() {
  const { token } = Route.useParams();
  const router = useRouter();
  const { account } = useMe();
  const { data, loading } = useQuery(PlaylistByInviteTokenDocument, {
    variables: { token },
  });
  const [join, { loading: joining }] = useMutation(JoinPlaylistDocument);

  if (loading) {
    return <p className="container py-8 text-muted-foreground">Loading…</p>;
  }

  const playlist = data?.playlistByInviteToken;
  if (!playlist) {
    return (
      <div className="container py-8">
        <Card>
          <CardHeader>
            <CardTitle>Invalid invite link</CardTitle>
            <CardDescription>
              This link is invalid or the playlist no longer exists.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const alreadyMember = account
    ? playlist.members.some((m) => m.account.id === account.id)
    : false;

  async function handleJoin() {
    try {
      const { data: joined } = await join({ variables: { token } });
      if (joined?.joinPlaylist.id) {
        toast.success("Joined!");
        await router.navigate({
          to: "/playlists/$id",
          params: { id: joined.joinPlaylist.id },
        });
      }
    } catch {
      toast.error("Could not join.");
    }
  }

  return (
    <div className="container max-w-xl py-8">
      <Card>
        <CardHeader>
          <CardTitle>{playlist.name}</CardTitle>
          {playlist.description ? (
            <CardDescription>{playlist.description}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="text-sm font-medium mb-2">Members</h3>
            <MemberList
              members={playlist.members}
              currentAccountId={account?.id ?? ""}
            />
          </div>
          {!account ? (
            <Link to="/sign-in" search={{ next: `/join/${token}` }}>
              <Button className="w-full">Sign in to join</Button>
            </Link>
          ) : alreadyMember ? (
            <Link to="/playlists/$id" params={{ id: playlist.id }}>
              <Button className="w-full" variant="secondary">
                Open playlist
              </Button>
            </Link>
          ) : (
            <Button className="w-full" onClick={handleJoin} disabled={joining}>
              {joining ? "Joining…" : "Join playlist"}
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export const Route = createFileRoute("/join/$token")({
  component: JoinPage,
});

import * as React from "react";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";

function Home() {
  const { account, loading } = useMe();

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("spotify_linked") === "1") {
      toast.success("Spotify linked!");
      params.delete("spotify_linked");
      const newSearch = params.toString();
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (newSearch ? `?${newSearch}` : ""),
      );
    }
  }, []);

  if (loading) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (account) return <Navigate to={"/playlists" as any} />;
  return (
    <div className="container py-16 text-center space-y-6">
      <h1 className="text-4xl font-bold tracking-tight">Queuetip</h1>
      <p className="text-lg text-muted-foreground max-w-prose mx-auto">
        Build a playlist with your friends. Add songs, vote, export the mix.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link to="/sign-in">
          <Button size="lg">Sign in</Button>
        </Link>
        <Link to="/sign-up">
          <Button size="lg" variant="outline">
            Sign up
          </Button>
        </Link>
      </div>
    </div>
  );
}

export const Route = createFileRoute("/")({
  component: Home,
});

import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { useMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";

function Home() {
  const { account, loading } = useMe();
  if (loading) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (account) return <Navigate to={"/playlists" as any} />;
  return (
    <div className="container py-16 text-center space-y-6">
      <h1 className="text-4xl font-bold tracking-tight">Queuetip</h1>
      <p className="text-lg text-muted-foreground max-w-prose mx-auto">
        Build a playlist with your friends. Add songs, vote, export the mix.
      </p>
      <div className="flex justify-center gap-3">
        <Link to="/sign-in">
          <Button size="lg">Sign up or sign in</Button>
        </Link>
      </div>
    </div>
  );
}

export const Route = createFileRoute("/")({
  component: Home,
});

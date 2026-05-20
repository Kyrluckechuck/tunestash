import { Link, Outlet, useRouter } from "@tanstack/react-router";
import { useMe, signOut } from "@/lib/auth";
import { Button } from "@/components/ui/button";

export function Layout() {
  const { account, loading, refetch } = useMe();
  const router = useRouter();

  async function handleSignOut() {
    await signOut();
    await refetch();
    await router.navigate({ to: "/" });
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/" className="font-bold text-lg">Queuetip</Link>
          <nav className="flex items-center gap-2">
            {loading ? null : account ? (
              <>
                <span className="hidden sm:inline text-sm text-muted-foreground">
                  {account.displayName}
                </span>
                <Link to="/settings">
                  <Button variant="ghost" size="sm">Settings</Button>
                </Link>
                <Button variant="outline" size="sm" onClick={handleSignOut}>
                  Sign out
                </Button>
              </>
            ) : (
              <Link to="/sign-in">
                <Button variant="default" size="sm">Sign in</Button>
              </Link>
            )}
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}

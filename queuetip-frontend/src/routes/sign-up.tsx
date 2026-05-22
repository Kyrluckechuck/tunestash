import * as React from "react";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { useMutation } from "@apollo/client";

import { RequestMagicLinkDocument } from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { usePublicSettings } from "@/lib/public-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MagicLinkSuccess } from "@/features/auth/MagicLinkSuccess";

export function SignUpPage() {
  const { next } = Route.useSearch();
  const { account, loading: meLoading } = useMe();
  const [email, setEmail] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [sent, setSent] = React.useState<{ message: string } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const { signupAllowlistEnforced } = usePublicSettings();

  const [requestMagicLink, { loading }] = useMutation(RequestMagicLinkDocument);

  // Already authenticated → no point asking them to sign up again. Honour
  // `next` if present so deep-link returns work; otherwise the dashboard.
  if (meLoading) return null;
  if (account) {
    const destination = next ?? "/playlists";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return <Navigate to={destination as any} replace />;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const result = await requestMagicLink({
        variables: { email, displayName },
      });
      const payload = result.data?.requestMagicLink;
      if (!payload) {
        setError("Something went wrong. Please try again.");
        return;
      }
      if (payload.sent) {
        setSent({ message: payload.message });
      } else {
        setError(payload.message);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setError(message);
    }
  }

  if (sent) {
    return (
      <MagicLinkSuccess
        message={sent.message}
        next={next}
        onReset={() => {
          setSent(null);
          setError(null);
        }}
      />
    );
  }

  return (
    <div className="container max-w-md py-16">
      <Card>
        <CardHeader>
          <CardTitle>Sign up for Queuetip</CardTitle>
          <CardDescription>
            Pick a display name your friends will see, then we&apos;ll email you a
            one-time link to confirm.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {signupAllowlistEnforced && (
              <Alert variant="default">
                <AlertDescription>
                  Sign-ups are currently invite-only. Make sure your email has
                  been approved by the operator — if it hasn&apos;t, you
                  won&apos;t receive a sign-in link even after submitting.
                </AlertDescription>
              </Alert>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                required
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="displayName">Display name</Label>
              <Input
                id="displayName"
                type="text"
                value={displayName}
                required
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="nickname"
              />
            </div>
            {error ? (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
            <p className="text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link
                to="/sign-in"
                search={next ? { next } : undefined}
                className="underline hover:text-foreground"
              >
                Sign in instead
              </Link>
            </p>
          </CardContent>
          <CardFooter className="flex justify-between">
            <Link to="/" className="text-sm text-muted-foreground hover:underline">
              Back home
            </Link>
            <Button
              type="submit"
              disabled={loading || !email || !displayName.trim()}
            >
              {loading ? "Sending..." : "Create account"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}

export const Route = createFileRoute("/sign-up")({
  component: SignUpPage,
  validateSearch: (search: Record<string, unknown>): { next?: string } => ({
    next: typeof search.next === "string" ? search.next : undefined,
  }),
});

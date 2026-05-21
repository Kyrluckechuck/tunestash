import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@apollo/client";

import { RequestMagicLinkDocument } from "@/types/generated/graphql";
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
  const [email, setEmail] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [sent, setSent] = React.useState<{ message: string } | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const [requestMagicLink, { loading }] = useMutation(RequestMagicLinkDocument);

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

import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@apollo/client";
import { CheckCircle2 } from "lucide-react";
import { ExternalLink } from "lucide-react";

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

export function SignInPage() {
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
        variables: { email, displayName: displayName || null },
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
      <div className="container max-w-md py-16">
        <Card>
          <CardHeader>
            <CheckCircle2 className="h-10 w-10 text-green-600" />
            <CardTitle>Check your email</CardTitle>
            <CardDescription>{sent.message}</CardDescription>
          </CardHeader>
          <CardFooter className="flex flex-col items-start gap-3">
            {next ? (
              <p className="text-sm text-muted-foreground flex items-center gap-1">
                <ExternalLink className="h-3 w-3 shrink-0" />
                After signing in, return to:{" "}
                <a href={next} className="underline hover:text-foreground break-all">
                  {next}
                </a>
              </p>
            ) : null}
            <Button
              variant="ghost"
              onClick={() => {
                setSent(null);
                setError(null);
              }}
            >
              Use a different email
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="container max-w-md py-16">
      <Card>
        <CardHeader>
          <CardTitle>Sign in to Queuetip</CardTitle>
          <CardDescription>
            We&apos;ll email you a one-time sign-in link. New here? Enter a
            display name to sign up at the same time.
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
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="displayName">Display name (new accounts)</Label>
              <Input
                id="displayName"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="nickname"
              />
            </div>
            {error ? (
              <p className="text-sm text-destructive" role="alert">{error}</p>
            ) : null}
          </CardContent>
          <CardFooter className="flex justify-between">
            <Link to="/" className="text-sm text-muted-foreground hover:underline">
              Back home
            </Link>
            <Button type="submit" disabled={loading || !email}>
              {loading ? "Sending..." : "Send sign-in link"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}

export const Route = createFileRoute("/sign-in")({
  component: SignInPage,
  validateSearch: (search: Record<string, unknown>): { next?: string } => ({
    next: typeof search.next === "string" ? search.next : undefined,
  }),
});

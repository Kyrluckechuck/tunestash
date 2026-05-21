import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@apollo/client";

import { RequestMagicLinkDocument } from "@/types/generated/graphql";
import { usePublicSettings } from "@/lib/public-settings";
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

export function SignInPage() {
  const { next } = Route.useSearch();
  const [email, setEmail] = React.useState("");
  const [sent, setSent] = React.useState<{ message: string } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const { signupAllowlistEnforced } = usePublicSettings();

  const [requestMagicLink, { loading }] = useMutation(RequestMagicLinkDocument);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      // Sign-in path — never sends a display name. Unknown emails get a neutral
      // response from the backend that points the user at the sign-up page.
      const result = await requestMagicLink({
        variables: { email, displayName: null },
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
          <CardTitle>Sign in to Queuetip</CardTitle>
          <CardDescription>
            We&apos;ll email you a one-time sign-in link.
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
            {error ? (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
            <p className="text-sm text-muted-foreground">
              New here?{" "}
              <Link
                to="/sign-up"
                search={next ? { next } : undefined}
                className="underline hover:text-foreground"
              >
                Sign up
              </Link>
              {signupAllowlistEnforced && " — invite-only during rollout."}
            </p>
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

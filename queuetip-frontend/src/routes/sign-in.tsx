import * as React from "react";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { useMutation } from "@apollo/client";

import { RequestMagicLinkDocument } from "@/types/generated/graphql";
import { useMe } from "@/lib/auth";
import { usePublicSettings } from "@/lib/public-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  const { next, resetToken } = Route.useSearch();
  const { account, loading: meLoading } = useMe();
  const [email, setEmail] = React.useState("");
  const [codeEmail, setCodeEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [passwordEmail, setPasswordEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [sent, setSent] = React.useState<{ message: string } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [codeError, setCodeError] = React.useState<string | null>(null);
  const [passwordError, setPasswordError] = React.useState<string | null>(null);
  const [resetMessage, setResetMessage] = React.useState<string | null>(null);
  const [loadingCode, setLoadingCode] = React.useState(false);
  const [loadingPassword, setLoadingPassword] = React.useState(false);
  const [loadingReset, setLoadingReset] = React.useState(false);
  const [resetPassword, setResetPassword] = React.useState("");
  const [resetConfirm, setResetConfirm] = React.useState("");
  const [resetPasswordError, setResetPasswordError] = React.useState<string | null>(null);
  const [resetPasswordDone, setResetPasswordDone] = React.useState(false);
  const [tab, setTab] = React.useState("magic");
  const { signupAllowlistEnforced } = usePublicSettings();

  const [requestMagicLink, { loading }] = useMutation(RequestMagicLinkDocument);

  React.useEffect(() => {
    if (!resetPasswordDone) return;
    const id = window.setTimeout(() => {
      window.location.assign(next ?? "/playlists");
    }, 300);
    return () => window.clearTimeout(id);
  }, [next, resetPasswordDone]);

  // Already authenticated → skip the form entirely. Honour `next` if present
  // (e.g. user followed an Apollo 401-redirect from a deep link) so they end
  // up where they were trying to go, not generically on the dashboard.
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

  async function handleCodeLogin(event: React.FormEvent) {
    event.preventDefault();
    setCodeError(null);
    setLoadingCode(true);
    try {
      const res = await fetch("/auth/code-login", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: codeEmail, code }),
      });
      if (!res.ok) {
        setCodeError("Invalid or expired code.");
        return;
      }
      window.location.assign(next ?? "/playlists");
    } finally {
      setLoadingCode(false);
    }
  }

  async function handlePasswordLogin(event: React.FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    setLoadingPassword(true);
    try {
      const res = await fetch("/auth/password-login", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: passwordEmail, password }),
      });
      if (!res.ok) {
        setPasswordError("Incorrect email or password.");
        return;
      }
      window.location.assign(next ?? "/playlists");
    } finally {
      setLoadingPassword(false);
    }
  }

  async function handleRequestReset() {
    setResetMessage(null);
    setLoadingReset(true);
    try {
      await fetch("/auth/password/request-reset", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: passwordEmail }),
      });
      setResetMessage("If an account exists for that email, a reset link was sent.");
    } finally {
      setLoadingReset(false);
    }
  }

  async function handleResetPassword(event: React.FormEvent) {
    event.preventDefault();
    setResetPasswordError(null);
    if (!resetToken) {
      setResetPasswordError("Missing reset token.");
      return;
    }
    if (resetPassword !== resetConfirm) {
      setResetPasswordError("Passwords do not match.");
      return;
    }
    setLoadingReset(true);
    try {
      const res = await fetch("/auth/password/reset", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token: resetToken, newPassword: resetPassword }),
      });
      if (!res.ok) {
        setResetPasswordError((await res.text()) || "Could not reset password.");
        return;
      }
      setResetPasswordDone(true);
    } finally {
      setLoadingReset(false);
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

  if (resetToken) {
    return (
      <div className="container max-w-md py-16">
        <Card>
          <CardHeader>
            <CardTitle>Reset password</CardTitle>
            <CardDescription>Choose a new password for your account.</CardDescription>
          </CardHeader>
          <form onSubmit={handleResetPassword}>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="resetPassword">New password</Label>
                <Input
                  id="resetPassword"
                  type="password"
                  value={resetPassword}
                  onChange={(e) => setResetPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="resetConfirm">Confirm password</Label>
                <Input
                  id="resetConfirm"
                  type="password"
                  value={resetConfirm}
                  onChange={(e) => setResetConfirm(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </div>
              {resetPasswordError ? (
                <p className="text-sm text-destructive">{resetPasswordError}</p>
              ) : null}
              {resetPasswordDone ? (
                <p className="text-sm text-muted-foreground">
                  Password reset complete. Reloading your account...
                </p>
              ) : null}
            </CardContent>
            <CardFooter className="flex items-center justify-between">
              <Link to="/sign-in" className="text-sm text-muted-foreground hover:underline">
                Back to sign-in
              </Link>
              <Button
                type="submit"
                disabled={loadingReset || !resetPassword || !resetConfirm || resetPasswordDone}
              >
                {loadingReset ? "Saving..." : "Set new password"}
              </Button>
            </CardFooter>
          </form>
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
            We&apos;ll email you a one-time sign-in link.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
            <Tabs value={tab} onValueChange={setTab} className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="magic">Magic Link</TabsTrigger>
                <TabsTrigger value="code">Code</TabsTrigger>
                <TabsTrigger value="password">Password</TabsTrigger>
              </TabsList>
              <TabsContent value="magic">
                <form onSubmit={handleSubmit} className="space-y-3">
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
                  <Button type="submit" disabled={loading || !email}>
                    {loading ? "Sending..." : "Send sign-in link"}
                  </Button>
                </form>
              </TabsContent>
              <TabsContent value="code" className="space-y-3">
                <form onSubmit={handleCodeLogin} className="space-y-3">
                  <div className="space-y-2">
                    <Label htmlFor="codeEmail">Email</Label>
                    <Input
                      id="codeEmail"
                      type="email"
                      value={codeEmail}
                      required
                      onChange={(e) => setCodeEmail(e.target.value)}
                      autoComplete="email"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="code">Sign-In Code</Label>
                    <Input
                      id="code"
                      type="text"
                      value={code}
                      required
                      onChange={(e) => setCode(e.target.value)}
                      autoComplete="one-time-code"
                    />
                  </div>
                  {codeError ? <p className="text-sm text-destructive">{codeError}</p> : null}
                  <Button type="submit" disabled={loadingCode || !codeEmail || !code}>
                    {loadingCode ? "Signing in..." : "Sign in with code"}
                  </Button>
                </form>
              </TabsContent>
              <TabsContent value="password" className="space-y-3">
                <form onSubmit={handlePasswordLogin} className="space-y-3">
                  <div className="space-y-2">
                    <Label htmlFor="passwordEmail">Email</Label>
                    <Input
                      id="passwordEmail"
                      type="email"
                      value={passwordEmail}
                      required
                      onChange={(e) => setPasswordEmail(e.target.value)}
                      autoComplete="email"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="password">Password</Label>
                    <Input
                      id="password"
                      type="password"
                      value={password}
                      required
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="current-password"
                    />
                  </div>
                  {passwordError ? (
                    <p className="text-sm text-destructive">{passwordError}</p>
                  ) : null}
                  {resetMessage ? (
                    <p className="text-sm text-muted-foreground">{resetMessage}</p>
                  ) : null}
                  <div className="flex items-center gap-3">
                    <Button type="submit" disabled={loadingPassword || !passwordEmail || !password}>
                      {loadingPassword ? "Signing in..." : "Sign in with password"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={loadingReset || !passwordEmail}
                      onClick={handleRequestReset}
                    >
                      {loadingReset ? "Sending..." : "Forgot password"}
                    </Button>
                  </div>
                </form>
              </TabsContent>
            </Tabs>
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
          </CardFooter>
      </Card>
    </div>
  );
}

export const Route = createFileRoute("/sign-in")({
  component: SignInPage,
  validateSearch: (search: Record<string, unknown>): { next?: string; resetToken?: string } => ({
    next: typeof search.next === "string" ? search.next : undefined,
    resetToken: typeof search.resetToken === "string" ? search.resetToken : undefined,
  }),
});

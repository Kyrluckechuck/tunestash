import * as React from "react";
import { Navigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";

import { useMe } from "@/lib/auth";

type Props = { children: React.ReactNode };

export function RequireAuth({ children }: Props) {
  const { account, loading } = useMe();

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!account) {
    return <Navigate to="/sign-in" />;
  }

  return <>{children}</>;
}

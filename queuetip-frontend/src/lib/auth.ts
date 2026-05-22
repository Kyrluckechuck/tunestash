import { useQuery } from "@apollo/client";
import { MeDocument } from "@/types/generated/graphql";

export function useMe() {
  const { data, loading, refetch } = useQuery(MeDocument, {
    fetchPolicy: "cache-and-network",
  });
  return { account: data?.me ?? null, loading, refetch };
}

export async function signOut(): Promise<void> {
  // Same-origin: Vite dev proxy (or nginx in prod) forwards /auth to backend.
  const base = (import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "/graphql").replace(
    /\/graphql\/?$/,
    "",
  );
  await fetch(`${base}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

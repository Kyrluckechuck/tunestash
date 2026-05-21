import { useQuery } from "@apollo/client";
import { MeDocument } from "@/types/generated/graphql";

export function useMe() {
  const { data, loading, refetch } = useQuery(MeDocument, {
    fetchPolicy: "cache-and-network",
  });
  return { account: data?.me ?? null, loading, refetch };
}

export async function signOut(): Promise<void> {
  const url = (import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "http://localhost:5050/graphql")
    .replace(/\/graphql\/?$/, "");
  await fetch(`${url}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

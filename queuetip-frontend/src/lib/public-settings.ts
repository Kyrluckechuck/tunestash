import { useQuery } from "@apollo/client";
import { PublicSettingsDocument } from "@/types/generated/graphql";

export function usePublicSettings(): {
  signupAllowlistEnforced: boolean;
  loading: boolean;
} {
  const { data, loading } = useQuery(PublicSettingsDocument, {
    fetchPolicy: "cache-first",
  });
  return {
    signupAllowlistEnforced: data?.publicSettings.signupAllowlistEnforced ?? true,
    loading,
  };
}

import { useState, useMemo, useCallback } from 'react';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GetUnlinkedArtistsDocument,
  LinkArtistToDeezerDocument,
} from '../types/generated/graphql';
import { useDebouncedSearch } from './useDebouncedSearch';
import { useToast } from '../components/ui/useToast';

export function useDeezerLinkingSection() {
  const [searchQuery, setSearchQuery] = useState('');
  const [hasDownloadsFilter, setHasDownloadsFilter] = useState<
    boolean | undefined
  >(undefined);
  const pageSize = 50;

  const { debouncedTerm, handleSearchChange, searchTerm } =
    useDebouncedSearch(setSearchQuery);

  const toast = useToast();

  const variables = useMemo(
    () => ({
      first: pageSize,
      search: debouncedTerm || undefined,
      hasDownloads: hasDownloadsFilter,
    }),
    [pageSize, debouncedTerm, hasDownloadsFilter]
  );

  const { data, loading, error, fetchMore } = useQuery(
    GetUnlinkedArtistsDocument,
    { variables }
  );

  const artists = data?.unlinkedArtists?.edges ?? [];
  const pageInfo = data?.unlinkedArtists?.pageInfo;
  const totalCount = data?.unlinkedArtists?.totalCount ?? 0;

  const [linkMutation] = useMutation(LinkArtistToDeezerDocument, {
    refetchQueries: [{ query: GetUnlinkedArtistsDocument, variables }],
  });

  const handleLink = useCallback(
    async (artistId: number, deezerId: number) => {
      try {
        const { data: result } = await linkMutation({
          variables: { artistId, deezerId },
        });
        if (result?.linkArtistToDeezer.success) {
          toast.success(result.linkArtistToDeezer.message);
        } else {
          toast.error(
            result?.linkArtistToDeezer.message ?? 'Failed to link artist'
          );
        }
        return result?.linkArtistToDeezer ?? null;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Failed to link artist');
        return null;
      }
    },
    [linkMutation, toast]
  );

  const handleLoadMore = useCallback(() => {
    if (!pageInfo?.hasNextPage || !pageInfo.endCursor) return;
    fetchMore({
      variables: { ...variables, after: pageInfo.endCursor },
    });
  }, [fetchMore, pageInfo, variables]);

  return {
    artists,
    totalCount,
    pageInfo,
    loading,
    error,

    searchTerm,
    searchQuery,
    handleSearchChange,
    hasDownloadsFilter,
    setHasDownloadsFilter,

    handleLink,
    handleLoadMore,
  };
}

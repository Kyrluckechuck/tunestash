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
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const { debouncedTerm, handleSearchChange, searchTerm } =
    useDebouncedSearch(setSearchQuery);

  const toast = useToast();

  const variables = useMemo(
    () => ({
      page,
      pageSize,
      search: debouncedTerm || undefined,
      hasDownloads: hasDownloadsFilter,
    }),
    [page, pageSize, debouncedTerm, hasDownloadsFilter]
  );

  const { data, loading, error } = useQuery(GetUnlinkedArtistsDocument, {
    variables,
  });

  const artists = data?.unlinkedArtists?.items ?? [];
  const totalCount = data?.unlinkedArtists?.pageInfo?.totalCount ?? 0;
  const totalPages = data?.unlinkedArtists?.pageInfo?.totalPages ?? 1;

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

  const handleSearchWithReset = useCallback(
    (query: string) => {
      handleSearchChange(query);
      setPage(1);
    },
    [handleSearchChange]
  );

  const handleHasDownloadsFilterChange = useCallback(
    (value: boolean | undefined) => {
      setHasDownloadsFilter(value);
      setPage(1);
    },
    []
  );

  return {
    artists,
    totalCount,
    totalPages,
    loading,
    error,

    page,
    setPage,

    searchTerm,
    searchQuery,
    handleSearchChange: handleSearchWithReset,
    hasDownloadsFilter,
    setHasDownloadsFilter: handleHasDownloadsFilterChange,

    handleLink,
  };
}

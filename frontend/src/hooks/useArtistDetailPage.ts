import { useState, useMemo, useCallback } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetArtistDocument,
  GetAlbumsDocument,
  GetSongsDocument,
  UpdateArtistDocument,
  SyncArtistDocument,
  DownloadArtistDocument,
  SetAlbumWantedDocument,
  DownloadAlbumDocument,
  CheckArtistMetadataDocument,
  CheckAlbumMetadataDocument,
  type Album,
  type Song,
} from '../types/generated/graphql';
import { useToast } from '../components/ui/useToast';
import { useMutationState, useMutationLoadingState } from './useMutationState';
import { useRequestState } from './useRequestState';
import type { AlbumSortField } from '../components/albums/AlbumsTable';
import type { SortField as SongSortField } from '../components/songs/SongsTable';
import type {
  SortDirection,
  WantedFilter,
  DownloadFilter,
} from '../types/shared';

interface UseArtistDetailPageOptions {
  artistId: string;
}

export function useArtistDetailPage({ artistId }: UseArtistDetailPageOptions) {
  const toast = useToast();

  // Albums state
  const [albumWantedFilter, setAlbumWantedFilter] =
    useState<WantedFilter>('all');
  const [albumDownloadFilter, setAlbumDownloadFilter] =
    useState<DownloadFilter>('all');
  const [albumPage, setAlbumPage] = useState(1);
  const [albumPageSize, setAlbumPageSize] = useState(50);
  const [albumSortField, setAlbumSortField] = useState<AlbumSortField>(null);
  const [albumSortDirection, setAlbumSortDirection] =
    useState<SortDirection>('asc');
  const [albumSearchQuery, setAlbumSearchQuery] = useState('');

  // Songs state
  const [songDownloadFilter, setSongDownloadFilter] =
    useState<DownloadFilter>('all');
  const [songPage, setSongPage] = useState(1);
  const [songPageSize, setSongPageSize] = useState(50);
  const [songSortField, setSongSortField] = useState<SongSortField>(null);
  const [songSortDirection, setSongSortDirection] =
    useState<SortDirection>('asc');
  const [songSearchQuery, setSongSearchQuery] = useState('');

  // Fetch artist details
  const {
    data: artistData,
    error: artistError,
    networkStatus: artistNetworkStatus,
  } = useQuery(GetArtistDocument, {
    variables: { id: artistId },
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  // Albums query variables
  const albumQueryVariables = useMemo(
    () => ({
      artistId: parseInt(artistId, 10),
      wanted:
        albumWantedFilter === 'all'
          ? undefined
          : albumWantedFilter === 'wanted',
      downloaded:
        albumDownloadFilter === 'all'
          ? undefined
          : albumDownloadFilter === 'downloaded',
      page: albumPage,
      pageSize: albumPageSize,
      sortBy: albumSortField,
      sortDirection: albumSortDirection,
      search: albumSearchQuery || undefined,
    }),
    [
      artistId,
      albumWantedFilter,
      albumDownloadFilter,
      albumPage,
      albumPageSize,
      albumSortField,
      albumSortDirection,
      albumSearchQuery,
    ]
  );

  // Fetch albums for this artist
  const {
    data: albumsData,
    loading: albumsLoading,
    networkStatus: albumsNetworkStatus,
  } = useQuery(GetAlbumsDocument, {
    variables: albumQueryVariables,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  // Songs query variables
  const songQueryVariables = useMemo(
    () => ({
      artistId: parseInt(artistId, 10),
      downloaded:
        songDownloadFilter === 'all'
          ? undefined
          : songDownloadFilter === 'downloaded',
      page: songPage,
      pageSize: songPageSize,
      sortBy: songSortField,
      sortDirection: songSortDirection,
      search: songSearchQuery || undefined,
    }),
    [
      artistId,
      songDownloadFilter,
      songPage,
      songPageSize,
      songSortField,
      songSortDirection,
      songSearchQuery,
    ]
  );

  // Fetch songs for this artist
  const {
    data: songsData,
    loading: songsLoading,
    networkStatus: songsNetworkStatus,
  } = useQuery(GetSongsDocument, {
    variables: songQueryVariables,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  // Mutations
  const [updateArtist] = useMutation(UpdateArtistDocument);
  const [syncArtist] = useMutation(SyncArtistDocument);
  const [downloadArtist] = useMutation(DownloadArtistDocument);
  const [setAlbumWanted] = useMutation(SetAlbumWantedDocument);
  const [downloadAlbum] = useMutation(DownloadAlbumDocument);
  const [checkArtistMetadata] = useMutation(CheckArtistMetadataDocument);
  const [checkAlbumMetadata] = useMutation(CheckAlbumMetadataDocument);

  // Mutation state management
  const {
    mutatingIds: albumMutatingIds,
    pulseIds: albumPulseIds,
    handleMutation: handleAlbumMutation,
  } = useMutationState();
  const {
    loadingIds: syncMutatingIds,
    startLoading: startSync,
    stopLoading: stopSync,
  } = useMutationLoadingState();
  const {
    loadingIds: downloadMutatingIds,
    startLoading: startDownload,
    stopLoading: stopDownload,
  } = useMutationLoadingState();
  const {
    loadingIds: checkMetadataMutatingIds,
    startLoading: startCheckMetadata,
    stopLoading: stopCheckMetadata,
  } = useMutationLoadingState();

  // Artist action handlers
  const handleTrackingTierChange = async (tier: number) => {
    const artist = artistData?.artist;
    if (!artist) return;

    try {
      await updateArtist({
        variables: {
          input: { artistId: artist.id.toString(), trackingTier: tier },
        },
      });
      const tierLabel =
        tier === 2 ? 'Favourite' : tier === 1 ? 'Tracked' : 'Untracked';
      toast.success(`Artist set to ${tierLabel}`);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to update tracking'
      );
    }
  };

  const handleSyncArtist = async () => {
    const artist = artistData?.artist;
    if (!artist) return;

    try {
      startSync(artist.id);
      await syncArtist({ variables: { artistId: artist.id.toString() } });
      toast.success('Artist sync started');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Sync failed');
    } finally {
      stopSync(artist.id);
    }
  };

  const handleDownloadArtist = async () => {
    const artist = artistData?.artist;
    if (!artist) return;

    try {
      startDownload(artist.id);
      const result = await downloadArtist({
        variables: { artistId: artist.id.toString() },
      });
      if (result.data?.downloadArtist?.success) {
        toast.success('Artist download started');
      } else {
        toast.error(result.data?.downloadArtist?.message || 'Download failed');
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Download failed');
    } finally {
      stopDownload(artist.id);
    }
  };

  const handleCheckArtistMetadata = async () => {
    const artist = artistData?.artist;
    if (!artist) return;

    try {
      startCheckMetadata(artist.id);
      const result = await checkArtistMetadata({
        variables: { artistId: artist.id },
      });
      const data = result.data?.checkArtistMetadata;
      if (data?.success) {
        if (data.changeDetected) {
          toast.success(
            `Change detected: "${data.oldValue}" → "${data.newValue}". Check the Metadata Changes tab.`
          );
        } else {
          toast.info('No metadata changes detected');
        }
      } else {
        toast.error(data?.message || 'Failed to check metadata');
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Metadata check failed'
      );
    } finally {
      stopCheckMetadata(artist.id);
    }
  };

  const handleCheckAlbumMetadata = async (albumId: number) => {
    try {
      startCheckMetadata(albumId);
      const result = await checkAlbumMetadata({
        variables: { albumId },
      });
      const data = result.data?.checkAlbumMetadata;
      if (data?.success) {
        if (data.changeDetected) {
          toast.success(
            `Change detected: "${data.oldValue}" → "${data.newValue}". Check the Metadata Changes tab.`
          );
        } else {
          toast.info('No metadata changes detected');
        }
      } else {
        toast.error(data?.message || 'Failed to check metadata');
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Metadata check failed'
      );
    } finally {
      stopCheckMetadata(albumId);
    }
  };

  // Album handlers
  const handleAlbumWantedFilterChange = (filter: WantedFilter) => {
    setAlbumWantedFilter(filter);
    setAlbumPage(1);
  };
  const handleAlbumDownloadFilterChange = (filter: DownloadFilter) => {
    setAlbumDownloadFilter(filter);
    setAlbumPage(1);
  };
  const handleAlbumPageSizeChange = (size: number) => {
    setAlbumPageSize(size);
    setAlbumPage(1);
  };
  const handleAlbumSearch = useCallback((query: string) => {
    setAlbumSearchQuery(query);
    setAlbumPage(1);
  }, []);

  const handleAlbumSort = (field: AlbumSortField) => {
    const newDirection: SortDirection =
      albumSortField === field && albumSortDirection === 'asc' ? 'desc' : 'asc';
    setAlbumSortField(field);
    setAlbumSortDirection(newDirection);
    setAlbumPage(1);
  };

  const handleAlbumWantedToggle = async (albumId: number, wanted: boolean) => {
    await handleAlbumMutation(
      albumId,
      async () => {
        await setAlbumWanted({ variables: { albumId, wanted } });
        toast.success(`Wanted ${wanted ? 'enabled' : 'disabled'}`);
      },
      { withPulse: true }
    );
  };

  const handleDownloadAlbum = async (albumId: number) => {
    await handleAlbumMutation(
      albumId,
      async () => {
        await downloadAlbum({ variables: { albumId: albumId.toString() } });
        toast.success('Album download queued');
      },
      { withPulse: false }
    );
  };

  // Song handlers
  const handleSongDownloadFilterChange = (filter: DownloadFilter) => {
    setSongDownloadFilter(filter);
    setSongPage(1);
  };
  const handleSongPageSizeChange = (size: number) => {
    setSongPageSize(size);
    setSongPage(1);
  };
  const handleSongSearch = useCallback((query: string) => {
    setSongSearchQuery(query);
    setSongPage(1);
  }, []);

  const handleSongSort = (field: SongSortField) => {
    const newDirection: SortDirection =
      songSortField === field && songSortDirection === 'asc' ? 'desc' : 'asc';
    setSongSortField(field);
    setSongSortDirection(newDirection);
    setSongPage(1);
  };

  // Derived state
  const artist = artistData?.artist;
  const albums = (albumsData?.albums.items as Album[]) || [];
  const albumsTotalCount = albumsData?.albums.pageInfo?.totalCount || 0;
  const albumsTotalPages = albumsData?.albums.pageInfo?.totalPages || 1;

  const songs = (songsData?.songs.items as Song[]) || [];
  const songsTotalCount = songsData?.songs.pageInfo?.totalCount || 0;
  const songsTotalPages = songsData?.songs.pageInfo?.totalPages || 1;

  const { isRefreshing: artistRefreshing, isInitial: artistInitialLoading } =
    useRequestState(artistNetworkStatus);
  const { isRefreshing: albumsRefreshing } =
    useRequestState(albumsNetworkStatus);
  const { isRefreshing: songsRefreshing } = useRequestState(songsNetworkStatus);

  return {
    // Artist data
    artist,
    artistError,
    artistRefreshing,
    artistInitialLoading,

    // Artist actions
    handleTrackingTierChange,
    handleSyncArtist,
    handleDownloadArtist,
    handleCheckArtistMetadata,
    syncMutatingIds,
    downloadMutatingIds,
    checkMetadataMutatingIds,

    // Albums data
    albums,
    albumsTotalCount,
    albumsTotalPages,
    albumsLoading,
    albumsRefreshing,

    // Albums pagination
    albumPage,
    setAlbumPage,

    // Albums filters & sorting
    albumWantedFilter,
    albumDownloadFilter,
    albumPageSize,
    albumSortField,
    albumSortDirection,

    // Albums mutation states
    albumMutatingIds,
    albumPulseIds,

    // Albums handlers
    handleAlbumWantedFilterChange,
    handleAlbumDownloadFilterChange,
    handleAlbumPageSizeChange,
    handleAlbumSort,
    handleAlbumSearch,
    handleAlbumWantedToggle,
    handleDownloadAlbum,
    handleCheckAlbumMetadata,

    // Songs data
    songs,
    songsTotalCount,
    songsTotalPages,
    songsLoading,
    songsRefreshing,

    // Songs pagination
    songPage,
    setSongPage,

    // Songs filters & sorting
    songDownloadFilter,
    songPageSize,
    songSortField,
    songSortDirection,

    // Songs handlers
    handleSongDownloadFilterChange,
    handleSongPageSizeChange,
    handleSongSort,
    handleSongSearch,
  };
}

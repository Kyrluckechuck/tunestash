import { createFileRoute, Link } from '@tanstack/react-router';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GetAlbumByIdDocument,
  GetSongsDocument,
  SetAlbumWantedDocument,
  DownloadAlbumDocument,
  CheckAlbumMetadataDocument,
} from '../types/generated/graphql';
import { PageContainer } from '../components/layout/PageContainer';
import { SongsTable } from '../components/songs/SongsTable';
import { PageSpinner } from '../components/ui/PageSpinner';
import { ErrorBanner } from '../components/ui/ErrorBanner';
import { InlineSpinner } from '../components/ui/InlineSpinner';
import { LoadMoreButton } from '../components/ui/LoadMoreButton';
import { PageSizeSelector } from '../components/ui/PageSizeSelector';
import { SearchInput } from '../components/ui/SearchInput';
import { ProviderBadges } from '../components/ui/ProviderBadges';
import { useState, useCallback } from 'react';
import type { SortField } from '../components/songs/SongsTable';

function AlbumDetail() {
  const { albumId } = Route.useParams();
  const albumIdNum = parseInt(albumId, 10);

  const [songPageSize, setSongPageSize] = useState(50);
  const [songSortField, setSongSortField] = useState<SortField>(null);
  const [songSortDirection, setSongSortDirection] = useState<'asc' | 'desc'>(
    'asc'
  );
  const [songSearch, setSongSearch] = useState<string | undefined>(undefined);
  const [songDownloadFilter, setSongDownloadFilter] = useState<
    'all' | 'downloaded' | 'not_downloaded'
  >('all');

  const {
    data: albumData,
    loading: albumLoading,
    error: albumError,
    refetch: refetchAlbum,
  } = useQuery(GetAlbumByIdDocument, {
    variables: { id: albumIdNum },
  });

  const {
    data: songsData,
    loading: songsLoading,
    fetchMore,
  } = useQuery(GetSongsDocument, {
    variables: {
      first: songPageSize,
      albumId: albumIdNum,
      downloaded:
        songDownloadFilter === 'all'
          ? undefined
          : songDownloadFilter === 'downloaded',
      sortBy: songSortField ?? undefined,
      sortDirection: songSortDirection,
      search: songSearch,
    },
  });

  const [setAlbumWanted] = useMutation(SetAlbumWantedDocument);
  const [downloadAlbum, { loading: downloadLoading }] = useMutation(
    DownloadAlbumDocument
  );
  const [checkMetadata, { loading: checkingMetadata }] = useMutation(
    CheckAlbumMetadataDocument
  );

  const album = albumData?.albumById;
  const songs = songsData?.songs?.edges ?? [];
  const songsTotalCount = songsData?.songs?.totalCount ?? 0;
  const songsPageInfo = songsData?.songs?.pageInfo;

  const handleWantedToggle = useCallback(async () => {
    if (!album) return;
    await setAlbumWanted({
      variables: { albumId: album.id, wanted: !album.wanted },
    });
    refetchAlbum();
  }, [album, setAlbumWanted, refetchAlbum]);

  const handleDownload = useCallback(async () => {
    if (!album?.spotifyGid) return;
    await downloadAlbum({ variables: { albumId: album.spotifyGid } });
  }, [album, downloadAlbum]);

  const handleCheckMetadata = useCallback(async () => {
    if (!album) return;
    await checkMetadata({ variables: { albumId: album.id } });
  }, [album, checkMetadata]);

  const handleSongSort = useCallback((field: SortField) => {
    setSongSortField(prev => {
      if (prev === field) {
        setSongSortDirection(d => (d === 'asc' ? 'desc' : 'asc'));
        return prev;
      }
      setSongSortDirection('asc');
      return field;
    });
  }, []);

  const handleLoadMoreSongs = useCallback(() => {
    if (!songsPageInfo?.endCursor) return;
    fetchMore({ variables: { after: songsPageInfo.endCursor } });
  }, [fetchMore, songsPageInfo]);

  if (albumLoading) {
    return (
      <PageContainer>
        <PageSpinner message='Loading album...' />
      </PageContainer>
    );
  }

  if (albumError) {
    return (
      <PageContainer>
        <ErrorBanner title='Error loading album' message={albumError.message} />
      </PageContainer>
    );
  }

  if (!album) {
    return (
      <PageContainer>
        <ErrorBanner
          title='Album not found'
          message='The requested album could not be found.'
        />
      </PageContainer>
    );
  }

  const formatAlbumValue = (value: string | null | undefined): string => {
    if (!value) return 'Album';
    return value
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  };

  return (
    <PageContainer>
      {/* Back navigation */}
      <div className='mb-4'>
        <Link
          to='/albums'
          search={{ artistId: undefined }}
          className='text-sm text-indigo-600 dark:text-blue-400 hover:text-indigo-800 flex items-center gap-1'
        >
          &larr; Back to Albums
        </Link>
      </div>

      {/* Album Header */}
      <div className='bg-gradient-to-r from-green-50 dark:from-slate-800 to-emerald-50 dark:to-slate-800 border border-green-200 dark:border-slate-700 rounded-lg p-6 mb-6'>
        <div className='flex items-start justify-between'>
          <div>
            <div className='flex items-center gap-3 mb-2'>
              <h1 className='text-3xl font-bold text-green-900 dark:text-slate-100'>
                {album.name}
              </h1>
            </div>
            <div className='flex items-center gap-4 text-sm text-green-700 dark:text-green-400'>
              {album.artistId && (
                <Link
                  to='/artists/$artistId'
                  params={{ artistId: album.artistId.toString() }}
                  className='hover:text-green-900 underline'
                >
                  {album.artist || 'Unknown Artist'}
                </Link>
              )}
              <span className='text-slate-400'>·</span>
              <span>{formatAlbumValue(album.albumType)}</span>
              {album.albumGroup && album.albumGroup !== album.albumType && (
                <>
                  <span className='text-slate-400'>·</span>
                  <span>{formatAlbumValue(album.albumGroup)}</span>
                </>
              )}
              <ProviderBadges
                deezerId={album.deezerId}
                spotifyId={album.spotifyGid}
                deezerUrl={
                  album.deezerId
                    ? `https://www.deezer.com/album/${album.deezerId}`
                    : undefined
                }
                spotifyUrl={
                  album.spotifyGid
                    ? `https://open.spotify.com/album/${album.spotifyGid}`
                    : undefined
                }
              />
            </div>
          </div>
          <div className='flex items-center gap-2'>
            <button
              onClick={handleWantedToggle}
              className={`px-4 py-2 rounded-md transition-colors ${
                album.wanted
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-200 dark:bg-slate-600 text-gray-700 dark:text-slate-300 hover:bg-gray-300'
              }`}
            >
              {album.wanted ? 'Wanted' : 'Unwanted'}
            </button>
            <button
              onClick={handleDownload}
              disabled={downloadLoading}
              className='px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
            >
              {downloadLoading ? 'Starting...' : 'Download'}
            </button>
            <button
              onClick={handleCheckMetadata}
              disabled={checkingMetadata}
              className='px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
              title='Check for metadata changes'
            >
              {checkingMetadata ? 'Checking...' : 'Check Metadata'}
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className='grid grid-cols-2 md:grid-cols-3 gap-4 mt-6'>
          <div className='bg-white/60 dark:bg-slate-800/60 rounded-lg p-3'>
            <div className='text-2xl font-bold text-green-900 dark:text-slate-100'>
              {album.totalTracks}
            </div>
            <div className='text-xs text-green-600 dark:text-green-400'>
              Total Tracks
            </div>
          </div>
          <div className='bg-white/60 dark:bg-slate-800/60 rounded-lg p-3'>
            <div className='text-2xl font-bold text-green-900 dark:text-slate-100'>
              <span
                className={
                  album.downloaded
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-yellow-600 dark:text-yellow-400'
                }
              >
                {album.downloaded ? 'Yes' : 'No'}
              </span>
            </div>
            <div className='text-xs text-green-600 dark:text-green-400'>
              Downloaded
            </div>
          </div>
          <div className='bg-white/60 dark:bg-slate-800/60 rounded-lg p-3'>
            <div className='text-2xl font-bold text-green-900 dark:text-slate-100'>
              <span
                className={
                  album.wanted
                    ? 'text-blue-600 dark:text-blue-400'
                    : 'text-slate-400'
                }
              >
                {album.wanted ? 'Yes' : 'No'}
              </span>
            </div>
            <div className='text-xs text-green-600 dark:text-green-400'>
              Wanted
            </div>
          </div>
        </div>
      </div>

      {/* Songs Section */}
      <section>
        <div className='flex items-center justify-between mb-4'>
          <div className='flex items-center gap-3'>
            <h2 className='text-xl font-semibold'>
              Songs ({songs.length} of {songsTotalCount})
            </h2>
            {songsLoading && <InlineSpinner label='Loading...' />}
          </div>
          <div className='flex items-center gap-4'>
            <SearchInput
              placeholder='Search songs...'
              onSearch={setSongSearch}
              className='w-48'
            />
            <PageSizeSelector
              pageSize={songPageSize}
              onPageSizeChange={setSongPageSize}
            />
          </div>
        </div>

        {/* Download filter */}
        <div className='flex gap-2 mb-4'>
          {(['all', 'downloaded', 'not_downloaded'] as const).map(filter => (
            <button
              key={filter}
              onClick={() => setSongDownloadFilter(filter)}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${
                songDownloadFilter === filter
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-500'
              }`}
            >
              {filter === 'all'
                ? 'All'
                : filter === 'downloaded'
                  ? 'Downloaded'
                  : 'Not Downloaded'}
            </button>
          ))}
        </div>

        <SongsTable
          songs={songs}
          sortField={songSortField}
          sortDirection={songSortDirection}
          onSort={handleSongSort}
          loading={songsLoading}
        />

        <LoadMoreButton
          hasNextPage={!!songsPageInfo?.hasNextPage}
          loading={songsLoading}
          remainingCount={songsTotalCount - songs.length}
          onLoadMore={handleLoadMoreSongs}
        />
      </section>
    </PageContainer>
  );
}

export const Route = createFileRoute('/albums_/$albumId')({
  component: AlbumDetail,
});

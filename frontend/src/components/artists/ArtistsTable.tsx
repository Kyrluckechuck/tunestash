import type { Artist } from '../../types/generated/graphql';
import { SortableTableHeader } from '../ui/SortableTableHeader';
import { Link } from '@tanstack/react-router';

export type SortField =
  | 'name'
  | 'trackingTier'
  | 'addedAt'
  | 'lastSynced'
  | 'lastDownloaded'
  | null;

interface ArtistsTableProps {
  artists: Artist[];
  sortField: SortField;
  sortDirection: 'asc' | 'desc';
  onSort: (field: SortField) => void;
  onTrackToggle: (artist: Artist) => void;
  onSyncArtist: (artistId: number) => void;
  onDownloadArtist: (artistId: number) => void;
  onRetryFailedSongs: (artistId: number) => void;
  loading?: boolean;
  mutatingIds?: Set<number>;
  syncMutatingIds?: Set<number>;
  downloadMutatingIds?: Set<number>;
  retryMutatingIds?: Set<number>;
  errorById?: Record<number, string>;
  pulseIds?: Set<number>;
}

export function ArtistsTable({
  artists,
  sortField,
  sortDirection,
  onSort,
  onTrackToggle,
  onSyncArtist,
  onDownloadArtist,
  onRetryFailedSongs,
  loading = false,
  mutatingIds,
  syncMutatingIds,
  downloadMutatingIds,
  retryMutatingIds,
  errorById,
  pulseIds,
}: ArtistsTableProps) {
  if (artists.length === 0) {
    return (
      <div className='bg-white dark:bg-slate-800 rounded shadow overflow-hidden'>
        <div className='p-6 text-center text-gray-500 dark:text-slate-400'>
          {loading ? 'Loading artists...' : 'No artists found.'}
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Mobile card view */}
      <div className='md:hidden space-y-3'>
        {artists.map(artist => (
          <Link
            key={artist.id}
            to='/artists/$artistId'
            params={{ artistId: artist.id.toString() }}
            className='block bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 hover:border-slate-300 dark:hover:border-slate-600 transition-colors'
          >
            <div className='flex items-center justify-between mb-2'>
              <span className='text-sm font-semibold text-indigo-600 dark:text-blue-400 truncate mr-2'>
                {artist.name}
              </span>
              <span
                className={`shrink-0 px-2 py-0.5 rounded text-xs font-medium ${
                  artist.trackingTier === 2
                    ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300'
                    : artist.trackingTier === 1
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                      : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400'
                }`}
              >
                {artist.trackingTier === 2
                  ? '\u2605 Favourite'
                  : artist.trackingTier === 1
                    ? '\u2713 Tracked'
                    : 'Untracked'}
              </span>
            </div>
            <div className='grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400'>
              <span>Albums: {artist.albumCount}</span>
              <span>Songs: {artist.songCount}</span>
              <span>Downloaded: {artist.downloadedAlbumCount}</span>
              <span>Pending: {artist.undownloadedCount}</span>
            </div>
            {artist.lastSynced && (
              <div className='text-xs text-slate-400 dark:text-slate-500 mt-2'>
                Synced: {new Date(artist.lastSynced).toLocaleDateString()}
              </div>
            )}
          </Link>
        ))}
      </div>

      {/* Desktop table view */}
      <div className='hidden md:block bg-white dark:bg-slate-800 rounded shadow overflow-hidden'>
        <div className='overflow-x-auto'>
          <table className='min-w-full divide-y divide-gray-200 dark:divide-slate-700'>
            <thead className='bg-gray-50 dark:bg-slate-900'>
              <tr>
                <SortableTableHeader
                  field='name'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Artist
                </SortableTableHeader>
                <SortableTableHeader
                  field='trackingTier'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Status
                </SortableTableHeader>
                <SortableTableHeader
                  field='lastSynced'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Last Synced
                </SortableTableHeader>
                <SortableTableHeader
                  field='lastDownloaded'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Last Downloaded
                </SortableTableHeader>
                <SortableTableHeader
                  field={null}
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Actions
                </SortableTableHeader>
              </tr>
            </thead>
            <tbody className='bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-slate-700'>
              {artists.map(artist => (
                <tr
                  key={artist.id}
                  className='hover:bg-gray-50 dark:hover:bg-slate-700'
                >
                  <td className='px-6 py-4 whitespace-nowrap'>
                    <div className='text-sm font-medium'>
                      <Link
                        to='/artists/$artistId'
                        params={{ artistId: artist.id.toString() }}
                        className='text-indigo-600 dark:text-blue-400 hover:text-indigo-800 dark:hover:text-blue-300 hover:underline'
                        title={`View ${artist.name} details`}
                      >
                        {artist.name}
                      </Link>
                    </div>
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap'>
                    <button
                      onClick={() => onTrackToggle(artist)}
                      disabled={mutatingIds?.has(artist.id)}
                      className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                        pulseIds?.has(artist.id) ? 'animate-pulse' : ''
                      } ${
                        artist.trackingTier === 2
                          ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50'
                          : artist.trackingTier === 1
                            ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/50'
                            : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-600'
                      } disabled:opacity-50`}
                      aria-label={
                        artist.trackingTier >= 1
                          ? 'Untrack artist'
                          : 'Track artist'
                      }
                    >
                      {artist.trackingTier === 2
                        ? '\u2605 Favourite'
                        : artist.trackingTier === 1
                          ? '\u2713 Tracked'
                          : 'Not Tracked'}
                    </button>
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
                    {artist.lastSynced
                      ? new Date(artist.lastSynced).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
                    {artist.lastDownloaded
                      ? new Date(artist.lastDownloaded).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2'>
                    <button
                      onClick={() => onSyncArtist(artist.id)}
                      disabled={syncMutatingIds?.has(artist.id)}
                      className='px-3 py-1 rounded text-xs font-medium bg-blue-100 text-blue-800 hover:bg-blue-200 transition-colors disabled:opacity-60'
                    >
                      {syncMutatingIds?.has(artist.id) ? (
                        <span className='inline-flex items-center gap-2'>
                          <span className='w-3 h-3 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin' />
                          <span>Syncing…</span>
                        </span>
                      ) : (
                        '📄 Sync Library'
                      )}
                    </button>
                    <button
                      onClick={() => onDownloadArtist(artist.id)}
                      disabled={
                        downloadMutatingIds?.has(artist.id) ||
                        artist.undownloadedCount === 0
                      }
                      className='px-3 py-1 rounded text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200 transition-colors disabled:opacity-60'
                      title={
                        artist.undownloadedCount === 0
                          ? 'No undownloaded albums'
                          : `Download ${artist.undownloadedCount} missing albums/singles`
                      }
                    >
                      {downloadMutatingIds?.has(artist.id) ? (
                        <span className='inline-flex items-center gap-2'>
                          <span className='w-3 h-3 border-2 border-gray-300 border-t-green-500 rounded-full animate-spin' />
                          <span>Downloading…</span>
                        </span>
                      ) : (
                        `⬇️ Download (${artist.undownloadedCount})`
                      )}
                    </button>
                    {artist.failedSongCount > 0 && (
                      <button
                        onClick={() => onRetryFailedSongs(artist.id)}
                        disabled={retryMutatingIds?.has(artist.id)}
                        className='px-3 py-1 rounded text-xs font-medium bg-amber-100 text-amber-800 hover:bg-amber-200 transition-colors disabled:opacity-60'
                        title={`Retry ${artist.failedSongCount} failed songs (ignores backoff)`}
                      >
                        {retryMutatingIds?.has(artist.id) ? (
                          <span className='inline-flex items-center gap-2'>
                            <span className='w-3 h-3 border-2 border-gray-300 border-t-amber-500 rounded-full animate-spin' />
                            <span>Retrying…</span>
                          </span>
                        ) : (
                          `🔄 Retry (${artist.failedSongCount})`
                        )}
                      </button>
                    )}
                    <Link
                      to='/artists/$artistId'
                      params={{ artistId: artist.id.toString() }}
                      className='text-indigo-600 dark:text-blue-400 hover:text-indigo-900 underline'
                    >
                      View Details
                    </Link>
                    {errorById?.[artist.id] && (
                      <div className='text-xs text-red-600 dark:text-red-400 mt-1'>
                        {errorById[artist.id]}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

import type { Playlist } from '../../types/generated/graphql';
import { SortableTableHeader } from '../ui/SortableTableHeader';
import { StatusBadge } from '../ui/StatusBadge';
import { ToggleStatusButton } from '../ui/ToggleStatusButton';

function isRestrictedStatus(status: string): boolean {
  return status === 'spotify_api_restricted' || status === 'not_found';
}

export type PlaylistSortField =
  | 'name'
  | 'enabled'
  | 'autoTrackArtists'
  | 'lastSyncedAt'
  | null;

interface PlaylistsTableProps {
  playlists: Playlist[];
  sortField: PlaylistSortField;
  sortDirection: 'asc' | 'desc';
  onSort: (field: PlaylistSortField) => void;
  onToggleEnabled: (playlist: Playlist) => void;
  onToggleAutoTrack: (playlist: Playlist) => void;
  onToggleM3u: (playlist: Playlist) => void;
  onSyncPlaylist: (playlistId: number) => void;
  onForceSyncPlaylist?: (playlistId: number) => void;
  onRecheckPlaylist?: (playlistId: number) => void;
  onEditPlaylist?: (playlist: Playlist) => void;
  onDeletePlaylist?: (playlistId: number, playlistName: string) => void;
  loading?: boolean;
  enabledMutatingIds?: Set<number>;
  autoMutatingIds?: Set<number>;
  m3uMutatingIds?: Set<number>;
  syncMutatingIds?: Set<number>;
  forceSyncMutatingIds?: Set<number>;
  recheckMutatingIds?: Set<number>;
  deleteMutatingIds?: Set<number>;
  enabledPulseIds?: Set<number>;
  autoPulseIds?: Set<number>;
  m3uPulseIds?: Set<number>;
  errorById?: Record<number, string>;
}

export function PlaylistsTable({
  playlists,
  sortField,
  sortDirection,
  onSort,
  onToggleEnabled,
  onToggleAutoTrack,
  onToggleM3u,
  onSyncPlaylist,
  onForceSyncPlaylist,
  onRecheckPlaylist,
  onEditPlaylist,
  onDeletePlaylist,
  loading = false,
  enabledMutatingIds,
  autoMutatingIds,
  m3uMutatingIds,
  syncMutatingIds,
  forceSyncMutatingIds,
  recheckMutatingIds,
  deleteMutatingIds,
  enabledPulseIds,
  autoPulseIds,
  m3uPulseIds,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  errorById,
}: PlaylistsTableProps) {
  if (playlists.length === 0) {
    return (
      <div className='bg-white dark:bg-slate-800 rounded shadow overflow-hidden'>
        <div className='p-6 text-center text-gray-500 dark:text-slate-400'>
          {loading ? 'Loading playlists...' : 'No playlists found.'}
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Mobile card view */}
      <div className='md:hidden space-y-3'>
        {playlists.map(playlist => (
          <div
            key={playlist.id}
            className='bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4'
          >
            <div className='flex items-center justify-between mb-2'>
              <span className='text-sm font-semibold text-slate-900 dark:text-slate-100 truncate mr-2'>
                {playlist.name}
              </span>
              {isRestrictedStatus(playlist.status) ? (
                <StatusBadge
                  label={
                    playlist.status === 'spotify_api_restricted'
                      ? 'Not Supported'
                      : 'Not Found'
                  }
                  color={
                    playlist.status === 'spotify_api_restricted'
                      ? 'amber'
                      : 'red'
                  }
                  tooltip={playlist.statusMessage ?? undefined}
                />
              ) : (
                <span
                  className={`shrink-0 px-2 py-0.5 rounded text-xs font-medium ${
                    playlist.enabled
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                      : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
                  }`}
                >
                  {playlist.enabled ? 'Enabled' : 'Disabled'}
                </span>
              )}
            </div>
            <div className='grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400'>
              <span>
                Track Artists: {playlist.autoTrackArtists ? 'Yes' : 'No'}
              </span>
              <span>M3U: {playlist.m3uEnabled ? 'Yes' : 'No'}</span>
              <span>
                Synced:{' '}
                {playlist.lastSyncedAt
                  ? new Date(playlist.lastSyncedAt).toLocaleDateString()
                  : 'Never'}
              </span>
              <span className='capitalize'>{playlist.provider}</span>
            </div>
            <div className='flex items-center gap-2 mt-3'>
              {!isRestrictedStatus(playlist.status) && (
                <button
                  onClick={() => onSyncPlaylist(playlist.id)}
                  disabled={syncMutatingIds?.has(playlist.id)}
                  className='text-xs px-2 py-1 rounded bg-blue-100 text-blue-800 hover:bg-blue-200 disabled:opacity-60'
                >
                  {syncMutatingIds?.has(playlist.id) ? 'Syncing…' : 'Sync'}
                </button>
              )}
              <a
                href={playlist.url}
                target='_blank'
                rel='noopener noreferrer'
                className='text-xs text-indigo-600 dark:text-blue-400 hover:underline'
              >
                {playlist.provider === 'deezer'
                  ? 'Open Deezer'
                  : 'Open Spotify'}
              </a>
            </div>
          </div>
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
                  Playlist
                </SortableTableHeader>
                <SortableTableHeader
                  field='enabled'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Status
                </SortableTableHeader>
                <SortableTableHeader
                  field='autoTrackArtists'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Track Artists
                </SortableTableHeader>
                <SortableTableHeader
                  field={null}
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  M3U Export
                </SortableTableHeader>
                <SortableTableHeader
                  field='lastSyncedAt'
                  currentSortField={sortField}
                  currentSortDirection={sortDirection}
                  onSort={onSort}
                >
                  Last Synced
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
              {playlists.map(playlist => (
                <tr
                  key={playlist.id}
                  className='hover:bg-gray-50 dark:hover:bg-slate-700'
                >
                  <td className='px-6 py-4 whitespace-nowrap'>
                    <div className='text-sm font-medium text-gray-900 dark:text-slate-100'>
                      {playlist.name}
                    </div>
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap'>
                    {isRestrictedStatus(playlist.status) ? (
                      <StatusBadge
                        label={
                          playlist.status === 'spotify_api_restricted'
                            ? 'Not Supported'
                            : 'Not Found'
                        }
                        color={
                          playlist.status === 'spotify_api_restricted'
                            ? 'amber'
                            : 'red'
                        }
                        tooltip={playlist.statusMessage ?? undefined}
                      />
                    ) : (
                      <>
                        <ToggleStatusButton
                          variant='switch'
                          enabled={playlist.enabled}
                          onToggle={() => onToggleEnabled(playlist)}
                          mutating={enabledMutatingIds?.has(playlist.id)}
                          pulse={enabledPulseIds?.has(playlist.id)}
                          labels={{ on: 'Enabled', off: 'Disabled' }}
                          ariaLabel={
                            playlist.enabled
                              ? 'Disable playlist'
                              : 'Enable playlist'
                          }
                        />
                        <ToggleStatusButton
                          variant='badge'
                          enabled={playlist.enabled}
                          onToggle={() => onToggleEnabled(playlist)}
                          mutating={enabledMutatingIds?.has(playlist.id)}
                          pulse={enabledPulseIds?.has(playlist.id)}
                          labels={{ on: 'Enabled', off: 'Disabled' }}
                          colors={{ on: 'green', off: 'red' }}
                          ariaLabel={
                            playlist.enabled
                              ? 'Disable playlist'
                              : 'Enable playlist'
                          }
                        />
                      </>
                    )}
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap'>
                    <ToggleStatusButton
                      variant='switch'
                      enabled={playlist.autoTrackArtists}
                      onToggle={() => onToggleAutoTrack(playlist)}
                      mutating={autoMutatingIds?.has(playlist.id)}
                      pulse={autoPulseIds?.has(playlist.id)}
                      labels={{ on: 'Yes', off: 'No' }}
                      ariaLabel={
                        playlist.autoTrackArtists
                          ? 'Disable tracking artists'
                          : 'Enable tracking artists'
                      }
                    />
                    <ToggleStatusButton
                      variant='badge'
                      enabled={playlist.autoTrackArtists}
                      onToggle={() => onToggleAutoTrack(playlist)}
                      mutating={autoMutatingIds?.has(playlist.id)}
                      pulse={autoPulseIds?.has(playlist.id)}
                      labels={{ on: 'Yes', off: 'No' }}
                      colors={{ on: 'blue', off: 'red' }}
                      ariaLabel={
                        playlist.autoTrackArtists
                          ? 'Disable tracking artists'
                          : 'Enable tracking artists'
                      }
                    />
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap'>
                    <ToggleStatusButton
                      variant='switch'
                      enabled={playlist.m3uEnabled}
                      onToggle={() => onToggleM3u(playlist)}
                      mutating={m3uMutatingIds?.has(playlist.id)}
                      pulse={m3uPulseIds?.has(playlist.id)}
                      labels={{ on: 'Yes', off: 'No' }}
                      ariaLabel={
                        playlist.m3uEnabled
                          ? 'Disable M3U export'
                          : 'Enable M3U export'
                      }
                    />
                    <ToggleStatusButton
                      variant='badge'
                      enabled={playlist.m3uEnabled}
                      onToggle={() => onToggleM3u(playlist)}
                      mutating={m3uMutatingIds?.has(playlist.id)}
                      pulse={m3uPulseIds?.has(playlist.id)}
                      labels={{ on: 'Yes', off: 'No' }}
                      colors={{ on: 'blue', off: 'red' }}
                      ariaLabel={
                        playlist.m3uEnabled
                          ? 'Disable M3U export'
                          : 'Enable M3U export'
                      }
                    />
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
                    {playlist.lastSyncedAt
                      ? new Date(playlist.lastSyncedAt).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className='px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2'>
                    {isRestrictedStatus(playlist.status) &&
                      onRecheckPlaylist && (
                        <button
                          onClick={() => onRecheckPlaylist(playlist.id)}
                          disabled={recheckMutatingIds?.has(playlist.id)}
                          className='px-3 py-1 rounded text-xs font-medium bg-purple-100 text-purple-800 hover:bg-purple-200 transition-colors'
                          title='Re-check if this playlist has become accessible'
                        >
                          {recheckMutatingIds?.has(playlist.id) ? (
                            <span className='inline-flex items-center gap-2'>
                              <span className='w-3 h-3 border-2 border-gray-300 border-t-purple-500 rounded-full animate-spin' />
                              <span>Checking…</span>
                            </span>
                          ) : (
                            'Recheck'
                          )}
                        </button>
                      )}
                    {!isRestrictedStatus(playlist.status) && (
                      <>
                        <button
                          onClick={() => onSyncPlaylist(playlist.id)}
                          disabled={
                            syncMutatingIds?.has(playlist.id) ||
                            forceSyncMutatingIds?.has(playlist.id)
                          }
                          className='px-3 py-1 rounded text-xs font-medium bg-blue-100 text-blue-800 hover:bg-blue-200 transition-colors'
                        >
                          {syncMutatingIds?.has(playlist.id) ? (
                            <span className='inline-flex items-center gap-2'>
                              <span className='w-3 h-3 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin' />
                              <span>Syncing…</span>
                            </span>
                          ) : (
                            'Sync Now'
                          )}
                        </button>
                        {onForceSyncPlaylist && (
                          <button
                            onClick={() => onForceSyncPlaylist(playlist.id)}
                            disabled={
                              syncMutatingIds?.has(playlist.id) ||
                              forceSyncMutatingIds?.has(playlist.id)
                            }
                            className='px-3 py-1 rounded text-xs font-medium bg-orange-100 text-orange-800 hover:bg-orange-200 transition-colors'
                            title='Force sync will re-download all tracks, ignoring existing ones'
                          >
                            {forceSyncMutatingIds?.has(playlist.id) ? (
                              <span className='inline-flex items-center gap-2'>
                                <span className='w-3 h-3 border-2 border-gray-300 border-t-orange-500 rounded-full animate-spin' />
                                <span>Force Syncing…</span>
                              </span>
                            ) : (
                              'Force Sync'
                            )}
                          </button>
                        )}
                        {onEditPlaylist && (
                          <button
                            onClick={() => onEditPlaylist(playlist)}
                            className='px-3 py-1 rounded text-xs font-medium bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors'
                          >
                            Edit
                          </button>
                        )}
                      </>
                    )}
                    {onDeletePlaylist && (
                      <button
                        onClick={() =>
                          onDeletePlaylist(playlist.id, playlist.name)
                        }
                        disabled={deleteMutatingIds?.has(playlist.id)}
                        className='px-3 py-1 rounded text-xs font-medium bg-red-100 text-red-800 hover:bg-red-200 transition-colors disabled:opacity-50'
                      >
                        {deleteMutatingIds?.has(playlist.id) ? (
                          <span className='inline-flex items-center gap-2'>
                            <span className='w-3 h-3 border-2 border-gray-300 border-t-red-500 rounded-full animate-spin' />
                            <span>Deleting…</span>
                          </span>
                        ) : (
                          'Delete'
                        )}
                      </button>
                    )}
                    <a
                      href={playlist.url}
                      target='_blank'
                      rel='noopener noreferrer'
                      className='text-indigo-600 dark:text-blue-400 hover:text-indigo-900 underline'
                    >
                      {playlist.provider === 'deezer'
                        ? 'Open Deezer'
                        : 'Open Spotify'}
                    </a>
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

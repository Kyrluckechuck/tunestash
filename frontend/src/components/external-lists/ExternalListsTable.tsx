import { MappingStatusBadge } from './MappingStatusBadge';

export type ExternalListSortField =
  | 'name'
  | 'source'
  | 'username'
  | 'status'
  | 'lastSyncedAt'
  | 'totalTracks'
  | 'mappedTracks'
  | null;

interface ExternalListItem {
  id: number;
  name: string;
  source: string;
  listType: string;
  username: string;
  period?: string | null;
  listIdentifier?: string | null;
  status: string;
  statusMessage?: string | null;
  autoTrackArtists: boolean;
  lastSyncedAt?: string | null;
  totalTracks: number;
  mappedTracks: number;
  failedTracks: number;
}

interface ExternalListsTableProps {
  lists: ExternalListItem[];
  sortField: ExternalListSortField;
  sortDirection: 'asc' | 'desc';
  onSort: (field: ExternalListSortField) => void;
  onToggleEnabled: (list: ExternalListItem) => void;
  onToggleAutoTrack: (list: ExternalListItem) => void;
  onEditList: (list: ExternalListItem) => void;
  onSyncList: (listId: number) => void;
  onForceSyncList: (listId: number) => void;
  onDeleteList: (listId: number, name: string) => void;
  loading: boolean;
  enabledMutatingIds: Set<number>;
  syncMutatingIds: Set<number>;
  forceSyncMutatingIds: Set<number>;
  deleteMutatingIds: Set<number>;
}

function sourceLabel(source: string): string {
  if (source === 'lastfm') return 'Last.fm';
  if (source === 'listenbrainz') return 'ListenBrainz';
  if (source === 'youtube_music') return 'YouTube Music';
  return source;
}

function typeLabel(listType: string): string {
  if (listType === 'loved') return 'Loved';
  if (listType === 'top') return 'Top';
  if (listType === 'playlist') return 'Playlist';
  if (listType === 'chart') return 'Chart';
  return listType;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    active: 'bg-green-100 text-green-800',
    disabled_by_user:
      'bg-gray-100 dark:bg-slate-700 text-gray-800 dark:text-slate-200',
    auth_error: 'bg-red-100 text-red-800',
    not_found: 'bg-yellow-100 text-yellow-800',
    sync_error: 'bg-red-100 text-red-800',
  };
  const labels: Record<string, string> = {
    active: 'Active',
    disabled_by_user: 'Disabled',
    auth_error: 'Auth Error',
    not_found: 'Not Found',
    sync_error: 'Sync Error',
  };
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 dark:bg-slate-700 text-gray-800 dark:text-slate-200'}`}
    >
      {labels[status] || status}
    </span>
  );
}

function getExternalUrl(list: ExternalListItem): string | null {
  const { source, listType, username, period, listIdentifier } = list;
  const user = encodeURIComponent(username);

  if (source === 'lastfm') {
    if (listType === 'loved') return `https://www.last.fm/user/${user}/loved`;
    if (listType === 'top')
      return `https://www.last.fm/user/${user}/+tracks?date_preset=${encodeURIComponent(period || 'overall')}`;
    if (listType === 'chart') return `https://www.last.fm/music/+charts`;
  }
  if (source === 'listenbrainz') {
    if (listType === 'loved')
      return `https://listenbrainz.org/user/${user}/taste/`;
    if (listType === 'top')
      return `https://listenbrainz.org/user/${user}/stats/`;
    if (listType === 'playlist' && listIdentifier)
      return `https://listenbrainz.org/playlist/${encodeURIComponent(listIdentifier)}/`;
    if (listType === 'chart') return `https://listenbrainz.org/explore/`;
  }
  if (source === 'youtube_music') {
    if (listType === 'playlist' && listIdentifier)
      return `https://music.youtube.com/playlist?list=${encodeURIComponent(listIdentifier)}`;
  }
  return null;
}

function SortHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
}: {
  label: string;
  field: ExternalListSortField;
  currentField: ExternalListSortField;
  direction: 'asc' | 'desc';
  onSort: (field: ExternalListSortField) => void;
}) {
  return (
    <th
      className='px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider cursor-pointer hover:text-gray-700 dark:hover:text-slate-200'
      onClick={() => onSort(field)}
    >
      {label}
      {currentField === field && (
        <span className='ml-1'>{direction === 'asc' ? '↑' : '↓'}</span>
      )}
    </th>
  );
}

export function ExternalListsTable({
  lists,
  sortField,
  sortDirection,
  onSort,
  onToggleEnabled,
  onToggleAutoTrack,
  onEditList,
  onSyncList,
  onForceSyncList,
  onDeleteList,
  loading: _loading,
  enabledMutatingIds,
  syncMutatingIds,
  forceSyncMutatingIds,
  deleteMutatingIds,
}: ExternalListsTableProps) {
  if (lists.length === 0) {
    return (
      <div className='text-center py-12 text-gray-500 dark:text-slate-400'>
        <p className='text-lg'>No external lists found</p>
        <p className='text-sm mt-1'>
          Add a Last.fm, ListenBrainz, or YouTube Music list to get started
        </p>
      </div>
    );
  }

  return (
    <div className='overflow-x-auto'>
      <table className='min-w-full divide-y divide-gray-200 dark:divide-slate-700'>
        <thead className='bg-gray-50 dark:bg-slate-900'>
          <tr>
            <SortHeader
              label='Name'
              field='name'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortHeader
              label='Source'
              field='source'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <th className='px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
              Type
            </th>
            <SortHeader
              label='Username'
              field='username'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortHeader
              label='Status'
              field='status'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortHeader
              label='Mapping'
              field='mappedTracks'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <SortHeader
              label='Last Synced'
              field='lastSyncedAt'
              currentField={sortField}
              direction={sortDirection}
              onSort={onSort}
            />
            <th className='px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
              Actions
            </th>
          </tr>
        </thead>
        <tbody className='bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-slate-700'>
          {lists.map(list => (
            <tr
              key={list.id}
              className='hover:bg-gray-50 dark:hover:bg-slate-700'
            >
              <td className='px-4 py-3'>
                <div className='text-sm font-medium text-gray-900 dark:text-slate-100'>
                  {(() => {
                    const url = getExternalUrl(list);
                    return url ? (
                      <a
                        href={url}
                        target='_blank'
                        rel='noopener noreferrer'
                        className='text-indigo-600 dark:text-blue-400 hover:text-indigo-800 dark:hover:text-blue-300 hover:underline'
                      >
                        {list.name}
                        <span className='ml-1 text-xs text-gray-400 dark:text-slate-500'>
                          &#8599;
                        </span>
                      </a>
                    ) : (
                      list.name
                    );
                  })()}
                </div>
                {list.period && (
                  <div className='text-xs text-gray-500 dark:text-slate-400'>
                    Period: {list.period}
                  </div>
                )}
              </td>
              <td className='px-4 py-3'>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    list.source === 'lastfm'
                      ? 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400'
                      : list.source === 'youtube_music'
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-orange-50 text-orange-700'
                  }`}
                >
                  {sourceLabel(list.source)}
                </span>
              </td>
              <td className='px-4 py-3 text-sm text-gray-600 dark:text-slate-400'>
                {typeLabel(list.listType)}
              </td>
              <td className='px-4 py-3 text-sm text-gray-600 dark:text-slate-400'>
                {list.username}
              </td>
              <td className='px-4 py-3'>{statusBadge(list.status)}</td>
              <td className='px-4 py-3'>
                <MappingStatusBadge
                  totalTracks={list.totalTracks}
                  mappedTracks={list.mappedTracks}
                  failedTracks={list.failedTracks}
                />
              </td>
              <td className='px-4 py-3 text-sm text-gray-500 dark:text-slate-400'>
                {list.lastSyncedAt
                  ? new Date(list.lastSyncedAt).toLocaleDateString()
                  : 'Never'}
              </td>
              <td className='px-4 py-3'>
                <div className='flex items-center gap-2'>
                  <button
                    onClick={() => onToggleEnabled(list)}
                    disabled={enabledMutatingIds.has(list.id)}
                    className='text-xs px-2 py-1 rounded border hover:bg-gray-50 dark:hover:bg-slate-700 disabled:opacity-50'
                    title={
                      list.status === 'active'
                        ? 'Disable'
                        : list.status === 'disabled_by_user'
                          ? 'Enable'
                          : 'Reset to active'
                    }
                  >
                    {list.status === 'active'
                      ? 'Disable'
                      : list.status === 'disabled_by_user'
                        ? 'Enable'
                        : 'Reset'}
                  </button>
                  <button
                    onClick={() => onEditList(list)}
                    className='text-xs px-2 py-1 rounded border text-indigo-600 dark:text-blue-400 hover:bg-indigo-50 dark:hover:bg-blue-950'
                    title='Edit list settings'
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => onSyncList(list.id)}
                    disabled={
                      syncMutatingIds.has(list.id) ||
                      forceSyncMutatingIds.has(list.id)
                    }
                    className='text-xs px-2 py-1 rounded border text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950 disabled:opacity-50'
                    title='Sync now'
                  >
                    {syncMutatingIds.has(list.id) ? 'Syncing...' : 'Sync'}
                  </button>
                  <button
                    onClick={() => onForceSyncList(list.id)}
                    disabled={
                      syncMutatingIds.has(list.id) ||
                      forceSyncMutatingIds.has(list.id)
                    }
                    className='text-xs px-2 py-1 rounded border text-orange-600 hover:bg-orange-50 disabled:opacity-50'
                    title='Force sync ignores content hash and re-fetches all tracks'
                  >
                    {forceSyncMutatingIds.has(list.id)
                      ? 'Syncing...'
                      : 'Force Sync'}
                  </button>
                  <button
                    onClick={() => onToggleAutoTrack(list)}
                    className={`text-xs px-2 py-1 rounded border ${
                      list.autoTrackArtists
                        ? 'bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-400 border-green-200'
                        : 'text-gray-500 dark:text-slate-400 hover:bg-gray-50 dark:hover:bg-slate-700'
                    }`}
                    title={
                      list.autoTrackArtists
                        ? 'Auto-track enabled'
                        : 'Auto-track disabled'
                    }
                  >
                    {list.autoTrackArtists ? 'Tracking' : 'Track'}
                  </button>
                  <button
                    onClick={() => onDeleteList(list.id, list.name)}
                    disabled={deleteMutatingIds.has(list.id)}
                    className='text-xs px-2 py-1 rounded border text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-50'
                    title='Delete list'
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import React from 'react';
import { Link } from '@tanstack/react-router';
import type { GetSongsQuery } from '../../types/generated/graphql';
import { SortableTableHeader } from '../ui/SortableTableHeader';

export type SortField =
  | 'name'
  | 'primaryArtist'
  | 'createdAt'
  | 'downloaded'
  | null;

type Song = GetSongsQuery['songs']['edges'][number];

interface SongsTableProps {
  songs: Song[];
  sortField: SortField;
  sortDirection: 'asc' | 'desc';
  onSort: (field: SortField) => void;
  loading?: boolean;
  mutatingIds?: Set<number>;
  errorById?: Record<number, string>;
}

export const SongsTable: React.FC<SongsTableProps> = ({
  songs,
  sortField,
  sortDirection,
  onSort,
  loading = false,
}) => {
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString();
  };

  const formatBitrate = (bitrate: number) => {
    if (bitrate === 0) return 'N/A';
    return `${bitrate} kbps`;
  };

  const getStatusIcon = (song: Song) => {
    if (song.unavailable) {
      return (
        <span className='text-red-500' title='Unavailable'>
          ⚠️
        </span>
      );
    }
    if (song.downloaded) {
      return (
        <span className='text-green-500' title='Downloaded'>
          ✓
        </span>
      );
    }
    if (song.failedCount > 0) {
      return (
        <span
          className='text-yellow-500'
          title={`Download failed ${song.failedCount} time${song.failedCount === 1 ? '' : 's'}`}
        >
          ⚠️
        </span>
      );
    }
    return (
      <span
        className='text-gray-400 dark:text-slate-500'
        title='Not downloaded'
      >
        ○
      </span>
    );
  };

  const getStatusText = (song: Song) => {
    if (song.unavailable) {
      return 'Unavailable';
    }
    if (song.downloaded) {
      return 'Downloaded';
    }
    if (song.failedCount > 0) {
      return `Failed (${song.failedCount})`;
    }
    return 'Not downloaded';
  };

  if (loading && songs.length === 0) {
    return (
      <div className='bg-white dark:bg-slate-800 shadow overflow-hidden sm:rounded-md'>
        <div className='px-6 py-4 text-center text-gray-500 dark:text-slate-400'>
          Loading songs...
        </div>
      </div>
    );
  }

  if (songs.length === 0) {
    return (
      <div className='bg-white dark:bg-slate-800 shadow overflow-hidden sm:rounded-md'>
        <div className='px-6 py-4 text-center text-gray-500 dark:text-slate-400'>
          No songs found.
        </div>
      </div>
    );
  }

  return (
    <div className='bg-white dark:bg-slate-800 shadow overflow-hidden sm:rounded-md overflow-x-auto'>
      <table className='min-w-full divide-y divide-gray-200 dark:divide-slate-700'>
        <thead className='bg-gray-50 dark:bg-slate-900'>
          <tr>
            <SortableTableHeader
              field='downloaded'
              currentSortField={sortField}
              currentSortDirection={sortDirection}
              onSort={onSort}
              className='w-24'
            >
              Status
            </SortableTableHeader>
            <SortableTableHeader
              field='name'
              currentSortField={sortField}
              currentSortDirection={sortDirection}
              onSort={onSort}
            >
              Song Name
            </SortableTableHeader>
            <SortableTableHeader
              field='primaryArtist'
              currentSortField={sortField}
              currentSortDirection={sortDirection}
              onSort={onSort}
            >
              Artist
            </SortableTableHeader>
            <SortableTableHeader
              field='createdAt'
              currentSortField={sortField}
              currentSortDirection={sortDirection}
              onSort={onSort}
            >
              Added
            </SortableTableHeader>
            <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
              Bitrate
            </th>
            <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
              File Path
            </th>
          </tr>
        </thead>
        <tbody className='bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-slate-700'>
          {songs.map(song => (
            <tr
              key={song.id}
              className='hover:bg-gray-50 dark:hover:bg-slate-700'
            >
              <td className='px-6 py-4 whitespace-nowrap'>
                <div className='flex items-center gap-2'>
                  {getStatusIcon(song)}
                  <span className='text-sm text-gray-900 dark:text-slate-100'>
                    {getStatusText(song)}
                  </span>
                </div>
              </td>
              <td className='px-6 py-4 whitespace-nowrap'>
                <div className='text-sm font-medium'>
                  <a
                    href={
                      song.deezerId
                        ? `https://www.deezer.com/track/${song.deezerId}`
                        : (song.spotifyUri ?? '').replace(
                            'spotify:track:',
                            'https://open.spotify.com/track/'
                          )
                    }
                    target='_blank'
                    rel='noopener noreferrer'
                    className='text-green-600 hover:text-green-800 hover:underline'
                    title={`Open ${song.name} on ${song.deezerId ? 'Deezer' : 'Spotify'}`}
                  >
                    {song.name}
                  </a>
                  {song.deezerId && song.spotifyUri && (
                    <a
                      href={(song.spotifyUri ?? '').replace(
                        'spotify:track:',
                        'https://open.spotify.com/track/'
                      )}
                      target='_blank'
                      rel='noopener noreferrer'
                      className='ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-50 dark:bg-green-950 text-green-600 dark:text-green-400 hover:bg-green-100 transition-colors'
                      title='Also available on Spotify'
                    >
                      Spotify
                    </a>
                  )}
                </div>
                <div className='text-sm text-gray-500 dark:text-slate-400'>
                  ID: {song.id}
                </div>
              </td>
              <td className='px-6 py-4 whitespace-nowrap'>
                <Link
                  to='/albums'
                  search={{ artistId: song.primaryArtistId }}
                  className='text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-900'
                  title={`View albums by ${song.primaryArtist}`}
                >
                  {song.primaryArtist}
                </Link>
              </td>
              <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
                {formatDate(song.createdAt)}
              </td>

              <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
                {formatBitrate(song.bitrate)}
              </td>
              <td className='px-6 py-4 text-sm text-gray-500 dark:text-slate-400 min-w-0'>
                {song.filePath ? (
                  <span
                    className='truncate max-w-md block'
                    title={song.filePath}
                  >
                    {song.filePath}
                  </span>
                ) : (
                  '-'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

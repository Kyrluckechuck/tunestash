import React from 'react';
import { useDeezerLinkingSection } from '../../hooks/useDeezerLinkingSection';
import { DeezerLinkRow } from './DeezerLinkRow';
import { SearchInput } from '../ui/SearchInput';
import { PaginationBar } from '../ui/PaginationBar';

export function DeezerLinkingSection() {
  const {
    artists,
    totalCount,
    totalPages,
    loading,
    error,

    page,
    setPage,

    searchTerm,
    handleSearchChange,
    hasDownloadsFilter,
    setHasDownloadsFilter,

    handleLink,
  } = useDeezerLinkingSection();

  return (
    <div className='space-y-4'>
      {/* Filters */}
      <div className='flex items-center gap-4 flex-wrap'>
        <SearchInput
          placeholder='Search unlinked artists...'
          onSearch={handleSearchChange}
          initialValue={searchTerm}
          className='w-64'
        />

        <div className='flex items-center gap-2'>
          <button
            onClick={() =>
              setHasDownloadsFilter(
                hasDownloadsFilter === true ? undefined : true
              )
            }
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
              hasDownloadsFilter === true
                ? 'bg-indigo-100 text-indigo-800 hover:bg-indigo-200'
                : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-500'
            }`}
          >
            Has Downloads
          </button>
          <button
            onClick={() =>
              setHasDownloadsFilter(
                hasDownloadsFilter === false ? undefined : false
              )
            }
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
              hasDownloadsFilter === false
                ? 'bg-indigo-100 text-indigo-800 hover:bg-indigo-200'
                : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-500'
            }`}
          >
            No Downloads
          </button>
        </div>

        <span className='text-sm text-gray-500 dark:text-slate-400'>
          {totalCount} unlinked artist{totalCount !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Error state */}
      {error && (
        <div className='p-4 bg-red-50 dark:bg-red-950 border border-red-200 rounded-lg text-red-700 dark:text-red-400'>
          Error loading artists: {error.message}
        </div>
      )}

      {/* Table */}
      <div className='bg-white dark:bg-slate-800 rounded shadow overflow-hidden'>
        <div className='overflow-x-auto'>
          <table className='min-w-full divide-y divide-gray-200 dark:divide-slate-700'>
            <thead className='bg-gray-50 dark:bg-slate-900'>
              <tr>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
                  Artist
                </th>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
                  Songs
                </th>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
                  Link to Deezer
                </th>
              </tr>
            </thead>
            <tbody className='bg-white dark:bg-slate-800 divide-y divide-gray-200 dark:divide-slate-700'>
              {artists.map(artist => (
                <DeezerLinkRow
                  key={artist.id}
                  artist={artist}
                  onLink={handleLink}
                />
              ))}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <PaginationBar
            page={page}
            totalPages={totalPages}
            totalCount={totalCount}
            pageSize={50}
            onPageChange={setPage}
            loading={loading}
          />
        )}
      </div>

      {/* Empty state */}
      {!loading && artists.length === 0 && (
        <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
          No unlinked artists found
        </div>
      )}

      {/* Loading state */}
      {loading && artists.length === 0 && (
        <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
          Loading artists...
        </div>
      )}
    </div>
  );
}

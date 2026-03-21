import React from 'react';
import { useDeezerLinkingSection } from '../../hooks/useDeezerLinkingSection';
import { DeezerLinkRow } from './DeezerLinkRow';
import { SearchInput } from '../ui/SearchInput';

export function DeezerLinkingSection() {
  const {
    artists,
    totalCount,
    pageInfo,
    loading,
    error,

    searchTerm,
    handleSearchChange,
    hasDownloadsFilter,
    setHasDownloadsFilter,

    handleLink,
    handleLoadMore,
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
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
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
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            No Downloads
          </button>
        </div>

        <span className='text-sm text-gray-500'>
          {totalCount} unlinked artist{totalCount !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Error state */}
      {error && (
        <div className='p-4 bg-red-50 border border-red-200 rounded-lg text-red-700'>
          Error loading artists: {error.message}
        </div>
      )}

      {/* Table */}
      <div className='bg-white rounded shadow overflow-hidden'>
        <div className='overflow-x-auto'>
          <table className='min-w-full divide-y divide-gray-200'>
            <thead className='bg-gray-50'>
              <tr>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider'>
                  Artist
                </th>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider'>
                  Songs
                </th>
                <th className='px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider'>
                  Link to Deezer
                </th>
              </tr>
            </thead>
            <tbody className='bg-white divide-y divide-gray-200'>
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
      </div>

      {/* Empty state */}
      {!loading && artists.length === 0 && (
        <div className='text-center py-8 text-gray-500'>
          No unlinked artists found
        </div>
      )}

      {/* Loading state */}
      {loading && artists.length === 0 && (
        <div className='text-center py-8 text-gray-500'>Loading artists...</div>
      )}

      {/* Load more */}
      {pageInfo?.hasNextPage && (
        <div className='p-4 text-center border-t border-gray-200'>
          <button
            onClick={handleLoadMore}
            disabled={loading}
            className='px-6 py-3 rounded font-medium transition-colors bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed'
          >
            {loading
              ? 'Loading...'
              : `Load More (${artists.length} of ${totalCount})`}
          </button>
        </div>
      )}
    </div>
  );
}

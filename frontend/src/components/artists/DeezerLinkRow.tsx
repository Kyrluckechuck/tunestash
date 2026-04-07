import React, { useState, useCallback } from 'react';
import { useLazyQuery } from '@apollo/client/react';
import {
  CatalogSearchDocument,
  PreviewDeezerArtistDocument,
} from '../../types/generated/graphql';

interface DeezerLinkRowProps {
  artist: {
    id: number;
    name: string;
    trackingTier: number;
    songCount: number;
    downloadedSongCount: number;
  };
  onLink: (artistId: number, deezerId: number) => Promise<unknown>;
}

export function DeezerLinkRow({ artist, onLink }: DeezerLinkRowProps) {
  const [linking, setLinking] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [manualId, setManualId] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);

  // Deezer catalog search (artist name → Deezer results)
  const [searchDeezer, { data: searchData, loading: searchLoading }] =
    useLazyQuery(CatalogSearchDocument, { fetchPolicy: 'network-only' });

  // Single-ID preview (for manual entry)
  const [fetchPreview, { data: previewData, loading: previewLoading }] =
    useLazyQuery(PreviewDeezerArtistDocument, {
      fetchPolicy: 'network-only',
    });

  const preview = showPreview
    ? (previewData?.previewDeezerArtist ?? null)
    : null;
  const searchResults = searchData?.catalogSearch?.artists ?? [];

  const handleSearch = useCallback(() => {
    setShowSearch(true);
    setInputError(null);
    searchDeezer({
      variables: { query: artist.name, types: ['artist'], limit: 5 },
    });
  }, [artist.name, searchDeezer]);

  const handleSelectResult = useCallback(
    (providerId: string) => {
      setShowSearch(false);
      setShowPreview(true);
      fetchPreview({ variables: { deezerId: parseInt(providerId, 10) } });
      setManualId(providerId);
    },
    [fetchPreview]
  );

  const handleManualPreview = useCallback(() => {
    setInputError(null);
    const parsed = parseInt(manualId, 10);
    if (!manualId || isNaN(parsed) || parsed <= 0) {
      setInputError('Enter a valid Deezer ID');
      return;
    }
    setShowSearch(false);
    setShowPreview(true);
    fetchPreview({ variables: { deezerId: parsed } });
  }, [manualId, fetchPreview]);

  const handleConfirm = useCallback(async () => {
    const deezerId = parseInt(manualId, 10);
    if (isNaN(deezerId)) return;
    setLinking(true);
    await onLink(artist.id, deezerId);
    setLinking(false);
  }, [manualId, artist.id, onLink]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        if (preview) {
          handleConfirm();
        } else {
          handleManualPreview();
        }
      }
    },
    [preview, handleConfirm, handleManualPreview]
  );

  const handleReset = useCallback(() => {
    setManualId('');
    setShowSearch(false);
    setShowPreview(false);
    setInputError(null);
  }, []);

  return (
    <>
      <tr className='hover:bg-gray-50 dark:hover:bg-slate-700'>
        <td className='px-6 py-4 whitespace-nowrap'>
          <div className='flex items-center gap-2'>
            <span className='text-sm font-medium text-gray-900 dark:text-slate-100'>
              {artist.name}
            </span>
            {artist.trackingTier >= 1 && (
              <span className='px-1.5 py-0.5 text-xs rounded-full bg-green-100 text-green-800'>
                Tracked
              </span>
            )}
          </div>
        </td>
        <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-slate-400'>
          {artist.downloadedSongCount}/{artist.songCount}
        </td>
        <td className='px-6 py-4 whitespace-nowrap'>
          <div className='flex items-center gap-2'>
            {/* Search Deezer button */}
            {!preview && (
              <button
                onClick={handleSearch}
                disabled={searchLoading}
                className='px-3 py-1 rounded text-xs font-medium bg-indigo-100 text-indigo-800 hover:bg-indigo-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
              >
                {searchLoading ? 'Searching...' : 'Search Deezer'}
              </button>
            )}

            {/* Manual ID fallback */}
            {!preview && (
              <>
                <input
                  type='text'
                  value={manualId}
                  onChange={e => {
                    setManualId(e.target.value);
                    setInputError(null);
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder='or enter ID'
                  className='w-24 px-2 py-1 text-xs border border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500'
                />
                {manualId && (
                  <button
                    onClick={handleManualPreview}
                    disabled={previewLoading}
                    className='px-2 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
                  >
                    {previewLoading ? '...' : 'Go'}
                  </button>
                )}
              </>
            )}

            {/* Preview match */}
            {preview && (
              <>
                <div className='flex items-center gap-2'>
                  {preview.imageUrl && (
                    <img
                      src={preview.imageUrl}
                      alt={preview.name}
                      className='w-6 h-6 rounded-full object-cover'
                    />
                  )}
                  <span className='px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800'>
                    {preview.name}
                  </span>
                </div>
                <button
                  onClick={handleConfirm}
                  disabled={linking}
                  className='px-3 py-1 rounded text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
                >
                  {linking ? 'Linking...' : 'Confirm Link'}
                </button>
                <button
                  onClick={handleReset}
                  className='px-2 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-500 transition-colors'
                >
                  Cancel
                </button>
              </>
            )}

            {inputError && (
              <span className='text-red-600 dark:text-red-400 text-xs'>
                {inputError}
              </span>
            )}
            {!previewLoading && previewData && !preview && (
              <span className='text-red-600 dark:text-red-400 text-xs'>
                Not found on Deezer
              </span>
            )}
          </div>
        </td>
      </tr>

      {/* Inline search results dropdown */}
      {showSearch && searchResults.length > 0 && (
        <tr>
          <td colSpan={3} className='px-6 py-0'>
            <div className='ml-0 mb-3 border border-gray-200 dark:border-slate-700 rounded-lg bg-gray-50 dark:bg-slate-900 overflow-hidden'>
              <div className='px-3 py-1.5 bg-gray-100 dark:bg-slate-700 text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
                Deezer results for &ldquo;{artist.name}&rdquo;
              </div>
              {searchResults.map(result => (
                <button
                  key={result.providerId}
                  onClick={() => handleSelectResult(result.providerId)}
                  className='w-full flex items-center gap-3 px-3 py-2 hover:bg-white dark:hover:bg-slate-800 transition-colors text-left border-t border-gray-100 dark:border-slate-700'
                >
                  {result.imageUrl ? (
                    <img
                      src={result.imageUrl}
                      alt={result.name}
                      className='w-8 h-8 rounded-full object-cover flex-shrink-0'
                    />
                  ) : (
                    <div className='w-8 h-8 rounded-full bg-gray-200 dark:bg-slate-600 flex items-center justify-center flex-shrink-0'>
                      <svg
                        className='w-4 h-4 text-gray-400 dark:text-slate-500'
                        fill='currentColor'
                        viewBox='0 0 24 24'
                      >
                        <path d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z' />
                      </svg>
                    </div>
                  )}
                  <div className='flex-1 min-w-0'>
                    <div className='text-sm font-medium text-gray-900 dark:text-slate-100 truncate'>
                      {result.name}
                    </div>
                    <div className='text-xs text-gray-500 dark:text-slate-400'>
                      ID: {result.providerId}
                    </div>
                  </div>
                  {result.inLibrary &&
                    result.localId !== null &&
                    result.localId !== artist.id && (
                      <span className='px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-800 rounded'>
                        Already Linked
                      </span>
                    )}
                </button>
              ))}
            </div>
          </td>
        </tr>
      )}

      {/* No results state */}
      {showSearch &&
        !searchLoading &&
        searchResults.length === 0 &&
        searchData && (
          <tr>
            <td colSpan={3} className='px-6 py-0'>
              <div className='ml-0 mb-3 px-3 py-2 border border-gray-200 dark:border-slate-700 rounded-lg bg-gray-50 dark:bg-slate-900 text-sm text-gray-500 dark:text-slate-400'>
                No Deezer artists found for &ldquo;{artist.name}&rdquo; — try
                entering an ID manually
              </div>
            </td>
          </tr>
        )}
    </>
  );
}

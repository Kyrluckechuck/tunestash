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
    isTracked: boolean;
    songCount: number;
    downloadedSongCount: number;
  };
  onLink: (artistId: number, deezerId: number) => Promise<unknown>;
}

export function DeezerLinkRow({ artist, onLink }: DeezerLinkRowProps) {
  const [linking, setLinking] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
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

  const preview = previewData?.previewDeezerArtist ?? null;
  const searchResults = searchData?.catalogSearch?.artists ?? [];

  const handleSearch = useCallback(() => {
    setShowSearch(true);
    setInputError(null);
    searchDeezer({
      variables: { query: artist.name, types: ['artist'], limit: 5 },
    });
  }, [artist.name, searchDeezer]);

  const handleSelectResult = useCallback(
    (providerId: string, name: string) => {
      setShowSearch(false);
      // Populate preview directly from search result
      fetchPreview({ variables: { deezerId: parseInt(providerId, 10) } });
      setManualId(providerId);
      // Suppress unused variable warning — name is used for future reference
      void name;
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
    setInputError(null);
  }, []);

  return (
    <>
      <tr className='hover:bg-gray-50'>
        <td className='px-6 py-4 whitespace-nowrap'>
          <div className='flex items-center gap-2'>
            <span className='text-sm font-medium text-gray-900'>
              {artist.name}
            </span>
            {artist.isTracked && (
              <span className='px-1.5 py-0.5 text-xs rounded-full bg-green-100 text-green-800'>
                Tracked
              </span>
            )}
          </div>
        </td>
        <td className='px-6 py-4 whitespace-nowrap text-sm text-gray-500'>
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
                  className='w-24 px-2 py-1 text-xs border border-gray-300 rounded bg-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500'
                />
                {manualId && (
                  <button
                    onClick={handleManualPreview}
                    disabled={previewLoading}
                    className='px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
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
                  className='px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors'
                >
                  Cancel
                </button>
              </>
            )}

            {inputError && (
              <span className='text-red-600 text-xs'>{inputError}</span>
            )}
            {!previewLoading && previewData && !preview && (
              <span className='text-red-600 text-xs'>Not found on Deezer</span>
            )}
          </div>
        </td>
      </tr>

      {/* Inline search results dropdown */}
      {showSearch && searchResults.length > 0 && (
        <tr>
          <td colSpan={3} className='px-6 py-0'>
            <div className='ml-0 mb-3 border border-gray-200 rounded-lg bg-gray-50 overflow-hidden'>
              <div className='px-3 py-1.5 bg-gray-100 text-xs font-medium text-gray-500 uppercase tracking-wider'>
                Deezer results for &ldquo;{artist.name}&rdquo;
              </div>
              {searchResults.map(result => (
                <button
                  key={result.providerId}
                  onClick={() =>
                    handleSelectResult(result.providerId, result.name)
                  }
                  className='w-full flex items-center gap-3 px-3 py-2 hover:bg-white transition-colors text-left border-t border-gray-100'
                >
                  {result.imageUrl ? (
                    <img
                      src={result.imageUrl}
                      alt={result.name}
                      className='w-8 h-8 rounded-full object-cover flex-shrink-0'
                    />
                  ) : (
                    <div className='w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0'>
                      <svg
                        className='w-4 h-4 text-gray-400'
                        fill='currentColor'
                        viewBox='0 0 24 24'
                      >
                        <path d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z' />
                      </svg>
                    </div>
                  )}
                  <div className='flex-1 min-w-0'>
                    <div className='text-sm font-medium text-gray-900 truncate'>
                      {result.name}
                    </div>
                    <div className='text-xs text-gray-500'>
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
              <div className='ml-0 mb-3 px-3 py-2 border border-gray-200 rounded-lg bg-gray-50 text-sm text-gray-500'>
                No Deezer artists found for &ldquo;{artist.name}&rdquo; — try
                entering an ID manually
              </div>
            </td>
          </tr>
        )}
    </>
  );
}

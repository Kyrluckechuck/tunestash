import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useLazyQuery, useMutation } from '@apollo/client/react';
import { useNavigate } from '@tanstack/react-router';
import type { CatalogSearchQuery } from '../../types/generated/graphql';
import {
  CatalogSearchDocument,
  TrackArtistDocument,
  UntrackArtistDocument,
  ImportArtistDocument,
  ImportAlbumDocument,
} from '../../types/generated/graphql';
import { useToast } from './useToast';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabType = 'all' | 'artists' | 'albums' | 'tracks';

const DEBOUNCE_MS = 400;

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
}) => {
  const toast = useToast();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  const [executeSearch, { data, loading, error }] =
    useLazyQuery<CatalogSearchQuery>(CatalogSearchDocument);

  const [trackArtist] = useMutation(TrackArtistDocument);
  const [untrackArtist] = useMutation(UntrackArtistDocument);
  const [importArtist] = useMutation(ImportArtistDocument);
  const [importAlbum] = useMutation(ImportAlbumDocument);

  // Focus input when modal opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setActiveTab('all');
      setLoadingIds(new Set());
    }
  }, [isOpen]);

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        isOpen &&
        modalRef.current &&
        !modalRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, onClose]);

  const startLoading = useCallback((id: string) => {
    setLoadingIds(prev => new Set(prev).add(id));
  }, []);

  const stopLoading = useCallback((id: string) => {
    setLoadingIds(prev => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (query.trim().length < 2) return;

    debounceRef.current = setTimeout(() => {
      const types =
        activeTab === 'all'
          ? ['artist', 'album', 'track']
          : [activeTab.slice(0, -1)]; // Remove trailing 's'

      executeSearch({
        variables: {
          query: query.trim(),
          types,
          limit: 10,
        },
      });
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [query, activeTab, executeSearch]);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Build refetch queries for search results
  const getSearchRefetchQueries = useCallback(() => {
    if (query.trim().length < 2) return [];
    return [
      {
        query: CatalogSearchDocument,
        variables: {
          query: query.trim(),
          types:
            activeTab === 'all'
              ? ['artist', 'album', 'track']
              : [activeTab.slice(0, -1)],
          limit: 10,
        },
      },
    ];
  }, [query, activeTab]);

  const handleTrackArtist = useCallback(
    async (
      providerId: string,
      localId: number | null,
      name: string,
      isInLibrary: boolean
    ) => {
      startLoading(providerId);
      try {
        if (localId && isInLibrary) {
          await trackArtist({
            variables: { artistId: localId },
            refetchQueries: getSearchRefetchQueries(),
          });
          toast.success(`Now tracking "${name}"`);
        } else {
          const result = await importArtist({
            variables: {
              deezerId: parseInt(providerId, 10),
              name,
            },
            refetchQueries: getSearchRefetchQueries(),
          });
          const msg =
            result.data?.importArtist?.message || `Adding "${name}" to library`;
          toast.success(msg);
        }
      } catch (err) {
        toast.error(`Failed to track artist: ${err}`);
      } finally {
        stopLoading(providerId);
      }
    },
    [
      trackArtist,
      importArtist,
      toast,
      getSearchRefetchQueries,
      startLoading,
      stopLoading,
    ]
  );

  const handleUntrackArtist = useCallback(
    async (providerId: string, artistId: number, name: string) => {
      startLoading(providerId);
      try {
        await untrackArtist({
          variables: { artistId },
          refetchQueries: getSearchRefetchQueries(),
        });
        toast.success(`Stopped tracking "${name}"`);
      } catch (err) {
        toast.error(`Failed to untrack artist: ${err}`);
      } finally {
        stopLoading(providerId);
      }
    },
    [untrackArtist, toast, getSearchRefetchQueries, startLoading, stopLoading]
  );

  const handleImportAlbum = useCallback(
    async (providerId: string, name: string) => {
      startLoading(providerId);
      try {
        const result = await importAlbum({
          variables: { deezerId: parseInt(providerId, 10) },
          refetchQueries: getSearchRefetchQueries(),
        });
        if (result.data?.importAlbum?.success) {
          toast.success(
            result.data.importAlbum.message || `Added "${name}" to library`
          );
        } else {
          toast.error(
            result.data?.importAlbum?.message || `Failed to add "${name}"`
          );
        }
      } catch (err) {
        toast.error(`Failed to add album: ${err}`);
      } finally {
        stopLoading(providerId);
      }
    },
    [importAlbum, toast, getSearchRefetchQueries, startLoading, stopLoading]
  );

  const handleNavigate = useCallback(
    (path: string) => {
      onClose();
      navigate({ to: path });
    },
    [onClose, navigate]
  );

  const results = data?.catalogSearch;
  const hasResults =
    results &&
    (results.artists.length > 0 ||
      results.albums.length > 0 ||
      results.tracks.length > 0);

  if (!isOpen) return null;

  const tabs: { id: TabType; label: string; count?: number }[] = [
    { id: 'all', label: 'All' },
    { id: 'artists', label: 'Artists', count: results?.artists.length },
    { id: 'albums', label: 'Albums', count: results?.albums.length },
    { id: 'tracks', label: 'Tracks', count: results?.tracks.length },
  ];

  return (
    <div className='fixed inset-0 bg-black bg-opacity-50 flex items-start justify-center z-50 pt-[10vh]'>
      <div
        ref={modalRef}
        className='bg-white dark:bg-slate-800 rounded-lg w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col shadow-2xl'
      >
        {/* Header with search input */}
        <div className='p-4 border-b dark:border-slate-700'>
          <div className='flex items-center gap-3'>
            <svg
              className='w-5 h-5 text-gray-400 dark:text-slate-500'
              fill='none'
              stroke='currentColor'
              viewBox='0 0 24 24'
            >
              <path
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth={2}
                d='M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z'
              />
            </svg>
            <input
              ref={inputRef}
              type='text'
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder='Search for artists, albums, or tracks...'
              className='flex-1 text-lg outline-none placeholder-gray-400 dark:placeholder-slate-500 dark:bg-slate-800 dark:text-slate-100'
            />
            <button
              onClick={onClose}
              className='text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 p-1'
            >
              <svg
                className='w-5 h-5'
                fill='none'
                stroke='currentColor'
                viewBox='0 0 24 24'
              >
                <path
                  strokeLinecap='round'
                  strokeLinejoin='round'
                  strokeWidth={2}
                  d='M6 18L18 6M6 6l12 12'
                />
              </svg>
            </button>
          </div>

          {/* Tabs */}
          {query.trim().length >= 2 && (
            <div className='flex gap-1 mt-3'>
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                    activeTab === tab.id
                      ? 'bg-indigo-100 dark:bg-blue-900/30 text-indigo-700'
                      : 'text-gray-600 dark:text-slate-400 hover:text-gray-800 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600'
                  }`}
                >
                  {tab.label}
                  {tab.count !== undefined && tab.count > 0 && (
                    <span className='ml-1 text-xs opacity-70'>
                      ({tab.count})
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Results */}
        <div className='flex-1 overflow-y-auto'>
          {loading && (
            <div className='flex items-center justify-center py-12'>
              <svg
                className='animate-spin h-8 w-8 text-indigo-600 dark:text-blue-400'
                fill='none'
                viewBox='0 0 24 24'
              >
                <circle
                  className='opacity-25'
                  cx='12'
                  cy='12'
                  r='10'
                  stroke='currentColor'
                  strokeWidth='4'
                />
                <path
                  className='opacity-75'
                  fill='currentColor'
                  d='M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z'
                />
              </svg>
            </div>
          )}

          {error && (
            <div className='p-4 text-red-600 dark:text-red-400 text-center'>
              Search failed: {error.message}
            </div>
          )}

          {!loading && !error && query.trim().length < 2 && (
            <div className='flex flex-col items-center justify-center py-12 text-gray-500 dark:text-slate-400'>
              <svg
                className='w-12 h-12 mb-3 opacity-50'
                fill='none'
                stroke='currentColor'
                viewBox='0 0 24 24'
              >
                <path
                  strokeLinecap='round'
                  strokeLinejoin='round'
                  strokeWidth={1.5}
                  d='M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z'
                />
              </svg>
              <p>Type at least 2 characters to search</p>
            </div>
          )}

          {!loading && !error && query.trim().length >= 2 && !hasResults && (
            <div className='flex flex-col items-center justify-center py-12 text-gray-500 dark:text-slate-400'>
              <p>No results found for &ldquo;{query}&rdquo;</p>
            </div>
          )}

          {!loading && hasResults && (
            <div className='divide-y dark:divide-slate-700'>
              {/* Artists */}
              {(activeTab === 'all' || activeTab === 'artists') &&
                results.artists.length > 0 && (
                  <ResultSection title='Artists'>
                    {results.artists.map(artist => (
                      <ArtistResult
                        key={artist.providerId}
                        artist={artist}
                        onTrack={() =>
                          handleTrackArtist(
                            artist.providerId,
                            artist.localId ?? null,
                            artist.name,
                            artist.inLibrary
                          )
                        }
                        onUntrack={
                          artist.localId
                            ? () =>
                                handleUntrackArtist(
                                  artist.providerId,
                                  artist.localId as number,
                                  artist.name
                                )
                            : undefined
                        }
                        onNavigate={
                          artist.localId
                            ? () => handleNavigate(`/artists/${artist.localId}`)
                            : undefined
                        }
                        isLoading={loadingIds.has(artist.providerId)}
                      />
                    ))}
                  </ResultSection>
                )}

              {/* Albums */}
              {(activeTab === 'all' || activeTab === 'albums') &&
                results.albums.length > 0 && (
                  <ResultSection title='Albums'>
                    {results.albums.map(album => (
                      <AlbumResult
                        key={album.providerId}
                        album={album}
                        onImport={() =>
                          handleImportAlbum(album.providerId, album.name)
                        }
                        isLoading={loadingIds.has(album.providerId)}
                      />
                    ))}
                  </ResultSection>
                )}

              {/* Tracks */}
              {(activeTab === 'all' || activeTab === 'tracks') &&
                results.tracks.length > 0 && (
                  <ResultSection title='Tracks'>
                    {results.tracks.map(track => (
                      <TrackResult key={track.providerId} track={track} />
                    ))}
                  </ResultSection>
                )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className='px-4 py-2 border-t dark:border-slate-700 bg-gray-50 dark:bg-slate-900 text-xs text-gray-500 dark:text-slate-400 flex justify-between items-center rounded-b-lg'>
          <span>Press ESC to close</span>
          <span>Powered by Deezer</span>
        </div>
      </div>
    </div>
  );
};

// Sub-components

interface ResultSectionProps {
  title: string;
  children: React.ReactNode;
}

const ResultSection: React.FC<ResultSectionProps> = ({ title, children }) => (
  <div className='py-2'>
    <h3 className='px-4 py-1 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider'>
      {title}
    </h3>
    <div>{children}</div>
  </div>
);

const ButtonSpinner: React.FC = () => (
  <svg className='animate-spin h-4 w-4' fill='none' viewBox='0 0 24 24'>
    <circle
      className='opacity-25'
      cx='12'
      cy='12'
      r='10'
      stroke='currentColor'
      strokeWidth='4'
    />
    <path
      className='opacity-75'
      fill='currentColor'
      d='M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z'
    />
  </svg>
);

const ExternalLinkIcon: React.FC = () => (
  <svg
    className='w-4 h-4'
    fill='none'
    stroke='currentColor'
    viewBox='0 0 24 24'
  >
    <path
      strokeLinecap='round'
      strokeLinejoin='round'
      strokeWidth={2}
      d='M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14'
    />
  </svg>
);

interface ArtistResultProps {
  artist: CatalogSearchQuery['catalogSearch']['artists'][0];
  onTrack: () => void;
  onUntrack?: () => void;
  onNavigate?: () => void;
  isLoading: boolean;
}

const ArtistResult: React.FC<ArtistResultProps> = ({
  artist,
  onTrack,
  onUntrack,
  onNavigate,
  isLoading,
}) => (
  <div className='flex items-center gap-3 px-4 py-2 hover:bg-gray-50 dark:hover:bg-slate-700'>
    {artist.imageUrl ? (
      <img
        src={artist.imageUrl}
        alt={artist.name}
        className='w-12 h-12 rounded-full object-cover'
      />
    ) : (
      <div className='w-12 h-12 rounded-full bg-gray-200 dark:bg-slate-600 flex items-center justify-center'>
        <svg
          className='w-6 h-6 text-gray-400 dark:text-slate-500'
          fill='currentColor'
          viewBox='0 0 24 24'
        >
          <path d='M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z' />
        </svg>
      </div>
    )}
    <div className='flex-1 min-w-0'>
      <div className='font-medium text-gray-900 dark:text-slate-100 truncate'>
        {artist.name}
      </div>
    </div>
    <div className='flex items-center gap-2'>
      {artist.inLibrary && artist.trackingTier === 0 && (
        <span className='px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded'>
          In Library
        </span>
      )}
      {artist.externalUrl && (
        <a
          href={artist.externalUrl}
          target='_blank'
          rel='noopener noreferrer'
          className='px-3 py-1 text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600 rounded'
          title='View on Deezer'
        >
          <ExternalLinkIcon />
        </a>
      )}
      {onNavigate && (
        <button
          onClick={onNavigate}
          className='px-3 py-1 text-sm text-indigo-600 dark:text-blue-400 hover:text-indigo-700 hover:bg-indigo-50 rounded'
        >
          View
        </button>
      )}
      {artist.trackingTier >= 1 && onUntrack ? (
        <button
          onClick={onUntrack}
          disabled={isLoading}
          className='px-3 py-1 text-sm bg-orange-100 text-orange-800 rounded hover:bg-orange-200 disabled:opacity-50 min-w-[70px] flex items-center justify-center'
        >
          {isLoading ? <ButtonSpinner /> : 'Untrack'}
        </button>
      ) : (
        <button
          onClick={onTrack}
          disabled={isLoading}
          className='px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 min-w-[70px] flex items-center justify-center'
        >
          {isLoading ? (
            <ButtonSpinner />
          ) : artist.inLibrary ? (
            'Start Tracking'
          ) : (
            'Track'
          )}
        </button>
      )}
    </div>
  </div>
);

interface AlbumResultProps {
  album: CatalogSearchQuery['catalogSearch']['albums'][0];
  onImport: () => void;
  isLoading: boolean;
}

const AlbumResult: React.FC<AlbumResultProps> = ({
  album,
  onImport,
  isLoading,
}) => (
  <div className='flex items-center gap-3 px-4 py-2 hover:bg-gray-50 dark:hover:bg-slate-700'>
    {album.imageUrl ? (
      <img
        src={album.imageUrl}
        alt={album.name}
        className='w-12 h-12 rounded object-cover'
      />
    ) : (
      <div className='w-12 h-12 rounded bg-gray-200 dark:bg-slate-600 flex items-center justify-center'>
        <svg
          className='w-6 h-6 text-gray-400 dark:text-slate-500'
          fill='currentColor'
          viewBox='0 0 24 24'
        >
          <path d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 14.5c-2.49 0-4.5-2.01-4.5-4.5S9.51 7.5 12 7.5s4.5 2.01 4.5 4.5-2.01 4.5-4.5 4.5zm0-5.5c-.55 0-1 .45-1 1s.45 1 1 1 1-.45 1-1-.45-1-1-1z' />
        </svg>
      </div>
    )}
    <div className='flex-1 min-w-0'>
      <div className='font-medium text-gray-900 dark:text-slate-100 truncate'>
        {album.name}
      </div>
      <div className='text-sm text-gray-500 dark:text-slate-400 truncate'>
        {album.artistName}
        {' · '}
        {album.albumType} · {album.totalTracks} tracks
        {album.releaseDate && (
          <span className='ml-1'>· {album.releaseDate.slice(0, 4)}</span>
        )}
      </div>
    </div>
    <div className='flex items-center gap-2'>
      {album.inLibrary && (
        <span className='px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded'>
          In Library
        </span>
      )}
      {album.externalUrl && (
        <a
          href={album.externalUrl}
          target='_blank'
          rel='noopener noreferrer'
          className='px-3 py-1 text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600 rounded'
          title='View on Deezer'
        >
          <ExternalLinkIcon />
        </a>
      )}
      <button
        onClick={onImport}
        disabled={isLoading}
        className='px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 min-w-[100px] flex items-center justify-center'
      >
        {isLoading ? <ButtonSpinner /> : 'Add to Library'}
      </button>
    </div>
  </div>
);

interface TrackResultProps {
  track: CatalogSearchQuery['catalogSearch']['tracks'][0];
}

const TrackResult: React.FC<TrackResultProps> = ({ track }) => {
  const formatDuration = (ms: number) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  return (
    <div className='flex items-center gap-3 px-4 py-2 hover:bg-gray-50 dark:hover:bg-slate-700'>
      <div className='w-10 h-10 rounded bg-gray-200 dark:bg-slate-600 flex items-center justify-center'>
        <svg
          className='w-5 h-5 text-gray-400 dark:text-slate-500'
          fill='currentColor'
          viewBox='0 0 24 24'
        >
          <path d='M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z' />
        </svg>
      </div>
      <div className='flex-1 min-w-0'>
        <div className='font-medium text-gray-900 dark:text-slate-100 truncate'>
          {track.name}
        </div>
        <div className='text-sm text-gray-500 dark:text-slate-400 truncate'>
          {track.artistName}
          {track.albumName && (
            <>
              {' · '}
              {track.albumName}
            </>
          )}
        </div>
      </div>
      <div className='text-sm text-gray-400 dark:text-slate-500'>
        {formatDuration(track.durationMs)}
      </div>
      <div className='flex items-center gap-2'>
        {track.inLibrary && (
          <span className='px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded'>
            In Library
          </span>
        )}
        {track.externalUrl && (
          <a
            href={track.externalUrl}
            target='_blank'
            rel='noopener noreferrer'
            className='px-3 py-1 text-sm text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-600 rounded'
            title='View on Deezer'
          >
            <ExternalLinkIcon />
          </a>
        )}
      </div>
    </div>
  );
};

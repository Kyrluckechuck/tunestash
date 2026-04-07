import { useState, useEffect, useRef } from 'react';
import { useMutation, useLazyQuery } from '@apollo/client/react';
import {
  UpdatePlaylistDocument,
  CreatePlaylistDocument,
  GetPlaylistsDocument,
  GetPlaylistInfoDocument,
  type UpdatePlaylistMutation,
  type UpdatePlaylistMutationVariables,
  type Playlist,
} from '../../types/generated/graphql';

// Regex to detect valid Spotify or Deezer playlist URLs/URIs
const PLAYLIST_URL_REGEX =
  /^(spotify:playlist:[a-zA-Z0-9]+|https?:\/\/open\.spotify\.com\/playlist\/[a-zA-Z0-9]+|https?:\/\/(www\.)?deezer\.com\/(\w+\/)?playlist\/\d+)/;

interface PlaylistModalProps {
  isOpen: boolean;
  onClose: () => void;
  playlist?: Playlist | null;
  mode: 'create' | 'edit';
}

export function PlaylistModal({
  isOpen,
  onClose,
  playlist,
  mode,
}: PlaylistModalProps) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [autoTrackTier, setAutoTrackTier] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Track whether user has manually edited the name field
  const [nameManuallyEdited, setNameManuallyEdited] = useState(false);
  // Track the last URL we fetched info for (to avoid duplicate fetches)
  const lastFetchedUrlRef = useRef<string>('');

  const [updatePlaylist] = useMutation<
    UpdatePlaylistMutation,
    UpdatePlaylistMutationVariables
  >(UpdatePlaylistDocument, {
    refetchQueries: [{ query: GetPlaylistsDocument }],
  });

  const [createPlaylist] = useMutation(CreatePlaylistDocument, {
    refetchQueries: [{ query: GetPlaylistsDocument }],
  });

  const [fetchPlaylistInfo, { loading: fetchingInfo, data: playlistInfoData }] =
    useLazyQuery(GetPlaylistInfoDocument, {
      fetchPolicy: 'network-only',
    });

  // Handle playlist info fetch results
  useEffect(() => {
    if (playlistInfoData?.playlistInfo && !nameManuallyEdited) {
      setName(playlistInfoData.playlistInfo.name);
    }
  }, [playlistInfoData, nameManuallyEdited]);

  // Initialize form when editing
  useEffect(() => {
    if (playlist && mode === 'edit') {
      setName(playlist.name);
      setUrl(playlist.url);
      setAutoTrackTier(playlist.autoTrackTier ?? null);
      setNameManuallyEdited(true); // Don't overwrite existing playlist names
    } else {
      setName('');
      setUrl('');
      setAutoTrackTier(null);
      setNameManuallyEdited(false);
      lastFetchedUrlRef.current = '';
    }
    setError(null);
  }, [playlist, mode]);

  // Debounced effect to fetch playlist info when URL changes
  useEffect(() => {
    // Only fetch in create mode
    if (mode !== 'create') return;

    const trimmedUrl = url.trim();

    // Check if URL matches a playlist pattern (Spotify or Deezer)
    if (!PLAYLIST_URL_REGEX.test(trimmedUrl)) return;

    // Don't fetch if we already fetched this URL
    if (trimmedUrl === lastFetchedUrlRef.current) return;

    // Debounce the fetch
    const timeoutId = setTimeout(() => {
      lastFetchedUrlRef.current = trimmedUrl;
      fetchPlaylistInfo({ variables: { url: trimmedUrl } });
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [url, mode, fetchPlaylistInfo]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      setError('Please enter a playlist name');
      return;
    }

    if (!url.trim()) {
      setError('Please enter a playlist URL or URI');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      if (mode === 'create') {
        const result = await createPlaylist({
          variables: {
            name: name.trim(),
            url: url.trim(),
            autoTrackTier: autoTrackTier,
          },
        });

        if (result.data?.createPlaylist) {
          setName('');
          setUrl('');
          setAutoTrackTier(null);
          onClose();
        } else {
          setError('Failed to create playlist');
        }
      } else {
        const result = await updatePlaylist({
          variables: {
            playlistId: playlist?.id ?? 0,
            name: name.trim(),
            url: url.trim(),
            autoTrackTier: autoTrackTier,
          },
        });

        if (result.data?.updatePlaylist?.success) {
          setName('');
          setUrl('');
          setAutoTrackTier(null);
          onClose();
        } else {
          setError(
            result.data?.updatePlaylist?.message || 'Failed to update playlist'
          );
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setName('');
      setUrl('');
      setAutoTrackTier(null);
      setError(null);
      setNameManuallyEdited(false);
      lastFetchedUrlRef.current = '';
      onClose();
    }
  };

  const handleNameChange = (value: string) => {
    setName(value);
    // Mark as manually edited so we don't overwrite user's input
    setNameManuallyEdited(true);
  };

  if (!isOpen) return null;

  const title = mode === 'create' ? 'Create Playlist' : 'Edit Playlist';
  const submitText = mode === 'create' ? 'Create Playlist' : 'Update Playlist';

  return (
    <div className='fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50'>
      <div className='bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-md w-full mx-4'>
        <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
          <h3 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
            {title}
          </h3>
          <p className='text-sm text-gray-600 dark:text-slate-400 mt-1'>
            {mode === 'create'
              ? 'Create a new playlist and choose whether to auto-track artists'
              : 'Update the playlist name'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className='px-6 py-4'>
          <div className='mb-4'>
            <label
              htmlFor='url'
              className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
            >
              Playlist URL
            </label>
            <input
              type='text'
              id='url'
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder='Spotify or Deezer playlist URL'
              className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 dark:bg-slate-700 dark:text-slate-100'
              disabled={isSubmitting}
            />
            <p className='text-xs text-gray-500 dark:text-slate-400 mt-1'>
              Paste a playlist link to auto-fill the name
            </p>
          </div>

          <div className='mb-4'>
            <label
              htmlFor='name'
              className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
            >
              Playlist Name
              {fetchingInfo && (
                <span className='ml-2 text-xs text-gray-400 dark:text-slate-500 font-normal'>
                  Loading...
                </span>
              )}
            </label>
            <input
              type='text'
              id='name'
              value={name}
              onChange={e => handleNameChange(e.target.value)}
              placeholder={
                fetchingInfo
                  ? 'Fetching playlist name...'
                  : 'Enter playlist name'
              }
              className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 dark:bg-slate-700 dark:text-slate-100'
              disabled={isSubmitting}
            />
          </div>

          <div className='mb-6'>
            <label
              htmlFor='autoTrackTier'
              className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
            >
              Auto-track artists
            </label>
            <select
              id='autoTrackTier'
              value={autoTrackTier ?? ''}
              onChange={e => {
                const val = e.target.value;
                setAutoTrackTier(val === '' ? null : parseInt(val));
              }}
              className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 dark:bg-slate-700 dark:text-slate-100'
              disabled={isSubmitting}
            >
              <option value=''>Off</option>
              <option value={1}>Tracked</option>
              <option value={2}>Favourite</option>
            </select>
            <p className='text-xs text-gray-500 dark:text-slate-400 mt-1'>
              Automatically set this tracking tier for all artists found in this
              playlist
            </p>
          </div>

          {error && (
            <div className='mb-4 p-3 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-md'>
              <p className='text-sm text-red-600 dark:text-red-400'>{error}</p>
            </div>
          )}

          <div className='flex justify-end gap-3'>
            <button
              type='button'
              onClick={handleClose}
              disabled={isSubmitting}
              className='px-4 py-2 text-sm font-medium text-gray-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md hover:bg-gray-50 dark:hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50'
            >
              Cancel
            </button>
            <button
              type='submit'
              disabled={isSubmitting || !name.trim() || !url.trim()}
              className='px-4 py-2 text-sm font-medium text-white bg-indigo-600 border border-transparent rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50'
            >
              {isSubmitting ? 'Updating...' : submitText}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

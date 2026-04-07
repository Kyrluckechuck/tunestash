import { useState, useEffect, useMemo } from 'react';

export interface CreateExternalListFormData {
  source: string;
  listType: string;
  username: string;
  period?: string;
  listIdentifier?: string;
  autoTrackTier: number | null;
}

export interface EditExternalListFields {
  name?: string;
  username?: string;
  period?: string;
  listIdentifier?: string;
}

export interface EditingExternalList {
  id: number;
  name: string;
  source: string;
  listType: string;
  username: string;
  period?: string | null;
  listIdentifier?: string | null;
}

interface ExternalListModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: CreateExternalListFormData) => Promise<boolean>;
  onEdit?: (listId: number, fields: EditExternalListFields) => Promise<boolean>;
  editingList?: EditingExternalList | null;
}

const SOURCE_OPTIONS = [
  { value: 'lastfm', label: 'Last.fm' },
  { value: 'listenbrainz', label: 'ListenBrainz' },
  { value: 'youtube_music', label: 'YouTube Music' },
];

const LIST_TYPE_OPTIONS: Record<string, { value: string; label: string }[]> = {
  lastfm: [
    { value: 'loved', label: 'Loved Tracks' },
    { value: 'top', label: 'Top Tracks' },
    { value: 'chart', label: 'Chart' },
  ],
  listenbrainz: [
    { value: 'loved', label: 'Loved Tracks' },
    { value: 'top', label: 'Top Tracks' },
    { value: 'playlist', label: 'Playlist' },
    { value: 'chart', label: 'Chart' },
  ],
  youtube_music: [
    { value: 'playlist', label: 'Playlist' },
    { value: 'loved', label: 'Liked Songs' },
  ],
};

const PERIOD_OPTIONS: Record<string, { value: string; label: string }[]> = {
  lastfm: [
    { value: '7day', label: 'Last 7 days' },
    { value: '1month', label: 'Last month' },
    { value: '3month', label: 'Last 3 months' },
    { value: '6month', label: 'Last 6 months' },
    { value: '12month', label: 'Last 12 months' },
    { value: 'overall', label: 'All time' },
  ],
  listenbrainz: [
    { value: 'this_week', label: 'This week' },
    { value: 'this_month', label: 'This month' },
    { value: 'this_year', label: 'This year' },
    { value: 'all_time', label: 'All time' },
  ],
};

function sourceLabel(source: string): string {
  return SOURCE_OPTIONS.find(o => o.value === source)?.label || source;
}

function typeLabel(source: string, listType: string): string {
  return (
    LIST_TYPE_OPTIONS[source]?.find(o => o.value === listType)?.label ||
    listType
  );
}

export function ExternalListModal({
  isOpen,
  onClose,
  onSubmit,
  onEdit,
  editingList,
}: ExternalListModalProps) {
  const isEditMode = !!editingList;

  const [name, setName] = useState('');
  const [source, setSource] = useState('lastfm');
  const [listType, setListType] = useState('loved');
  const [username, setUsername] = useState('');
  const [period, setPeriod] = useState('');
  const [listIdentifier, setListIdentifier] = useState('');
  const [autoTrackTier, setAutoTrackTier] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const availableTypes = useMemo(
    () => LIST_TYPE_OPTIONS[source] || [],
    [source]
  );

  const availablePeriods = useMemo(
    () => PERIOD_OPTIONS[source] || [],
    [source]
  );

  const isYouTubeMusic = source === 'youtube_music';
  const showPeriod = listType === 'top';
  const showUsername = !isYouTubeMusic;
  const showListIdentifier =
    listType === 'playlist' || (listType === 'chart' && !isYouTubeMusic);

  // Reset dependent fields when source changes (create mode only)
  useEffect(() => {
    if (isEditMode) return;
    const types = LIST_TYPE_OPTIONS[source] || [];
    if (!types.find(t => t.value === listType)) {
      setListType(types[0]?.value || 'loved');
    }
    setPeriod('');
    setListIdentifier('');
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  // Set default period when switching to top tracks (create mode only)
  useEffect(() => {
    if (isEditMode) return;
    if (listType === 'top' && !period) {
      const periods = PERIOD_OPTIONS[source] || [];
      setPeriod(periods[0]?.value || '');
    }
  }, [listType, source]); // eslint-disable-line react-hooks/exhaustive-deps

  // Initialize form on open
  useEffect(() => {
    if (!isOpen) return;
    setError(null);

    if (editingList) {
      setName(editingList.name);
      setSource(editingList.source);
      setListType(editingList.listType);
      setUsername(editingList.username);
      setPeriod(editingList.period || '');
      setListIdentifier(editingList.listIdentifier || '');
    } else {
      setName('');
      setSource('lastfm');
      setListType('loved');
      setUsername('');
      setPeriod('');
      setListIdentifier('');
      setAutoTrackTier(null);
    }
  }, [isOpen, editingList]);

  const listIdentifierLabel = useMemo(() => {
    if (listType === 'playlist') {
      if (isYouTubeMusic) return 'Playlist URL or ID';
      return 'Playlist MBID or URL';
    }
    if (listType === 'chart') {
      if (source === 'lastfm')
        return 'Chart type (e.g. "global", "rock", "US")';
      return 'Chart identifier';
    }
    return 'Identifier';
  }, [listType, source, isYouTubeMusic]);

  const listIdentifierPlaceholder = useMemo(() => {
    if (listType === 'playlist') {
      if (isYouTubeMusic)
        return 'https://music.youtube.com/playlist?list=... or playlist ID';
      return 'https://listenbrainz.org/playlist/... or MBID';
    }
    if (listType === 'chart') {
      if (source === 'lastfm') return 'global, rock, US, etc.';
      return 'Chart identifier';
    }
    return '';
  }, [listType, source, isYouTubeMusic]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (showUsername && !username.trim()) {
      setError('Please enter a username or profile URL');
      return;
    }

    if (showPeriod && !period) {
      setError('Please select a time period');
      return;
    }

    if (showListIdentifier && !listIdentifier.trim()) {
      setError(
        `Please enter a ${listType === 'playlist' ? (isYouTubeMusic ? 'playlist URL or ID' : 'playlist MBID or URL') : 'chart identifier'}`
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      let success: boolean;

      if (isEditMode && onEdit && editingList) {
        const fields: EditExternalListFields = {};
        if (name.trim() !== editingList.name) fields.name = name.trim();
        if (username.trim() !== editingList.username)
          fields.username = username.trim();
        const newPeriod = showPeriod ? period : undefined;
        if ((newPeriod || null) !== (editingList.period || null))
          fields.period = newPeriod || '';
        const newIdentifier = showListIdentifier
          ? listIdentifier.trim()
          : undefined;
        if ((newIdentifier || null) !== (editingList.listIdentifier || null))
          fields.listIdentifier = newIdentifier || '';

        success = await onEdit(editingList.id, fields);
      } else {
        success = await onSubmit({
          source,
          listType,
          username: username.trim(),
          period: showPeriod ? period : undefined,
          listIdentifier: showListIdentifier
            ? listIdentifier.trim()
            : undefined,
          autoTrackTier,
        });
      }

      if (success) {
        onClose();
      } else {
        setError(
          isEditMode
            ? 'Failed to update list'
            : 'Failed to create external list'
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className='fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50'>
      <div className='bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-md w-full mx-4'>
        <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
          <h3 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
            {isEditMode ? 'Edit External List' : 'Add External List'}
          </h3>
          <p className='text-sm text-gray-600 dark:text-slate-400 mt-1'>
            {isEditMode
              ? 'Update list settings. Source and type cannot be changed.'
              : 'Import tracks from Last.fm, ListenBrainz, or YouTube Music'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className='px-6 py-4'>
          {isEditMode && (
            <div className='mb-4'>
              <label
                htmlFor='el-name'
                className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
              >
                Name
              </label>
              <input
                type='text'
                id='el-name'
                value={name}
                onChange={e => setName(e.target.value)}
                className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
                disabled={isSubmitting}
              />
            </div>
          )}

          <div className='mb-4'>
            <label className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'>
              Source
            </label>
            {isEditMode ? (
              <span className='inline-block px-4 py-2 text-sm rounded-md border bg-gray-50 dark:bg-slate-900 border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-400'>
                {sourceLabel(source)}
              </span>
            ) : (
              <div className='flex gap-2'>
                {SOURCE_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    type='button'
                    onClick={() => setSource(opt.value)}
                    className={`px-4 py-2 text-sm rounded-md border transition-colors ${
                      source === opt.value
                        ? 'bg-indigo-50 dark:bg-blue-950 border-indigo-300 text-indigo-700 dark:text-blue-400'
                        : 'bg-white dark:bg-slate-700 border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-600'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className='mb-4'>
            <label className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'>
              List Type
            </label>
            {isEditMode ? (
              <span className='inline-block px-3 py-1.5 text-sm rounded-md border bg-gray-50 dark:bg-slate-900 border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-400'>
                {typeLabel(source, listType)}
              </span>
            ) : (
              <div className='flex flex-wrap gap-2'>
                {availableTypes.map(opt => (
                  <button
                    key={opt.value}
                    type='button'
                    onClick={() => setListType(opt.value)}
                    className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                      listType === opt.value
                        ? 'bg-indigo-50 dark:bg-blue-950 border-indigo-300 text-indigo-700 dark:text-blue-400'
                        : 'bg-white dark:bg-slate-700 border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-600'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {showUsername && (
            <div className='mb-4'>
              <label
                htmlFor='el-username'
                className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
              >
                Username or Profile URL
              </label>
              <input
                type='text'
                id='el-username'
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder={
                  source === 'lastfm'
                    ? 'username or https://www.last.fm/user/...'
                    : 'username or https://listenbrainz.org/user/...'
                }
                className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
                disabled={isSubmitting}
              />
            </div>
          )}

          {showPeriod && (
            <div className='mb-4'>
              <label
                htmlFor='el-period'
                className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
              >
                Time Period
              </label>
              <select
                id='el-period'
                value={period}
                onChange={e => setPeriod(e.target.value)}
                className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
                disabled={isSubmitting}
              >
                <option value=''>Select period...</option>
                {availablePeriods.map(opt => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {showListIdentifier && (
            <div className='mb-4'>
              <label
                htmlFor='el-identifier'
                className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
              >
                {listIdentifierLabel}
              </label>
              <input
                type='text'
                id='el-identifier'
                value={listIdentifier}
                onChange={e => setListIdentifier(e.target.value)}
                placeholder={listIdentifierPlaceholder}
                className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
                disabled={isSubmitting}
              />
            </div>
          )}

          {!isEditMode && (
            <div className='mb-6'>
              <label
                htmlFor='el-autoTrackTier'
                className='block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2'
              >
                Auto-track artists
              </label>
              <select
                id='el-autoTrackTier'
                value={autoTrackTier ?? ''}
                onChange={e => {
                  const val = e.target.value;
                  setAutoTrackTier(val === '' ? null : parseInt(val));
                }}
                className='w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'
                disabled={isSubmitting}
              >
                <option value=''>Off</option>
                <option value={1}>Tracked</option>
                <option value={2}>Favourite</option>
              </select>
              <p className='text-xs text-gray-500 dark:text-slate-400 mt-1'>
                Automatically set this tracking tier for all artists found in
                this list
              </p>
            </div>
          )}

          {error && (
            <div className='mb-4 p-3 bg-red-50 dark:bg-red-950 border border-red-200 rounded-md'>
              <p className='text-sm text-red-600 dark:text-red-400'>{error}</p>
            </div>
          )}

          <div className='flex justify-end gap-3'>
            <button
              type='button'
              onClick={handleClose}
              disabled={isSubmitting}
              className='px-4 py-2 text-sm font-medium text-gray-700 dark:text-slate-300 bg-white dark:bg-slate-700 border border-gray-300 dark:border-slate-600 rounded-md hover:bg-gray-50 dark:hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50'
            >
              Cancel
            </button>
            <button
              type='submit'
              disabled={
                isSubmitting ||
                (showUsername && !username.trim()) ||
                (showListIdentifier && !listIdentifier.trim()) ||
                (isEditMode && !name.trim())
              }
              className='px-4 py-2 text-sm font-medium text-white bg-indigo-600 border border-transparent rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50'
            >
              {isSubmitting
                ? isEditMode
                  ? 'Saving...'
                  : 'Creating...'
                : isEditMode
                  ? 'Save Changes'
                  : 'Add List'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

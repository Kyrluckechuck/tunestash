import { createFileRoute } from '@tanstack/react-router';

// Components
import { PlaylistFilters } from '../components/playlists/PlaylistFilters';
import { PlaylistsTable } from '../components/playlists/PlaylistsTable';
import { PageSizeSelector } from '../components/ui/PageSizeSelector';
import { InlineSpinner } from '../components/ui/InlineSpinner';
import { PageSpinner } from '../components/ui/PageSpinner';
import { ErrorBanner } from '../components/ui/ErrorBanner';
import { PaginationBar } from '../components/ui/PaginationBar';
import { PlaylistModal } from '../components/ui/PlaylistModal';
import { SearchInput } from '../components/ui/SearchInput';
import { ExternalListsSection } from '../components/external-lists/ExternalListsSection';

// Hooks
import { usePlaylistsPage } from '../hooks/usePlaylistsPage';

type PlaylistTab = 'synced' | 'external';

function Playlists() {
  const { tab } = Route.useSearch();
  const activeTab = tab || 'synced';
  const navigate = Route.useNavigate();
  const setActiveTab = (tab: string) => {
    navigate({ search: { tab } });
  };

  const {
    // Data
    playlists,
    totalCount,
    totalPages,
    loading,
    error,
    isRefreshing,
    isInitialLoading,
    issuesCount,

    // Pagination
    page,
    setPage,

    // Filters & sorting
    filter,
    pageSize,
    sortField,
    sortDirection,
    searchQuery,

    // Modal state
    showPlaylistModal,
    editingPlaylist,

    // Mutation states
    enabledMutatingIds,
    enabledPulseIds,
    autoMutatingIds,
    autoPulseIds,
    m3uMutatingIds,
    m3uPulseIds,
    syncMutatingIds,
    forceSyncMutatingIds,
    deleteMutatingIds,
    recheckMutatingIds,
    errorById,

    // Handlers
    handleEnabledFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleTogglePlaylist,
    handleSyncPlaylist,
    handleForceSyncPlaylist,
    handleRecheckPlaylist,
    handleDeletePlaylist,
    handleToggleAutoTrack,
    handleToggleM3u,
    handleEditPlaylist,
    handleClosePlaylistModal,
    handleCreatePlaylist,
    handleDownloadAllPlaylists,
  } = usePlaylistsPage();

  const tabClass = (tab: PlaylistTab) =>
    `px-4 py-2 text-sm font-medium rounded-t-md border-b-2 transition-colors ${
      activeTab === tab
        ? 'border-indigo-500 text-indigo-600 dark:text-blue-400'
        : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:border-gray-300 dark:hover:border-slate-600'
    }`;

  return (
    <section>
      <h1 className='text-2xl font-semibold mb-4'>Playlists</h1>

      <div className='flex gap-1 border-b border-gray-200 dark:border-slate-700 mb-6'>
        <button
          className={tabClass('synced')}
          onClick={() => setActiveTab('synced')}
        >
          Synced Playlists
        </button>
        <button
          className={tabClass('external')}
          onClick={() => setActiveTab('external')}
        >
          External Lists
        </button>
      </div>

      {activeTab === 'synced' && (
        <SyncedPlaylistsTab
          playlists={playlists}
          totalCount={totalCount}
          totalPages={totalPages}
          loading={loading}
          error={error}
          isRefreshing={isRefreshing}
          isInitialLoading={isInitialLoading}
          issuesCount={issuesCount}
          page={page}
          setPage={setPage}
          filter={filter}
          pageSize={pageSize}
          sortField={sortField}
          sortDirection={sortDirection}
          showPlaylistModal={showPlaylistModal}
          editingPlaylist={editingPlaylist}
          enabledMutatingIds={enabledMutatingIds}
          enabledPulseIds={enabledPulseIds}
          autoMutatingIds={autoMutatingIds}
          autoPulseIds={autoPulseIds}
          m3uMutatingIds={m3uMutatingIds}
          m3uPulseIds={m3uPulseIds}
          syncMutatingIds={syncMutatingIds}
          forceSyncMutatingIds={forceSyncMutatingIds}
          deleteMutatingIds={deleteMutatingIds}
          recheckMutatingIds={recheckMutatingIds}
          errorById={errorById}
          searchQuery={searchQuery}
          handleEnabledFilterChange={handleEnabledFilterChange}
          handlePageSizeChange={handlePageSizeChange}
          handleSort={handleSort}
          handleSearch={handleSearch}
          handleTogglePlaylist={handleTogglePlaylist}
          handleSyncPlaylist={handleSyncPlaylist}
          handleForceSyncPlaylist={handleForceSyncPlaylist}
          handleRecheckPlaylist={handleRecheckPlaylist}
          handleDeletePlaylist={handleDeletePlaylist}
          handleToggleAutoTrack={handleToggleAutoTrack}
          handleToggleM3u={handleToggleM3u}
          handleEditPlaylist={handleEditPlaylist}
          handleClosePlaylistModal={handleClosePlaylistModal}
          handleCreatePlaylist={handleCreatePlaylist}
          handleDownloadAllPlaylists={handleDownloadAllPlaylists}
        />
      )}

      {activeTab === 'external' && <ExternalListsSection />}
    </section>
  );
}

function SyncedPlaylistsTab({
  playlists,
  totalCount,
  totalPages,
  loading,
  error,
  isRefreshing,
  isInitialLoading,
  issuesCount,
  page,
  setPage,
  filter,
  pageSize,
  sortField,
  sortDirection,
  showPlaylistModal,
  editingPlaylist,
  enabledMutatingIds,
  enabledPulseIds,
  autoMutatingIds,
  autoPulseIds,
  m3uMutatingIds,
  m3uPulseIds,
  syncMutatingIds,
  forceSyncMutatingIds,
  deleteMutatingIds,
  recheckMutatingIds,
  errorById,
  handleEnabledFilterChange,
  handlePageSizeChange,
  handleSort,
  handleSearch,
  handleTogglePlaylist,
  handleSyncPlaylist,
  handleForceSyncPlaylist,
  handleRecheckPlaylist,
  handleDeletePlaylist,
  handleToggleAutoTrack,
  handleToggleM3u,
  handleEditPlaylist,
  handleClosePlaylistModal,
  handleCreatePlaylist,
  handleDownloadAllPlaylists,
}: ReturnType<typeof usePlaylistsPage>) {
  if (isInitialLoading && !playlists.length) {
    return <PageSpinner message='Loading playlists...' />;
  }

  if (error) {
    return (
      <ErrorBanner title='Error loading playlists' message={error.message} />
    );
  }

  return (
    <>
      <div className='flex items-center justify-between mb-4'>
        <div className='flex items-center gap-3'>
          <h2 className='text-lg font-medium text-gray-700 dark:text-slate-300'>
            Synced Playlists ({totalCount})
          </h2>
          {isRefreshing && <InlineSpinner label='Updating...' />}
        </div>
        <div className='flex items-center gap-4'>
          <button
            onClick={handleDownloadAllPlaylists}
            disabled={loading}
            className='px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm'
          >
            Download All Enabled Playlists
          </button>
          <button
            onClick={handleCreatePlaylist}
            className='px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors text-sm'
          >
            Create Playlist
          </button>

          <SearchInput
            placeholder='Search playlists...'
            onSearch={handleSearch}
            className='w-64'
          />
          <PageSizeSelector
            pageSize={pageSize}
            onPageSizeChange={handlePageSizeChange}
          />
        </div>
      </div>

      <PlaylistFilters
        currentEnabledFilter={filter}
        onEnabledFilterChange={handleEnabledFilterChange}
        issuesCount={issuesCount}
      />

      <div className='relative'>
        <PlaylistsTable
          playlists={playlists}
          sortField={sortField}
          sortDirection={sortDirection}
          onSort={handleSort}
          onToggleEnabled={handleTogglePlaylist}
          onToggleAutoTrack={handleToggleAutoTrack}
          onToggleM3u={handleToggleM3u}
          onSyncPlaylist={handleSyncPlaylist}
          onForceSyncPlaylist={handleForceSyncPlaylist}
          onRecheckPlaylist={handleRecheckPlaylist}
          onEditPlaylist={handleEditPlaylist}
          onDeletePlaylist={handleDeletePlaylist}
          loading={loading}
          enabledMutatingIds={enabledMutatingIds}
          autoMutatingIds={autoMutatingIds}
          m3uMutatingIds={m3uMutatingIds}
          syncMutatingIds={syncMutatingIds}
          forceSyncMutatingIds={forceSyncMutatingIds}
          recheckMutatingIds={recheckMutatingIds}
          deleteMutatingIds={deleteMutatingIds}
          enabledPulseIds={enabledPulseIds}
          autoPulseIds={autoPulseIds}
          m3uPulseIds={m3uPulseIds}
          errorById={errorById}
        />
      </div>

      {totalPages > 1 && (
        <PaginationBar
          page={page}
          totalPages={totalPages}
          totalCount={totalCount}
          pageSize={pageSize}
          onPageChange={setPage}
          loading={loading}
        />
      )}

      <PlaylistModal
        isOpen={showPlaylistModal}
        onClose={handleClosePlaylistModal}
        playlist={editingPlaylist}
        mode={editingPlaylist ? 'edit' : 'create'}
      />
    </>
  );
}

export const Route = createFileRoute('/playlists')({
  component: Playlists,
  validateSearch: (search: Record<string, unknown>) => ({
    tab: search.tab as string | undefined,
  }),
});

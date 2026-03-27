import { ExternalListsTable } from './ExternalListsTable';
import { ExternalListFilters } from './ExternalListFilters';
import { ExternalListModal } from './ExternalListModal';
import { PageSizeSelector } from '../ui/PageSizeSelector';
import { InlineSpinner } from '../ui/InlineSpinner';
import { PageSpinner } from '../ui/PageSpinner';
import { ErrorBanner } from '../ui/ErrorBanner';
import { LoadMoreButton } from '../ui/LoadMoreButton';
import { SearchInput } from '../ui/SearchInput';
import { useExternalListsPage } from '../../hooks/useExternalListsPage';

export function ExternalListsSection() {
  const {
    // Data
    lists,
    totalCount,
    pageInfo,
    loading,
    error,
    isRefreshing,
    isInitialLoading,

    // Filters & sorting
    sourceFilter,
    pageSize,
    sortField,
    sortDirection,

    // Modal state
    showCreateModal,
    editingList,

    // Mutation states
    enabledMutatingIds,
    syncMutatingIds,
    forceSyncMutatingIds,
    deleteMutatingIds,

    // Handlers
    handleSourceFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleCreateList,
    handleEditList,
    handleToggleEnabled,
    handleToggleAutoTrack,
    handleSyncList,
    handleForceSyncList,
    handleSyncAll,
    handleDeleteList,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseCreateModal,
    handleLoadMore,
  } = useExternalListsPage();

  if (isInitialLoading && !lists.length) {
    return <PageSpinner message='Loading external lists...' />;
  }

  if (error) {
    return (
      <ErrorBanner
        title='Error loading external lists'
        message={error.message}
      />
    );
  }

  return (
    <>
      <div className='flex items-center justify-between mb-4'>
        <div className='flex items-center gap-3'>
          <h2 className='text-lg font-medium text-gray-700 dark:text-slate-300'>
            External Lists ({lists.length} of {totalCount})
          </h2>
          {isRefreshing && <InlineSpinner label='Updating...' />}
        </div>
        <div className='flex items-center gap-4'>
          <button
            onClick={handleSyncAll}
            disabled={loading}
            className='px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm'
          >
            Sync All Lists
          </button>
          <button
            onClick={handleOpenCreateModal}
            className='px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors text-sm'
          >
            Add External List
          </button>
          <SearchInput
            placeholder='Search lists...'
            onSearch={handleSearch}
            className='w-64'
          />
          <PageSizeSelector
            pageSize={pageSize}
            onPageSizeChange={handlePageSizeChange}
          />
        </div>
      </div>

      <ExternalListFilters
        currentSourceFilter={sourceFilter}
        onSourceFilterChange={handleSourceFilterChange}
      />

      <div className='relative'>
        <ExternalListsTable
          lists={lists}
          sortField={sortField}
          sortDirection={sortDirection}
          onSort={handleSort}
          onToggleEnabled={handleToggleEnabled}
          onToggleAutoTrack={handleToggleAutoTrack}
          onEditList={handleOpenEditModal}
          onSyncList={handleSyncList}
          onForceSyncList={handleForceSyncList}
          onDeleteList={handleDeleteList}
          loading={loading}
          enabledMutatingIds={enabledMutatingIds}
          syncMutatingIds={syncMutatingIds}
          forceSyncMutatingIds={forceSyncMutatingIds}
          deleteMutatingIds={deleteMutatingIds}
        />
      </div>

      <LoadMoreButton
        hasNextPage={!!pageInfo?.hasNextPage}
        loading={loading}
        remainingCount={totalCount - lists.length}
        onLoadMore={handleLoadMore}
      />

      <ExternalListModal
        isOpen={showCreateModal}
        onClose={handleCloseCreateModal}
        onSubmit={handleCreateList}
        onEdit={handleEditList}
        editingList={editingList}
      />
    </>
  );
}

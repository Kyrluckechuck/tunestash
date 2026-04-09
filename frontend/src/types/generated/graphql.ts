import type { TypedDocumentNode as DocumentNode } from '@graphql-typed-document-node/core';
export type Maybe<T> = T | null;
export type InputMaybe<T> = T | null | undefined;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
  /** The `DateTime` scalar type represents a date and time following the ISO 8601 standard. */
  DateTime: { input: string; output: string; }
  /** The `JSON` scalar type represents JSON values as specified by [ECMA-404](https://ecma-international.org/wp-content/uploads/ECMA-404_2nd_edition_december_2017.pdf). */
  JSON: { input: unknown; output: unknown; }
};

export type ApiRateLimitInfo = {
  __typename?: 'APIRateLimitInfo';
  apiName: Scalars['String']['output'];
  isRateLimited: Scalars['Boolean']['output'];
  maxRequestsPerSecond: Scalars['Float']['output'];
  requestCount: Scalars['Int']['output'];
};

export type Album = {
  __typename?: 'Album';
  albumGroup: Maybe<Scalars['String']['output']>;
  albumType: Maybe<Scalars['String']['output']>;
  artist: Maybe<Scalars['String']['output']>;
  artistGid: Maybe<Scalars['String']['output']>;
  artistId: Maybe<Scalars['Int']['output']>;
  deezerId: Maybe<Scalars['String']['output']>;
  downloaded: Scalars['Boolean']['output'];
  id: Scalars['Int']['output'];
  name: Scalars['String']['output'];
  spotifyGid: Maybe<Scalars['String']['output']>;
  totalTracks: Scalars['Int']['output'];
  wanted: Scalars['Boolean']['output'];
};

export type AlbumPage = {
  __typename?: 'AlbumPage';
  items: Array<Album>;
  pageInfo: OffsetPageInfo;
};

export type AppSettingType = {
  __typename?: 'AppSettingType';
  category: Scalars['String']['output'];
  description: Scalars['String']['output'];
  isDefault: Scalars['Boolean']['output'];
  key: Scalars['String']['output'];
  label: Scalars['String']['output'];
  options: Maybe<Array<Scalars['String']['output']>>;
  sensitive: Scalars['Boolean']['output'];
  type: Scalars['String']['output'];
  value: Scalars['String']['output'];
};

export type Artist = {
  __typename?: 'Artist';
  addedAt: Maybe<Scalars['DateTime']['output']>;
  albumCount: Scalars['Int']['output'];
  deezerId: Maybe<Scalars['String']['output']>;
  downloadedAlbumCount: Scalars['Int']['output'];
  downloadedSongCount: Scalars['Int']['output'];
  failedSongCount: Scalars['Int']['output'];
  gid: Maybe<Scalars['String']['output']>;
  id: Scalars['Int']['output'];
  lastDownloaded: Maybe<Scalars['DateTime']['output']>;
  lastSynced: Maybe<Scalars['DateTime']['output']>;
  name: Scalars['String']['output'];
  songCount: Scalars['Int']['output'];
  spotifyUri: Maybe<Scalars['String']['output']>;
  trackingTier: Scalars['Int']['output'];
  undownloadedCount: Scalars['Int']['output'];
};

export type ArtistPage = {
  __typename?: 'ArtistPage';
  items: Array<Artist>;
  pageInfo: OffsetPageInfo;
};

export type AuthenticationStatus = {
  __typename?: 'AuthenticationStatus';
  cookiesErrorMessage: Maybe<Scalars['String']['output']>;
  cookiesErrorType: Maybe<Scalars['String']['output']>;
  cookiesExpireInDays: Maybe<Scalars['Int']['output']>;
  cookiesValid: Scalars['Boolean']['output'];
  poTokenConfigured: Scalars['Boolean']['output'];
  poTokenErrorMessage: Maybe<Scalars['String']['output']>;
  poTokenValid: Scalars['Boolean']['output'];
  spotifyAuthMode: Scalars['String']['output'];
  spotifyTokenErrorMessage: Maybe<Scalars['String']['output']>;
  spotifyTokenExpired: Scalars['Boolean']['output'];
  spotifyTokenExpiresInHours: Maybe<Scalars['Int']['output']>;
  spotifyTokenValid: Scalars['Boolean']['output'];
  spotifyUserAuthEnabled: Scalars['Boolean']['output'];
};

export type CachedStatType = {
  __typename?: 'CachedStatType';
  category: Scalars['String']['output'];
  displayName: Scalars['String']['output'];
  key: Scalars['String']['output'];
  updatedAt: Scalars['DateTime']['output'];
  value: Scalars['JSON']['output'];
};

export type CatalogSearchAlbum = {
  __typename?: 'CatalogSearchAlbum';
  albumType: Scalars['String']['output'];
  artistName: Scalars['String']['output'];
  artistProviderId: Scalars['String']['output'];
  externalUrl: Maybe<Scalars['String']['output']>;
  imageUrl: Maybe<Scalars['String']['output']>;
  inLibrary: Scalars['Boolean']['output'];
  localId: Maybe<Scalars['Int']['output']>;
  name: Scalars['String']['output'];
  providerId: Scalars['String']['output'];
  releaseDate: Maybe<Scalars['String']['output']>;
  totalTracks: Scalars['Int']['output'];
};

export type CatalogSearchArtist = {
  __typename?: 'CatalogSearchArtist';
  externalUrl: Maybe<Scalars['String']['output']>;
  imageUrl: Maybe<Scalars['String']['output']>;
  inLibrary: Scalars['Boolean']['output'];
  localId: Maybe<Scalars['Int']['output']>;
  name: Scalars['String']['output'];
  providerId: Scalars['String']['output'];
  trackingTier: Scalars['Int']['output'];
};

export type CatalogSearchResults = {
  __typename?: 'CatalogSearchResults';
  albums: Array<CatalogSearchAlbum>;
  artists: Array<CatalogSearchArtist>;
  tracks: Array<CatalogSearchTrack>;
};

export type CatalogSearchTrack = {
  __typename?: 'CatalogSearchTrack';
  albumName: Scalars['String']['output'];
  albumProviderId: Scalars['String']['output'];
  artistName: Scalars['String']['output'];
  artistProviderId: Scalars['String']['output'];
  durationMs: Scalars['Int']['output'];
  externalUrl: Maybe<Scalars['String']['output']>;
  inLibrary: Scalars['Boolean']['output'];
  localId: Maybe<Scalars['Int']['output']>;
  name: Scalars['String']['output'];
  providerId: Scalars['String']['output'];
};

export type CookieUploadResult = {
  __typename?: 'CookieUploadResult';
  message: Scalars['String']['output'];
  success: Scalars['Boolean']['output'];
};

export type DeezerArtistPreview = {
  __typename?: 'DeezerArtistPreview';
  deezerId: Scalars['Int']['output'];
  imageUrl: Maybe<Scalars['String']['output']>;
  name: Scalars['String']['output'];
};

export type DeezerGenreType = {
  __typename?: 'DeezerGenreType';
  id: Scalars['Int']['output'];
  name: Scalars['String']['output'];
};

export type DownloadHistory = {
  __typename?: 'DownloadHistory';
  completedAt: Maybe<Scalars['DateTime']['output']>;
  entityId: Scalars['String']['output'];
  entityType: Scalars['String']['output'];
  errorMessage: Maybe<Scalars['String']['output']>;
  id: Scalars['String']['output'];
  startedAt: Scalars['DateTime']['output'];
  status: DownloadStatus;
};

export type DownloadProgress = {
  __typename?: 'DownloadProgress';
  entityId: Scalars['String']['output'];
  entityType: Scalars['String']['output'];
  message: Scalars['String']['output'];
  progress: Scalars['Float']['output'];
  status: DownloadStatus;
};

export type DownloadProvider =
  | 'QOBUZ'
  | 'SPOTDL'
  | 'TIDAL'
  | 'UNKNOWN';

export type DownloadStatus =
  | 'COMPLETED'
  | 'FAILED'
  | 'IN_PROGRESS'
  | 'PENDING'
  | 'SKIPPED';

export type EntityType =
  | 'ALBUM'
  | 'ARTIST'
  | 'PLAYLIST'
  | 'TRACK';

export type ExternalListPage = {
  __typename?: 'ExternalListPage';
  items: Array<ExternalListType>;
  pageInfo: OffsetPageInfo;
};

export type ExternalListType = {
  __typename?: 'ExternalListType';
  autoTrackTier: Maybe<Scalars['Int']['output']>;
  createdAt: Maybe<Scalars['DateTime']['output']>;
  failedTracks: Scalars['Int']['output'];
  id: Scalars['Int']['output'];
  lastSyncedAt: Maybe<Scalars['DateTime']['output']>;
  listIdentifier: Maybe<Scalars['String']['output']>;
  listType: Scalars['String']['output'];
  mappedTracks: Scalars['Int']['output'];
  name: Scalars['String']['output'];
  period: Maybe<Scalars['String']['output']>;
  source: Scalars['String']['output'];
  status: Scalars['String']['output'];
  statusMessage: Maybe<Scalars['String']['output']>;
  totalTracks: Scalars['Int']['output'];
  username: Scalars['String']['output'];
};

export type FailureReasonCount = {
  __typename?: 'FailureReasonCount';
  count: Scalars['Int']['output'];
  reason: Scalars['String']['output'];
};

export type FallbackMetrics = {
  __typename?: 'FallbackMetrics';
  failureReasons: Array<FailureReasonCount>;
  successRate: Scalars['Float']['output'];
  timeSeries: Array<MetricTimePoint>;
  totalAttempts: Scalars['Int']['output'];
  totalFailures: Scalars['Int']['output'];
  totalSuccesses: Scalars['Int']['output'];
};

export type HistoryPage = {
  __typename?: 'HistoryPage';
  items: Array<DownloadHistory>;
  pageInfo: OffsetPageInfo;
};

export type LibraryStats = {
  __typename?: 'LibraryStats';
  albumCompletionPercentage: Scalars['Float']['output'];
  desiredAlbumCompletionPercentage: Scalars['Float']['output'];
  desiredAlbums: Scalars['Int']['output'];
  desiredAlbumsDownloaded: Scalars['Int']['output'];
  desiredAlbumsMissing: Scalars['Int']['output'];
  desiredAlbumsPartial: Scalars['Int']['output'];
  desiredCompletionPercentage: Scalars['Float']['output'];
  desiredDownloaded: Scalars['Int']['output'];
  desiredFailed: Scalars['Int']['output'];
  desiredMissing: Scalars['Int']['output'];
  desiredSongs: Scalars['Int']['output'];
  desiredUnavailable: Scalars['Int']['output'];
  downloadedAlbums: Scalars['Int']['output'];
  downloadedSongs: Scalars['Int']['output'];
  failedSongs: Scalars['Int']['output'];
  missingAlbums: Scalars['Int']['output'];
  missingSongs: Scalars['Int']['output'];
  partialAlbums: Scalars['Int']['output'];
  songCompletionPercentage: Scalars['Float']['output'];
  totalAlbums: Scalars['Int']['output'];
  totalArtists: Scalars['Int']['output'];
  totalSongs: Scalars['Int']['output'];
  trackedArtists: Scalars['Int']['output'];
  unavailableSongs: Scalars['Int']['output'];
};

export type MetadataCheckResult = {
  __typename?: 'MetadataCheckResult';
  changeDetected: Scalars['Boolean']['output'];
  message: Scalars['String']['output'];
  newValue: Maybe<Scalars['String']['output']>;
  oldValue: Maybe<Scalars['String']['output']>;
  success: Scalars['Boolean']['output'];
};

export type MetadataEntityType =
  | 'ALBUM'
  | 'ARTIST'
  | 'SONG';

export type MetadataUpdate = {
  __typename?: 'MetadataUpdate';
  affectedSongsCount: Scalars['Int']['output'];
  detectedAt: Scalars['DateTime']['output'];
  entityId: Scalars['Int']['output'];
  entityName: Scalars['String']['output'];
  entityType: MetadataEntityType;
  fieldName: Scalars['String']['output'];
  id: Scalars['Int']['output'];
  newValue: Scalars['String']['output'];
  oldValue: Scalars['String']['output'];
  resolvedAt: Maybe<Scalars['DateTime']['output']>;
  status: MetadataUpdateStatus;
};

export type MetadataUpdateConnection = {
  __typename?: 'MetadataUpdateConnection';
  edges: Array<MetadataUpdate>;
  summary: MetadataUpdateSummary;
};

export type MetadataUpdateStatus =
  | 'APPLIED'
  | 'DISMISSED'
  | 'PENDING';

export type MetadataUpdateSummary = {
  __typename?: 'MetadataUpdateSummary';
  albumUpdates: Scalars['Int']['output'];
  artistUpdates: Scalars['Int']['output'];
  songUpdates: Scalars['Int']['output'];
  totalAffectedSongs: Scalars['Int']['output'];
};

export type MetricTimePoint = {
  __typename?: 'MetricTimePoint';
  count: Scalars['Int']['output'];
  timestamp: Scalars['DateTime']['output'];
  value: Scalars['Float']['output'];
};

export type Mutation = {
  __typename?: 'Mutation';
  applyAllMetadataUpdates: MutationResult;
  applyMetadataUpdate: MutationResult;
  batchArtistOperations: MutationResult;
  cancelAllPendingTasks: MutationResult;
  cancelAllTasks: MutationResult;
  cancelRunningTasksByName: MutationResult;
  cancelTaskById: MutationResult;
  cancelTasksByName: MutationResult;
  checkAlbumMetadata: MetadataCheckResult;
  checkArtistMetadata: MetadataCheckResult;
  checkSongMetadata: MetadataCheckResult;
  createExternalList: ExternalListType;
  createPlaylist: Playlist;
  deleteExternalList: MutationResult;
  deletePlaylist: MutationResult;
  disconnectSpotify: MutationResult;
  dismissMetadataUpdate: MutationResult;
  downloadAlbum: Album;
  downloadAllPlaylists: MutationResult;
  downloadAllTrackedArtists: MutationResult;
  downloadArtist: MutationResult;
  downloadUrl: MutationResult;
  importAlbum: MutationResult;
  importArtist: MutationResult;
  linkArtistToDeezer: MutationResult;
  migrateSettingsFromYaml: YamlMigrationResult;
  resetAppSetting: UpdateSettingResult;
  retryFailedSongs: MutationResult;
  runOneOffTask: MutationResult;
  runPeriodicTaskNow: MutationResult;
  saveDeezerPlaylist: Playlist;
  setAlbumWanted: MutationResult;
  setPeriodicTaskEnabled: PeriodicTask;
  syncAllExternalLists: MutationResult;
  syncAllTrackedArtists: MutationResult;
  syncArtist: Artist;
  syncExternalList: MutationResult;
  syncPlaylist: MutationResult;
  toggleExternalList: MutationResult;
  toggleExternalListAutoTrack: MutationResult;
  togglePlaylist: MutationResult;
  togglePlaylistAutoTrack: MutationResult;
  togglePlaylistM3u: MutationResult;
  trackArtist: MutationResult;
  trackPlaylist: Playlist;
  untrackArtist: MutationResult;
  updateAlbum: Album;
  updateAppSetting: UpdateSettingResult;
  updateArtist: Artist;
  updateExternalList: MutationResult;
  updatePlaylist: MutationResult;
  uploadCookieFile: CookieUploadResult;
};


export type MutationApplyMetadataUpdateArgs = {
  updateId: Scalars['Int']['input'];
};


export type MutationBatchArtistOperationsArgs = {
  artistIds: Array<Scalars['Int']['input']>;
  operations?: InputMaybe<Array<Scalars['String']['input']>>;
};


export type MutationCancelRunningTasksByNameArgs = {
  taskName: Scalars['String']['input'];
};


export type MutationCancelTaskByIdArgs = {
  taskId: Scalars['String']['input'];
};


export type MutationCancelTasksByNameArgs = {
  taskName: Scalars['String']['input'];
};


export type MutationCheckAlbumMetadataArgs = {
  albumId: Scalars['Int']['input'];
};


export type MutationCheckArtistMetadataArgs = {
  artistId: Scalars['Int']['input'];
};


export type MutationCheckSongMetadataArgs = {
  songId: Scalars['Int']['input'];
};


export type MutationCreateExternalListArgs = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  listIdentifier?: InputMaybe<Scalars['String']['input']>;
  listType: Scalars['String']['input'];
  period?: InputMaybe<Scalars['String']['input']>;
  source: Scalars['String']['input'];
  username: Scalars['String']['input'];
};


export type MutationCreatePlaylistArgs = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  name: Scalars['String']['input'];
  url: Scalars['String']['input'];
};


export type MutationDeleteExternalListArgs = {
  listId: Scalars['Int']['input'];
};


export type MutationDeletePlaylistArgs = {
  playlistId: Scalars['Int']['input'];
};


export type MutationDismissMetadataUpdateArgs = {
  updateId: Scalars['Int']['input'];
};


export type MutationDownloadAlbumArgs = {
  albumId: Scalars['String']['input'];
};


export type MutationDownloadArtistArgs = {
  artistId: Scalars['String']['input'];
};


export type MutationDownloadUrlArgs = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  url: Scalars['String']['input'];
};


export type MutationImportAlbumArgs = {
  deezerId: Scalars['Int']['input'];
};


export type MutationImportArtistArgs = {
  deezerId: Scalars['Int']['input'];
  name: Scalars['String']['input'];
};


export type MutationLinkArtistToDeezerArgs = {
  artistId: Scalars['Int']['input'];
  deezerId: Scalars['Int']['input'];
};


export type MutationResetAppSettingArgs = {
  key: Scalars['String']['input'];
};


export type MutationRetryFailedSongsArgs = {
  artistId: Scalars['String']['input'];
};


export type MutationRunOneOffTaskArgs = {
  taskId: Scalars['String']['input'];
};


export type MutationRunPeriodicTaskNowArgs = {
  taskId: Scalars['Int']['input'];
};


export type MutationSaveDeezerPlaylistArgs = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  deezerId: Scalars['String']['input'];
};


export type MutationSetAlbumWantedArgs = {
  albumId: Scalars['Int']['input'];
  wanted: Scalars['Boolean']['input'];
};


export type MutationSetPeriodicTaskEnabledArgs = {
  enabled: Scalars['Boolean']['input'];
  taskId: Scalars['Int']['input'];
};


export type MutationSyncArtistArgs = {
  artistId: Scalars['String']['input'];
};


export type MutationSyncExternalListArgs = {
  force?: Scalars['Boolean']['input'];
  listId: Scalars['Int']['input'];
};


export type MutationSyncPlaylistArgs = {
  force?: Scalars['Boolean']['input'];
  playlistId: Scalars['Int']['input'];
  recheck?: Scalars['Boolean']['input'];
};


export type MutationToggleExternalListArgs = {
  listId: Scalars['Int']['input'];
};


export type MutationToggleExternalListAutoTrackArgs = {
  listId: Scalars['Int']['input'];
};


export type MutationTogglePlaylistArgs = {
  playlistId: Scalars['Int']['input'];
};


export type MutationTogglePlaylistAutoTrackArgs = {
  playlistId: Scalars['Int']['input'];
};


export type MutationTogglePlaylistM3uArgs = {
  playlistId: Scalars['Int']['input'];
};


export type MutationTrackArtistArgs = {
  artistId: Scalars['Int']['input'];
};


export type MutationTrackPlaylistArgs = {
  input: TrackPlaylistInput;
};


export type MutationUntrackArtistArgs = {
  artistId: Scalars['Int']['input'];
};


export type MutationUpdateAlbumArgs = {
  input: UpdateAlbumInput;
};


export type MutationUpdateAppSettingArgs = {
  key: Scalars['String']['input'];
  value: Scalars['String']['input'];
};


export type MutationUpdateArtistArgs = {
  input: UpdateArtistInput;
};


export type MutationUpdateExternalListArgs = {
  listId: Scalars['Int']['input'];
  listIdentifier?: InputMaybe<Scalars['String']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
  period?: InputMaybe<Scalars['String']['input']>;
  username?: InputMaybe<Scalars['String']['input']>;
};


export type MutationUpdatePlaylistArgs = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  name: Scalars['String']['input'];
  playlistId: Scalars['Int']['input'];
  url: Scalars['String']['input'];
};


export type MutationUploadCookieFileArgs = {
  content: Scalars['String']['input'];
};

export type MutationResult = {
  __typename?: 'MutationResult';
  album: Maybe<Album>;
  artist: Maybe<Artist>;
  message: Scalars['String']['output'];
  playlist: Maybe<Playlist>;
  success: Scalars['Boolean']['output'];
};

export type OffsetPageInfo = {
  __typename?: 'OffsetPageInfo';
  page: Scalars['Int']['output'];
  pageSize: Scalars['Int']['output'];
  totalCount: Scalars['Int']['output'];
  totalPages: Scalars['Int']['output'];
};

export type OneOffTask = {
  __typename?: 'OneOffTask';
  category: Scalars['String']['output'];
  description: Scalars['String']['output'];
  id: Scalars['String']['output'];
  name: Scalars['String']['output'];
};

export type PendingTask = {
  __typename?: 'PendingTask';
  createdAt: Maybe<Scalars['String']['output']>;
  displayName: Scalars['String']['output'];
  entityId: Maybe<Scalars['String']['output']>;
  entityName: Maybe<Scalars['String']['output']>;
  entityType: Maybe<Scalars['String']['output']>;
  status: Scalars['String']['output'];
  taskId: Scalars['String']['output'];
  taskName: Scalars['String']['output'];
};

export type PeriodicTask = {
  __typename?: 'PeriodicTask';
  description: Maybe<Scalars['String']['output']>;
  enabled: Scalars['Boolean']['output'];
  id: Scalars['Int']['output'];
  isCore: Scalars['Boolean']['output'];
  lastRunAt: Maybe<Scalars['DateTime']['output']>;
  name: Scalars['String']['output'];
  scheduleDescription: Scalars['String']['output'];
  task: Scalars['String']['output'];
  totalRunCount: Scalars['Int']['output'];
};

export type Playlist = {
  __typename?: 'Playlist';
  autoTrackTier: Maybe<Scalars['Int']['output']>;
  enabled: Scalars['Boolean']['output'];
  id: Scalars['Int']['output'];
  lastSyncedAt: Maybe<Scalars['DateTime']['output']>;
  m3uEnabled: Scalars['Boolean']['output'];
  name: Scalars['String']['output'];
  provider: Scalars['String']['output'];
  status: Scalars['String']['output'];
  statusMessage: Maybe<Scalars['String']['output']>;
  url: Scalars['String']['output'];
};

export type PlaylistInfo = {
  __typename?: 'PlaylistInfo';
  imageUrl: Maybe<Scalars['String']['output']>;
  name: Scalars['String']['output'];
  ownerName: Maybe<Scalars['String']['output']>;
  provider: Scalars['String']['output'];
  trackCount: Scalars['Int']['output'];
};

export type PlaylistPage = {
  __typename?: 'PlaylistPage';
  items: Array<Playlist>;
  pageInfo: OffsetPageInfo;
};

export type Query = {
  __typename?: 'Query';
  album: Maybe<Album>;
  albumById: Maybe<Album>;
  albums: AlbumPage;
  appSetting: Maybe<AppSettingType>;
  appSettings: Array<SettingsCategoryType>;
  artist: Maybe<Artist>;
  artists: ArtistPage;
  cachedStats: Array<CachedStatType>;
  catalogSearch: CatalogSearchResults;
  deezerGenres: Array<DeezerGenreType>;
  downloadHistory: HistoryPage;
  externalList: Maybe<ExternalListType>;
  externalLists: ExternalListPage;
  fallbackMetrics: FallbackMetrics;
  libraryStats: LibraryStats;
  oneOffTasks: Array<OneOffTask>;
  pendingMetadataUpdates: MetadataUpdateConnection;
  periodicTasks: Array<PeriodicTask>;
  playlist: Maybe<Playlist>;
  playlistInfo: Maybe<PlaylistInfo>;
  playlists: PlaylistPage;
  previewDeezerArtist: Maybe<DeezerArtistPreview>;
  queueStatus: QueueStatus;
  song: Maybe<Song>;
  songs: SongPage;
  systemHealth: SystemHealth;
  taskHistory: TaskHistoryPage;
  unlinkedArtists: ArtistPage;
  upgradeStats: UpgradeStats;
};


export type QueryAlbumArgs = {
  id: Scalars['String']['input'];
};


export type QueryAlbumByIdArgs = {
  id: Scalars['Int']['input'];
};


export type QueryAlbumsArgs = {
  artistId?: InputMaybe<Scalars['Int']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  wanted?: InputMaybe<Scalars['Boolean']['input']>;
};


export type QueryAppSettingArgs = {
  key: Scalars['String']['input'];
};


export type QueryArtistArgs = {
  id: Scalars['String']['input'];
};


export type QueryArtistsArgs = {
  hasUndownloaded?: InputMaybe<Scalars['Boolean']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  trackingTier?: InputMaybe<Scalars['Int']['input']>;
};


export type QueryCachedStatsArgs = {
  category?: InputMaybe<Scalars['String']['input']>;
};


export type QueryCatalogSearchArgs = {
  limit?: InputMaybe<Scalars['Int']['input']>;
  query: Scalars['String']['input'];
  types?: InputMaybe<Array<Scalars['String']['input']>>;
};


export type QueryDownloadHistoryArgs = {
  entityType?: InputMaybe<Scalars['String']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  status?: InputMaybe<Scalars['String']['input']>;
};


export type QueryExternalListArgs = {
  id: Scalars['String']['input'];
};


export type QueryExternalListsArgs = {
  listType?: InputMaybe<Scalars['String']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  source?: InputMaybe<Scalars['String']['input']>;
  status?: InputMaybe<Scalars['String']['input']>;
};


export type QueryFallbackMetricsArgs = {
  days?: InputMaybe<Scalars['Int']['input']>;
};


export type QueryPendingMetadataUpdatesArgs = {
  entityType?: InputMaybe<MetadataEntityType>;
  includeResolved?: Scalars['Boolean']['input'];
  status?: InputMaybe<MetadataUpdateStatus>;
};


export type QueryPeriodicTasksArgs = {
  enabledOnly?: InputMaybe<Scalars['Boolean']['input']>;
};


export type QueryPlaylistArgs = {
  id: Scalars['String']['input'];
};


export type QueryPlaylistInfoArgs = {
  url: Scalars['String']['input'];
};


export type QueryPlaylistsArgs = {
  enabled?: InputMaybe<Scalars['Boolean']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  status?: InputMaybe<Scalars['String']['input']>;
};


export type QueryPreviewDeezerArtistArgs = {
  deezerId: Scalars['Int']['input'];
};


export type QuerySongArgs = {
  id: Scalars['String']['input'];
};


export type QuerySongsArgs = {
  albumId?: InputMaybe<Scalars['Int']['input']>;
  artistId?: InputMaybe<Scalars['Int']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  maxBitrate?: InputMaybe<Scalars['Int']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  unavailable?: InputMaybe<Scalars['Boolean']['input']>;
};


export type QueryTaskHistoryArgs = {
  entityType?: InputMaybe<Scalars['String']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  status?: InputMaybe<Scalars['String']['input']>;
  type?: InputMaybe<Scalars['String']['input']>;
};


export type QueryUnlinkedArtistsArgs = {
  hasDownloads?: InputMaybe<Scalars['Boolean']['input']>;
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
};

export type QueueStatus = {
  __typename?: 'QueueStatus';
  pendingTasks: Array<PendingTask>;
  queueSize: Scalars['Int']['output'];
  taskCounts: Array<TaskCount>;
  totalPendingTasks: Scalars['Int']['output'];
};

export type SettingsCategoryType = {
  __typename?: 'SettingsCategoryType';
  category: Scalars['String']['output'];
  label: Scalars['String']['output'];
  settings: Array<AppSettingType>;
};

export type Song = {
  __typename?: 'Song';
  bitrate: Scalars['Int']['output'];
  createdAt: Scalars['DateTime']['output'];
  deezerId: Maybe<Scalars['String']['output']>;
  downloadProvider: Maybe<DownloadProvider>;
  downloaded: Scalars['Boolean']['output'];
  failedCount: Scalars['Int']['output'];
  filePath: Maybe<Scalars['String']['output']>;
  gid: Maybe<Scalars['String']['output']>;
  id: Scalars['Int']['output'];
  name: Scalars['String']['output'];
  primaryArtist: Scalars['String']['output'];
  primaryArtistGid: Maybe<Scalars['String']['output']>;
  primaryArtistId: Scalars['Int']['output'];
  spotifyUri: Maybe<Scalars['String']['output']>;
  unavailable: Scalars['Boolean']['output'];
};

export type SongPage = {
  __typename?: 'SongPage';
  items: Array<Song>;
  pageInfo: OffsetPageInfo;
};

export type SpotifyRateLimitStatus = {
  __typename?: 'SpotifyRateLimitStatus';
  burstCalls: Scalars['Int']['output'];
  burstMax: Scalars['Int']['output'];
  currentDelaySeconds: Scalars['Float']['output'];
  hourlyCalls: Scalars['Int']['output'];
  hourlyMax: Scalars['Int']['output'];
  isRateLimited: Scalars['Boolean']['output'];
  isThrottling: Scalars['Boolean']['output'];
  rateLimitedUntil: Maybe<Scalars['DateTime']['output']>;
  secondsUntilClear: Maybe<Scalars['Int']['output']>;
  sustainedCalls: Scalars['Int']['output'];
  sustainedMax: Scalars['Int']['output'];
  windowCallCount: Scalars['Int']['output'];
  windowMaxCalls: Scalars['Int']['output'];
  windowUsagePercent: Scalars['Float']['output'];
};

export type StorageStatus = {
  __typename?: 'StorageStatus';
  availableGb: Maybe<Scalars['Float']['output']>;
  errorMessage: Maybe<Scalars['String']['output']>;
  exists: Scalars['Boolean']['output'];
  isCriticallyLow: Scalars['Boolean']['output'];
  isLow: Scalars['Boolean']['output'];
  isWritable: Scalars['Boolean']['output'];
  path: Scalars['String']['output'];
  totalGb: Maybe<Scalars['Float']['output']>;
  usagePercent: Maybe<Scalars['Float']['output']>;
  usedGb: Maybe<Scalars['Float']['output']>;
};

export type Subscription = {
  __typename?: 'Subscription';
  allDownloadProgress: DownloadProgress;
  downloadProgress: DownloadProgress;
};


export type SubscriptionDownloadProgressArgs = {
  entityId: Scalars['String']['input'];
};

export type SystemHealth = {
  __typename?: 'SystemHealth';
  apiRateLimits: Array<ApiRateLimitInfo>;
  authentication: AuthenticationStatus;
  canDownload: Scalars['Boolean']['output'];
  downloadBlockerReason: Maybe<Scalars['String']['output']>;
  spotifyRateLimit: SpotifyRateLimitStatus;
  storage: StorageStatus;
};

export type TaskCount = {
  __typename?: 'TaskCount';
  count: Scalars['Int']['output'];
  taskName: Scalars['String']['output'];
};

export type TaskHistory = {
  __typename?: 'TaskHistory';
  completedAt: Maybe<Scalars['DateTime']['output']>;
  durationSeconds: Maybe<Scalars['Int']['output']>;
  entityId: Scalars['String']['output'];
  entityType: EntityType;
  id: Scalars['String']['output'];
  logMessages: Array<Scalars['String']['output']>;
  progressPercentage: Maybe<Scalars['Float']['output']>;
  startedAt: Scalars['DateTime']['output'];
  status: TaskStatus;
  taskId: Scalars['String']['output'];
  type: TaskType;
};

export type TaskHistoryPage = {
  __typename?: 'TaskHistoryPage';
  items: Array<TaskHistory>;
  pageInfo: OffsetPageInfo;
};

export type TaskStatus =
  | 'CANCELLED'
  | 'COMPLETED'
  | 'FAILED'
  | 'PENDING'
  | 'RUNNING';

export type TaskType =
  | 'DOWNLOAD'
  | 'FETCH'
  | 'SYNC';

export type TrackPlaylistInput = {
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
  playlistId: Scalars['String']['input'];
};

export type UpdateAlbumInput = {
  albumId: Scalars['String']['input'];
  isWanted?: InputMaybe<Scalars['Boolean']['input']>;
};

export type UpdateArtistInput = {
  artistId: Scalars['String']['input'];
  autoDownload?: InputMaybe<Scalars['Boolean']['input']>;
  trackingTier?: InputMaybe<Scalars['Int']['input']>;
};

export type UpdateSettingResult = {
  __typename?: 'UpdateSettingResult';
  message: Scalars['String']['output'];
  setting: Maybe<AppSettingType>;
  success: Scalars['Boolean']['output'];
};

export type UpgradeStats = {
  __typename?: 'UpgradeStats';
  notUpgradeable: Scalars['Int']['output'];
  totalLowQuality: Scalars['Int']['output'];
  upgradeable: Scalars['Int']['output'];
  upgraded: Scalars['Int']['output'];
};

export type YamlMigrationResult = {
  __typename?: 'YamlMigrationResult';
  message: Scalars['String']['output'];
  migrated: Scalars['Int']['output'];
  skipped: Scalars['Int']['output'];
  success: Scalars['Boolean']['output'];
};

export type GetArtistQueryVariables = Exact<{
  id: Scalars['String']['input'];
}>;


export type GetArtistQuery = { __typename?: 'Query', artist: { __typename?: 'Artist', id: number, name: string, gid: string | null, spotifyUri: string | null, deezerId: string | null, trackingTier: number, addedAt: string | null, lastSynced: string | null, lastDownloaded: string | null, undownloadedCount: number, albumCount: number, downloadedAlbumCount: number, songCount: number } | null };

export type GetAlbumQueryVariables = Exact<{
  id: Scalars['String']['input'];
}>;


export type GetAlbumQuery = { __typename?: 'Query', album: { __typename?: 'Album', id: number, name: string, spotifyGid: string | null, deezerId: string | null, totalTracks: number, wanted: boolean, downloaded: boolean, albumType: string | null, albumGroup: string | null, artist: string | null, artistId: number | null, artistGid: string | null } | null };

export type GetAlbumByIdQueryVariables = Exact<{
  id: Scalars['Int']['input'];
}>;


export type GetAlbumByIdQuery = { __typename?: 'Query', albumById: { __typename?: 'Album', id: number, name: string, spotifyGid: string | null, deezerId: string | null, totalTracks: number, wanted: boolean, downloaded: boolean, albumType: string | null, albumGroup: string | null, artist: string | null, artistId: number | null, artistGid: string | null } | null };

export type GetArtistsQueryVariables = Exact<{
  trackingTier?: InputMaybe<Scalars['Int']['input']>;
  hasUndownloaded?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetArtistsQuery = { __typename?: 'Query', artists: { __typename?: 'ArtistPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Artist', id: number, name: string, gid: string | null, spotifyUri: string | null, deezerId: string | null, trackingTier: number, addedAt: string | null, lastSynced: string | null, lastDownloaded: string | null, undownloadedCount: number, failedSongCount: number, albumCount: number, downloadedAlbumCount: number, songCount: number, downloadedSongCount: number }> } };

export type GetAlbumsQueryVariables = Exact<{
  artistId?: InputMaybe<Scalars['Int']['input']>;
  wanted?: InputMaybe<Scalars['Boolean']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetAlbumsQuery = { __typename?: 'Query', albums: { __typename?: 'AlbumPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Album', id: number, name: string, spotifyGid: string | null, deezerId: string | null, totalTracks: number, wanted: boolean, downloaded: boolean, albumType: string | null, albumGroup: string | null, artist: string | null, artistId: number | null, artistGid: string | null }> } };

export type GetPlaylistsQueryVariables = Exact<{
  enabled?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetPlaylistsQuery = { __typename?: 'Query', playlists: { __typename?: 'PlaylistPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Playlist', id: number, name: string, url: string, status: string, statusMessage: string | null, enabled: boolean, autoTrackTier: number | null, m3uEnabled: boolean, lastSyncedAt: string | null, provider: string }> } };

export type SyncArtistMutationVariables = Exact<{
  artistId: Scalars['String']['input'];
}>;


export type SyncArtistMutation = { __typename?: 'Mutation', syncArtist: { __typename?: 'Artist', id: number, name: string, gid: string | null, spotifyUri: string | null, trackingTier: number, addedAt: string | null, lastSynced: string | null, undownloadedCount: number } };

export type DownloadArtistMutationVariables = Exact<{
  artistId: Scalars['String']['input'];
}>;


export type DownloadArtistMutation = { __typename?: 'Mutation', downloadArtist: { __typename?: 'MutationResult', success: boolean, message: string } };

export type RetryFailedSongsMutationVariables = Exact<{
  artistId: Scalars['String']['input'];
}>;


export type RetryFailedSongsMutation = { __typename?: 'Mutation', retryFailedSongs: { __typename?: 'MutationResult', success: boolean, message: string } };

export type SyncPlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type SyncPlaylistMutation = { __typename?: 'Mutation', syncPlaylist: { __typename?: 'MutationResult', success: boolean, message: string } };

export type TrackArtistMutationVariables = Exact<{
  artistId: Scalars['Int']['input'];
}>;


export type TrackArtistMutation = { __typename?: 'Mutation', trackArtist: { __typename?: 'MutationResult', success: boolean, message: string, artist: { __typename?: 'Artist', id: number, name: string, trackingTier: number } | null } };

export type UntrackArtistMutationVariables = Exact<{
  artistId: Scalars['Int']['input'];
}>;


export type UntrackArtistMutation = { __typename?: 'Mutation', untrackArtist: { __typename?: 'MutationResult', success: boolean, message: string, artist: { __typename?: 'Artist', id: number, name: string, trackingTier: number } | null } };

export type UpdateArtistMutationVariables = Exact<{
  input: UpdateArtistInput;
}>;


export type UpdateArtistMutation = { __typename?: 'Mutation', updateArtist: { __typename?: 'Artist', id: number, name: string, trackingTier: number } };

export type SetAlbumWantedMutationVariables = Exact<{
  albumId: Scalars['Int']['input'];
  wanted: Scalars['Boolean']['input'];
}>;


export type SetAlbumWantedMutation = { __typename?: 'Mutation', setAlbumWanted: { __typename?: 'MutationResult', success: boolean, message: string, album: { __typename?: 'Album', id: number, name: string, wanted: boolean } | null } };

export type DownloadAlbumMutationVariables = Exact<{
  albumId: Scalars['String']['input'];
}>;


export type DownloadAlbumMutation = { __typename?: 'Mutation', downloadAlbum: { __typename?: 'Album', id: number, name: string, spotifyGid: string | null, wanted: boolean, downloaded: boolean } };

export type TogglePlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type TogglePlaylistMutation = { __typename?: 'Mutation', togglePlaylist: { __typename?: 'MutationResult', success: boolean, message: string, playlist: { __typename?: 'Playlist', id: number, name: string, status: string, statusMessage: string | null, enabled: boolean } | null } };

export type ForceSyncPlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type ForceSyncPlaylistMutation = { __typename?: 'Mutation', syncPlaylist: { __typename?: 'MutationResult', success: boolean, message: string } };

export type RecheckPlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type RecheckPlaylistMutation = { __typename?: 'Mutation', syncPlaylist: { __typename?: 'MutationResult', success: boolean, message: string, playlist: { __typename?: 'Playlist', id: number, name: string, status: string, statusMessage: string | null, enabled: boolean } | null } };

export type TogglePlaylistAutoTrackMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type TogglePlaylistAutoTrackMutation = { __typename?: 'Mutation', togglePlaylistAutoTrack: { __typename?: 'MutationResult', success: boolean, message: string, playlist: { __typename?: 'Playlist', id: number, name: string, autoTrackTier: number | null } | null } };

export type TogglePlaylistM3uMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type TogglePlaylistM3uMutation = { __typename?: 'Mutation', togglePlaylistM3u: { __typename?: 'MutationResult', success: boolean, message: string, playlist: { __typename?: 'Playlist', id: number, name: string, m3uEnabled: boolean } | null } };

export type UpdatePlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
  name: Scalars['String']['input'];
  url: Scalars['String']['input'];
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
}>;


export type UpdatePlaylistMutation = { __typename?: 'Mutation', updatePlaylist: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CreatePlaylistMutationVariables = Exact<{
  name: Scalars['String']['input'];
  url: Scalars['String']['input'];
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
}>;


export type CreatePlaylistMutation = { __typename?: 'Mutation', createPlaylist: { __typename?: 'Playlist', id: number, name: string, url: string, status: string, statusMessage: string | null, enabled: boolean, autoTrackTier: number | null } };

export type GetUnlinkedArtistsQueryVariables = Exact<{
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
  hasDownloads?: InputMaybe<Scalars['Boolean']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetUnlinkedArtistsQuery = { __typename?: 'Query', unlinkedArtists: { __typename?: 'ArtistPage', items: Array<{ __typename?: 'Artist', id: number, name: string, trackingTier: number, songCount: number, downloadedSongCount: number }>, pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number } } };

export type PreviewDeezerArtistQueryVariables = Exact<{
  deezerId: Scalars['Int']['input'];
}>;


export type PreviewDeezerArtistQuery = { __typename?: 'Query', previewDeezerArtist: { __typename?: 'DeezerArtistPreview', deezerId: number, name: string, imageUrl: string | null } | null };

export type LinkArtistToDeezerMutationVariables = Exact<{
  artistId: Scalars['Int']['input'];
  deezerId: Scalars['Int']['input'];
}>;


export type LinkArtistToDeezerMutation = { __typename?: 'Mutation', linkArtistToDeezer: { __typename?: 'MutationResult', success: boolean, message: string } };

export type SyncAllTrackedArtistsMutationVariables = Exact<{ [key: string]: never; }>;


export type SyncAllTrackedArtistsMutation = { __typename?: 'Mutation', syncAllTrackedArtists: { __typename?: 'MutationResult', success: boolean, message: string } };

export type DownloadAllTrackedArtistsMutationVariables = Exact<{ [key: string]: never; }>;


export type DownloadAllTrackedArtistsMutation = { __typename?: 'Mutation', downloadAllTrackedArtists: { __typename?: 'MutationResult', success: boolean, message: string } };

export type DownloadAllPlaylistsMutationVariables = Exact<{ [key: string]: never; }>;


export type DownloadAllPlaylistsMutation = { __typename?: 'Mutation', downloadAllPlaylists: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetCachedStatsQueryVariables = Exact<{
  category?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetCachedStatsQuery = { __typename?: 'Query', cachedStats: Array<{ __typename?: 'CachedStatType', key: string, displayName: string, value: unknown, category: string, updatedAt: string }> };

export type CatalogSearchQueryVariables = Exact<{
  query: Scalars['String']['input'];
  types?: InputMaybe<Array<Scalars['String']['input']> | Scalars['String']['input']>;
  limit?: InputMaybe<Scalars['Int']['input']>;
}>;


export type CatalogSearchQuery = { __typename?: 'Query', catalogSearch: { __typename?: 'CatalogSearchResults', artists: Array<{ __typename?: 'CatalogSearchArtist', providerId: string, name: string, imageUrl: string | null, externalUrl: string | null, inLibrary: boolean, localId: number | null, trackingTier: number }>, albums: Array<{ __typename?: 'CatalogSearchAlbum', providerId: string, name: string, imageUrl: string | null, externalUrl: string | null, artistName: string, artistProviderId: string, releaseDate: string | null, albumType: string, totalTracks: number, inLibrary: boolean, localId: number | null }>, tracks: Array<{ __typename?: 'CatalogSearchTrack', providerId: string, name: string, externalUrl: string | null, artistName: string, artistProviderId: string, albumName: string, albumProviderId: string, durationMs: number, inLibrary: boolean, localId: number | null }> } };

export type ImportArtistMutationVariables = Exact<{
  deezerId: Scalars['Int']['input'];
  name: Scalars['String']['input'];
}>;


export type ImportArtistMutation = { __typename?: 'Mutation', importArtist: { __typename?: 'MutationResult', success: boolean, message: string, artist: { __typename?: 'Artist', id: number, name: string, trackingTier: number } | null } };

export type ImportAlbumMutationVariables = Exact<{
  deezerId: Scalars['Int']['input'];
}>;


export type ImportAlbumMutation = { __typename?: 'Mutation', importAlbum: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetLibraryStatsQueryVariables = Exact<{ [key: string]: never; }>;


export type GetLibraryStatsQuery = { __typename?: 'Query', libraryStats: { __typename?: 'LibraryStats', trackedArtists: number, desiredSongs: number, desiredDownloaded: number, desiredMissing: number, desiredFailed: number, desiredUnavailable: number, desiredCompletionPercentage: number, desiredAlbums: number, desiredAlbumsDownloaded: number, desiredAlbumsPartial: number, desiredAlbumsMissing: number, desiredAlbumCompletionPercentage: number, totalArtists: number, totalSongs: number, downloadedSongs: number, missingSongs: number, failedSongs: number, unavailableSongs: number, totalAlbums: number, downloadedAlbums: number, partialAlbums: number, missingAlbums: number, songCompletionPercentage: number, albumCompletionPercentage: number } };

export type GetFallbackMetricsQueryVariables = Exact<{
  days?: InputMaybe<Scalars['Int']['input']>;
}>;


export type GetFallbackMetricsQuery = { __typename?: 'Query', fallbackMetrics: { __typename?: 'FallbackMetrics', totalAttempts: number, totalSuccesses: number, totalFailures: number, successRate: number, timeSeries: Array<{ __typename?: 'MetricTimePoint', timestamp: string, value: number, count: number }>, failureReasons: Array<{ __typename?: 'FailureReasonCount', reason: string, count: number }> } };

export type DownloadUrlMutationVariables = Exact<{
  url: Scalars['String']['input'];
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
}>;


export type DownloadUrlMutation = { __typename?: 'Mutation', downloadUrl: { __typename?: 'MutationResult', success: boolean, message: string, artist: { __typename?: 'Artist', id: number, name: string, gid: string | null, trackingTier: number, addedAt: string | null, lastSynced: string | null } | null, album: { __typename?: 'Album', id: number, name: string, spotifyGid: string | null, deezerId: string | null, totalTracks: number, wanted: boolean, downloaded: boolean, albumType: string | null, albumGroup: string | null, artist: string | null, artistId: number | null } | null, playlist: { __typename?: 'Playlist', id: number, name: string, url: string, enabled: boolean, autoTrackTier: number | null, lastSyncedAt: string | null } | null } };

export type CreatePlaylistFromDownloadMutationVariables = Exact<{
  name: Scalars['String']['input'];
  url: Scalars['String']['input'];
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
}>;


export type CreatePlaylistFromDownloadMutation = { __typename?: 'Mutation', createPlaylist: { __typename?: 'Playlist', id: number, name: string, url: string, enabled: boolean, autoTrackTier: number | null, lastSyncedAt: string | null } };

export type GetExternalListsQueryVariables = Exact<{
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  source?: InputMaybe<Scalars['String']['input']>;
  listType?: InputMaybe<Scalars['String']['input']>;
  status?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetExternalListsQuery = { __typename?: 'Query', externalLists: { __typename?: 'ExternalListPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'ExternalListType', id: number, name: string, source: string, listType: string, username: string, period: string | null, listIdentifier: string | null, status: string, statusMessage: string | null, autoTrackTier: number | null, lastSyncedAt: string | null, createdAt: string | null, totalTracks: number, mappedTracks: number, failedTracks: number }> } };

export type GetExternalListQueryVariables = Exact<{
  id: Scalars['String']['input'];
}>;


export type GetExternalListQuery = { __typename?: 'Query', externalList: { __typename?: 'ExternalListType', id: number, name: string, source: string, listType: string, username: string, period: string | null, listIdentifier: string | null, status: string, statusMessage: string | null, autoTrackTier: number | null, lastSyncedAt: string | null, createdAt: string | null, totalTracks: number, mappedTracks: number, failedTracks: number } | null };

export type CreateExternalListMutationVariables = Exact<{
  source: Scalars['String']['input'];
  listType: Scalars['String']['input'];
  username: Scalars['String']['input'];
  period?: InputMaybe<Scalars['String']['input']>;
  listIdentifier?: InputMaybe<Scalars['String']['input']>;
  autoTrackTier?: InputMaybe<Scalars['Int']['input']>;
}>;


export type CreateExternalListMutation = { __typename?: 'Mutation', createExternalList: { __typename?: 'ExternalListType', id: number, name: string, source: string, listType: string, username: string, status: string, totalTracks: number, mappedTracks: number, failedTracks: number } };

export type UpdateExternalListMutationVariables = Exact<{
  listId: Scalars['Int']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  username?: InputMaybe<Scalars['String']['input']>;
  period?: InputMaybe<Scalars['String']['input']>;
  listIdentifier?: InputMaybe<Scalars['String']['input']>;
}>;


export type UpdateExternalListMutation = { __typename?: 'Mutation', updateExternalList: { __typename?: 'MutationResult', success: boolean, message: string } };

export type DeleteExternalListMutationVariables = Exact<{
  listId: Scalars['Int']['input'];
}>;


export type DeleteExternalListMutation = { __typename?: 'Mutation', deleteExternalList: { __typename?: 'MutationResult', success: boolean, message: string } };

export type ToggleExternalListMutationVariables = Exact<{
  listId: Scalars['Int']['input'];
}>;


export type ToggleExternalListMutation = { __typename?: 'Mutation', toggleExternalList: { __typename?: 'MutationResult', success: boolean, message: string } };

export type ToggleExternalListAutoTrackMutationVariables = Exact<{
  listId: Scalars['Int']['input'];
}>;


export type ToggleExternalListAutoTrackMutation = { __typename?: 'Mutation', toggleExternalListAutoTrack: { __typename?: 'MutationResult', success: boolean, message: string } };

export type SyncExternalListMutationVariables = Exact<{
  listId: Scalars['Int']['input'];
  force?: InputMaybe<Scalars['Boolean']['input']>;
}>;


export type SyncExternalListMutation = { __typename?: 'Mutation', syncExternalList: { __typename?: 'MutationResult', success: boolean, message: string } };

export type SyncAllExternalListsMutationVariables = Exact<{ [key: string]: never; }>;


export type SyncAllExternalListsMutation = { __typename?: 'Mutation', syncAllExternalLists: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetSystemStatusQueryVariables = Exact<{ [key: string]: never; }>;


export type GetSystemStatusQuery = { __typename?: 'Query', systemHealth: { __typename?: 'SystemHealth', canDownload: boolean, downloadBlockerReason: string | null, authentication: { __typename?: 'AuthenticationStatus', cookiesValid: boolean, cookiesErrorType: string | null, cookiesExpireInDays: number | null, poTokenConfigured: boolean, spotifyUserAuthEnabled: boolean, spotifyAuthMode: string }, spotifyRateLimit: { __typename?: 'SpotifyRateLimitStatus', isRateLimited: boolean, rateLimitedUntil: string | null, secondsUntilClear: number | null, isThrottling: boolean, currentDelaySeconds: number, windowCallCount: number, windowMaxCalls: number, windowUsagePercent: number, burstCalls: number, burstMax: number, sustainedCalls: number, sustainedMax: number, hourlyCalls: number, hourlyMax: number }, apiRateLimits: Array<{ __typename?: 'APIRateLimitInfo', apiName: string, isRateLimited: boolean, requestCount: number, maxRequestsPerSecond: number }>, storage: { __typename?: 'StorageStatus', path: string, exists: boolean, isWritable: boolean, availableGb: number | null, usagePercent: number | null, isLow: boolean, isCriticallyLow: boolean, errorMessage: string | null } }, queueStatus: { __typename?: 'QueueStatus', totalPendingTasks: number, queueSize: number } };

export type DisconnectSpotifyMutationVariables = Exact<{ [key: string]: never; }>;


export type DisconnectSpotifyMutation = { __typename?: 'Mutation', disconnectSpotify: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetPendingMetadataUpdatesQueryVariables = Exact<{
  entityType?: InputMaybe<MetadataEntityType>;
  status?: InputMaybe<MetadataUpdateStatus>;
  includeResolved?: InputMaybe<Scalars['Boolean']['input']>;
}>;


export type GetPendingMetadataUpdatesQuery = { __typename?: 'Query', pendingMetadataUpdates: { __typename?: 'MetadataUpdateConnection', edges: Array<{ __typename?: 'MetadataUpdate', id: number, entityType: MetadataEntityType, entityId: number, entityName: string, fieldName: string, oldValue: string, newValue: string, status: MetadataUpdateStatus, detectedAt: string, resolvedAt: string | null, affectedSongsCount: number }>, summary: { __typename?: 'MetadataUpdateSummary', artistUpdates: number, albumUpdates: number, songUpdates: number, totalAffectedSongs: number } } };

export type ApplyMetadataUpdateMutationVariables = Exact<{
  updateId: Scalars['Int']['input'];
}>;


export type ApplyMetadataUpdateMutation = { __typename?: 'Mutation', applyMetadataUpdate: { __typename?: 'MutationResult', success: boolean, message: string } };

export type DismissMetadataUpdateMutationVariables = Exact<{
  updateId: Scalars['Int']['input'];
}>;


export type DismissMetadataUpdateMutation = { __typename?: 'Mutation', dismissMetadataUpdate: { __typename?: 'MutationResult', success: boolean, message: string } };

export type ApplyAllMetadataUpdatesMutationVariables = Exact<{ [key: string]: never; }>;


export type ApplyAllMetadataUpdatesMutation = { __typename?: 'Mutation', applyAllMetadataUpdates: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CheckArtistMetadataMutationVariables = Exact<{
  artistId: Scalars['Int']['input'];
}>;


export type CheckArtistMetadataMutation = { __typename?: 'Mutation', checkArtistMetadata: { __typename?: 'MetadataCheckResult', success: boolean, message: string, changeDetected: boolean, oldValue: string | null, newValue: string | null } };

export type CheckAlbumMetadataMutationVariables = Exact<{
  albumId: Scalars['Int']['input'];
}>;


export type CheckAlbumMetadataMutation = { __typename?: 'Mutation', checkAlbumMetadata: { __typename?: 'MetadataCheckResult', success: boolean, message: string, changeDetected: boolean, oldValue: string | null, newValue: string | null } };

export type CheckSongMetadataMutationVariables = Exact<{
  songId: Scalars['Int']['input'];
}>;


export type CheckSongMetadataMutation = { __typename?: 'Mutation', checkSongMetadata: { __typename?: 'MetadataCheckResult', success: boolean, message: string, changeDetected: boolean, oldValue: string | null, newValue: string | null } };

export type DeletePlaylistMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type DeletePlaylistMutation = { __typename?: 'Mutation', deletePlaylist: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetPlaylistInfoQueryVariables = Exact<{
  url: Scalars['String']['input'];
}>;


export type GetPlaylistInfoQuery = { __typename?: 'Query', playlistInfo: { __typename?: 'PlaylistInfo', name: string, ownerName: string | null, trackCount: number, imageUrl: string | null, provider: string } | null };

export type GetAppSettingsQueryVariables = Exact<{ [key: string]: never; }>;


export type GetAppSettingsQuery = { __typename?: 'Query', appSettings: Array<{ __typename?: 'SettingsCategoryType', category: string, label: string, settings: Array<{ __typename?: 'AppSettingType', key: string, value: string, type: string, category: string, label: string, description: string, isDefault: boolean, sensitive: boolean, options: Array<string> | null }> }> };

export type UpdateAppSettingMutationVariables = Exact<{
  key: Scalars['String']['input'];
  value: Scalars['String']['input'];
}>;


export type UpdateAppSettingMutation = { __typename?: 'Mutation', updateAppSetting: { __typename?: 'UpdateSettingResult', success: boolean, message: string, setting: { __typename?: 'AppSettingType', key: string, value: string, type: string, category: string, label: string, description: string, isDefault: boolean, sensitive: boolean, options: Array<string> | null } | null } };

export type ResetAppSettingMutationVariables = Exact<{
  key: Scalars['String']['input'];
}>;


export type ResetAppSettingMutation = { __typename?: 'Mutation', resetAppSetting: { __typename?: 'UpdateSettingResult', success: boolean, message: string, setting: { __typename?: 'AppSettingType', key: string, value: string, type: string, category: string, label: string, description: string, isDefault: boolean, sensitive: boolean, options: Array<string> | null } | null } };

export type GetDeezerGenresQueryVariables = Exact<{ [key: string]: never; }>;


export type GetDeezerGenresQuery = { __typename?: 'Query', deezerGenres: Array<{ __typename?: 'DeezerGenreType', id: number, name: string }> };

export type UploadCookieFileMutationVariables = Exact<{
  content: Scalars['String']['input'];
}>;


export type UploadCookieFileMutation = { __typename?: 'Mutation', uploadCookieFile: { __typename?: 'CookieUploadResult', success: boolean, message: string } };

export type MigrateSettingsFromYamlMutationVariables = Exact<{ [key: string]: never; }>;


export type MigrateSettingsFromYamlMutation = { __typename?: 'Mutation', migrateSettingsFromYaml: { __typename?: 'YamlMigrationResult', success: boolean, migrated: number, skipped: number, message: string } };

export type GetSongsQueryVariables = Exact<{
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  artistId?: InputMaybe<Scalars['Int']['input']>;
  albumId?: InputMaybe<Scalars['Int']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  unavailable?: InputMaybe<Scalars['Boolean']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
  maxBitrate?: InputMaybe<Scalars['Int']['input']>;
}>;


export type GetSongsQuery = { __typename?: 'Query', songs: { __typename?: 'SongPage', items: Array<{ __typename?: 'Song', id: number, name: string, gid: string | null, deezerId: string | null, primaryArtist: string, primaryArtistId: number, primaryArtistGid: string | null, createdAt: string, failedCount: number, bitrate: number, unavailable: boolean, filePath: string | null, downloaded: boolean, spotifyUri: string | null, downloadProvider: DownloadProvider | null }>, pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number } } };

export type GetSongQueryVariables = Exact<{
  id: Scalars['String']['input'];
}>;


export type GetSongQuery = { __typename?: 'Query', song: { __typename?: 'Song', id: number, name: string, gid: string | null, deezerId: string | null, primaryArtist: string, primaryArtistId: number, createdAt: string, failedCount: number, bitrate: number, unavailable: boolean, filePath: string | null, downloaded: boolean, spotifyUri: string | null, downloadProvider: DownloadProvider | null } | null };

export type GetSystemHealthQueryVariables = Exact<{ [key: string]: never; }>;


export type GetSystemHealthQuery = { __typename?: 'Query', systemHealth: { __typename?: 'SystemHealth', canDownload: boolean, downloadBlockerReason: string | null, authentication: { __typename?: 'AuthenticationStatus', cookiesValid: boolean, cookiesErrorType: string | null, cookiesErrorMessage: string | null, cookiesExpireInDays: number | null, poTokenConfigured: boolean, spotifyAuthMode: string, spotifyTokenValid: boolean, spotifyTokenExpired: boolean, spotifyTokenExpiresInHours: number | null, spotifyTokenErrorMessage: string | null } } };

export type GetQueueStatusQueryVariables = Exact<{ [key: string]: never; }>;


export type GetQueueStatusQuery = { __typename?: 'Query', queueStatus: { __typename?: 'QueueStatus', totalPendingTasks: number, queueSize: number, taskCounts: Array<{ __typename?: 'TaskCount', taskName: string, count: number }>, pendingTasks: Array<{ __typename?: 'PendingTask', taskId: string, taskName: string, displayName: string, entityType: string | null, entityId: string | null, entityName: string | null, status: string, createdAt: string | null }> } };

export type CancelAllPendingTasksMutationVariables = Exact<{ [key: string]: never; }>;


export type CancelAllPendingTasksMutation = { __typename?: 'Mutation', cancelAllPendingTasks: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CancelTasksByNameMutationVariables = Exact<{
  taskName: Scalars['String']['input'];
}>;


export type CancelTasksByNameMutation = { __typename?: 'Mutation', cancelTasksByName: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CancelRunningTasksByNameMutationVariables = Exact<{
  taskName: Scalars['String']['input'];
}>;


export type CancelRunningTasksByNameMutation = { __typename?: 'Mutation', cancelRunningTasksByName: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CancelAllTasksMutationVariables = Exact<{ [key: string]: never; }>;


export type CancelAllTasksMutation = { __typename?: 'Mutation', cancelAllTasks: { __typename?: 'MutationResult', success: boolean, message: string } };

export type CancelTaskByIdMutationVariables = Exact<{
  taskId: Scalars['String']['input'];
}>;


export type CancelTaskByIdMutation = { __typename?: 'Mutation', cancelTaskById: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetPeriodicTasksQueryVariables = Exact<{
  enabledOnly?: InputMaybe<Scalars['Boolean']['input']>;
}>;


export type GetPeriodicTasksQuery = { __typename?: 'Query', periodicTasks: Array<{ __typename?: 'PeriodicTask', id: number, name: string, task: string, enabled: boolean, isCore: boolean, description: string | null, scheduleDescription: string, lastRunAt: string | null, totalRunCount: number }> };

export type SetPeriodicTaskEnabledMutationVariables = Exact<{
  taskId: Scalars['Int']['input'];
  enabled: Scalars['Boolean']['input'];
}>;


export type SetPeriodicTaskEnabledMutation = { __typename?: 'Mutation', setPeriodicTaskEnabled: { __typename?: 'PeriodicTask', id: number, name: string, enabled: boolean, isCore: boolean } };

export type RunPeriodicTaskNowMutationVariables = Exact<{
  taskId: Scalars['Int']['input'];
}>;


export type RunPeriodicTaskNowMutation = { __typename?: 'Mutation', runPeriodicTaskNow: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetOneOffTasksQueryVariables = Exact<{ [key: string]: never; }>;


export type GetOneOffTasksQuery = { __typename?: 'Query', oneOffTasks: Array<{ __typename?: 'OneOffTask', id: string, name: string, description: string, category: string }> };

export type RunOneOffTaskMutationVariables = Exact<{
  taskId: Scalars['String']['input'];
}>;


export type RunOneOffTaskMutation = { __typename?: 'Mutation', runOneOffTask: { __typename?: 'MutationResult', success: boolean, message: string } };

export type GetTaskHistoryQueryVariables = Exact<{
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  status?: InputMaybe<Scalars['String']['input']>;
  type?: InputMaybe<Scalars['String']['input']>;
  entityType?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetTaskHistoryQuery = { __typename?: 'Query', taskHistory: { __typename?: 'TaskHistoryPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'TaskHistory', id: string, taskId: string, type: TaskType, entityId: string, entityType: EntityType, status: TaskStatus, startedAt: string, completedAt: string | null, durationSeconds: number | null, progressPercentage: number | null, logMessages: Array<string> }> } };

export type GetArtistsTestQueryVariables = Exact<{
  trackingTier?: InputMaybe<Scalars['Int']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetArtistsTestQuery = { __typename?: 'Query', artists: { __typename?: 'ArtistPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Artist', id: number, name: string, gid: string | null, deezerId: string | null, trackingTier: number, addedAt: string | null, lastSynced: string | null }> } };

export type GetAlbumsTestQueryVariables = Exact<{
  artistId?: InputMaybe<Scalars['Int']['input']>;
  wanted?: InputMaybe<Scalars['Boolean']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetAlbumsTestQuery = { __typename?: 'Query', albums: { __typename?: 'AlbumPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Album', id: number, name: string, spotifyGid: string | null, deezerId: string | null, totalTracks: number, wanted: boolean, downloaded: boolean, albumType: string | null, albumGroup: string | null, artist: string | null, artistId: number | null }> } };

export type GetPlaylistsTestQueryVariables = Exact<{
  enabled?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetPlaylistsTestQuery = { __typename?: 'Query', playlists: { __typename?: 'PlaylistPage', pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number }, items: Array<{ __typename?: 'Playlist', id: number, name: string, url: string, status: string, statusMessage: string | null, enabled: boolean, autoTrackTier: number | null, lastSyncedAt: string | null }> } };

export type GetSongsTestQueryVariables = Exact<{
  page?: InputMaybe<Scalars['Int']['input']>;
  pageSize?: InputMaybe<Scalars['Int']['input']>;
  artistId?: InputMaybe<Scalars['Int']['input']>;
  downloaded?: InputMaybe<Scalars['Boolean']['input']>;
  unavailable?: InputMaybe<Scalars['Boolean']['input']>;
  sortBy?: InputMaybe<Scalars['String']['input']>;
  sortDirection?: InputMaybe<Scalars['String']['input']>;
  search?: InputMaybe<Scalars['String']['input']>;
}>;


export type GetSongsTestQuery = { __typename?: 'Query', songs: { __typename?: 'SongPage', items: Array<{ __typename?: 'Song', id: number, name: string, gid: string | null, deezerId: string | null, primaryArtist: string, primaryArtistId: number, createdAt: string, failedCount: number, bitrate: number, unavailable: boolean, filePath: string | null, downloaded: boolean, spotifyUri: string | null }>, pageInfo: { __typename?: 'OffsetPageInfo', page: number, pageSize: number, totalPages: number, totalCount: number } } };

export type TogglePlaylistTestMutationVariables = Exact<{
  playlistId: Scalars['Int']['input'];
}>;


export type TogglePlaylistTestMutation = { __typename?: 'Mutation', togglePlaylist: { __typename?: 'MutationResult', success: boolean, message: string, playlist: { __typename?: 'Playlist', id: number, name: string, status: string, statusMessage: string | null, enabled: boolean } | null } };


export const GetArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"artist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"addedAt"}},{"kind":"Field","name":{"kind":"Name","value":"lastSynced"}},{"kind":"Field","name":{"kind":"Name","value":"lastDownloaded"}},{"kind":"Field","name":{"kind":"Name","value":"undownloadedCount"}},{"kind":"Field","name":{"kind":"Name","value":"albumCount"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedAlbumCount"}},{"kind":"Field","name":{"kind":"Name","value":"songCount"}}]}}]}}]} as unknown as DocumentNode<GetArtistQuery, GetArtistQueryVariables>;
export const GetAlbumDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetAlbum"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"album"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"albumGroup"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"artistId"}},{"kind":"Field","name":{"kind":"Name","value":"artistGid"}}]}}]}}]} as unknown as DocumentNode<GetAlbumQuery, GetAlbumQueryVariables>;
export const GetAlbumByIdDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetAlbumById"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"albumById"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"albumGroup"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"artistId"}},{"kind":"Field","name":{"kind":"Name","value":"artistGid"}}]}}]}}]} as unknown as DocumentNode<GetAlbumByIdQuery, GetAlbumByIdQueryVariables>;
export const GetArtistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetArtists"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"trackingTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"hasUndownloaded"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"artists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"trackingTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"trackingTier"}}},{"kind":"Argument","name":{"kind":"Name","value":"hasUndownloaded"},"value":{"kind":"Variable","name":{"kind":"Name","value":"hasUndownloaded"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"addedAt"}},{"kind":"Field","name":{"kind":"Name","value":"lastSynced"}},{"kind":"Field","name":{"kind":"Name","value":"lastDownloaded"}},{"kind":"Field","name":{"kind":"Name","value":"undownloadedCount"}},{"kind":"Field","name":{"kind":"Name","value":"failedSongCount"}},{"kind":"Field","name":{"kind":"Name","value":"albumCount"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedAlbumCount"}},{"kind":"Field","name":{"kind":"Name","value":"songCount"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedSongCount"}}]}}]}}]}}]} as unknown as DocumentNode<GetArtistsQuery, GetArtistsQueryVariables>;
export const GetAlbumsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetAlbums"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"albums"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"wanted"},"value":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}}},{"kind":"Argument","name":{"kind":"Name","value":"downloaded"},"value":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"albumGroup"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"artistId"}},{"kind":"Field","name":{"kind":"Name","value":"artistGid"}}]}}]}}]}}]} as unknown as DocumentNode<GetAlbumsQuery, GetAlbumsQueryVariables>;
export const GetPlaylistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetPlaylists"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"enabled"},"value":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"url"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"m3uEnabled"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}},{"kind":"Field","name":{"kind":"Name","value":"provider"}}]}}]}}]}}]} as unknown as DocumentNode<GetPlaylistsQuery, GetPlaylistsQueryVariables>;
export const SyncArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SyncArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"addedAt"}},{"kind":"Field","name":{"kind":"Name","value":"lastSynced"}},{"kind":"Field","name":{"kind":"Name","value":"undownloadedCount"}}]}}]}}]} as unknown as DocumentNode<SyncArtistMutation, SyncArtistMutationVariables>;
export const DownloadArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DownloadArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"downloadArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DownloadArtistMutation, DownloadArtistMutationVariables>;
export const RetryFailedSongsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RetryFailedSongs"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"retryFailedSongs"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<RetryFailedSongsMutation, RetryFailedSongsMutationVariables>;
export const SyncPlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SyncPlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<SyncPlaylistMutation, SyncPlaylistMutationVariables>;
export const TrackArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"TrackArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"trackArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"artist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}}]}}]}}]}}]} as unknown as DocumentNode<TrackArtistMutation, TrackArtistMutationVariables>;
export const UntrackArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UntrackArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"untrackArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"artist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}}]}}]}}]}}]} as unknown as DocumentNode<UntrackArtistMutation, UntrackArtistMutationVariables>;
export const UpdateArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UpdateArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"input"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"UpdateArtistInput"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"updateArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"input"},"value":{"kind":"Variable","name":{"kind":"Name","value":"input"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}}]}}]}}]} as unknown as DocumentNode<UpdateArtistMutation, UpdateArtistMutationVariables>;
export const SetAlbumWantedDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SetAlbumWanted"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"setAlbumWanted"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"albumId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}}},{"kind":"Argument","name":{"kind":"Name","value":"wanted"},"value":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"album"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}}]}}]}}]}}]} as unknown as DocumentNode<SetAlbumWantedMutation, SetAlbumWantedMutationVariables>;
export const DownloadAlbumDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DownloadAlbum"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"downloadAlbum"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"albumId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}}]}}]}}]} as unknown as DocumentNode<DownloadAlbumMutation, DownloadAlbumMutationVariables>;
export const TogglePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"TogglePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"togglePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}}]}}]}}]}}]} as unknown as DocumentNode<TogglePlaylistMutation, TogglePlaylistMutationVariables>;
export const ForceSyncPlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ForceSyncPlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"force"},"value":{"kind":"BooleanValue","value":true}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ForceSyncPlaylistMutation, ForceSyncPlaylistMutationVariables>;
export const RecheckPlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RecheckPlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"recheck"},"value":{"kind":"BooleanValue","value":true}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}}]}}]}}]}}]} as unknown as DocumentNode<RecheckPlaylistMutation, RecheckPlaylistMutationVariables>;
export const TogglePlaylistAutoTrackDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"TogglePlaylistAutoTrack"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"togglePlaylistAutoTrack"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}}]}}]}}]}}]} as unknown as DocumentNode<TogglePlaylistAutoTrackMutation, TogglePlaylistAutoTrackMutationVariables>;
export const TogglePlaylistM3uDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"TogglePlaylistM3u"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"togglePlaylistM3u"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"m3uEnabled"}}]}}]}}]}}]} as unknown as DocumentNode<TogglePlaylistM3uMutation, TogglePlaylistM3uMutationVariables>;
export const UpdatePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UpdatePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"updatePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}},{"kind":"Argument","name":{"kind":"Name","value":"autoTrackTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<UpdatePlaylistMutation, UpdatePlaylistMutationVariables>;
export const CreatePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreatePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}},{"kind":"Argument","name":{"kind":"Name","value":"autoTrackTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"url"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}}]}}]}}]} as unknown as DocumentNode<CreatePlaylistMutation, CreatePlaylistMutationVariables>;
export const GetUnlinkedArtistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetUnlinkedArtists"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"hasDownloads"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"unlinkedArtists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}},{"kind":"Argument","name":{"kind":"Name","value":"hasDownloads"},"value":{"kind":"Variable","name":{"kind":"Name","value":"hasDownloads"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"songCount"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedSongCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}}]}}]}}]} as unknown as DocumentNode<GetUnlinkedArtistsQuery, GetUnlinkedArtistsQueryVariables>;
export const PreviewDeezerArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"PreviewDeezerArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"previewDeezerArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"deezerId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"imageUrl"}}]}}]}}]} as unknown as DocumentNode<PreviewDeezerArtistQuery, PreviewDeezerArtistQueryVariables>;
export const LinkArtistToDeezerDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"LinkArtistToDeezer"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"linkArtistToDeezer"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"deezerId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<LinkArtistToDeezerMutation, LinkArtistToDeezerMutationVariables>;
export const SyncAllTrackedArtistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SyncAllTrackedArtists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncAllTrackedArtists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<SyncAllTrackedArtistsMutation, SyncAllTrackedArtistsMutationVariables>;
export const DownloadAllTrackedArtistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DownloadAllTrackedArtists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"downloadAllTrackedArtists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DownloadAllTrackedArtistsMutation, DownloadAllTrackedArtistsMutationVariables>;
export const DownloadAllPlaylistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DownloadAllPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"downloadAllPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DownloadAllPlaylistsMutation, DownloadAllPlaylistsMutationVariables>;
export const GetCachedStatsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetCachedStats"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"category"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cachedStats"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"category"},"value":{"kind":"Variable","name":{"kind":"Name","value":"category"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"key"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}},{"kind":"Field","name":{"kind":"Name","value":"value"}},{"kind":"Field","name":{"kind":"Name","value":"category"}},{"kind":"Field","name":{"kind":"Name","value":"updatedAt"}}]}}]}}]} as unknown as DocumentNode<GetCachedStatsQuery, GetCachedStatsQueryVariables>;
export const CatalogSearchDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"CatalogSearch"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"query"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"types"}},"type":{"kind":"ListType","type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"limit"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"catalogSearch"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"query"},"value":{"kind":"Variable","name":{"kind":"Name","value":"query"}}},{"kind":"Argument","name":{"kind":"Name","value":"types"},"value":{"kind":"Variable","name":{"kind":"Name","value":"types"}}},{"kind":"Argument","name":{"kind":"Name","value":"limit"},"value":{"kind":"Variable","name":{"kind":"Name","value":"limit"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"artists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"providerId"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"imageUrl"}},{"kind":"Field","name":{"kind":"Name","value":"externalUrl"}},{"kind":"Field","name":{"kind":"Name","value":"inLibrary"}},{"kind":"Field","name":{"kind":"Name","value":"localId"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}}]}},{"kind":"Field","name":{"kind":"Name","value":"albums"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"providerId"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"imageUrl"}},{"kind":"Field","name":{"kind":"Name","value":"externalUrl"}},{"kind":"Field","name":{"kind":"Name","value":"artistName"}},{"kind":"Field","name":{"kind":"Name","value":"artistProviderId"}},{"kind":"Field","name":{"kind":"Name","value":"releaseDate"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"inLibrary"}},{"kind":"Field","name":{"kind":"Name","value":"localId"}}]}},{"kind":"Field","name":{"kind":"Name","value":"tracks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"providerId"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"externalUrl"}},{"kind":"Field","name":{"kind":"Name","value":"artistName"}},{"kind":"Field","name":{"kind":"Name","value":"artistProviderId"}},{"kind":"Field","name":{"kind":"Name","value":"albumName"}},{"kind":"Field","name":{"kind":"Name","value":"albumProviderId"}},{"kind":"Field","name":{"kind":"Name","value":"durationMs"}},{"kind":"Field","name":{"kind":"Name","value":"inLibrary"}},{"kind":"Field","name":{"kind":"Name","value":"localId"}}]}}]}}]}}]} as unknown as DocumentNode<CatalogSearchQuery, CatalogSearchQueryVariables>;
export const ImportArtistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ImportArtist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"importArtist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"deezerId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}}},{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"artist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}}]}}]}}]}}]} as unknown as DocumentNode<ImportArtistMutation, ImportArtistMutationVariables>;
export const ImportAlbumDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ImportAlbum"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"importAlbum"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"deezerId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"deezerId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ImportAlbumMutation, ImportAlbumMutationVariables>;
export const GetLibraryStatsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetLibraryStats"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"libraryStats"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"trackedArtists"}},{"kind":"Field","name":{"kind":"Name","value":"desiredSongs"}},{"kind":"Field","name":{"kind":"Name","value":"desiredDownloaded"}},{"kind":"Field","name":{"kind":"Name","value":"desiredMissing"}},{"kind":"Field","name":{"kind":"Name","value":"desiredFailed"}},{"kind":"Field","name":{"kind":"Name","value":"desiredUnavailable"}},{"kind":"Field","name":{"kind":"Name","value":"desiredCompletionPercentage"}},{"kind":"Field","name":{"kind":"Name","value":"desiredAlbums"}},{"kind":"Field","name":{"kind":"Name","value":"desiredAlbumsDownloaded"}},{"kind":"Field","name":{"kind":"Name","value":"desiredAlbumsPartial"}},{"kind":"Field","name":{"kind":"Name","value":"desiredAlbumsMissing"}},{"kind":"Field","name":{"kind":"Name","value":"desiredAlbumCompletionPercentage"}},{"kind":"Field","name":{"kind":"Name","value":"totalArtists"}},{"kind":"Field","name":{"kind":"Name","value":"totalSongs"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedSongs"}},{"kind":"Field","name":{"kind":"Name","value":"missingSongs"}},{"kind":"Field","name":{"kind":"Name","value":"failedSongs"}},{"kind":"Field","name":{"kind":"Name","value":"unavailableSongs"}},{"kind":"Field","name":{"kind":"Name","value":"totalAlbums"}},{"kind":"Field","name":{"kind":"Name","value":"downloadedAlbums"}},{"kind":"Field","name":{"kind":"Name","value":"partialAlbums"}},{"kind":"Field","name":{"kind":"Name","value":"missingAlbums"}},{"kind":"Field","name":{"kind":"Name","value":"songCompletionPercentage"}},{"kind":"Field","name":{"kind":"Name","value":"albumCompletionPercentage"}}]}}]}}]} as unknown as DocumentNode<GetLibraryStatsQuery, GetLibraryStatsQueryVariables>;
export const GetFallbackMetricsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetFallbackMetrics"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"days"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"fallbackMetrics"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"days"},"value":{"kind":"Variable","name":{"kind":"Name","value":"days"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"totalAttempts"}},{"kind":"Field","name":{"kind":"Name","value":"totalSuccesses"}},{"kind":"Field","name":{"kind":"Name","value":"totalFailures"}},{"kind":"Field","name":{"kind":"Name","value":"successRate"}},{"kind":"Field","name":{"kind":"Name","value":"timeSeries"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"timestamp"}},{"kind":"Field","name":{"kind":"Name","value":"value"}},{"kind":"Field","name":{"kind":"Name","value":"count"}}]}},{"kind":"Field","name":{"kind":"Name","value":"failureReasons"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"reason"}},{"kind":"Field","name":{"kind":"Name","value":"count"}}]}}]}}]}}]} as unknown as DocumentNode<GetFallbackMetricsQuery, GetFallbackMetricsQueryVariables>;
export const DownloadUrlDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DownloadUrl"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"downloadUrl"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}},{"kind":"Argument","name":{"kind":"Name","value":"autoTrackTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"artist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"addedAt"}},{"kind":"Field","name":{"kind":"Name","value":"lastSynced"}}]}},{"kind":"Field","name":{"kind":"Name","value":"album"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"albumGroup"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"artistId"}}]}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"url"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}}]}}]}}]}}]} as unknown as DocumentNode<DownloadUrlMutation, DownloadUrlMutationVariables>;
export const CreatePlaylistFromDownloadDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreatePlaylistFromDownload"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}},{"kind":"Argument","name":{"kind":"Name","value":"autoTrackTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"url"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}}]}}]}}]} as unknown as DocumentNode<CreatePlaylistFromDownloadMutation, CreatePlaylistFromDownloadMutationVariables>;
export const GetExternalListsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetExternalLists"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"source"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listType"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"status"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"externalLists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"source"},"value":{"kind":"Variable","name":{"kind":"Name","value":"source"}}},{"kind":"Argument","name":{"kind":"Name","value":"listType"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listType"}}},{"kind":"Argument","name":{"kind":"Name","value":"status"},"value":{"kind":"Variable","name":{"kind":"Name","value":"status"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"source"}},{"kind":"Field","name":{"kind":"Name","value":"listType"}},{"kind":"Field","name":{"kind":"Name","value":"username"}},{"kind":"Field","name":{"kind":"Name","value":"period"}},{"kind":"Field","name":{"kind":"Name","value":"listIdentifier"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"mappedTracks"}},{"kind":"Field","name":{"kind":"Name","value":"failedTracks"}}]}}]}}]}}]} as unknown as DocumentNode<GetExternalListsQuery, GetExternalListsQueryVariables>;
export const GetExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"externalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"source"}},{"kind":"Field","name":{"kind":"Name","value":"listType"}},{"kind":"Field","name":{"kind":"Name","value":"username"}},{"kind":"Field","name":{"kind":"Name","value":"period"}},{"kind":"Field","name":{"kind":"Name","value":"listIdentifier"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"mappedTracks"}},{"kind":"Field","name":{"kind":"Name","value":"failedTracks"}}]}}]}}]} as unknown as DocumentNode<GetExternalListQuery, GetExternalListQueryVariables>;
export const CreateExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreateExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"source"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listType"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"username"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"period"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listIdentifier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createExternalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"source"},"value":{"kind":"Variable","name":{"kind":"Name","value":"source"}}},{"kind":"Argument","name":{"kind":"Name","value":"listType"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listType"}}},{"kind":"Argument","name":{"kind":"Name","value":"username"},"value":{"kind":"Variable","name":{"kind":"Name","value":"username"}}},{"kind":"Argument","name":{"kind":"Name","value":"period"},"value":{"kind":"Variable","name":{"kind":"Name","value":"period"}}},{"kind":"Argument","name":{"kind":"Name","value":"listIdentifier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listIdentifier"}}},{"kind":"Argument","name":{"kind":"Name","value":"autoTrackTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"autoTrackTier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"source"}},{"kind":"Field","name":{"kind":"Name","value":"listType"}},{"kind":"Field","name":{"kind":"Name","value":"username"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"mappedTracks"}},{"kind":"Field","name":{"kind":"Name","value":"failedTracks"}}]}}]}}]} as unknown as DocumentNode<CreateExternalListMutation, CreateExternalListMutationVariables>;
export const UpdateExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UpdateExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"username"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"period"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listIdentifier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"updateExternalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"listId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listId"}}},{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"username"},"value":{"kind":"Variable","name":{"kind":"Name","value":"username"}}},{"kind":"Argument","name":{"kind":"Name","value":"period"},"value":{"kind":"Variable","name":{"kind":"Name","value":"period"}}},{"kind":"Argument","name":{"kind":"Name","value":"listIdentifier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listIdentifier"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<UpdateExternalListMutation, UpdateExternalListMutationVariables>;
export const DeleteExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DeleteExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleteExternalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"listId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DeleteExternalListMutation, DeleteExternalListMutationVariables>;
export const ToggleExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ToggleExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"toggleExternalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"listId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ToggleExternalListMutation, ToggleExternalListMutationVariables>;
export const ToggleExternalListAutoTrackDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ToggleExternalListAutoTrack"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"toggleExternalListAutoTrack"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"listId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ToggleExternalListAutoTrackMutation, ToggleExternalListAutoTrackMutationVariables>;
export const SyncExternalListDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SyncExternalList"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"listId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"force"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncExternalList"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"listId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"listId"}}},{"kind":"Argument","name":{"kind":"Name","value":"force"},"value":{"kind":"Variable","name":{"kind":"Name","value":"force"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<SyncExternalListMutation, SyncExternalListMutationVariables>;
export const SyncAllExternalListsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SyncAllExternalLists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"syncAllExternalLists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<SyncAllExternalListsMutation, SyncAllExternalListsMutationVariables>;
export const GetSystemStatusDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetSystemStatus"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"systemHealth"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"canDownload"}},{"kind":"Field","name":{"kind":"Name","value":"downloadBlockerReason"}},{"kind":"Field","name":{"kind":"Name","value":"authentication"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cookiesValid"}},{"kind":"Field","name":{"kind":"Name","value":"cookiesErrorType"}},{"kind":"Field","name":{"kind":"Name","value":"cookiesExpireInDays"}},{"kind":"Field","name":{"kind":"Name","value":"poTokenConfigured"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUserAuthEnabled"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyAuthMode"}}]}},{"kind":"Field","name":{"kind":"Name","value":"spotifyRateLimit"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"isRateLimited"}},{"kind":"Field","name":{"kind":"Name","value":"rateLimitedUntil"}},{"kind":"Field","name":{"kind":"Name","value":"secondsUntilClear"}},{"kind":"Field","name":{"kind":"Name","value":"isThrottling"}},{"kind":"Field","name":{"kind":"Name","value":"currentDelaySeconds"}},{"kind":"Field","name":{"kind":"Name","value":"windowCallCount"}},{"kind":"Field","name":{"kind":"Name","value":"windowMaxCalls"}},{"kind":"Field","name":{"kind":"Name","value":"windowUsagePercent"}},{"kind":"Field","name":{"kind":"Name","value":"burstCalls"}},{"kind":"Field","name":{"kind":"Name","value":"burstMax"}},{"kind":"Field","name":{"kind":"Name","value":"sustainedCalls"}},{"kind":"Field","name":{"kind":"Name","value":"sustainedMax"}},{"kind":"Field","name":{"kind":"Name","value":"hourlyCalls"}},{"kind":"Field","name":{"kind":"Name","value":"hourlyMax"}}]}},{"kind":"Field","name":{"kind":"Name","value":"apiRateLimits"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"apiName"}},{"kind":"Field","name":{"kind":"Name","value":"isRateLimited"}},{"kind":"Field","name":{"kind":"Name","value":"requestCount"}},{"kind":"Field","name":{"kind":"Name","value":"maxRequestsPerSecond"}}]}},{"kind":"Field","name":{"kind":"Name","value":"storage"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"path"}},{"kind":"Field","name":{"kind":"Name","value":"exists"}},{"kind":"Field","name":{"kind":"Name","value":"isWritable"}},{"kind":"Field","name":{"kind":"Name","value":"availableGb"}},{"kind":"Field","name":{"kind":"Name","value":"usagePercent"}},{"kind":"Field","name":{"kind":"Name","value":"isLow"}},{"kind":"Field","name":{"kind":"Name","value":"isCriticallyLow"}},{"kind":"Field","name":{"kind":"Name","value":"errorMessage"}}]}}]}},{"kind":"Field","name":{"kind":"Name","value":"queueStatus"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"totalPendingTasks"}},{"kind":"Field","name":{"kind":"Name","value":"queueSize"}}]}}]}}]} as unknown as DocumentNode<GetSystemStatusQuery, GetSystemStatusQueryVariables>;
export const DisconnectSpotifyDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DisconnectSpotify"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"disconnectSpotify"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DisconnectSpotifyMutation, DisconnectSpotifyMutationVariables>;
export const GetPendingMetadataUpdatesDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetPendingMetadataUpdates"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"entityType"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"MetadataEntityType"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"status"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"MetadataUpdateStatus"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"includeResolved"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pendingMetadataUpdates"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"entityType"},"value":{"kind":"Variable","name":{"kind":"Name","value":"entityType"}}},{"kind":"Argument","name":{"kind":"Name","value":"status"},"value":{"kind":"Variable","name":{"kind":"Name","value":"status"}}},{"kind":"Argument","name":{"kind":"Name","value":"includeResolved"},"value":{"kind":"Variable","name":{"kind":"Name","value":"includeResolved"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"edges"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"entityType"}},{"kind":"Field","name":{"kind":"Name","value":"entityId"}},{"kind":"Field","name":{"kind":"Name","value":"entityName"}},{"kind":"Field","name":{"kind":"Name","value":"fieldName"}},{"kind":"Field","name":{"kind":"Name","value":"oldValue"}},{"kind":"Field","name":{"kind":"Name","value":"newValue"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"detectedAt"}},{"kind":"Field","name":{"kind":"Name","value":"resolvedAt"}},{"kind":"Field","name":{"kind":"Name","value":"affectedSongsCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"summary"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"artistUpdates"}},{"kind":"Field","name":{"kind":"Name","value":"albumUpdates"}},{"kind":"Field","name":{"kind":"Name","value":"songUpdates"}},{"kind":"Field","name":{"kind":"Name","value":"totalAffectedSongs"}}]}}]}}]}}]} as unknown as DocumentNode<GetPendingMetadataUpdatesQuery, GetPendingMetadataUpdatesQueryVariables>;
export const ApplyMetadataUpdateDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ApplyMetadataUpdate"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"updateId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"applyMetadataUpdate"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"updateId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"updateId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ApplyMetadataUpdateMutation, ApplyMetadataUpdateMutationVariables>;
export const DismissMetadataUpdateDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DismissMetadataUpdate"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"updateId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"dismissMetadataUpdate"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"updateId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"updateId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DismissMetadataUpdateMutation, DismissMetadataUpdateMutationVariables>;
export const ApplyAllMetadataUpdatesDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ApplyAllMetadataUpdates"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"applyAllMetadataUpdates"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<ApplyAllMetadataUpdatesMutation, ApplyAllMetadataUpdatesMutationVariables>;
export const CheckArtistMetadataDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CheckArtistMetadata"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"checkArtistMetadata"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"changeDetected"}},{"kind":"Field","name":{"kind":"Name","value":"oldValue"}},{"kind":"Field","name":{"kind":"Name","value":"newValue"}}]}}]}}]} as unknown as DocumentNode<CheckArtistMetadataMutation, CheckArtistMetadataMutationVariables>;
export const CheckAlbumMetadataDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CheckAlbumMetadata"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"checkAlbumMetadata"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"albumId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"changeDetected"}},{"kind":"Field","name":{"kind":"Name","value":"oldValue"}},{"kind":"Field","name":{"kind":"Name","value":"newValue"}}]}}]}}]} as unknown as DocumentNode<CheckAlbumMetadataMutation, CheckAlbumMetadataMutationVariables>;
export const CheckSongMetadataDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CheckSongMetadata"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"songId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"checkSongMetadata"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"songId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"songId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"changeDetected"}},{"kind":"Field","name":{"kind":"Name","value":"oldValue"}},{"kind":"Field","name":{"kind":"Name","value":"newValue"}}]}}]}}]} as unknown as DocumentNode<CheckSongMetadataMutation, CheckSongMetadataMutationVariables>;
export const DeletePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DeletePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deletePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<DeletePlaylistMutation, DeletePlaylistMutationVariables>;
export const GetPlaylistInfoDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetPlaylistInfo"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlistInfo"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"ownerName"}},{"kind":"Field","name":{"kind":"Name","value":"trackCount"}},{"kind":"Field","name":{"kind":"Name","value":"imageUrl"}},{"kind":"Field","name":{"kind":"Name","value":"provider"}}]}}]}}]} as unknown as DocumentNode<GetPlaylistInfoQuery, GetPlaylistInfoQueryVariables>;
export const GetAppSettingsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetAppSettings"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"appSettings"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"category"}},{"kind":"Field","name":{"kind":"Name","value":"label"}},{"kind":"Field","name":{"kind":"Name","value":"settings"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"key"}},{"kind":"Field","name":{"kind":"Name","value":"value"}},{"kind":"Field","name":{"kind":"Name","value":"type"}},{"kind":"Field","name":{"kind":"Name","value":"category"}},{"kind":"Field","name":{"kind":"Name","value":"label"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"isDefault"}},{"kind":"Field","name":{"kind":"Name","value":"sensitive"}},{"kind":"Field","name":{"kind":"Name","value":"options"}}]}}]}}]}}]} as unknown as DocumentNode<GetAppSettingsQuery, GetAppSettingsQueryVariables>;
export const UpdateAppSettingDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UpdateAppSetting"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"key"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"value"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"updateAppSetting"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"key"},"value":{"kind":"Variable","name":{"kind":"Name","value":"key"}}},{"kind":"Argument","name":{"kind":"Name","value":"value"},"value":{"kind":"Variable","name":{"kind":"Name","value":"value"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"setting"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"key"}},{"kind":"Field","name":{"kind":"Name","value":"value"}},{"kind":"Field","name":{"kind":"Name","value":"type"}},{"kind":"Field","name":{"kind":"Name","value":"category"}},{"kind":"Field","name":{"kind":"Name","value":"label"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"isDefault"}},{"kind":"Field","name":{"kind":"Name","value":"sensitive"}},{"kind":"Field","name":{"kind":"Name","value":"options"}}]}}]}}]}}]} as unknown as DocumentNode<UpdateAppSettingMutation, UpdateAppSettingMutationVariables>;
export const ResetAppSettingDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ResetAppSetting"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"key"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"resetAppSetting"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"key"},"value":{"kind":"Variable","name":{"kind":"Name","value":"key"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"setting"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"key"}},{"kind":"Field","name":{"kind":"Name","value":"value"}},{"kind":"Field","name":{"kind":"Name","value":"type"}},{"kind":"Field","name":{"kind":"Name","value":"category"}},{"kind":"Field","name":{"kind":"Name","value":"label"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"isDefault"}},{"kind":"Field","name":{"kind":"Name","value":"sensitive"}},{"kind":"Field","name":{"kind":"Name","value":"options"}}]}}]}}]}}]} as unknown as DocumentNode<ResetAppSettingMutation, ResetAppSettingMutationVariables>;
export const GetDeezerGenresDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetDeezerGenres"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deezerGenres"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}}]}}]}}]} as unknown as DocumentNode<GetDeezerGenresQuery, GetDeezerGenresQueryVariables>;
export const UploadCookieFileDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UploadCookieFile"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"content"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"uploadCookieFile"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"content"},"value":{"kind":"Variable","name":{"kind":"Name","value":"content"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<UploadCookieFileMutation, UploadCookieFileMutationVariables>;
export const MigrateSettingsFromYamlDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"MigrateSettingsFromYaml"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"migrateSettingsFromYaml"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"migrated"}},{"kind":"Field","name":{"kind":"Name","value":"skipped"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<MigrateSettingsFromYamlMutation, MigrateSettingsFromYamlMutationVariables>;
export const GetSongsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetSongs"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"unavailable"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"maxBitrate"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"songs"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"albumId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"albumId"}}},{"kind":"Argument","name":{"kind":"Name","value":"downloaded"},"value":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}}},{"kind":"Argument","name":{"kind":"Name","value":"unavailable"},"value":{"kind":"Variable","name":{"kind":"Name","value":"unavailable"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}},{"kind":"Argument","name":{"kind":"Name","value":"maxBitrate"},"value":{"kind":"Variable","name":{"kind":"Name","value":"maxBitrate"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtist"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtistId"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtistGid"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"failedCount"}},{"kind":"Field","name":{"kind":"Name","value":"bitrate"}},{"kind":"Field","name":{"kind":"Name","value":"unavailable"}},{"kind":"Field","name":{"kind":"Name","value":"filePath"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}},{"kind":"Field","name":{"kind":"Name","value":"downloadProvider"}}]}},{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}}]}}]}}]} as unknown as DocumentNode<GetSongsQuery, GetSongsQueryVariables>;
export const GetSongDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetSong"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"song"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtist"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtistId"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"failedCount"}},{"kind":"Field","name":{"kind":"Name","value":"bitrate"}},{"kind":"Field","name":{"kind":"Name","value":"unavailable"}},{"kind":"Field","name":{"kind":"Name","value":"filePath"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}},{"kind":"Field","name":{"kind":"Name","value":"downloadProvider"}}]}}]}}]} as unknown as DocumentNode<GetSongQuery, GetSongQueryVariables>;
export const GetSystemHealthDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetSystemHealth"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"systemHealth"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"canDownload"}},{"kind":"Field","name":{"kind":"Name","value":"downloadBlockerReason"}},{"kind":"Field","name":{"kind":"Name","value":"authentication"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cookiesValid"}},{"kind":"Field","name":{"kind":"Name","value":"cookiesErrorType"}},{"kind":"Field","name":{"kind":"Name","value":"cookiesErrorMessage"}},{"kind":"Field","name":{"kind":"Name","value":"cookiesExpireInDays"}},{"kind":"Field","name":{"kind":"Name","value":"poTokenConfigured"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyAuthMode"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyTokenValid"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyTokenExpired"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyTokenExpiresInHours"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyTokenErrorMessage"}}]}}]}}]}}]} as unknown as DocumentNode<GetSystemHealthQuery, GetSystemHealthQueryVariables>;
export const GetQueueStatusDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetQueueStatus"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"queueStatus"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"totalPendingTasks"}},{"kind":"Field","name":{"kind":"Name","value":"taskCounts"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"taskName"}},{"kind":"Field","name":{"kind":"Name","value":"count"}}]}},{"kind":"Field","name":{"kind":"Name","value":"pendingTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"taskId"}},{"kind":"Field","name":{"kind":"Name","value":"taskName"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}},{"kind":"Field","name":{"kind":"Name","value":"entityType"}},{"kind":"Field","name":{"kind":"Name","value":"entityId"}},{"kind":"Field","name":{"kind":"Name","value":"entityName"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}}]}},{"kind":"Field","name":{"kind":"Name","value":"queueSize"}}]}}]}}]} as unknown as DocumentNode<GetQueueStatusQuery, GetQueueStatusQueryVariables>;
export const CancelAllPendingTasksDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CancelAllPendingTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cancelAllPendingTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<CancelAllPendingTasksMutation, CancelAllPendingTasksMutationVariables>;
export const CancelTasksByNameDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CancelTasksByName"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskName"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cancelTasksByName"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskName"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskName"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<CancelTasksByNameMutation, CancelTasksByNameMutationVariables>;
export const CancelRunningTasksByNameDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CancelRunningTasksByName"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskName"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cancelRunningTasksByName"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskName"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskName"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<CancelRunningTasksByNameMutation, CancelRunningTasksByNameMutationVariables>;
export const CancelAllTasksDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CancelAllTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cancelAllTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<CancelAllTasksMutation, CancelAllTasksMutationVariables>;
export const CancelTaskByIdDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CancelTaskById"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"cancelTaskById"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<CancelTaskByIdMutation, CancelTaskByIdMutationVariables>;
export const GetPeriodicTasksDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetPeriodicTasks"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"enabledOnly"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"periodicTasks"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"enabledOnly"},"value":{"kind":"Variable","name":{"kind":"Name","value":"enabledOnly"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"task"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"isCore"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"scheduleDescription"}},{"kind":"Field","name":{"kind":"Name","value":"lastRunAt"}},{"kind":"Field","name":{"kind":"Name","value":"totalRunCount"}}]}}]}}]} as unknown as DocumentNode<GetPeriodicTasksQuery, GetPeriodicTasksQueryVariables>;
export const SetPeriodicTaskEnabledDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"SetPeriodicTaskEnabled"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"setPeriodicTaskEnabled"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}}},{"kind":"Argument","name":{"kind":"Name","value":"enabled"},"value":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"isCore"}}]}}]}}]} as unknown as DocumentNode<SetPeriodicTaskEnabledMutation, SetPeriodicTaskEnabledMutationVariables>;
export const RunPeriodicTaskNowDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RunPeriodicTaskNow"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"runPeriodicTaskNow"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<RunPeriodicTaskNowMutation, RunPeriodicTaskNowMutationVariables>;
export const GetOneOffTasksDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetOneOffTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"oneOffTasks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"category"}}]}}]}}]} as unknown as DocumentNode<GetOneOffTasksQuery, GetOneOffTasksQueryVariables>;
export const RunOneOffTaskDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RunOneOffTask"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"runOneOffTask"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"taskId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"taskId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<RunOneOffTaskMutation, RunOneOffTaskMutationVariables>;
export const GetTaskHistoryDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetTaskHistory"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"status"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"type"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"entityType"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"taskHistory"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"status"},"value":{"kind":"Variable","name":{"kind":"Name","value":"status"}}},{"kind":"Argument","name":{"kind":"Name","value":"type"},"value":{"kind":"Variable","name":{"kind":"Name","value":"type"}}},{"kind":"Argument","name":{"kind":"Name","value":"entityType"},"value":{"kind":"Variable","name":{"kind":"Name","value":"entityType"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"taskId"}},{"kind":"Field","name":{"kind":"Name","value":"type"}},{"kind":"Field","name":{"kind":"Name","value":"entityId"}},{"kind":"Field","name":{"kind":"Name","value":"entityType"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"startedAt"}},{"kind":"Field","name":{"kind":"Name","value":"completedAt"}},{"kind":"Field","name":{"kind":"Name","value":"durationSeconds"}},{"kind":"Field","name":{"kind":"Name","value":"progressPercentage"}},{"kind":"Field","name":{"kind":"Name","value":"logMessages"}}]}}]}}]}}]} as unknown as DocumentNode<GetTaskHistoryQuery, GetTaskHistoryQueryVariables>;
export const GetArtistsTestDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetArtistsTest"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"trackingTier"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"artists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"trackingTier"},"value":{"kind":"Variable","name":{"kind":"Name","value":"trackingTier"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"trackingTier"}},{"kind":"Field","name":{"kind":"Name","value":"addedAt"}},{"kind":"Field","name":{"kind":"Name","value":"lastSynced"}}]}}]}}]}}]} as unknown as DocumentNode<GetArtistsTestQuery, GetArtistsTestQueryVariables>;
export const GetAlbumsTestDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetAlbumsTest"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"albums"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"wanted"},"value":{"kind":"Variable","name":{"kind":"Name","value":"wanted"}}},{"kind":"Argument","name":{"kind":"Name","value":"downloaded"},"value":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyGid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"totalTracks"}},{"kind":"Field","name":{"kind":"Name","value":"wanted"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"albumType"}},{"kind":"Field","name":{"kind":"Name","value":"albumGroup"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"artistId"}}]}}]}}]}}]} as unknown as DocumentNode<GetAlbumsTestQuery, GetAlbumsTestQueryVariables>;
export const GetPlaylistsTestDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetPlaylistsTest"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlists"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"enabled"},"value":{"kind":"Variable","name":{"kind":"Name","value":"enabled"}}},{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}},{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"url"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}},{"kind":"Field","name":{"kind":"Name","value":"autoTrackTier"}},{"kind":"Field","name":{"kind":"Name","value":"lastSyncedAt"}}]}}]}}]}}]} as unknown as DocumentNode<GetPlaylistsTestQuery, GetPlaylistsTestQueryVariables>;
export const GetSongsTestDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"GetSongsTest"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"page"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"1"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}},"defaultValue":{"kind":"IntValue","value":"50"}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"unavailable"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Boolean"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"search"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"songs"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"page"},"value":{"kind":"Variable","name":{"kind":"Name","value":"page"}}},{"kind":"Argument","name":{"kind":"Name","value":"pageSize"},"value":{"kind":"Variable","name":{"kind":"Name","value":"pageSize"}}},{"kind":"Argument","name":{"kind":"Name","value":"artistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"artistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"downloaded"},"value":{"kind":"Variable","name":{"kind":"Name","value":"downloaded"}}},{"kind":"Argument","name":{"kind":"Name","value":"unavailable"},"value":{"kind":"Variable","name":{"kind":"Name","value":"unavailable"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortBy"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortBy"}}},{"kind":"Argument","name":{"kind":"Name","value":"sortDirection"},"value":{"kind":"Variable","name":{"kind":"Name","value":"sortDirection"}}},{"kind":"Argument","name":{"kind":"Name","value":"search"},"value":{"kind":"Variable","name":{"kind":"Name","value":"search"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"items"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"gid"}},{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtist"}},{"kind":"Field","name":{"kind":"Name","value":"primaryArtistId"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"failedCount"}},{"kind":"Field","name":{"kind":"Name","value":"bitrate"}},{"kind":"Field","name":{"kind":"Name","value":"unavailable"}},{"kind":"Field","name":{"kind":"Name","value":"filePath"}},{"kind":"Field","name":{"kind":"Name","value":"downloaded"}},{"kind":"Field","name":{"kind":"Name","value":"spotifyUri"}}]}},{"kind":"Field","name":{"kind":"Name","value":"pageInfo"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"page"}},{"kind":"Field","name":{"kind":"Name","value":"pageSize"}},{"kind":"Field","name":{"kind":"Name","value":"totalPages"}},{"kind":"Field","name":{"kind":"Name","value":"totalCount"}}]}}]}}]}}]} as unknown as DocumentNode<GetSongsTestQuery, GetSongsTestQueryVariables>;
export const TogglePlaylistTestDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"TogglePlaylistTest"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"togglePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"success"}},{"kind":"Field","name":{"kind":"Name","value":"message"}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"statusMessage"}},{"kind":"Field","name":{"kind":"Name","value":"enabled"}}]}}]}}]}}]} as unknown as DocumentNode<TogglePlaylistTestMutation, TogglePlaylistTestMutationVariables>;
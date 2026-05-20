/* eslint-disable */
import { TypedDocumentNode as DocumentNode } from '@graphql-typed-document-node/core';
export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
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
  /** Date with time (isoformat) */
  DateTime: { input: any; output: any; }
};

export type AccountType = {
  __typename?: 'AccountType';
  createdAt: Scalars['DateTime']['output'];
  displayName: Scalars['String']['output'];
  id: Scalars['ID']['output'];
};

export type BulkImportJobType = {
  __typename?: 'BulkImportJobType';
  addedCount: Scalars['Int']['output'];
  createdAt: Scalars['DateTime']['output'];
  error: Scalars['String']['output'];
  finishedAt?: Maybe<Scalars['DateTime']['output']>;
  id: Scalars['ID']['output'];
  skippedCount: Scalars['Int']['output'];
  sourceUrl: Scalars['String']['output'];
  status: Scalars['String']['output'];
  unresolvedCount: Scalars['Int']['output'];
  unresolvedTitles: Array<Scalars['String']['output']>;
};

export type CatalogSearchResultType = {
  __typename?: 'CatalogSearchResultType';
  artist: Scalars['String']['output'];
  deezerId: Scalars['String']['output'];
  inLibrary: Scalars['Boolean']['output'];
  isrc?: Maybe<Scalars['String']['output']>;
  title: Scalars['String']['output'];
};

export type ContributionResult = {
  __typename?: 'ContributionResult';
  alreadyPresent: Scalars['Boolean']['output'];
  contribution: ContributionType;
};

export type ContributionType = {
  __typename?: 'ContributionType';
  contributedBy: AccountType;
  createdAt: Scalars['DateTime']['output'];
  id: Scalars['ID']['output'];
  netScore: Scalars['Int']['output'];
  song: SongRef;
  votes: Array<VoteType>;
};

export type DeletePlaylistResult = {
  __typename?: 'DeletePlaylistResult';
  deleted: Scalars['Boolean']['output'];
};

export type EngineSettings = {
  __typename?: 'EngineSettings';
  base: Scalars['Float']['output'];
  maxSize?: Maybe<Scalars['Int']['output']>;
  minSize: Scalars['Int']['output'];
  pFloor: Scalars['Float']['output'];
  tHigh: Scalars['Int']['output'];
  tLow: Scalars['Int']['output'];
};

export type EngineSettingsInput = {
  base?: InputMaybe<Scalars['Float']['input']>;
  maxSize?: InputMaybe<Scalars['Int']['input']>;
  minSize?: InputMaybe<Scalars['Int']['input']>;
  pFloor?: InputMaybe<Scalars['Float']['input']>;
  tHigh?: InputMaybe<Scalars['Int']['input']>;
  tLow?: InputMaybe<Scalars['Int']['input']>;
};

export type ExportOptionsInput = {
  excludeMyDownvotes?: Scalars['Boolean']['input'];
};

export type ExportSnapshotTrackType = {
  __typename?: 'ExportSnapshotTrackType';
  id: Scalars['ID']['output'];
  inclusionReason: Scalars['String']['output'];
  position: Scalars['Int']['output'];
  rollProbability: Scalars['Float']['output'];
  song: SongRef;
};

export type ExportSnapshotType = {
  __typename?: 'ExportSnapshotType';
  createdAt: Scalars['DateTime']['output'];
  id: Scalars['ID']['output'];
  m3uUrl: Scalars['String']['output'];
  parameters: Scalars['String']['output'];
  playlist: PlaylistType;
  requestedBy: AccountType;
  rngSeed: Scalars['String']['output'];
  tracks: Array<ExportSnapshotTrackType>;
  warningMessage: Scalars['String']['output'];
};

export type MembershipType = {
  __typename?: 'MembershipType';
  account: AccountType;
  joinedAt: Scalars['DateTime']['output'];
  role: Scalars['String']['output'];
};

export type Mutation = {
  __typename?: 'Mutation';
  bulkImportPlaylist: BulkImportJobType;
  castVote: ContributionType;
  clearVote: ContributionType;
  contributeFromLink: ContributionResult;
  contributeFromSearch: ContributionResult;
  createExport: ExportSnapshotType;
  createPlaylist: PlaylistType;
  deletePlaylist: DeletePlaylistResult;
  joinPlaylist: PlaylistType;
  kickMember: DeletePlaylistResult;
  leavePlaylist: DeletePlaylistResult;
  promoteMember: PlaylistType;
  regenerateInviteToken: RegenerateInviteResult;
  removeContribution: DeletePlaylistResult;
  requestMagicLink: RequestMagicLinkResult;
  updatePlaylistSettings: PlaylistType;
};


export type MutationBulkImportPlaylistArgs = {
  playlistId: Scalars['ID']['input'];
  url: Scalars['String']['input'];
};


export type MutationCastVoteArgs = {
  contributionId: Scalars['ID']['input'];
  value: Scalars['Int']['input'];
};


export type MutationClearVoteArgs = {
  contributionId: Scalars['ID']['input'];
};


export type MutationContributeFromLinkArgs = {
  playlistId: Scalars['ID']['input'];
  url: Scalars['String']['input'];
};


export type MutationContributeFromSearchArgs = {
  deezerTrackId: Scalars['String']['input'];
  playlistId: Scalars['ID']['input'];
};


export type MutationCreateExportArgs = {
  options?: InputMaybe<ExportOptionsInput>;
  playlistId: Scalars['ID']['input'];
};


export type MutationCreatePlaylistArgs = {
  description?: Scalars['String']['input'];
  name: Scalars['String']['input'];
};


export type MutationDeletePlaylistArgs = {
  id: Scalars['ID']['input'];
};


export type MutationJoinPlaylistArgs = {
  inviteToken: Scalars['String']['input'];
};


export type MutationKickMemberArgs = {
  accountId: Scalars['ID']['input'];
  playlistId: Scalars['ID']['input'];
};


export type MutationLeavePlaylistArgs = {
  id: Scalars['ID']['input'];
};


export type MutationPromoteMemberArgs = {
  accountId: Scalars['ID']['input'];
  playlistId: Scalars['ID']['input'];
};


export type MutationRegenerateInviteTokenArgs = {
  id: Scalars['ID']['input'];
};


export type MutationRemoveContributionArgs = {
  id: Scalars['ID']['input'];
};


export type MutationRequestMagicLinkArgs = {
  displayName?: InputMaybe<Scalars['String']['input']>;
  email: Scalars['String']['input'];
};


export type MutationUpdatePlaylistSettingsArgs = {
  description?: InputMaybe<Scalars['String']['input']>;
  engine?: InputMaybe<EngineSettingsInput>;
  id: Scalars['ID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
};

export type PlaylistType = {
  __typename?: 'PlaylistType';
  createdAt: Scalars['DateTime']['output'];
  createdBy: AccountType;
  description: Scalars['String']['output'];
  engineSettings: EngineSettings;
  id: Scalars['ID']['output'];
  inviteToken: Scalars['String']['output'];
  members: Array<MembershipType>;
  name: Scalars['String']['output'];
};

export type Query = {
  __typename?: 'Query';
  bulkImportJob: BulkImportJobType;
  catalogSearch: Array<CatalogSearchResultType>;
  export: ExportSnapshotType;
  me?: Maybe<AccountType>;
  myPlaylistExports: Array<ExportSnapshotType>;
  myPlaylists: Array<PlaylistType>;
  playlist: PlaylistType;
  playlistContributions: Array<ContributionType>;
};


export type QueryBulkImportJobArgs = {
  id: Scalars['ID']['input'];
};


export type QueryCatalogSearchArgs = {
  limit?: Scalars['Int']['input'];
  query: Scalars['String']['input'];
};


export type QueryExportArgs = {
  id: Scalars['ID']['input'];
};


export type QueryMyPlaylistExportsArgs = {
  playlistId: Scalars['ID']['input'];
};


export type QueryPlaylistArgs = {
  id?: InputMaybe<Scalars['ID']['input']>;
  inviteToken?: InputMaybe<Scalars['String']['input']>;
};


export type QueryPlaylistContributionsArgs = {
  playlistId: Scalars['ID']['input'];
};

export type RegenerateInviteResult = {
  __typename?: 'RegenerateInviteResult';
  inviteToken: Scalars['String']['output'];
};

export type RequestMagicLinkResult = {
  __typename?: 'RequestMagicLinkResult';
  message: Scalars['String']['output'];
  sent: Scalars['Boolean']['output'];
};

export type SongRef = {
  __typename?: 'SongRef';
  artist: Scalars['String']['output'];
  id: Scalars['ID']['output'];
  isrc?: Maybe<Scalars['String']['output']>;
  title: Scalars['String']['output'];
};

export type VoteType = {
  __typename?: 'VoteType';
  account: AccountType;
  createdAt: Scalars['DateTime']['output'];
  value: Scalars['Int']['output'];
};

export type RequestMagicLinkMutationVariables = Exact<{
  email: Scalars['String']['input'];
  displayName?: InputMaybe<Scalars['String']['input']>;
}>;


export type RequestMagicLinkMutation = { __typename?: 'Mutation', requestMagicLink: { __typename?: 'RequestMagicLinkResult', sent: boolean, message: string } };

export type BulkImportPlaylistMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  url: Scalars['String']['input'];
}>;


export type BulkImportPlaylistMutation = { __typename?: 'Mutation', bulkImportPlaylist: { __typename?: 'BulkImportJobType', id: string, status: string, sourceUrl: string, addedCount: number, skippedCount: number, unresolvedCount: number, unresolvedTitles: Array<string>, error: string } };

export type BulkImportJobQueryVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type BulkImportJobQuery = { __typename?: 'Query', bulkImportJob: { __typename?: 'BulkImportJobType', id: string, status: string, addedCount: number, skippedCount: number, unresolvedCount: number, unresolvedTitles: Array<string>, error: string, finishedAt?: any | null } };

export type CatalogSearchQueryVariables = Exact<{
  query: Scalars['String']['input'];
  limit?: InputMaybe<Scalars['Int']['input']>;
}>;


export type CatalogSearchQuery = { __typename?: 'Query', catalogSearch: Array<{ __typename?: 'CatalogSearchResultType', deezerId: string, title: string, artist: string, isrc?: string | null, inLibrary: boolean }> };

export type ContributeFromSearchMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  deezerTrackId: Scalars['String']['input'];
}>;


export type ContributeFromSearchMutation = { __typename?: 'Mutation', contributeFromSearch: { __typename?: 'ContributionResult', alreadyPresent: boolean, contribution: { __typename?: 'ContributionType', id: string, netScore: number, song: { __typename?: 'SongRef', id: string, title: string, artist: string, isrc?: string | null }, contributedBy: { __typename?: 'AccountType', id: string, displayName: string }, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> } } };

export type ContributeFromLinkMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  url: Scalars['String']['input'];
}>;


export type ContributeFromLinkMutation = { __typename?: 'Mutation', contributeFromLink: { __typename?: 'ContributionResult', alreadyPresent: boolean, contribution: { __typename?: 'ContributionType', id: string, netScore: number, song: { __typename?: 'SongRef', id: string, title: string, artist: string, isrc?: string | null }, contributedBy: { __typename?: 'AccountType', id: string, displayName: string }, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> } } };

export type CreateExportMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  options?: InputMaybe<ExportOptionsInput>;
}>;


export type CreateExportMutation = { __typename?: 'Mutation', createExport: { __typename?: 'ExportSnapshotType', id: string, m3uUrl: string, warningMessage: string } };

export type ExportQueryVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type ExportQuery = { __typename?: 'Query', export: { __typename?: 'ExportSnapshotType', id: string, createdAt: any, parameters: string, rngSeed: string, warningMessage: string, m3uUrl: string, requestedBy: { __typename?: 'AccountType', id: string, displayName: string }, playlist: { __typename?: 'PlaylistType', id: string, name: string, description: string }, tracks: Array<{ __typename?: 'ExportSnapshotTrackType', id: string, position: number, inclusionReason: string, rollProbability: number, song: { __typename?: 'SongRef', id: string, title: string, artist: string, isrc?: string | null } }> } };

export type PlaylistByInviteTokenQueryVariables = Exact<{
  token: Scalars['String']['input'];
}>;


export type PlaylistByInviteTokenQuery = { __typename?: 'Query', playlist: { __typename?: 'PlaylistType', id: string, name: string, description: string, members: Array<{ __typename?: 'MembershipType', role: string, account: { __typename?: 'AccountType', id: string, displayName: string } }> } };

export type JoinPlaylistMutationVariables = Exact<{
  token: Scalars['String']['input'];
}>;


export type JoinPlaylistMutation = { __typename?: 'Mutation', joinPlaylist: { __typename?: 'PlaylistType', id: string } };

export type MeQueryVariables = Exact<{ [key: string]: never; }>;


export type MeQuery = { __typename?: 'Query', me?: { __typename?: 'AccountType', id: string, displayName: string, createdAt: any } | null };

export type PlaylistDetailQueryVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type PlaylistDetailQuery = { __typename?: 'Query', playlist: { __typename?: 'PlaylistType', id: string, name: string, description: string, inviteToken: string, createdBy: { __typename?: 'AccountType', id: string, displayName: string }, engineSettings: { __typename?: 'EngineSettings', minSize: number, maxSize?: number | null, tHigh: number, tLow: number, base: number, pFloor: number }, members: Array<{ __typename?: 'MembershipType', role: string, account: { __typename?: 'AccountType', id: string, displayName: string } }> }, playlistContributions: Array<{ __typename?: 'ContributionType', id: string, netScore: number, createdAt: any, contributedBy: { __typename?: 'AccountType', id: string, displayName: string }, song: { __typename?: 'SongRef', id: string, title: string, artist: string, isrc?: string | null }, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> }> };

export type CastVoteMutationVariables = Exact<{
  contributionId: Scalars['ID']['input'];
  value: Scalars['Int']['input'];
}>;


export type CastVoteMutation = { __typename?: 'Mutation', castVote: { __typename?: 'ContributionType', id: string, netScore: number, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> } };

export type ClearVoteMutationVariables = Exact<{
  contributionId: Scalars['ID']['input'];
}>;


export type ClearVoteMutation = { __typename?: 'Mutation', clearVote: { __typename?: 'ContributionType', id: string, netScore: number, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> } };

export type RemoveContributionMutationVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type RemoveContributionMutation = { __typename?: 'Mutation', removeContribution: { __typename?: 'DeletePlaylistResult', deleted: boolean } };

export type MyPlaylistsQueryVariables = Exact<{ [key: string]: never; }>;


export type MyPlaylistsQuery = { __typename?: 'Query', myPlaylists: Array<{ __typename?: 'PlaylistType', id: string, name: string, description: string, createdAt: any, members: Array<{ __typename?: 'MembershipType', role: string, account: { __typename?: 'AccountType', id: string, displayName: string } }> }> };

export type CreatePlaylistMutationVariables = Exact<{
  name: Scalars['String']['input'];
  description?: InputMaybe<Scalars['String']['input']>;
}>;


export type CreatePlaylistMutation = { __typename?: 'Mutation', createPlaylist: { __typename?: 'PlaylistType', id: string, name: string } };

export type UpdatePlaylistSettingsMutationVariables = Exact<{
  id: Scalars['ID']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  description?: InputMaybe<Scalars['String']['input']>;
  engine?: InputMaybe<EngineSettingsInput>;
}>;


export type UpdatePlaylistSettingsMutation = { __typename?: 'Mutation', updatePlaylistSettings: { __typename?: 'PlaylistType', id: string, name: string, description: string } };

export type RegenerateInviteTokenMutationVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type RegenerateInviteTokenMutation = { __typename?: 'Mutation', regenerateInviteToken: { __typename?: 'RegenerateInviteResult', inviteToken: string } };

export type DeletePlaylistMutationVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type DeletePlaylistMutation = { __typename?: 'Mutation', deletePlaylist: { __typename?: 'DeletePlaylistResult', deleted: boolean } };

export type LeavePlaylistMutationVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type LeavePlaylistMutation = { __typename?: 'Mutation', leavePlaylist: { __typename?: 'DeletePlaylistResult', deleted: boolean } };

export type KickMemberMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  accountId: Scalars['ID']['input'];
}>;


export type KickMemberMutation = { __typename?: 'Mutation', kickMember: { __typename?: 'DeletePlaylistResult', deleted: boolean } };

export type PromoteMemberMutationVariables = Exact<{
  playlistId: Scalars['ID']['input'];
  accountId: Scalars['ID']['input'];
}>;


export type PromoteMemberMutation = { __typename?: 'Mutation', promoteMember: { __typename?: 'PlaylistType', id: string, members: Array<{ __typename?: 'MembershipType', role: string, account: { __typename?: 'AccountType', id: string, displayName: string } }> } };


export const RequestMagicLinkDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RequestMagicLink"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"email"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"displayName"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"requestMagicLink"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"email"},"value":{"kind":"Variable","name":{"kind":"Name","value":"email"}}},{"kind":"Argument","name":{"kind":"Name","value":"displayName"},"value":{"kind":"Variable","name":{"kind":"Name","value":"displayName"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"sent"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<RequestMagicLinkMutation, RequestMagicLinkMutationVariables>;
export const BulkImportPlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"BulkImportPlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"bulkImportPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"sourceUrl"}},{"kind":"Field","name":{"kind":"Name","value":"addedCount"}},{"kind":"Field","name":{"kind":"Name","value":"skippedCount"}},{"kind":"Field","name":{"kind":"Name","value":"unresolvedCount"}},{"kind":"Field","name":{"kind":"Name","value":"unresolvedTitles"}},{"kind":"Field","name":{"kind":"Name","value":"error"}}]}}]}}]} as unknown as DocumentNode<BulkImportPlaylistMutation, BulkImportPlaylistMutationVariables>;
export const BulkImportJobDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"BulkImportJob"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"bulkImportJob"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"status"}},{"kind":"Field","name":{"kind":"Name","value":"addedCount"}},{"kind":"Field","name":{"kind":"Name","value":"skippedCount"}},{"kind":"Field","name":{"kind":"Name","value":"unresolvedCount"}},{"kind":"Field","name":{"kind":"Name","value":"unresolvedTitles"}},{"kind":"Field","name":{"kind":"Name","value":"error"}},{"kind":"Field","name":{"kind":"Name","value":"finishedAt"}}]}}]}}]} as unknown as DocumentNode<BulkImportJobQuery, BulkImportJobQueryVariables>;
export const CatalogSearchDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"CatalogSearch"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"query"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"limit"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"catalogSearch"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"query"},"value":{"kind":"Variable","name":{"kind":"Name","value":"query"}}},{"kind":"Argument","name":{"kind":"Name","value":"limit"},"value":{"kind":"Variable","name":{"kind":"Name","value":"limit"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deezerId"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}},{"kind":"Field","name":{"kind":"Name","value":"inLibrary"}}]}}]}}]} as unknown as DocumentNode<CatalogSearchQuery, CatalogSearchQueryVariables>;
export const ContributeFromSearchDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ContributeFromSearch"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"deezerTrackId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"contributeFromSearch"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"deezerTrackId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"deezerTrackId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"alreadyPresent"}},{"kind":"Field","name":{"kind":"Name","value":"contribution"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"song"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}}]}},{"kind":"Field","name":{"kind":"Name","value":"contributedBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]}}]} as unknown as DocumentNode<ContributeFromSearchMutation, ContributeFromSearchMutationVariables>;
export const ContributeFromLinkDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ContributeFromLink"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"url"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"contributeFromLink"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"url"},"value":{"kind":"Variable","name":{"kind":"Name","value":"url"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"alreadyPresent"}},{"kind":"Field","name":{"kind":"Name","value":"contribution"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"song"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}}]}},{"kind":"Field","name":{"kind":"Name","value":"contributedBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]}}]} as unknown as DocumentNode<ContributeFromLinkMutation, ContributeFromLinkMutationVariables>;
export const CreateExportDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreateExport"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"options"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"ExportOptionsInput"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createExport"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"options"},"value":{"kind":"Variable","name":{"kind":"Name","value":"options"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"m3uUrl"}},{"kind":"Field","name":{"kind":"Name","value":"warningMessage"}}]}}]}}]} as unknown as DocumentNode<CreateExportMutation, CreateExportMutationVariables>;
export const ExportDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"Export"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"export"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"parameters"}},{"kind":"Field","name":{"kind":"Name","value":"rngSeed"}},{"kind":"Field","name":{"kind":"Name","value":"warningMessage"}},{"kind":"Field","name":{"kind":"Name","value":"m3uUrl"}},{"kind":"Field","name":{"kind":"Name","value":"requestedBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"playlist"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}}]}},{"kind":"Field","name":{"kind":"Name","value":"tracks"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"position"}},{"kind":"Field","name":{"kind":"Name","value":"inclusionReason"}},{"kind":"Field","name":{"kind":"Name","value":"rollProbability"}},{"kind":"Field","name":{"kind":"Name","value":"song"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}}]}}]}}]}}]}}]} as unknown as DocumentNode<ExportQuery, ExportQueryVariables>;
export const PlaylistByInviteTokenDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"PlaylistByInviteToken"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"token"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"inviteToken"},"value":{"kind":"Variable","name":{"kind":"Name","value":"token"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}}]}}]} as unknown as DocumentNode<PlaylistByInviteTokenQuery, PlaylistByInviteTokenQueryVariables>;
export const JoinPlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"JoinPlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"token"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"joinPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"inviteToken"},"value":{"kind":"Variable","name":{"kind":"Name","value":"token"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}}]}}]} as unknown as DocumentNode<JoinPlaylistMutation, JoinPlaylistMutationVariables>;
export const MeDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"Me"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"me"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}}]}}]}}]} as unknown as DocumentNode<MeQuery, MeQueryVariables>;
export const PlaylistDetailDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"PlaylistDetail"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"inviteToken"}},{"kind":"Field","name":{"kind":"Name","value":"createdBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"engineSettings"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"minSize"}},{"kind":"Field","name":{"kind":"Name","value":"maxSize"}},{"kind":"Field","name":{"kind":"Name","value":"tHigh"}},{"kind":"Field","name":{"kind":"Name","value":"tLow"}},{"kind":"Field","name":{"kind":"Name","value":"base"}},{"kind":"Field","name":{"kind":"Name","value":"pFloor"}}]}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}},{"kind":"Field","name":{"kind":"Name","value":"playlistContributions"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"contributedBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"song"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}}]}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<PlaylistDetailQuery, PlaylistDetailQueryVariables>;
export const CastVoteDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CastVote"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"value"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"castVote"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"contributionId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}}},{"kind":"Argument","name":{"kind":"Name","value":"value"},"value":{"kind":"Variable","name":{"kind":"Name","value":"value"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<CastVoteMutation, CastVoteMutationVariables>;
export const ClearVoteDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ClearVote"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"clearVote"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"contributionId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<ClearVoteMutation, ClearVoteMutationVariables>;
export const RemoveContributionDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RemoveContribution"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"removeContribution"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleted"}}]}}]}}]} as unknown as DocumentNode<RemoveContributionMutation, RemoveContributionMutationVariables>;
export const MyPlaylistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"MyPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"myPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}}]}}]} as unknown as DocumentNode<MyPlaylistsQuery, MyPlaylistsQueryVariables>;
export const CreatePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreatePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"description"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"description"},"value":{"kind":"Variable","name":{"kind":"Name","value":"description"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}}]}}]}}]} as unknown as DocumentNode<CreatePlaylistMutation, CreatePlaylistMutationVariables>;
export const UpdatePlaylistSettingsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"UpdatePlaylistSettings"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"description"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"engine"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"EngineSettingsInput"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"updatePlaylistSettings"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}},{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"description"},"value":{"kind":"Variable","name":{"kind":"Name","value":"description"}}},{"kind":"Argument","name":{"kind":"Name","value":"engine"},"value":{"kind":"Variable","name":{"kind":"Name","value":"engine"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}}]}}]}}]} as unknown as DocumentNode<UpdatePlaylistSettingsMutation, UpdatePlaylistSettingsMutationVariables>;
export const RegenerateInviteTokenDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RegenerateInviteToken"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"regenerateInviteToken"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"inviteToken"}}]}}]}}]} as unknown as DocumentNode<RegenerateInviteTokenMutation, RegenerateInviteTokenMutationVariables>;
export const DeletePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"DeletePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deletePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleted"}}]}}]}}]} as unknown as DocumentNode<DeletePlaylistMutation, DeletePlaylistMutationVariables>;
export const LeavePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"LeavePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"leavePlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleted"}}]}}]}}]} as unknown as DocumentNode<LeavePlaylistMutation, LeavePlaylistMutationVariables>;
export const KickMemberDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"KickMember"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"accountId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"kickMember"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"accountId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"accountId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleted"}}]}}]}}]} as unknown as DocumentNode<KickMemberMutation, KickMemberMutationVariables>;
export const PromoteMemberDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"PromoteMember"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"accountId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"promoteMember"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"playlistId"}}},{"kind":"Argument","name":{"kind":"Name","value":"accountId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"accountId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}}]}}]} as unknown as DocumentNode<PromoteMemberMutation, PromoteMemberMutationVariables>;

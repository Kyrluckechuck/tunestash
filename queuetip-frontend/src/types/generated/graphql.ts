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

export type MeQueryVariables = Exact<{ [key: string]: never; }>;


export type MeQuery = { __typename?: 'Query', me?: { __typename?: 'AccountType', id: string, displayName: string, createdAt: any } | null };

export type PlaylistDetailQueryVariables = Exact<{
  id: Scalars['ID']['input'];
}>;


export type PlaylistDetailQuery = { __typename?: 'Query', playlist: { __typename?: 'PlaylistType', id: string, name: string, description: string, inviteToken: string, createdBy: { __typename?: 'AccountType', id: string, displayName: string }, members: Array<{ __typename?: 'MembershipType', role: string, account: { __typename?: 'AccountType', id: string, displayName: string } }> }, playlistContributions: Array<{ __typename?: 'ContributionType', id: string, netScore: number, createdAt: any, contributedBy: { __typename?: 'AccountType', id: string, displayName: string }, song: { __typename?: 'SongRef', id: string, title: string, artist: string, isrc?: string | null }, votes: Array<{ __typename?: 'VoteType', value: number, account: { __typename?: 'AccountType', id: string } }> }> };

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


export const RequestMagicLinkDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RequestMagicLink"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"email"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"displayName"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"requestMagicLink"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"email"},"value":{"kind":"Variable","name":{"kind":"Name","value":"email"}}},{"kind":"Argument","name":{"kind":"Name","value":"displayName"},"value":{"kind":"Variable","name":{"kind":"Name","value":"displayName"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"sent"}},{"kind":"Field","name":{"kind":"Name","value":"message"}}]}}]}}]} as unknown as DocumentNode<RequestMagicLinkMutation, RequestMagicLinkMutationVariables>;
export const MeDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"Me"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"me"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}}]}}]}}]} as unknown as DocumentNode<MeQuery, MeQueryVariables>;
export const PlaylistDetailDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"PlaylistDetail"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"playlist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"inviteToken"}},{"kind":"Field","name":{"kind":"Name","value":"createdBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}},{"kind":"Field","name":{"kind":"Name","value":"playlistContributions"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"playlistId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"contributedBy"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"song"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"title"}},{"kind":"Field","name":{"kind":"Name","value":"artist"}},{"kind":"Field","name":{"kind":"Name","value":"isrc"}}]}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<PlaylistDetailQuery, PlaylistDetailQueryVariables>;
export const CastVoteDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CastVote"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"value"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"Int"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"castVote"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"contributionId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}}},{"kind":"Argument","name":{"kind":"Name","value":"value"},"value":{"kind":"Variable","name":{"kind":"Name","value":"value"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<CastVoteMutation, CastVoteMutationVariables>;
export const ClearVoteDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"ClearVote"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"clearVote"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"contributionId"},"value":{"kind":"Variable","name":{"kind":"Name","value":"contributionId"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"netScore"}},{"kind":"Field","name":{"kind":"Name","value":"votes"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}}]}},{"kind":"Field","name":{"kind":"Name","value":"value"}}]}}]}}]}}]} as unknown as DocumentNode<ClearVoteMutation, ClearVoteMutationVariables>;
export const RemoveContributionDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"RemoveContribution"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"id"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"ID"}}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"removeContribution"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"id"},"value":{"kind":"Variable","name":{"kind":"Name","value":"id"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"deleted"}}]}}]}}]} as unknown as DocumentNode<RemoveContributionMutation, RemoveContributionMutationVariables>;
export const MyPlaylistsDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"query","name":{"kind":"Name","value":"MyPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"myPlaylists"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}},{"kind":"Field","name":{"kind":"Name","value":"description"}},{"kind":"Field","name":{"kind":"Name","value":"createdAt"}},{"kind":"Field","name":{"kind":"Name","value":"members"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"account"},"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"displayName"}}]}},{"kind":"Field","name":{"kind":"Name","value":"role"}}]}}]}}]}}]} as unknown as DocumentNode<MyPlaylistsQuery, MyPlaylistsQueryVariables>;
export const CreatePlaylistDocument = {"kind":"Document","definitions":[{"kind":"OperationDefinition","operation":"mutation","name":{"kind":"Name","value":"CreatePlaylist"},"variableDefinitions":[{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"name"}},"type":{"kind":"NonNullType","type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}},{"kind":"VariableDefinition","variable":{"kind":"Variable","name":{"kind":"Name","value":"description"}},"type":{"kind":"NamedType","name":{"kind":"Name","value":"String"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"createPlaylist"},"arguments":[{"kind":"Argument","name":{"kind":"Name","value":"name"},"value":{"kind":"Variable","name":{"kind":"Name","value":"name"}}},{"kind":"Argument","name":{"kind":"Name","value":"description"},"value":{"kind":"Variable","name":{"kind":"Name","value":"description"}}}],"selectionSet":{"kind":"SelectionSet","selections":[{"kind":"Field","name":{"kind":"Name","value":"id"}},{"kind":"Field","name":{"kind":"Name","value":"name"}}]}}]}}]} as unknown as DocumentNode<CreatePlaylistMutation, CreatePlaylistMutationVariables>;

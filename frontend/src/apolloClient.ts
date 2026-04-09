import {
  ApolloClient,
  InMemoryCache,
  createHttpLink,
  from,
} from '@apollo/client';
import { onError } from '@apollo/client/link/error';

const httpLink = createHttpLink({
  uri: import.meta.env.VITE_API_URL ?? '/graphql',
});

const errorLink = onError(context => {
  // Apollo Client v4 error handling
  const errorContext = context as {
    graphQLErrors?: Array<{
      message: string;
      locations?: Array<{ line: number; column: number }>;
      path?: string[];
    }>;
    networkError?: Error;
  };

  if (errorContext.graphQLErrors)
    errorContext.graphQLErrors.forEach(({ message, locations, path }) =>
      console.error(
        `[GraphQL error]: Message: ${message}, Location: ${locations}, Path: ${path}`
      )
    );
  if (errorContext.networkError)
    console.error(`[Network error]: ${errorContext.networkError}`);
});

const link = from([errorLink, httpLink]);

export const apolloClient = new ApolloClient({
  link: link,
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          artists: {
            keyArgs: [
              'trackingTier',
              'hasUndownloaded',
              'search',
              'sortBy',
              'sortDirection',
              'page',
              'pageSize',
            ],
          },
          unlinkedArtists: {
            keyArgs: [
              'search',
              'hasDownloads',
              'sortBy',
              'sortDirection',
              'page',
              'pageSize',
            ],
          },
          albums: {
            keyArgs: [
              'artistId',
              'wanted',
              'downloaded',
              'search',
              'sortBy',
              'sortDirection',
              'page',
              'pageSize',
            ],
          },
          songs: {
            keyArgs: [
              'artistId',
              'albumId',
              'downloaded',
              'unavailable',
              'search',
              'sortBy',
              'sortDirection',
              'maxBitrate',
              'page',
              'pageSize',
            ],
          },
          playlists: {
            keyArgs: [
              'enabled',
              'search',
              'sortBy',
              'sortDirection',
              'page',
              'pageSize',
            ],
          },
          externalLists: {
            keyArgs: [
              'source',
              'listType',
              'status',
              'search',
              'sortBy',
              'sortDirection',
              'page',
              'pageSize',
            ],
          },
          taskHistory: {
            keyArgs: [
              'status',
              'type',
              'entityType',
              'search',
              'daysLookback',
              'page',
              'pageSize',
            ],
          },
          downloadHistory: {
            keyArgs: ['entityType', 'status', 'page', 'pageSize'],
          },
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: {
      errorPolicy: 'all',
      fetchPolicy: 'cache-first', // Use cache first, only fetch from network if not in cache
      nextFetchPolicy: 'cache-first',
    },
    query: {
      errorPolicy: 'all',
      fetchPolicy: 'cache-first',
    },
  },
});

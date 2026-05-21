import { ApolloClient, InMemoryCache, createHttpLink, from } from "@apollo/client";
import { onError } from "@apollo/client/link/error";

const errorLink = onError(({ networkError }) => {
  if (networkError && "statusCode" in networkError && networkError.statusCode === 401) {
    // Hard redirect — TanStack Router state isn't preserved through cookie expiry anyway.
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/sign-in?next=${next}`);
  }
});

const httpLink = createHttpLink({
  uri: import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "http://127.0.0.1:5050/graphql",
  credentials: "include",
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, httpLink]),
  cache: new InMemoryCache(),
});

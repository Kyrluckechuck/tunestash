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
  // Same-origin '/graphql' — Vite dev proxy (or nginx in prod) forwards to
  // the backend. Keeps cookies, CORS, and OAuth allowlist on one origin.
  uri: import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "/graphql",
  credentials: "include",
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, httpLink]),
  cache: new InMemoryCache(),
});

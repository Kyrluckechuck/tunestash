import React from "react";
import ReactDOM from "react-dom/client";
import { ApolloProvider } from "@apollo/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { Toaster } from "sonner";

import { apolloClient } from "@/lib/apollo";
import { routeTree } from "./routeTree.gen";
import "./index.css";

// Spotify OAuth + magic-link emails always anchor on 127.0.0.1 (Spotify
// rejects 'localhost'; emails embed QUEUETIP_PUBLIC_URL). Browsers treat
// 'localhost' and '127.0.0.1' as distinct origins, so a session cookie set
// on one is invisible to the other. Without this redirect, every OAuth /
// magic-link flow would land the user on '127.0.0.1' while their cookie
// (and bookmarks) live on 'localhost' — silent sign-outs everywhere.
//
// The redirect happens BEFORE the React render so we don't waste a paint
// and the router never registers on the wrong origin.
function maybeRedirectLocalhost(): boolean {
  if (typeof window === "undefined") return false;
  if (window.location.hostname !== "localhost") return false;
  const url = new URL(window.location.href);
  url.hostname = "127.0.0.1";
  window.location.replace(url.toString());
  return true;
}

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

if (!maybeRedirectLocalhost()) {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ApolloProvider client={apolloClient}>
        <RouterProvider router={router} />
        <Toaster />
      </ApolloProvider>
    </React.StrictMode>,
  );
}

import React from "react";
import ReactDOM from "react-dom/client";
import { ApolloProvider } from "@apollo/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { Toaster } from "sonner";

import { apolloClient } from "@/lib/apollo";
import { routeTree } from "./routeTree.gen";
import "./index.css";

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ApolloProvider client={apolloClient}>
      <RouterProvider router={router} />
      <Toaster />
    </ApolloProvider>
  </React.StrictMode>,
);

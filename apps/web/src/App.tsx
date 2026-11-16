import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { createQueryClient } from "./lib/api";
import { PreferencesProvider } from "./lib/preferences";
import { appRoutes, askForHubList } from "./routes";
import "./styles/tokens.css";
import "./styles/fonts.css";
import "./styles/bundle.css";

/** The app's root: queries, preferences and the router over the Phase 2 routes. */
export function App() {
  // The shell read first: the router starts loading the first page's code as it is made.
  const [queryClient] = useState(() => {
    const client = createQueryClient();
    askForHubList(client);
    return client;
  });
  const [router] = useState(() => createBrowserRouter(appRoutes));
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <RouterProvider router={router} />
      </PreferencesProvider>
    </QueryClientProvider>
  );
}

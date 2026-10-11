import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { createQueryClient } from "./lib/api";
import { PreferencesProvider } from "./lib/preferences";
import { appRoutes } from "./routes";
import "./styles/tokens.css";
import "./styles/fonts.css";
import "./styles/bundle.css";

/** The app's root: queries, preferences and the router over the Phase 2 routes. */
export function App() {
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(appRoutes));
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <RouterProvider router={router} />
      </PreferencesProvider>
    </QueryClientProvider>
  );
}

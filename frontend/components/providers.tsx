"use client";

/**
 * GS-Prep Frontend — Client-side Providers
 *
 * Wraps the application with TanStack Query and any other client providers.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { usePipelineStore } from "@/hooks/use-pipeline-store";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000,
            retry: 1,
          },
        },
      })
  );

  useEffect(() => {
    void Promise.resolve(usePipelineStore.persist.rehydrate()).finally(() => {
      usePipelineStore.getState().setHasHydrated(true);
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

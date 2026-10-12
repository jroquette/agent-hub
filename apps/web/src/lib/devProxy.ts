import type { ProxyOptions } from "vite";

// `make dev`: Vite serves the app with hot reload on 127.0.0.1:5173 and forwards /api to the
// `hub web` it starts on 7420. The proxy sends the API's own Host and drops the browser's Origin,
// so the API's loopback Host and Origin checks pass unchanged: no dev exception in the server.
export const API_TARGET = "http://127.0.0.1:7420";
export const DEV_SERVER = { host: "127.0.0.1", port: 5173, strictPort: true } as const;

export function apiProxy(target: string = API_TARGET): { "/api": ProxyOptions } {
  return {
    "/api": {
      target,
      changeOrigin: true,
      configure: (proxy) => {
        proxy.on("proxyReq", (proxyReq) => {
          proxyReq.removeHeader("origin");
        });
      },
    },
  };
}

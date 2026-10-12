import type { ProxyOptions } from "vite";

// `make dev`: Vite serves the app with hot reload on 127.0.0.1:5173 and forwards /api to the
// `hub web` it starts on 7420. The proxy sends the API's own Host, and it maps the dev server's
// own Origin to the API's and drops any other (E9): the learning actions need the server's own
// Origin, the other writes take none, and a page on another site still gets no Origin through,
// so the API refuses it. No dev exception in the server.
export const API_TARGET = "http://127.0.0.1:7420";
export const DEV_SERVER = { host: "127.0.0.1", port: 5173, strictPort: true } as const;
// The origins a browser sends from the dev app: Vite listens on the IPv4 loopback only.
export const DEV_ORIGINS = [
  `http://${DEV_SERVER.host}:${String(DEV_SERVER.port)}`,
  `http://localhost:${String(DEV_SERVER.port)}`,
] as const;

interface ProxiedRequest {
  getHeader(name: string): unknown;
  setHeader(name: string, value: string): unknown;
  removeHeader(name: string): void;
}

function forwardOrigin(request: ProxiedRequest, target: string): void {
  const origin = request.getHeader("origin");
  request.removeHeader("origin");
  if (typeof origin === "string" && (DEV_ORIGINS as readonly string[]).includes(origin)) {
    request.setHeader("origin", new URL(target).origin);
  }
}

export function apiProxy(target: string = API_TARGET): { "/api": ProxyOptions } {
  return {
    "/api": {
      target,
      changeOrigin: true,
      configure: (proxy) => {
        proxy.on("proxyReq", (proxyReq) => {
          forwardOrigin(proxyReq, target);
        });
      },
    },
  };
}

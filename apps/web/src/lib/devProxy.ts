import type { ProxyOptions } from "vite";

// `make dev`: Vite serves the app with hot reload on 127.0.0.1:5173 and forwards /api to the
// `hub web` it starts on 7420. The proxy sends the API's own Host, and it maps the dev server's
// own Origin to the API's and drops any other (E9): the learning actions need the server's own
// Origin, the other writes take none, and a page on another site still gets no Origin through,
// so the API refuses it. No dev exception in the server.
//
// `make live` splits the API in two: the agent-session routes go to a stable `hub web` that drives
// the Claude sessions (it never restarts, so a session survives a change to the server code), and
// every other route goes to the `hub web` of the checkout being edited, which restarts on each change.
export const API_TARGET = "http://127.0.0.1:7420";
export const SESSIONS_PATH = "/api/v1/agent-sessions";
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

function proxyTo(target: string): ProxyOptions {
  return {
    target,
    changeOrigin: true,
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        forwardOrigin(proxyReq, target);
      });
    },
  };
}

/**
 * `make playground` opens `<dev server>/__playground/session?token=…`: the sessions server trades the
 * token for its session cookie and redirects to `/`, so the browser gets the cookie (host-only,
 * shared by every port of 127.0.0.1) without ever opening the sessions server's own address.
 */
export const SESSION_LOGIN_PATH = "/__playground/session";

/**
 * The dev server's proxy: /api to `target`; with a different `sessionsTarget`, the agent-session
 * routes go there instead (listed first, so Vite matches them before /api), and so does the token
 * login of `make playground`.
 */
export function apiProxy(
  target: string = API_TARGET,
  sessionsTarget: string = target,
): {
  [SESSION_LOGIN_PATH]?: ProxyOptions;
  [SESSIONS_PATH]?: ProxyOptions;
  "/api": ProxyOptions;
} {
  if (sessionsTarget === target) return { "/api": proxyTo(target) };
  return {
    [SESSION_LOGIN_PATH]: {
      ...proxyTo(sessionsTarget),
      rewrite: (path) => path.replace(SESSION_LOGIN_PATH, "/"),
    },
    [SESSIONS_PATH]: proxyTo(sessionsTarget),
    "/api": proxyTo(target),
  };
}

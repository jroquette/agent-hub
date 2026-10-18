import { screen } from "./screen";

// The app shell on three screens: sidebar with Hub config, header, scrolling main area (AC-PG-7.1).
screen("shell", "portfolio", "/", { fitsViewport: true });
screen("shell", "sessions", "/sessions", { fitsViewport: true });
screen("shell", "features", "/features", { fitsViewport: true });

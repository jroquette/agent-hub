import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { noteLaunchCookie } from "../lib/launchCookie";

afterEach(() => {
  cleanup();
  // The launch cookie's state is module-wide: each test starts not knowing it.
  noteLaunchCookie(undefined);
});

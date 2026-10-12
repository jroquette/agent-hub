import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** The typed client of the API; requests go to the page's own origin only. */
export const client = createClient<paths>({ baseUrl: "" });

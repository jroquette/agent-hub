import { useState } from "react";

import { Banner } from "../components/feedback";
import { useLaunchCookie } from "./queries";

/**
 * The non-blocking banner under the top bar while this browser lacks the launch cookie: the page
 * reads everything, but the owner's changes, runs and sessions answer 401 until the address
 * hub web printed is opened. The container says nothing here: it is read-only by design.
 */
export function LockedBanner() {
  const { lock, locked } = useLaunchCookie();
  const [dismissed, setDismissed] = useState(false);
  if (!locked || lock === null || dismissed) return null;
  return (
    <Banner
      tone="warning"
      icon="shield-alert"
      onDismiss={() => {
        setDismissed(true);
      }}
    >
      <b>{lock.title}.</b> You can read everything here. {lock.detail}
    </Banner>
  );
}

import { Fragment } from "react";

import { AppLink } from "../components/core";
import { Icon } from "../components/Icon";

export interface BreadcrumbItem {
  label: string;
  href?: string | undefined;
  mono?: boolean | undefined;
}

/** Containment, not history: Portfolio › Project › Run › Session (spec 01). The last is the page. */
export function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav className="ah-crumbs" aria-label="Breadcrumb">
      {items.map((item, i) => (
        <Fragment key={i}>
          {i > 0 && <Icon name="chevron-right" />}
          {i === items.length - 1 || item.href === undefined ? (
            <span
              aria-current={i === items.length - 1 ? "page" : undefined}
              className={item.mono ? "ah-mono" : undefined}
            >
              {item.label}
            </span>
          ) : (
            <AppLink href={item.href} className={item.mono ? "ah-mono" : undefined}>
              {item.label}
            </AppLink>
          )}
        </Fragment>
      ))}
    </nav>
  );
}

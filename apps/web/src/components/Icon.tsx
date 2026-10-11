import { createElement, type SVGProps } from "react";

import { cx } from "../lib/cx";
import { ICONS, type IconName } from "./icons";

export type { IconName } from "./icons";

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name" | "ref"> {
  /** A bundled Lucide icon name. */
  name: IconName;
  size?: "sm" | "lg" | undefined;
  /** Makes the icon an image with this accessible name; without it the icon is decorative. */
  title?: string | undefined;
  className?: string | undefined;
}

/** A Lucide outline icon on a 24 grid with a 2px stroke. */
export function Icon({ name, size, className, title, ...rest }: IconProps) {
  const nodes = ICONS[name];
  return (
    <svg
      viewBox="0 0 24 24"
      className={cx(
        "ah-icon",
        size === "sm" && "ah-icon-sm",
        size === "lg" && "ah-icon-lg",
        className,
      )}
      aria-hidden={title === undefined ? true : undefined}
      role={title === undefined ? undefined : "img"}
      {...rest}
    >
      {title === undefined ? null : <title>{title}</title>}
      {nodes.map(([tag, attrs], index) => createElement(tag, { key: index, ...attrs }))}
    </svg>
  );
}

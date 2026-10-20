import "./OptionRow.css";

import { useId, type ReactNode } from "react";

import { cx } from "../lib/cx";
import { Icon, type IconName } from "./Icon";

/** A label that ends in "(Recommended)" (as Claude marks its preferred option). */
export const RECOMMENDED_MARK = /\s*\(recommended\)\s*$/i;

/**
 * One choice of a question: a radio or checkbox row with its label and, below it, its description.
 * A label ending in "(Recommended)", or `recommended`, shows the Recommended tag. `children` go
 * under the description (the free-text box of an "Other" row). `disabled` greys the row out and
 * turns its input off; say why in its description. `icon` puts a small icon box between the input
 * and the label, a scan cue for a list of kinds. Wrap the rows in `.ah-options`.
 */
export function OptionRow({
  type,
  name,
  label,
  description,
  checked,
  onToggle,
  recommended = false,
  disabled = false,
  icon,
  children,
}: {
  type: "radio" | "checkbox";
  name: string;
  label: string;
  description: ReactNode;
  checked: boolean;
  onToggle: () => void;
  recommended?: boolean;
  disabled?: boolean;
  icon?: IconName | undefined;
  children?: ReactNode;
}) {
  const labelId = useId();
  const descriptionId = useId();
  const tagged = recommended || RECOMMENDED_MARK.test(label);
  return (
    <label
      className={cx("ah-option", checked && "ah-option-checked", disabled && "ah-option-disabled")}
    >
      <input
        type={type}
        name={name}
        className="ah-check"
        checked={checked}
        disabled={disabled}
        aria-labelledby={labelId}
        aria-describedby={description ? descriptionId : undefined}
        onChange={onToggle}
      />
      {icon && (
        <span className="ah-option-icon" aria-hidden="true">
          <Icon name={icon} />
        </span>
      )}
      <span className="ah-option-body">
        <span className="ah-option-label">
          <span id={labelId}>{label.replace(RECOMMENDED_MARK, "")}</span>
          {tagged && <span className="ah-option-tag">Recommended</span>}
        </span>
        {description && (
          <span id={descriptionId} className="ah-small ah-muted">
            {description}
          </span>
        )}
        {children}
      </span>
    </label>
  );
}

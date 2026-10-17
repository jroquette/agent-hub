import { useEffect, useRef, useState } from "react";
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  CSSProperties,
  MouseEvent,
  ReactNode,
} from "react";
import { Link } from "react-router";

import { cx } from "../lib/cx";
import { fmtAgo, fmtMoney, middleTruncate } from "../lib/format";
import { safeHref } from "../lib/safeHref";
import { usePreferences } from "../lib/preferences";
import { Icon, type IconName } from "./Icon";

/** A phase whose actions ship later; its controls render disabled with this tag (D21). */
export type Phase = "P3" | "P4";

/**
 * Copies text and resolves whether the clipboard took it: false when there is no clipboard (plain
 * http is not a secure context, or an old browser) or the write is refused. Never rejects.
 */
export async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Copies text without waiting for the outcome, for controls that do not report it. */
export function copyText(text: string): void {
  void writeClipboard(text);
}

/** Shows a "copied" state for 1.5 s after `mark()`. */
export function useCopied(initial = false): [boolean, () => void] {
  const [copied, setCopied] = useState(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
    },
    [],
  );
  const mark = () => {
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setCopied(false);
    }, 1500);
  };
  return [copied, mark];
}

/* ---------- Links: in-app paths go through the router, others leave the app ---------- */
export interface AppLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  href: string;
}
export function AppLink({ href, children, ...rest }: AppLinkProps) {
  const safe = safeHref(href);
  if (safe === null) {
    return (
      <span className={rest.className} style={rest.style} title={UNSAFE_LINK_TITLE}>
        {children}
      </span>
    );
  }
  if (safe.startsWith("/")) {
    return (
      <Link to={safe} {...rest}>
        {children}
      </Link>
    );
  }
  return (
    <a href={safe} {...rest}>
      {children}
    </a>
  );
}

const UNSAFE_LINK_TITLE = "Link not shown: only http(s) and same-origin links are opened";

/* ---------- Outside link: a URL from API data that opens in a new tab, or plain text if unsafe ---------- */
export interface OutsideLinkProps extends Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  "href" | "target" | "rel"
> {
  href: string | null | undefined;
}
export function OutsideLink({ href, children, ...rest }: OutsideLinkProps) {
  const safe = safeHref(href);
  if (safe === null) {
    return (
      <span className={rest.className} style={rest.style} title={UNSAFE_LINK_TITLE}>
        {children}
      </span>
    );
  }
  return (
    <a href={safe} target="_blank" rel="noreferrer" {...rest}>
      {children}
    </a>
  );
}

/* ---------- Phase tag: marks actions that ship later ---------- */
export function PhaseTag({ phase }: { phase: Phase }) {
  return (
    <span className="ah-phase" title={`Arrives in Phase ${phase.replace("P", "")}`}>
      {phase}
    </span>
  );
}

/** The tooltip of a control whose phase has not shipped (D21). */
export function phaseTooltip(phase: Phase): string {
  return `Available in Phase ${phase.replace("P", "")}. This version is read-only.`;
}

/* ---------- Buttons ---------- */
export type ButtonVariant = "default" | "primary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | undefined;
  icon?: IconName | undefined;
  iconRight?: IconName | undefined;
  /** A later phase: the button is disabled, tagged and explains why (D21). */
  phase?: Phase | undefined;
  children?: ReactNode;
}
export function Button({
  variant = "default",
  size,
  icon,
  iconRight,
  phase,
  children,
  className,
  disabled,
  title,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cx(
        "ah-btn",
        variant !== "default" && `ah-btn-${variant}`,
        size === "sm" && "ah-btn-sm",
        className,
      )}
      disabled={phase !== undefined || disabled}
      title={phase === undefined ? title : phaseTooltip(phase)}
      {...rest}
    >
      {icon && <Icon name={icon} size={size === "sm" ? "sm" : undefined} />}
      {children}
      {iconRight && <Icon name={iconRight} size="sm" />}
      {phase && <PhaseTag phase={phase} />}
    </button>
  );
}

export interface CopyButtonProps {
  /** What is copied, read when pressed. */
  text: string;
  /** The accessible name before copying ("Copy command"); "Copied" or "Copy failed" for 1.5 s after. */
  label: string;
  className?: string | undefined;
}
/**
 * A small ghost "Copy" button that copies `text`, then shows and announces "Copied" only when the
 * clipboard took it, and "Copy failed" otherwise, for a moment.
 */
export function CopyButton({ text, label, className }: CopyButtonProps) {
  const [shown, markShown] = useCopied();
  const [ok, setOk] = useState(true);
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );
  const outcome = shown ? (ok ? "Copied" : "Copy failed") : "";
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        icon={shown ? (ok ? "check" : "circle-alert") : "copy"}
        className={className}
        onClick={() => {
          void writeClipboard(text).then((copied) => {
            if (!mounted.current) return;
            setOk(copied);
            markShown();
          });
        }}
        aria-label={outcome || label}
      >
        {outcome || "Copy"}
      </Button>
      <span className="ah-sr" role="status">
        {outcome}
      </span>
    </>
  );
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  /** The accessible name, also shown as the tooltip. */
  label: string;
  size?: "sm" | undefined;
  variant?: ButtonVariant;
}
export function IconButton({
  icon,
  label,
  size,
  variant = "ghost",
  className,
  ...rest
}: IconButtonProps) {
  return (
    <Tooltip label={label}>
      <button
        type="button"
        aria-label={label}
        className={cx(
          "ah-btn ah-iconbtn",
          `ah-btn-${variant}`,
          size === "sm" && "ah-btn-sm",
          className,
        )}
        {...rest}
      >
        <Icon name={icon} size={size === "sm" ? "sm" : undefined} />
      </button>
    </Tooltip>
  );
}

export function Kbd({ children }: { children?: ReactNode }) {
  return <kbd className="ah-kbd">{children}</kbd>;
}

/* ---------- Tooltip / Popover / menu ---------- */
export interface TooltipProps {
  label?: ReactNode;
  open?: boolean | undefined;
  children?: ReactNode;
  block?: boolean | undefined;
}
export function Tooltip({ label, open, children, block }: TooltipProps) {
  if (label === undefined || label === null || label === "") return <>{children}</>;
  return (
    <span className="ah-tip-wrap" style={block ? { display: "flex", width: "100%" } : undefined}>
      {children}
      <span role="tooltip" className={cx("ah-tip", open && "ah-tip-open")}>
        {label}
      </span>
    </span>
  );
}

export interface PopoverProps {
  open?: boolean | undefined;
  children?: ReactNode;
  style?: CSSProperties | undefined;
  className?: string | undefined;
  label?: string | undefined;
}
export function Popover({ open, children, style, className, label }: PopoverProps) {
  if (!open) return null;
  return (
    <div className={cx("ah-pop", className)} style={style} role="dialog" aria-label={label}>
      {children}
    </div>
  );
}

export interface MenuItemProps {
  icon?: IconName | undefined;
  children?: ReactNode;
  hint?: ReactNode;
  onClick?: (() => void) | undefined;
  selected?: boolean | undefined;
  danger?: boolean | undefined;
}
export function MenuItem({ icon, children, hint, onClick, selected, danger }: MenuItemProps) {
  return (
    <button
      type="button"
      className="ah-menu-item"
      aria-current={selected ? true : undefined}
      onClick={onClick}
      style={danger ? { color: "var(--failed)" } : undefined}
    >
      {icon && <Icon name={icon} />}
      <span className="ah-grow">{children}</span>
      {hint}
    </button>
  );
}

/* ---------- Id chip: short id, copies the full id ---------- */
export interface IdChipProps {
  id: string;
  short?: string | undefined;
  kind?: string | undefined;
  copied?: boolean | undefined;
}
export function IdChip({ id, short, kind, copied: copiedProp }: IdChipProps) {
  const [copied, markCopied] = useCopied(Boolean(copiedProp));
  const shown = short ?? id.replace(/-/g, "").slice(0, 8);
  const copy = (event: MouseEvent) => {
    event.stopPropagation();
    copyText(id);
    markCopied();
  };
  return (
    <Tooltip label={copied ? "Copied full id" : `${kind ? kind + " " : ""}${id} · click to copy`}>
      <button
        type="button"
        className={cx("ah-id", copied && "ah-id-copied")}
        onClick={copy}
        aria-label={`Copy ${kind ?? "id"} ${id}`}
      >
        {kind && <span style={{ color: "var(--text-subtle)" }}>{kind}</span>}
        {shown}
        <Icon name={copied ? "check" : "copy"} />
      </button>
    </Tooltip>
  );
}

/* ---------- Issue link (tracker, opens outside) ---------- */
export interface IssueLinkProps {
  id: string;
  title?: string | null | undefined;
  href?: string | null | undefined;
  showTitle?: boolean | undefined;
}
export function IssueLink({ id, title, href, showTitle }: IssueLinkProps) {
  const label = `${id}${title ? " · " + title : ""}`;
  return (
    <span className="ah-row" style={{ gap: 6, minWidth: 0 }}>
      {safeHref(href) !== null ? (
        <OutsideLink className="ah-issue" href={href} title={`${label} · opens in Linear`}>
          {id}
          <Icon name="arrow-up-right" />
        </OutsideLink>
      ) : (
        <span className="ah-issue" title={`${label} · Linear is not connected in this version.`}>
          {id}
        </span>
      )}
      {showTitle && title && (
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {title}
        </span>
      )}
    </span>
  );
}

/* ---------- Path: mono, middle-truncated, full value on hover ---------- */
export interface PathTextProps {
  path: string;
  max?: number;
  dimDir?: boolean | undefined;
}
export function PathText({ path, max = 48, dimDir }: PathTextProps) {
  const shown = middleTruncate(path, max);
  if (dimDir && shown.includes("/")) {
    const cut = shown.lastIndexOf("/");
    return (
      <span className="ah-path" title={path}>
        <span className="ah-path-dim">{shown.slice(0, cut + 1)}</span>
        {shown.slice(cut + 1)}
      </span>
    );
  }
  return (
    <span className="ah-path" title={path}>
      {shown}
    </span>
  );
}

/* ---------- Money and time ---------- */
export interface MoneyProps {
  value: number | string | null | undefined;
  precise?: boolean | undefined;
  className?: string | undefined;
}
export function Money({ value, precise, className }: MoneyProps) {
  return (
    <span className={cx("ah-num", className)} title={`${fmtMoney(value, 4)} USD`}>
      {fmtMoney(value, precise ? 4 : 2)}
    </span>
  );
}

export interface TimeProps {
  iso?: string | null | undefined;
  /** Age in seconds: shows "3 s ago" with the absolute time on hover. */
  ago?: number | undefined;
  absolute?: boolean | undefined;
  /** Forces UTC; otherwise the time zone preference applies. */
  utc?: boolean | undefined;
}
export function Time({ iso, ago, absolute, utc }: TimeProps) {
  const { tz } = usePreferences();
  const inUtc = utc ?? tz === "utc";
  const date = iso ? new Date(iso) : null;
  const abs = date
    ? inUtc
      ? `${date.toISOString().replace("T", " ").slice(0, 16)} UTC`
      : date.toLocaleString("en-GB", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })
    : "";
  const label = absolute ? abs : ago !== undefined ? fmtAgo(ago) : abs;
  return (
    <time
      dateTime={iso ?? undefined}
      title={abs || undefined}
      className={absolute ? "ah-num" : undefined}
      style={absolute ? { fontWeight: 400 } : undefined}
    >
      {label}
    </time>
  );
}

/* ---------- Tabs & segmented control ---------- */
export interface TabItem {
  id: string;
  label: string;
  icon?: IconName | undefined;
  count?: number | undefined;
  phase?: Phase | undefined;
}
export interface TabsProps {
  tabs: TabItem[];
  value: string;
  onChange?: ((id: string) => void) | undefined;
  label?: string | undefined;
}
export function Tabs({ tabs, value, onChange, label }: TabsProps) {
  return (
    <div className="ah-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          className="ah-tab"
          aria-selected={tab.id === value}
          onClick={() => onChange?.(tab.id)}
        >
          {tab.icon && <Icon name={tab.icon} size="sm" />}
          {tab.label}
          {tab.count !== undefined && <span className="ah-tab-count">{tab.count}</span>}
          {tab.phase && <PhaseTag phase={tab.phase} />}
        </button>
      ))}
    </div>
  );
}

export interface SegmentOption {
  id: string;
  label?: string | undefined;
  icon?: IconName | undefined;
  title?: string | undefined;
}
export interface SegmentedControlProps {
  options: (string | SegmentOption)[];
  value: string;
  onChange?: ((id: string) => void) | undefined;
  label?: string | undefined;
  /** Every segment off (focusable no more, read as unavailable); the value still shows. */
  disabled?: boolean | undefined;
}
export function SegmentedControl({
  options,
  value,
  onChange,
  label,
  disabled,
}: SegmentedControlProps) {
  return (
    <div className="ah-seg" role="group" aria-label={label}>
      {options.map((option) => {
        const opt: SegmentOption =
          typeof option === "string" ? { id: option, label: option } : option;
        return (
          <button
            key={opt.id}
            type="button"
            aria-pressed={opt.id === value}
            disabled={disabled}
            onClick={() => onChange?.(opt.id)}
            aria-label={opt.icon && !opt.label ? opt.title : undefined}
            title={opt.title}
          >
            {opt.icon && <Icon name={opt.icon} size="sm" />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { cx } from "../lib/cx";
import { Button, type Phase } from "./core";
import { Dialog } from "./Dialog";
import { Icon, type IconName } from "./Icon";
import { CodeBlock } from "./trace";

/** The default wait before a loading placeholder shows, so fast answers never flash one. */
export const SKELETON_DELAY_MS = 300;

/** True once `ms` have passed since the first render. */
export function useDelayed(ms: number): boolean {
  const [shown, setShown] = useState(ms <= 0);
  useEffect(() => {
    if (ms <= 0) return undefined;
    const timer = setTimeout(() => {
      setShown(true);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [ms]);
  return shown;
}

export interface SkeletonProps {
  width?: number | string;
  height?: number;
  radius?: number | string | undefined;
  style?: CSSProperties | undefined;
  lines?: number | undefined;
  /** Milliseconds before it shows (default 300); 0 shows it at once. */
  delay?: number;
}
export function Skeleton({
  width = "100%",
  height = 12,
  radius,
  style,
  lines,
  delay = SKELETON_DELAY_MS,
}: SkeletonProps) {
  const shown = useDelayed(delay);
  if (!shown) return null;
  if (lines) {
    return (
      <div className="ah-stack" style={{ gap: 8, ...style }} aria-hidden="true">
        {Array.from({ length: lines }, (_, i) => (
          <span
            key={i}
            className="ah-skel"
            style={{ width: i === lines - 1 ? "60%" : "100%", height }}
          />
        ))}
      </div>
    );
  }
  return (
    <span
      className="ah-skel"
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

/* Empty state: explains why, and the next action (often an exact command) */
export interface EmptyStateProps {
  icon?: IconName;
  title: string;
  children?: ReactNode;
  command?: string | undefined;
  action?: ReactNode;
}
export function EmptyState({
  icon = "circle-dashed",
  title,
  children,
  command,
  action,
}: EmptyStateProps) {
  return (
    <div className="ah-empty">
      <div className="ah-empty-icon">
        <Icon name={icon} size="lg" />
      </div>
      <h3 className="ah-empty-title">{title}</h3>
      {children && <p>{children}</p>}
      {command && (
        <div style={{ width: "100%", textAlign: "left" }}>
          <CodeBlock code={command} />
        </div>
      )}
      {action}
    </div>
  );
}

/* RFC 9457 Problem Details: title + detail + "Try again" */
export interface ProblemErrorProps {
  title?: string;
  detail?: string | null | undefined;
  status?: number | undefined;
  type?: string | undefined;
  instance?: string | null | undefined;
  onRetry?: (() => void) | undefined;
  compact?: boolean | undefined;
}
export function ProblemError({
  title = "Could not load this view",
  detail,
  status,
  type,
  instance,
  onRetry,
  compact,
}: ProblemErrorProps) {
  const meta = [
    status ? `HTTP ${String(status)}` : "",
    type && type !== "about:blank" ? type : "",
    instance ?? "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="ah-problem" role="alert">
      <Icon name="circle-alert" className="ah-problem-icon" size="lg" />
      <div className="ah-grow">
        <p className="ah-problem-title">{title}</p>
        {detail && <p className="ah-problem-detail">{detail}</p>}
        <div className="ah-row ah-wrap">
          {onRetry && (
            <Button size="sm" icon="refresh-cw" onClick={onRetry}>
              Try again
            </Button>
          )}
          {!compact && meta && <span className="ah-problem-meta">{meta}</span>}
        </div>
      </div>
    </div>
  );
}

export type BannerTone = "info" | "warning" | "offline" | "error";
const BANNER_ICON: Record<BannerTone, IconName> = {
  info: "info",
  warning: "triangle-alert",
  offline: "wifi-off",
  error: "circle-alert",
};
export interface BannerProps {
  tone?: BannerTone;
  icon?: IconName | undefined;
  children?: ReactNode;
  action?: ReactNode;
  boxed?: boolean | undefined;
  onDismiss?: (() => void) | undefined;
}
export function Banner({ tone = "info", icon, children, action, boxed, onDismiss }: BannerProps) {
  return (
    <div
      className={cx("ah-banner", `ah-banner-${tone}`, boxed && "ah-banner-boxed")}
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon name={icon ?? BANNER_ICON[tone]} />
      <div className="ah-grow">{children}</div>
      {action}
      {onDismiss && (
        <Button size="sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss">
          <Icon name="x" size="sm" />
        </Button>
      )}
    </div>
  );
}

/* Toast: only for results of the user's own actions, never for routine events */
export interface ToastProps {
  children?: ReactNode;
  tone?: "ok" | "error";
  action?: ReactNode;
  onUndo?: (() => void) | undefined;
}
export function Toast({ children, tone = "ok", action, onUndo }: ToastProps) {
  return (
    <div className={cx("ah-toast", `ah-toast-${tone}`)} role="status" aria-live="polite">
      <Icon name={tone === "ok" ? "circle-check" : "circle-alert"} />
      <span className="ah-grow">{children}</span>
      {onUndo && (
        <button type="button" className="ah-btn" onClick={onUndo}>
          Undo
        </button>
      )}
      {action}
    </div>
  );
}

/* Confirmation only for irreversible actions; states consequences; verb on the button. On Dialog:
   Escape, the X and the scrim cancel; focus starts on Cancel (or the text to type). */
export interface ConfirmDialogProps {
  title: string;
  children?: ReactNode;
  consequences?: ReactNode[];
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  requireText?: string | undefined;
  onCancel?: (() => void) | undefined;
  onConfirm?: (() => void) | undefined;
  /** While true (the confirmed request runs), nothing closes it and its buttons are off. */
  pending?: boolean | undefined;
  phase?: Phase | undefined;
}
export function ConfirmDialog({
  title,
  children,
  consequences = [],
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  requireText,
  onCancel,
  onConfirm,
  pending,
  phase,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const ok = !requireText || typed === requireText;
  return (
    <Dialog
      title={title}
      role="alertdialog"
      onClose={onCancel}
      pending={pending}
      footer={
        <>
          <Button disabled={pending} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            disabled={!ok || pending}
            onClick={onConfirm}
            phase={phase}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children && <div className="ah-muted">{children}</div>}
      {consequences.length > 0 && (
        <ul className="ah-consequences">
          {consequences.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      {requireText && (
        <label className="ah-stack" style={{ gap: 4 }}>
          <span className="ah-small ah-muted">
            Type{" "}
            <b className="ah-mono" style={{ color: "var(--text)" }}>
              {requireText}
            </b>{" "}
            to confirm
          </span>
          <input
            className="ah-input"
            value={typed}
            onChange={(e) => {
              setTyped(e.target.value);
            }}
          />
        </label>
      )}
    </Dialog>
  );
}

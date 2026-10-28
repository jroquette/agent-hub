import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";

import { Icon } from "../../../components";

/* Where a step's value goes, picked from what the hub declares (spec 23, the open step): the
 * services of the environment in the run bar, grouped by kind, found by typing. A service input
 * holds a service's name; the run resolves it to that service's address in its environment. One
 * list, filtered by what is typed; ↑/↓ move, Enter picks, Esc closes. */

/** A declared service as the picker lists it: its name, kind and address in the environment. */
export interface ServiceOption {
  name: string;
  /** The repo that declares it, when it has one (`<repo>/<name>` names it then). */
  repo: string | null;
  kind: string | null;
  description: string | null;
  /** Its URL, else its resource name, in the environment; null when it has none there. */
  address: string | null;
}

const KIND_WORDS: Readonly<Record<string, string>> = {
  api: "APIs and backends",
  frontend: "Frontends",
  database: "Databases",
  sqs: "Queues (SQS)",
  queue: "Queues",
  bucket: "Buckets",
  lambda: "Functions",
  dynamodb: "Tables (DynamoDB)",
  cognito: "User pools",
};

const MENU_WIDTH = 440;

/** The value a picked service is written as. */
export function serviceValue(option: ServiceOption): string {
  return option.repo ? `${option.repo}/${option.name}` : option.name;
}

function matches(option: ServiceOption, value: string): boolean {
  return value === option.name || value === serviceValue(option);
}

/** The field: the picked service and its address; a press opens the list. */
export function ServiceField({
  label,
  value,
  options,
  environment,
  onPick,
}: {
  label: string;
  value: string;
  options: readonly ServiceOption[];
  environment: string | null;
  onPick: (value: string) => void;
}) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const picked = options.find((option) => matches(option, value)) ?? null;
  return (
    <>
      <button
        type="button"
        className="st-service"
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        aria-label={`${label}: ${value || "choose a service"}`}
        title={picked?.address ?? undefined}
        onClick={(event) => {
          event.stopPropagation();
          setAnchor(event.currentTarget.getBoundingClientRect());
        }}
      >
        <span className="st-service-name">{value || "Choose a service"}</span>
        {picked?.address && <span className="st-service-address">{picked.address}</span>}
        {value !== "" && picked === null && (
          <span className="st-service-missing">
            not declared{environment ? ` in ${environment}` : ""}
          </span>
        )}
        <Icon name="chevrons-up-down" size="sm" />
      </button>
      {anchor &&
        createPortal(
          <ServicePicker
            anchor={anchor}
            title={label}
            value={value}
            options={options}
            environment={environment}
            onPick={(next) => {
              setAnchor(null);
              onPick(next);
            }}
            onClose={() => {
              setAnchor(null);
            }}
          />,
          document.body,
        )}
    </>
  );
}

export function ServicePicker({
  anchor,
  title,
  value,
  options,
  environment,
  onPick,
  onClose,
}: {
  anchor: DOMRect;
  title: string;
  value: string;
  options: readonly ServiceOption[];
  environment: string | null;
  onPick: (value: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const field = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(() => {
    field.current?.focus();
  }, []);
  const needle = query.trim().toLowerCase();
  // Grouped by kind, in the order the kinds are named above, then by name.
  const order = Object.keys(KIND_WORDS);
  const sorted = [...options].sort((a, b) => {
    const ka = order.indexOf(a.kind ?? "");
    const kb = order.indexOf(b.kind ?? "");
    return (ka === -1 ? 99 : ka) - (kb === -1 ? 99 : kb) || a.name.localeCompare(b.name);
  });
  const shown = needle
    ? sorted.filter((option) =>
        [option.name, option.kind, option.address, option.description, option.repo]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(needle),
      )
    : sorted;
  const pick = (index: number) => {
    const option = shown[index];
    if (option) onPick(serviceValue(option));
  };
  const onKey = (event: KeyboardEvent) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((at) => Math.min(shown.length - 1, at + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((at) => Math.max(0, at - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(Math.min(active, shown.length - 1));
    }
  };
  const left = Math.max(8, Math.min(window.innerWidth - MENU_WIDTH - 8, anchor.right - MENU_WIDTH));
  const below = anchor.bottom + 6;
  const top = below + 420 > window.innerHeight ? Math.max(8, anchor.top - 426) : below;
  const groupOf = (option: ServiceOption) =>
    KIND_WORDS[option.kind ?? ""] ?? option.kind ?? "Other services";
  return (
    <>
      <div className="bk-menu-scrim" onPointerDown={onClose} aria-hidden />
      <div
        className="ah-pop bk-menu"
        role="dialog"
        aria-label={`Choose ${title}`}
        style={{ left, top, width: MENU_WIDTH }}
      >
        <div className="bk-menu-head">
          Choose {title}
          {environment ? ` · services in ${environment}` : ""}
        </div>
        <input
          ref={field}
          className="ah-input"
          aria-label="Find a service by name, kind or address"
          placeholder="Find a service by name, kind or address"
          value={query}
          onKeyDown={onKey}
          role="combobox"
          aria-expanded
          aria-controls={`${id}-options`}
          aria-activedescendant={shown.length > 0 ? `${id}-option-${String(active)}` : undefined}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
        />
        <div className="bk-menu-list" id={`${id}-options`} role="listbox" aria-label="Services">
          {shown.map((option, index) => {
            const group = groupOf(option);
            const previous = shown[index - 1];
            const head = previous === undefined || groupOf(previous) !== group ? group : null;
            const current = matches(option, value);
            return (
              <div key={serviceValue(option)}>
                {head && <div className="bk-menu-group">{head}</div>}
                <button
                  type="button"
                  role="option"
                  id={`${id}-option-${String(index)}`}
                  aria-selected={index === active}
                  className="bk-menu-row bk-menu-row-2"
                  onPointerEnter={() => {
                    setActive(index);
                  }}
                  onClick={() => {
                    pick(index);
                  }}
                >
                  <Icon name={current ? "check" : "server"} size="sm" />
                  <span className="bk-menu-label">{option.name}</span>
                  <span className="bk-menu-hint">{option.repo ?? ""}</span>
                  <span className="bk-menu-about">
                    {option.address ?? `no address in ${environment ?? "this environment"}`}
                  </span>
                </button>
              </div>
            );
          })}
          {shown.length === 0 && (
            <span className="ah-small ah-subtle">
              {options.length === 0
                ? `No service is declared${environment ? ` in ${environment}` : ""}. Add one in Environments.`
                : "Nothing matches."}
            </span>
          )}
        </div>
        <div className="bk-menu-foot">
          <span>↑↓ move · Enter picks · Esc closes</span>
        </div>
      </div>
    </>
  );
}

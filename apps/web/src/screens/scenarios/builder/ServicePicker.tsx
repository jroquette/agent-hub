import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";

import { Icon } from "../../../components";
import { serviceKindRank, serviceKindWords } from "../../hub-config/environments";

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

const MENU_WIDTH = 440;

/** A kind in words ("Queue (SQS)"), as the Environments pages name it, or null for none. */
export function kindWordsOf(kind: string | null | undefined): string | null {
  return kind ? serviceKindWords(kind).label : null;
}

/** The value a picked service is written as: its name, or `<repo>/<name>` only when another
 * repo has a service of that name (the run refuses an ambiguous name). A service of no repo has
 * no longer form (core action_call._service reads an empty repo as any): its name is written,
 * and the field then says it is in more than one repo. */
export function serviceValue(option: ServiceOption, all: readonly ServiceOption[] = []): string {
  const shared = all.some((other) => other.name === option.name && other.repo !== option.repo);
  return shared && option.repo ? `${option.repo}/${option.name}` : option.name;
}

function key(option: ServiceOption): string {
  return `${option.repo ?? ""}/${option.name}`;
}

/** The services a value names, as the run finds them (core action_call._service): `<repo>/<name>`
 * names that repo's, a bare name the service of that name in any repo. */
export function servicesNamed(
  value: string,
  options: readonly ServiceOption[],
): readonly ServiceOption[] {
  const cut = value.lastIndexOf("/");
  const repo = value.slice(0, Math.max(0, cut));
  const name = value.slice(cut + 1);
  return options.filter(
    (option) => option.name === name && (repo === "" || repo === (option.repo ?? "")),
  );
}

interface ServiceFieldProps {
  label: string;
  value: string;
  options: readonly ServiceOption[];
  environment: string | null;
  onPick: (value: string) => void;
}

/** A service input's two controls: the kind (a filter, set by the picked service unless one is
 * chosen) and the field that opens the list. They share one state, so a row can lay them apart:
 * the kind where the input's name goes, the service where its value goes. */
export function useServiceField({ label, value, options, environment, onPick }: ServiceFieldProps) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const named = value === "" ? [] : servicesNamed(value, options);
  const picked = named.length === 1 ? (named[0] ?? null) : null;
  // A bare name two repos declare: the run refuses it, so it is not shown as either one.
  const ambiguous = named.length > 1;
  const [chosenKind, setChosenKind] = useState<string | null>(null);
  const kind = chosenKind ?? picked?.kind ?? "";
  const kinds = [...new Set(options.map((option) => option.kind ?? "").filter(Boolean))].sort(
    (a, b) => serviceKindWords(a).label.localeCompare(serviceKindWords(b).label),
  );
  const listed = kind === "" ? options : options.filter((option) => option.kind === kind);
  /** The kind in words ("Queue (SQS)"), the one chosen or the picked service's; null for any. */
  const kindWords = kindWordsOf(kind);
  const where = environment ? ` in ${environment}` : "";
  /** What the input's note says of the pick: its kind, description and address; what is in the
   * way of one; or, nothing picked yet, what to choose. The open step and the side panel both
   * say it. */
  const about =
    picked !== null
      ? [kindWordsOf(picked.kind), picked.description, picked.address ?? `no address${where}`]
          .filter(Boolean)
          .join(" · ")
      : ambiguous
        ? `In ${named.map((option) => option.repo ?? "no repo").join(" and ")}: pick the one it means`
        : value === ""
          ? `Choose ${kind === "" ? "a service" : serviceKindWords(kind).one}${where}`
          : null;
  const kindSelect = (
    <select
      className="ah-input st-service-kind"
      aria-label={`Kind of service for ${label}`}
      value={kind}
      onClick={(event) => {
        event.stopPropagation();
      }}
      onChange={(event) => {
        setChosenKind(event.target.value);
      }}
    >
      <option value="">Any kind</option>
      {kinds.map((each) => (
        <option key={each} value={each}>
          {serviceKindWords(each).label}
        </option>
      ))}
    </select>
  );
  const field = (
    <>
      <button
        type="button"
        className="ah-input st-service"
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        aria-label={`${label}: ${picked?.name ?? (value || "choose a service")}`}
        title={picked?.address ?? undefined}
        onClick={(event) => {
          event.stopPropagation();
          setAnchor(event.currentTarget.getBoundingClientRect());
        }}
      >
        <span className="st-service-name">{picked?.name ?? (value || "Choose a service")}</span>
        {value !== "" && picked === null && (
          <span className="st-service-missing">
            <Icon name="circle-alert" size="sm" />
            {ambiguous
              ? "in more than one repo"
              : `not declared${environment ? ` in ${environment}` : ""}`}
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
            options={listed}
            all={options}
            kindWords={kindWords}
            environment={environment}
            onPick={(next) => {
              setAnchor(null);
              // The kind follows the service picked, unless one was chosen to filter by.
              if (chosenKind === "") setChosenKind(null);
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
  return { kindSelect, field, picked, about };
}

/** Both controls side by side, the note on the pick under them (the side panel, under the
 * input's name). */
export function ServiceField(props: ServiceFieldProps) {
  const { kindSelect, field, about } = useServiceField(props);
  return (
    <>
      <span className="st-service-pair">
        {kindSelect}
        {field}
      </span>
      {about && <span className="ah-small ah-muted">{about}</span>}
    </>
  );
}

// Debt: its search list (keys, placing, groups) repeats InsertMenu's; a shared SearchMenu waits.
export function ServicePicker({
  anchor,
  title,
  value,
  options,
  all = options,
  kindWords = null,
  environment,
  onPick,
  onClose,
}: {
  anchor: DOMRect;
  title: string;
  value: string;
  options: readonly ServiceOption[];
  /** Every declared service, the filter aside: a name is written short when it is unique. */
  all?: readonly ServiceOption[];
  /** The kind the list is filtered to, in words (null: every kind). */
  kindWords?: string | null;
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
  // Grouped by kind, in the picker's order of kinds (a service of no kind with the others), then
  // by name.
  const kindOf = (option: ServiceOption) => option.kind ?? "other";
  const sorted = [...options].sort(
    (a, b) =>
      serviceKindRank(kindOf(a)) - serviceKindRank(kindOf(b)) ||
      kindOf(a).localeCompare(kindOf(b)) ||
      a.name.localeCompare(b.name),
  );
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
    if (option) onPick(serviceValue(option, all));
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
  const groupOf = (option: ServiceOption) => serviceKindWords(kindOf(option)).plural;
  const picked = servicesNamed(value, all);
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
          {` · ${kindWords ?? "services"}${environment ? ` in ${environment}` : ""}`}
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
            const current = picked.length === 1 && picked[0] === option;
            return (
              <div key={key(option)}>
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

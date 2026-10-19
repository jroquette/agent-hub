/* Feature nicknames: a name the owner gives a feature; the slug stays its identity. */
import "./names.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { components } from "../../api/schema";
import { Icon } from "../../components";
import { ApiProblem, apiKey, apiPut, useApi } from "../../lib/api";

type FeatureName = components["schemas"]["FeatureName"];
type FeatureNamesView = components["schemas"]["FeatureNamesView"];
interface Ref {
  project: string;
  slug: string;
}

/** Longest nickname the API keeps. */
export const MAX_FEATURE_NAME = 80;

const NAMES_KEY = apiKey("/api/v1/feature-names");
const keyOf = (f: Ref) => `${f.project}/${f.slug}`;

/** The nickname of each feature, by `project/slug`; empty while loading or when the API has none. */
export function useFeatureNames(): (f: Ref) => string | null {
  const names = useApi("/api/v1/feature-names", undefined, { staleTime: 60_000 });
  const map = new Map((names.data?.items ?? []).map((n) => [keyOf(n), n.name]));
  return (f) => map.get(keyOf(f)) ?? null;
}

/** Saves a nickname ("" clears it), shown at once and rolled back if the API refuses it. */
export function useSetFeatureName() {
  const client = useQueryClient();
  return useMutation<
    FeatureName,
    ApiProblem,
    FeatureName,
    { before: FeatureNamesView | undefined }
  >({
    mutationFn: (body) => apiPut("/api/v1/feature-names", body),
    onMutate: async (body) => {
      await client.cancelQueries({ queryKey: NAMES_KEY });
      const before = client.getQueryData<FeatureNamesView>(NAMES_KEY);
      const others = (before?.items ?? []).filter((n) => keyOf(n) !== keyOf(body));
      const name = body.name.trim();
      client.setQueryData<FeatureNamesView>(NAMES_KEY, {
        items: name ? [...others, { ...body, name }] : others,
      });
      return { before };
    },
    onError: (_error, _body, context) => {
      if (context?.before) client.setQueryData(NAMES_KEY, context.before);
    },
    onSettled: () => client.invalidateQueries({ queryKey: NAMES_KEY }),
  });
}

/**
 * The inline editor of a nickname: Enter or leaving the field saves, Esc cancels, an empty
 * field goes back to the slug. Clicks and keys stay inside, so a list row does not open.
 */
export function FeatureNameField({
  feature,
  name,
  onDone,
  className,
}: {
  feature: Ref;
  name: string | null;
  onDone: () => void;
  className?: string;
}) {
  const [value, setValue] = useState(name ?? "");
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  const save = useSetFeatureName();
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const finish = (keep: boolean) => {
    if (done.current) return;
    done.current = true;
    const next = value.trim();
    if (keep && next !== (name ?? ""))
      save.mutate({ project: feature.project, slug: feature.slug, name: next });
    onDone();
  };
  return (
    <input
      ref={ref}
      className={`ah-input ft-name-input ${className ?? ""}`}
      aria-label={`Name for ${feature.slug}`}
      placeholder={feature.slug}
      maxLength={MAX_FEATURE_NAME}
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
      }}
      onClick={(event) => {
        event.stopPropagation();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") finish(true);
        if (event.key === "Escape") finish(false);
      }}
      onBlur={() => {
        finish(true);
      }}
    />
  );
}

/** The pencil that opens the editor; a real button, so it is reachable by keyboard. */
export function RenameButton({
  slug,
  named,
  onClick,
}: {
  slug: string;
  named: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="ah-btn ah-btn-sm ah-btn-ghost ft-rename"
      aria-label={named ? `Rename ${slug}` : `Give ${slug} a name`}
      title={named ? "Rename" : "Give it a name"}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
      }}
    >
      <Icon name="pencil" size="sm" />
    </button>
  );
}

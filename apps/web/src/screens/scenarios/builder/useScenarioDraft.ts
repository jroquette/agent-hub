import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { components } from "../../../api/schema";
import { apiKey, apiPost, apiPut, useApi, type ApiProblem } from "../../../lib/api";
import { readStored, removeStored, writeStored } from "../../../lib/storage";
import type { Json, ScenarioDocument } from "./model";

/* The builder's working copy of a scenario: the document as edited (a graph, or a scenario
 * written as blocks: the draft holds either as the file's mapping), undo and redo, whether it
 * differs from the file, the server's check of it (the YAML Save would write, whether it loads,
 * each problem on its block), kept live a moment after each edit, and Save. */

type Schemas = components["schemas"];
export type ValidateResult = Schemas["ValidateResult"];
export type BuilderProblem = Schemas["BuilderProblem"];
export type SaveResult = Schemas["SaveResult"];
export type LibraryAction = Schemas["LibraryAction"];

const CHECK_AFTER_MS = 350;
const MAX_UNDO = 100;

export function useActionLibrary(project: string) {
  return useApi("/api/v1/projects/{project}/actions", { path: { project } });
}

export interface ScenarioDraft {
  document: ScenarioDocument;
  dirty: boolean;
  edit: (next: ScenarioDocument) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  check: ValidateResult | null;
  checking: boolean;
  checkError: ApiProblem | null;
  save: () => void;
  saving: boolean;
  saveError: ApiProblem | null;
  saved: SaveResult | null;
  reset: (document: ScenarioDocument) => void;
  /** The unsaved changes came back from this browser (kept across Build/Run and reloads). */
  restored: boolean;
  /** Throws the unsaved changes away and shows the file again. */
  discard: () => void;
  /** The file changed outside the builder while it held unsaved changes. */
  conflict: boolean;
  /** Takes the file's new version, dropping the unsaved changes. */
  takeFile: () => void;
  /** Keeps the unsaved changes; Save then replaces the file's new version. */
  keepMine: () => void;
}

interface Stored {
  base: string | null;
  document: ScenarioDocument;
}

function draftKey(project: string, name: string): string {
  return `ah.builder.draft.${project}/${name}`;
}

function readDraft(
  project: string,
  name: string,
  read: (value: unknown) => ScenarioDocument,
): Stored | null {
  try {
    const value = JSON.parse(readStored(draftKey(project, name)) ?? "null") as Stored | null;
    const held: Json | undefined = value?.document.nodes ?? value?.document.stages;
    return value && Array.isArray(held) ? { ...value, document: read(value.document) } : null;
  } catch {
    return null;
  }
}

export function useScenarioDraft({
  project,
  name,
  pack,
  initial,
  contentHash,
  read,
}: {
  project: string;
  name: string;
  pack: string;
  initial: ScenarioDocument;
  contentHash: string | null;
  /** The builder's copy of a mapping read back (a kept draft, the file's text). */
  read: (value: unknown) => ScenarioDocument;
}): ScenarioDraft {
  const client = useQueryClient();
  const [past, setPast] = useState<ScenarioDocument[]>([]);
  const [future, setFuture] = useState<ScenarioDocument[]>([]);
  // A draft this browser kept for the same file comes back; one for an older file does not.
  const [stored] = useState(() => {
    const kept = readDraft(project, name, read);
    return kept?.base === contentHash ? kept : null;
  });
  const [document, setDocument] = useState<ScenarioDocument>(stored?.document ?? initial);
  const [restored, setRestored] = useState(stored !== null);
  const [base, setBase] = useState<{ text: string; hash: string | null }>({
    text: JSON.stringify(initial),
    hash: contentHash,
  });
  // The file as the page last read it: a new hash is a change made outside the builder.
  const [seen, setSeen] = useState(contentHash);
  const [conflict, setConflict] = useState(false);
  const dirtyNow = JSON.stringify(document) !== base.text;
  if (seen !== contentHash) {
    setSeen(contentHash);
    if (contentHash !== base.hash) {
      if (dirtyNow) setConflict(true);
      else {
        setDocument(initial);
        setBase({ text: JSON.stringify(initial), hash: contentHash });
        setPast([]);
        setFuture([]);
      }
    }
  }

  useEffect(() => {
    if (dirtyNow) {
      writeStored(draftKey(project, name), JSON.stringify({ base: base.hash, document }));
    } else {
      removeStored(draftKey(project, name));
    }
  }, [dirtyNow, document, base.hash, project, name]);
  const [check, setCheck] = useState<ValidateResult | null>(null);
  const latest = useRef(0);

  const validate = useMutation<ValidateResult, ApiProblem, ScenarioDocument>({
    mutationFn: (body) =>
      apiPost(
        "/api/v1/projects/{project}/scenarios/validate",
        { pack, document: body },
        { path: { project } },
      ),
  });
  const { mutate: runCheck } = validate;

  useEffect(() => {
    const ticket = ++latest.current;
    const timer = setTimeout(() => {
      runCheck(document, {
        onSuccess: (result) => {
          if (ticket === latest.current) setCheck(result);
        },
      });
    }, CHECK_AFTER_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [document, runCheck]);

  const saveMutation = useMutation<SaveResult, ApiProblem, ScenarioDocument>({
    mutationFn: (body) =>
      apiPut(
        "/api/v1/scenarios/{project}/{name}",
        { pack, document: body, base_content_hash: base.hash },
        { path: { project, name } },
      ),
    onSuccess: (result, body) => {
      const next = { ...body, revision: result.revision };
      setDocument(next);
      setBase({ text: JSON.stringify(next), hash: result.content_hash });
      setSeen(result.content_hash);
      setConflict(false);
      setRestored(false);
      void client.invalidateQueries({
        queryKey: apiKey("/api/v1/scenarios/{project}/{name}", { path: { project, name } }),
      });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/scenarios") });
    },
  });

  const edit = (next: ScenarioDocument) => {
    setPast((items) => [...items.slice(-MAX_UNDO + 1), document]);
    setFuture([]);
    setDocument(next);
  };

  return {
    document,
    dirty: dirtyNow,
    restored: restored && dirtyNow,
    discard: () => {
      setDocument(read(JSON.parse(base.text)));
      setPast([]);
      setFuture([]);
      setRestored(false);
    },
    conflict,
    takeFile: () => {
      setDocument(initial);
      setBase({ text: JSON.stringify(initial), hash: contentHash });
      setPast([]);
      setFuture([]);
      setConflict(false);
      setRestored(false);
    },
    keepMine: () => {
      setBase({ text: JSON.stringify(initial), hash: contentHash });
      setConflict(false);
    },
    edit,
    undo: () => {
      const previous = past.at(-1);
      if (!previous) return;
      setPast(past.slice(0, -1));
      setFuture([document, ...future]);
      setDocument(previous);
    },
    redo: () => {
      const [next, ...rest] = future;
      if (!next) return;
      setFuture(rest);
      setPast([...past, document]);
      setDocument(next);
    },
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    check,
    checking: validate.isPending,
    checkError: validate.error,
    save: () => {
      saveMutation.mutate(document);
    },
    saving: saveMutation.isPending,
    saveError: saveMutation.error,
    saved: saveMutation.data ?? null,
    reset: (next) => {
      setDocument(next);
      setPast([]);
      setFuture([]);
      setBase({ text: JSON.stringify(next), hash: contentHash });
    },
  };
}

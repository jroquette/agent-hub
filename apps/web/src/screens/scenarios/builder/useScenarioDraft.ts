import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { components } from "../../../api/schema";
import { apiKey, apiPost, apiPut, useApi, type ApiProblem } from "../../../lib/api";
import type { BuilderDocument } from "./model";

/* The builder's working copy of a scenario: the document as edited, undo and redo, whether it
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
  document: BuilderDocument;
  dirty: boolean;
  edit: (next: BuilderDocument) => void;
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
  reset: (document: BuilderDocument) => void;
}

export function useScenarioDraft({
  project,
  name,
  pack,
  initial,
  contentHash,
}: {
  project: string;
  name: string;
  pack: string;
  initial: BuilderDocument;
  contentHash: string | null;
}): ScenarioDraft {
  const client = useQueryClient();
  const [past, setPast] = useState<BuilderDocument[]>([]);
  const [future, setFuture] = useState<BuilderDocument[]>([]);
  const [document, setDocument] = useState<BuilderDocument>(initial);
  const [base, setBase] = useState<{ text: string; hash: string | null }>({
    text: JSON.stringify(initial),
    hash: contentHash,
  });
  const [check, setCheck] = useState<ValidateResult | null>(null);
  const latest = useRef(0);

  const validate = useMutation<ValidateResult, ApiProblem, BuilderDocument>({
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

  const saveMutation = useMutation<SaveResult, ApiProblem, BuilderDocument>({
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
      void client.invalidateQueries({
        queryKey: apiKey("/api/v1/scenarios/{project}/{name}", { path: { project, name } }),
      });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/scenarios") });
    },
  });

  const edit = (next: BuilderDocument) => {
    setPast((items) => [...items.slice(-MAX_UNDO + 1), document]);
    setFuture([]);
    setDocument(next);
  };

  return {
    document,
    dirty: JSON.stringify(document) !== base.text,
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

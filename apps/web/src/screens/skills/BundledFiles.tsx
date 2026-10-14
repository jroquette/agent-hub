/* A skill's bundled files by role (S7, AC-164.21): text viewable by server-issued id, never run. */
import "./SkillDetail.css";

import { useEffect, useState } from "react";

import { Button, Icon, ProblemError, Skeleton } from "../../components";
import type { IconName } from "../../components";
import type { components } from "../../api/schema";
import { bundledFileAnchor } from "../../lib/skillLinks";
import { scrollToAnchor } from "./BodyView";
import { useSkillFile, type SkillRef } from "./queries";

type BundledFile = components["schemas"]["BundledFile"];
type FileRole = BundledFile["role"];

const ROLES: readonly { role: FileRole; label: string; help: string; icon: IconName }[] = [
  { role: "scripts", label: "Scripts", help: "executed at invocation", icon: "square-terminal" },
  { role: "references", label: "References", help: "read on demand", icon: "book-open" },
  { role: "assets", label: "Assets", help: "used in output, not read as text", icon: "box" },
  { role: "other", label: "Other files", help: "in the skill folder", icon: "file" },
];

/** "64 B", "2.0 KiB", "1.5 MiB". */
export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function FileText({ project, item, file }: { project: string; item: SkillRef; file: BundledFile }) {
  const text = useSkillFile(project, item, file.id);
  if (text.isPending) return <Skeleton width={240} />;
  if (text.isError) {
    if (text.error.status === 413) {
      return <p className="ah-small ah-muted">This file is over 256 KiB, so it is not shown.</p>;
    }
    return (
      <ProblemError
        title={text.error.title}
        detail={text.error.detail}
        status={text.error.status}
        onRetry={() => void text.refetch()}
      />
    );
  }
  if (text.data.binary || text.data.text === null) {
    return <p className="ah-small ah-muted">Binary file: not shown.</p>;
  }
  return (
    <>
      {/* A scrolling region must take keyboard focus (axe scrollable-region-focusable). */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <pre className="ah-skill-raw" tabIndex={0}>
        {text.data.text}
      </pre>
      <p className="ah-small ah-muted" style={{ margin: "6px 0 0" }}>
        Shown as text; this page never runs or follows it.
      </p>
    </>
  );
}

export interface BundledFilesProps {
  project: string;
  item: SkillRef;
  files: readonly BundledFile[];
  /** The open file's id, when the page owns it (a body link opens a file); else internal. */
  openId?: string | null | undefined;
  onOpenChange?: ((id: string | null) => void) | undefined;
}

export function BundledFiles({ project, item, files, openId, onOpenChange }: BundledFilesProps) {
  const [own, setOwn] = useState<string | null>(null);
  const open = openId === undefined ? own : openId;
  const setOpen = (id: string | null) => {
    setOwn(id);
    onOpenChange?.(id);
  };
  useEffect(() => {
    if (openId) scrollToAnchor(bundledFileAnchor(openId));
  }, [openId]);

  return (
    <section className="ah-card ah-skill-section" aria-labelledby="skill-files">
      <div className="ah-card-head">
        <h2 id="skill-files" className="ah-h3">
          Bundled files <span className="ah-count">{files.length}</span>
        </h2>
      </div>
      <div className="ah-card-body ah-stack" style={{ gap: 16 }}>
        {files.length === 0 && (
          <p className="ah-small ah-muted" style={{ margin: 0 }}>
            No files besides SKILL.md.
          </p>
        )}
        {ROLES.map(({ role, label, help, icon }) => {
          const group = files.filter((file) => file.role === role);
          if (group.length === 0) return null;
          const headingId = `skill-files-${role}`;
          return (
            <section key={role} aria-labelledby={headingId}>
              <h3 id={headingId} className="ah-skill-role">
                <Icon name={icon} size="sm" />
                {label}
                <span className="ah-small ah-muted" style={{ fontWeight: 400 }}>
                  {help}
                </span>
              </h3>
              <ul className="ah-skill-files" aria-labelledby={headingId}>
                {group.map((file) => {
                  const isOpen = open === file.id;
                  const panelId = `${bundledFileAnchor(file.id)}-text`;
                  return (
                    <li key={file.id} id={bundledFileAnchor(file.id)}>
                      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
                        <span className="ah-mono ah-small">{file.path}</span>
                        <span className="ah-small ah-muted">{fmtSize(file.size)}</span>
                        <span className="ah-grow" />
                        {file.link ? (
                          <span className="ah-skill-note">
                            <Icon name="link" size="sm" />
                            Link: not read
                          </span>
                        ) : file.too_large ? (
                          <span className="ah-skill-note">
                            <Icon name="file-x" size="sm" />
                            Too large to show
                          </span>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={isOpen ? "chevron-up" : "chevron-down"}
                            aria-expanded={isOpen}
                            aria-controls={isOpen ? panelId : undefined}
                            aria-label={`${isOpen ? "Hide" : "View"} ${file.path}`}
                            onClick={() => {
                              setOpen(isOpen ? null : file.id);
                            }}
                          >
                            {isOpen ? "Hide" : "View"}
                          </Button>
                        )}
                      </div>
                      {isOpen && (
                        <div id={panelId} className="ah-skill-file-text">
                          <FileText project={project} item={item} file={file} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
    </section>
  );
}

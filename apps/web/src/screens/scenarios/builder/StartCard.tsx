import { Button, Icon, type IconName } from "../../../components";
import type { BuilderDocument } from "./model";
import { blockItem } from "./palette";
import type { Item } from "./program";
import { freshKey } from "./program";

/* An empty scenario's start: describe it to Claude (the main way), or start from a shape and fill
 * its blocks. Each template is only blocks with empty slots: nothing is assumed about the system. */

interface Template {
  key: string;
  label: string;
  hint: string;
  icon: IconName;
  make: (taken: BuilderDocument) => Item[];
}

const TEMPLATES: readonly Template[] = [
  {
    key: "send-wait",
    label: "Do something, then wait for a state",
    hint: "run an action · wait until …",
    icon: "timer",
    make: (taken) => {
      const run = blockItem(taken, "action");
      const after = run.kind === "block" ? { ...taken, nodes: [run.node] } : taken;
      return [run, blockItem(after, "expect")];
    },
  },
  {
    key: "manual-check",
    label: "A step by hand, then a check",
    hint: "ask me to … · wait until …",
    icon: "stamp",
    make: (taken) => {
      const step = blockItem(taken, "approval");
      const after = step.kind === "block" ? { ...taken, nodes: [step.node] } : taken;
      return [step, blockItem(after, "expect")];
    },
  },
  {
    key: "branch",
    label: "Decide on a result",
    hint: "wait until … · if … else",
    icon: "split",
    make: (taken) => [
      blockItem(taken, "expect"),
      { kind: "if", key: freshKey("if"), condition: "", then: [], otherwise: [] },
    ],
  },
  {
    key: "poll",
    label: "Repeat until done",
    hint: "repeat until … with an action inside",
    icon: "refresh-cw",
    make: (taken) => {
      const loop = blockItem(taken, "loop_group");
      const inner = blockItem(
        { ...taken, nodes: loop.kind === "repeat" ? [loop.node] : [] },
        "action",
      );
      return loop.kind === "repeat" ? [{ ...loop, body: [inner] }] : [loop];
    },
  },
];

export function StartCard({
  onDescribe,
  onTemplate,
  taken,
}: {
  onDescribe: () => void;
  onTemplate: (items: Item[]) => void;
  taken: BuilderDocument;
}) {
  return (
    <section className="sb-start-card" aria-label="Start the scenario">
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Start this scenario
      </h2>
      <Button variant="primary" icon="message-square" onClick={onDescribe}>
        Describe it to Claude
      </Button>
      <span className="ah-small ah-muted">
        Say what it does in your own words; Claude turns it into blocks you review before anything
        changes.
      </span>
      <span className="ah-overline">Or start from a shape</span>
      <div className="sb-start-grid">
        {TEMPLATES.map((template) => (
          <button
            key={template.key}
            type="button"
            className="sb-start-tile"
            onClick={() => {
              onTemplate(template.make(taken));
            }}
          >
            <Icon name={template.icon} size="sm" />
            <span className="ah-stack" style={{ gap: 0 }}>
              <b>{template.label}</b>
              <span className="ah-small ah-muted">{template.hint}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

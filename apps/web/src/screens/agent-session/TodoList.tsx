import { Icon, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import type { TodoView } from "./model";

const LOOK: Record<string, { icon: IconName; text: string }> = {
  completed: { icon: "circle-check", text: "done" },
  in_progress: { icon: "circle-dot", text: "in progress" },
  pending: { icon: "circle-dashed", text: "to do" },
};

export interface TodoListProps {
  items: readonly TodoView[];
}

/**
 * Claude's todo list (`TodoWrite`) as a live checklist, collapsed to its count in the chat header
 * (AC-234.16); nothing while it is empty.
 */
export function TodoList({ items }: TodoListProps) {
  if (items.length === 0) return null;
  const done = items.filter((item) => item.status === "completed").length;
  return (
    <section className="as-todos" aria-label="Todo list">
      <details>
        <summary className="as-todos-head ah-small">
          <Icon name="list-todo" size="sm" />
          <b>Todos</b>
          <span className="ah-muted ah-num">
            {done} of {items.length} done
          </span>
        </summary>
        <ul>
          {items.map((item, i) => {
            const look = LOOK[item.status] ?? { icon: "circle-dashed", text: item.status };
            const text =
              item.status === "in_progress" && item.activeForm ? item.activeForm : item.content;
            return (
              <li key={i} className={cx("as-todo", `as-todo-${item.status}`)}>
                <Icon name={look.icon} size="sm" />
                <span>{text}</span>
                <span className="ah-sr"> ({look.text})</span>
              </li>
            );
          })}
        </ul>
      </details>
    </section>
  );
}

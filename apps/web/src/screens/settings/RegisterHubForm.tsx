import { useId, useState } from "react";
import type { FormEvent } from "react";

import { Button, Icon } from "../../components";
import { useRegisterHub } from "./queries";

export interface RegisterHubFormProps {
  /** "Hub path" (Welcome) or the Settings helper line. */
  label: string;
  helper?: string | undefined;
  placeholder?: string | undefined;
  primary?: boolean | undefined;
}

/**
 * Registers a hub by its path (`POST /hubs`, spec 22 step 1 and Settings › Hubs). A refused path
 * keeps its value and shows the problem under the input.
 */
export function RegisterHubForm({ label, helper, placeholder, primary }: RegisterHubFormProps) {
  const [path, setPath] = useState("");
  const register = useRegisterHub();
  const inputId = useId();
  const messageId = useId();
  const problem = register.error;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = path.trim();
    if (value === "") return;
    register.mutate(value, {
      onSuccess: () => {
        setPath("");
      },
    });
  };
  return (
    <form className="ah-stack" style={{ gap: 4 }} onSubmit={submit}>
      <label htmlFor={inputId} style={{ fontWeight: 500 }}>
        {label}
      </label>
      <span className="ah-row" style={{ gap: 8, maxWidth: 640 }}>
        <input
          id={inputId}
          className="ah-input ah-mono ah-grow"
          placeholder={placeholder}
          value={path}
          aria-invalid={problem ? true : undefined}
          aria-describedby={messageId}
          style={problem ? { borderColor: "var(--failed)" } : undefined}
          onChange={(event) => {
            setPath(event.target.value);
            if (register.isError) register.reset();
          }}
        />
        <Button
          type="submit"
          variant={primary ? "primary" : "default"}
          disabled={register.isPending || path.trim() === ""}
        >
          {register.isPending ? "Registering…" : "Register hub"}
        </Button>
      </span>
      <span id={messageId} className="ah-small" role={problem ? "alert" : undefined}>
        {problem ? (
          <span style={{ color: "var(--failed)" }}>
            <Icon name="circle-x" size="sm" style={{ verticalAlign: "-3px", marginRight: 4 }} />
            {problem.detail ?? problem.title}
          </span>
        ) : (
          helper && <span className="ah-muted">{helper}</span>
        )}
      </span>
    </form>
  );
}

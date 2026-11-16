/** Joins the truthy class names: `cx("a", flag && "b")`. */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

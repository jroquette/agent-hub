import { AppLink, Icon } from "../../components";

/** Where a feature's panel is. */
export const featureHref = (f: { project: string; slug: string }) =>
  `/features/${encodeURIComponent(f.project)}/${encodeURIComponent(f.slug)}`;

export interface FeatureChipProps {
  project: string;
  slug: string;
}

/** The feature a session works on, as a label that opens the feature's panel. */
export function FeatureChip({ project, slug }: FeatureChipProps) {
  return (
    <AppLink
      href={featureHref({ project, slug })}
      className="ah-chip ah-feature-chip"
      title={`Feature ${slug}: open its panel`}
      onClick={(event) => {
        // Inside a row that opens the session, the chip opens the feature instead.
        event.stopPropagation();
      }}
    >
      <Icon name="list-checks" />
      <span className="ah-feature-chip-slug">{slug}</span>
    </AppLink>
  );
}

import { AppLink, Icon } from "../../components";

/** Where a feature's panel is. */
export const featureHref = (f: { project: string; slug: string }) =>
  `/features/${encodeURIComponent(f.project)}/${encodeURIComponent(f.slug)}`;

export interface FeatureChipProps {
  project: string;
  slug: string;
}

/** What the label says on hover: the slug is fixed, a rename changes only the name. */
const labelTitle = (slug: string) =>
  `Feature label ${slug}: set when the feature was created, unique and never changes. A rename changes only its name.`;

/** The feature's label (its slug) on the feature's own page: the same chip, without a link. */
export function FeatureLabel({ slug }: { slug: string }) {
  return (
    <span
      className="ah-chip ah-feature-chip ah-feature-label"
      title={labelTitle(slug)}
      aria-label={`Feature label ${slug}`}
    >
      <Icon name="tag" />
      <span className="ah-feature-chip-slug">{slug}</span>
    </span>
  );
}

/** The feature something belongs to, as its label; it opens the feature's panel. */
export function FeatureChip({ project, slug }: FeatureChipProps) {
  return (
    <AppLink
      href={featureHref({ project, slug })}
      className="ah-chip ah-feature-chip"
      title={`${labelTitle(slug)} Open its panel.`}
      onClick={(event) => {
        // Inside a row that opens the session, the chip opens the feature instead.
        event.stopPropagation();
      }}
    >
      <Icon name="tag" />
      <span className="ah-feature-chip-slug">{slug}</span>
    </AppLink>
  );
}

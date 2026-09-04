import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "./Icon";

/**
 * The block every screen opens with: an optional back link, the <h1>, an
 * optional line of explanation, and the screen's controls on the right.
 *
 * A copy of the Staff Console's component of the same name, kept in step by
 * hand -- the two apps are separate Vite builds with no shared package, the
 * same arrangement `api/types.ts` and `theme.ts` already live with. The
 * styling is in .page-header, which is the same CSS in both.
 */
export function PageHeader({
  title,
  description,
  actions,
  back,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Renders "← Back to <label>" above the title. */
  back?: { to: string; label: string };
  /** Sits on the title's baseline -- a status badge, typically. */
  meta?: ReactNode;
}) {
  return (
    <>
      {back && (
        <Link to={back.to} className="backlink">
          <Icon name="arrowLeft" size={15} />
          Back to {back.label}
        </Link>
      )}
      <div className="page-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h1>{title}</h1>
            {meta}
          </div>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </>
  );
}

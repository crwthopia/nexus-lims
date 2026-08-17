import type { SampleStatus } from "../api/types";
import { SAMPLE_STATUS_LABELS } from "../api/types";

/**
 * Sample status colours, as CSS custom properties rather than literals.
 *
 * These were the only hardcoded colours left in the Staff Console, which made
 * them the only thing the theme couldn't reach. Now each status maps to a
 * token pair defined in index.css, so a palette change lands here too.
 *
 * The mapping is deliberately not one-colour-per-status: statuses that mean
 * the same thing to a reviewer share a colour, so the worklist reads as four
 * groups (waiting / in progress / accepted / rejected) rather than eleven
 * unrelated hues. `disposed` is muted rather than red -- it's a terminal
 * bookkeeping state, not a failure.
 */
const STATUS_TOKENS: Record<SampleStatus, { bg: string; fg: string }> = {
  pre_registered: { bg: "--color-status-neutral-bg", fg: "--color-status-neutral" },
  registered: { bg: "--color-status-info-bg", fg: "--color-status-info" },
  received: { bg: "--color-status-info-bg", fg: "--color-status-info" },
  in_prep: { bg: "--color-warning-bg", fg: "--color-warning" },
  in_testing: { bg: "--color-warning-bg", fg: "--color-warning" },
  under_review: { bg: "--color-status-review-bg", fg: "--color-status-review" },
  approved: { bg: "--color-success-bg", fg: "--color-success" },
  rejected: { bg: "--color-danger-bg", fg: "--color-danger" },
  under_investigation: { bg: "--color-danger-bg", fg: "--color-danger" },
  retest_pending: { bg: "--color-warning-bg", fg: "--color-warning" },
  disposed: { bg: "--color-status-neutral-bg", fg: "--color-status-muted" },
};

export function StatusBadge({ status }: { status: SampleStatus }) {
  const tokens = STATUS_TOKENS[status];
  return (
    <span
      className="badge"
      style={{ background: `var(${tokens.bg})`, color: `var(${tokens.fg})` }}
    >
      {SAMPLE_STATUS_LABELS[status]}
    </span>
  );
}

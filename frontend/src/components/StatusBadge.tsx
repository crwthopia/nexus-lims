import type { SampleStatus } from "../api/types";
import { SAMPLE_STATUS_LABELS } from "../api/types";

const STATUS_COLORS: Record<SampleStatus, { bg: string; fg: string }> = {
  pre_registered: { bg: "#f2f4f7", fg: "#344054" },
  registered: { bg: "#eff4ff", fg: "#2454ff" },
  received: { bg: "#eff4ff", fg: "#2454ff" },
  in_prep: { bg: "#fffaeb", fg: "#b54708" },
  in_testing: { bg: "#fffaeb", fg: "#b54708" },
  under_review: { bg: "#f4f3ff", fg: "#5925dc" },
  approved: { bg: "#ecfdf3", fg: "#12793f" },
  rejected: { bg: "#fef3f2", fg: "#d92d20" },
  under_investigation: { bg: "#fef3f2", fg: "#d92d20" },
  retest_pending: { bg: "#fffaeb", fg: "#b54708" },
  disposed: { bg: "#f2f4f7", fg: "#667085" },
};

export function StatusBadge({ status }: { status: SampleStatus }) {
  const colors = STATUS_COLORS[status];
  return (
    <span className="badge" style={{ background: colors.bg, color: colors.fg }}>
      {SAMPLE_STATUS_LABELS[status]}
    </span>
  );
}

// Mirrors each backend app's serializers.py field-for-field. Keep in sync by hand -- no codegen yet.

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface CustomerMe {
  id: number;
  email: string;
  is_email_verified: boolean;
  mfa_enabled: boolean;
  organization_name: string | null;
  prc_license_number: string | null;
  created_at: string;
}

export type ServiceLine = "failure_analysis" | "water_environmental" | "training";

export type OrderStatus = "draft" | "submitted" | "in_progress" | "completed" | "cancelled";

export interface Order {
  id: number;
  customer: number;
  service_line: ServiceLine;
  status: OrderStatus;
  created_at: string;
}

export type SampleStatus =
  | "pre_registered"
  | "registered"
  | "received"
  | "in_prep"
  | "in_testing"
  | "under_review"
  | "approved"
  | "rejected"
  | "under_investigation"
  | "retest_pending"
  | "disposed";

export interface Sample {
  id: number;
  order: number | null;
  service_line: ServiceLine;
  unique_sample_code: string;
  client_reference: string;
  sampling_point: string;
  collection_datetime: string | null;
  container_type: string;
  container_count: number;
  preservation_method: string;
  retention_period: string;
  holding_time: string | null;
  status: SampleStatus;
  safety_flags: string[];
  created_at: string;
  updated_at: string;
}

export interface TrainingCourse {
  id: number;
  title: string;
  description: string;
  cpd_units: string;
  price: string;
  early_bird_discount_pct: string;
  student_discount_pct: string;
}

export type TrainingSessionStatus = "scheduled" | "pending_reschedule" | "in_progress" | "completed" | "cancelled";

export interface TrainingSession {
  id: number;
  course: number;
  course_title: string;
  start_date: string;
  end_date: string;
  capacity: number;
  min_capacity: number;
  cancellation_threshold_days: number;
  instructor: number | null;
  instructor_display_name: string | null;
  status: TrainingSessionStatus;
  confirmed_enrollment_count: number;
}

export type EnrollmentStatus = "confirmed" | "rescheduled" | "completed" | "cancelled";

export type EnrollmentPaymentStatus = "unpaid" | "partially_paid" | "paid";

export interface Enrollment {
  id: number;
  session: number;
  customer: number;
  payment_status: EnrollmentPaymentStatus;
  discount_applied: string;
  discount_override: string | null;
  certificate_issued: boolean;
  status: EnrollmentStatus;
  created_at: string;
}

export type CreditNoteStatus = "available" | "applied" | "expired";

export interface CreditNote {
  id: number;
  customer: number;
  source_enrollment: number;
  amount: string;
  status: CreditNoteStatus;
  applied_to_enrollment: number | null;
  created_at: string;
}

export type InvoiceStatus = "unpaid" | "partially_paid" | "paid" | "void";

export interface Invoice {
  id: number;
  order: number | null;
  enrollment: number | null;
  customer_email: string | null;
  amount: string;
  currency: string;
  status: InvoiceStatus;
  created_at: string;
}

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "Draft",
  submitted: "Submitted",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const SAMPLE_STATUS_LABELS: Record<SampleStatus, string> = {
  pre_registered: "Pre-registered",
  registered: "Registered",
  received: "Received",
  in_prep: "In Prep",
  in_testing: "In Testing",
  under_review: "Under Review",
  approved: "Approved",
  rejected: "Rejected",
  under_investigation: "Under Investigation",
  retest_pending: "Retest Pending",
  disposed: "Disposed",
};

export const TRAINING_SESSION_STATUS_LABELS: Record<TrainingSessionStatus, string> = {
  scheduled: "Scheduled",
  pending_reschedule: "Pending Reschedule",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const ENROLLMENT_STATUS_LABELS: Record<EnrollmentStatus, string> = {
  confirmed: "Confirmed",
  rescheduled: "Rescheduled",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  unpaid: "Unpaid",
  partially_paid: "Partially Paid",
  paid: "Paid",
  void: "Void",
};

export type ReportType =
  | "failure_analysis_coa"
  | "water_environmental_coa"
  | "training_cpd_certificate"
  | "custom";

export const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  failure_analysis_coa: "Certificate of Analysis — Failure Analysis",
  water_environmental_coa: "Certificate of Analysis — Water/Environmental",
  training_cpd_certificate: "CPD Certificate",
  custom: "Laboratory Report",
};

/**
 * The customer-facing shape of a report (GET /my/reports/). Narrower than the
 * Staff Console's: no file_id, no generated_by, no failure_reason -- the API
 * doesn't send them, deliberately. Only `ready` reports are ever returned, so
 * there is no status to branch on here.
 */
export interface MyReport {
  id: number;
  sample: number | null;
  sample_code: string | null;
  order: number | null;
  report_type: ReportType;
  status: "ready";
  generated_at: string;
  version: number;
}

export interface ReportDownload {
  url: string;
  expires_in: number;
}

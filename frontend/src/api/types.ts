// Mirrors each backend app's serializers.py field-for-field. Keep in sync by hand -- no codegen yet.

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type RoleName =
  | "customer"
  | "sample_receiver"
  | "analyst"
  | "reviewer"
  | "approver"
  | "qa_officer"
  | "lab_supervisor"
  | "instrument_custodian"
  | "training_coordinator"
  | "system_administrator";

export interface Role {
  id: number;
  name: RoleName;
  permission_set: Record<string, unknown>;
}

export interface StaffMe {
  id: number;
  display_name: string;
  email: string;
  roles: Role[];
  is_active: boolean;
  instrument_certifications: number[];
  prc_license_number: string | null;
  prc_license_validity_date: string | null;
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

export type ChainOfCustodyEventType = "receipt" | "transfer" | "aliquot" | "disposal";

export interface ChainOfCustodyEvent {
  id: number;
  sample: number;
  from_holder: number | null;
  to_holder: number | null;
  from_location: string;
  to_location: string;
  timestamp: string;
  event_type: ChainOfCustodyEventType;
}

export interface SampleDetail extends Sample {
  chain_of_custody_events: ChainOfCustodyEvent[];
}

export type ReviewActionType = "reviewed" | "flagged" | "returned";

export interface ReviewAction {
  id: number;
  test_result: number | null;
  sample: number | null;
  reviewer: number;
  reviewer_display_name: string;
  action: ReviewActionType;
  comments: string;
  e_signature: number | null;
  created_at: string;
}

export type ApprovalDisposition = "approved" | "rejected";

export interface ApprovalAction {
  id: number;
  sample: number;
  approver: number;
  approver_display_name: string;
  disposition: ApprovalDisposition;
  e_signature: number | null;
  created_at: string;
}

export type DocumentType = "sop" | "manual" | "form" | "training_material" | "uploaded_supporting_file";

export interface Document {
  id: number;
  title: string;
  type: DocumentType;
  current_version: number | null;
  current_version_number: number | null;
  created_at: string;
}

export interface DocumentVersion {
  id: number;
  document: number;
  version_number: number;
  file_id: string;
  approved_by: number | null;
  approved_by_display_name: string | null;
  effective_date: string | null;
  is_current: boolean;
  created_at: string;
}

export interface DocumentDetail extends Document {
  versions: DocumentVersion[];
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  sop: "SOP",
  manual: "Manual",
  form: "Form",
  training_material: "Training Material",
  uploaded_supporting_file: "Uploaded Supporting File",
};

/** DOCUMENT_WRITE_ROLES (backend/apps/documents/views.py) -- keep in sync by hand. */
export const DOCUMENT_WRITE_ROLES: RoleName[] = ["qa_officer", "lab_supervisor"];

export type InvestigationType = "oos" | "oot";

export type InvestigationStatus = "open" | "root_cause_identified" | "capa_in_progress" | "closed";

export interface Investigation {
  id: number;
  related_test_result: number | null;
  related_sample: number | null;
  related_sample_code: string | null;
  type: InvestigationType;
  opened_by: number;
  opened_by_display_name: string;
  root_cause: string;
  capa_actions: string;
  status: InvestigationStatus;
  opened_at: string;
  closed_at: string | null;
}

export const INVESTIGATION_TYPE_LABELS: Record<InvestigationType, string> = {
  oos: "Out of Specification",
  oot: "Out of Trend",
};

export const INVESTIGATION_STATUS_LABELS: Record<InvestigationStatus, string> = {
  open: "Open",
  root_cause_identified: "Root Cause Identified",
  capa_in_progress: "CAPA In Progress",
  closed: "Closed",
};

/** INVESTIGATION_WRITE_ROLES (backend/apps/investigations/views.py) -- keep in sync by hand. */
export const INVESTIGATION_WRITE_ROLES: RoleName[] = ["qa_officer", "lab_supervisor"];

export interface TestMethod {
  id: number;
  name: string;
  method_reference: string;
  specification_limits: { min?: number; max?: number };
  holding_time: string | null;
  active_sop_version: number | null;
}

export type TestRequestStatus =
  | "assigned"
  | "in_progress"
  | "awaiting_review"
  | "under_investigation"
  | "retest_pending"
  | "completed";

export interface TestRequest {
  id: number;
  sample: number;
  sample_code: string;
  test_method: number;
  test_method_name: string;
  status: TestRequestStatus;
  assigned_analyst: number | null;
  assigned_analyst_display_name: string | null;
  assigned_instrument: number | null;
  created_at: string;
}

export type TestResultDataType = "float" | "int" | "text" | "date" | "list" | "file" | "calculated" | "boolean" | "interval";

export interface TestResult {
  id: number;
  test_request: number;
  /** Which parameter this measurement is of. Blank for single-parameter methods. */
  analyte: string;
  data_type: TestResultDataType;
  value: string;
  unit: string;
  entered_by: number;
  entered_by_display_name: string | null;
  entered_at: string;
  is_out_of_spec: boolean;
  instrument: number | null;
  standard_reagents: number[];
  raw_file_id: string | null;
  raw_file_checksum_sha256: string | null;
}

export type InstrumentStatus = "in_service" | "out_of_calibration" | "retired";

export type InstrumentModel =
  | "fesem"
  | "sem"
  | "edx"
  | "afm"
  | "ir_obirch"
  | "tga"
  | "xrf"
  | "ebsd"
  | "thermal_emission_microscope"
  | "dsc"
  | "other";

export interface Instrument {
  id: number;
  name: string;
  model: InstrumentModel;
  parent_instrument: number | null;
  calibration_due_date: string | null;
  status: InstrumentStatus;
  custodian: number | null;
  custodian_display_name: string | null;
}

export interface InstrumentDetail extends Instrument {
  child_instruments: Instrument[];
}

export interface CalibrationRecord {
  id: number;
  instrument: number;
  instrument_name: string;
  performed_by: number;
  performed_by_display_name: string | null;
  performed_at: string;
  result: string;
  next_due_date: string;
}

export type StandardReagentStatus = "active" | "retired";

export interface StandardReagent {
  id: number;
  name: string;
  lot_number: string;
  crm_traceability_reference: string;
  opened_date: string | null;
  expiry_date: string;
  status: StandardReagentStatus;
  storage_location: string;
}

export const INSTRUMENT_MODEL_LABELS: Record<InstrumentModel, string> = {
  fesem: "FESEM",
  sem: "SEM",
  edx: "EDX",
  afm: "AFM",
  ir_obirch: "IR-OBIRCH",
  tga: "TGA",
  xrf: "XRF",
  ebsd: "EBSD",
  thermal_emission_microscope: "Thermal Emission Microscope",
  dsc: "DSC",
  other: "Other",
};

export const INSTRUMENT_STATUS_LABELS: Record<InstrumentStatus, string> = {
  in_service: "In Service",
  out_of_calibration: "Out of Calibration",
  retired: "Retired",
};

/** EQUIPMENT_WRITE_ROLES (backend/apps/equipment/views.py) -- keep in sync by hand. */
export const EQUIPMENT_WRITE_ROLES: RoleName[] = ["instrument_custodian", "lab_supervisor"];

/** TestRequestViewSet._ROLE_MAP (backend/apps/testing/views.py) -- keep in sync by hand. */
export const TEST_REQUEST_ACTION_ROLES: Record<string, RoleName[]> = {
  start: ["analyst"],
  "submit-for-review": ["analyst"],
  "flag-nonconforming": ["reviewer", "qa_officer"],
  "authorize-retest": ["qa_officer", "lab_supervisor"],
  "resume-testing": ["analyst"],
  complete: ["reviewer", "approver", "qa_officer", "lab_supervisor"],
};

/** TestRequest.Status FSM edges (backend/apps/testing/models.py) -- which action(s) are legal from each status. */
export const TEST_REQUEST_ACTIONS_BY_STATUS: Record<TestRequestStatus, string[]> = {
  assigned: ["start"],
  in_progress: ["submit-for-review"],
  awaiting_review: ["flag-nonconforming", "complete"],
  under_investigation: ["authorize-retest"],
  retest_pending: ["resume-testing"],
  completed: [],
};

export const TEST_REQUEST_STATUS_LABELS: Record<TestRequestStatus, string> = {
  assigned: "Assigned",
  in_progress: "In Progress",
  awaiting_review: "Awaiting Review",
  under_investigation: "Under Investigation",
  retest_pending: "Retest Pending",
  completed: "Completed",
};

/** SampleViewSet._ROLE_MAP (backend/apps/samples/views.py) -- keep in sync by hand. */
export const SAMPLE_ACTION_ROLES: Record<string, RoleName[]> = {
  register: ["sample_receiver"],
  receive: ["sample_receiver"],
  "start-prep": ["analyst"],
  "start-testing": ["analyst"],
  "submit-for-review": ["analyst"],
  review: ["reviewer"],
  approve: ["approver"],
  reject: ["approver"],
  "authorize-retest": ["qa_officer", "lab_supervisor"],
  dispose: ["qa_officer", "lab_supervisor"],
  "requeue-for-retest": ["analyst", "qa_officer", "lab_supervisor"],
};

/** Sample.Status FSM edges (backend/apps/samples/models.py) -- which action(s) are legal from each status. */
export const SAMPLE_ACTIONS_BY_STATUS: Record<SampleStatus, string[]> = {
  pre_registered: ["register"],
  registered: ["receive"],
  received: ["start-prep"],
  in_prep: ["start-testing"],
  in_testing: ["submit-for-review"],
  under_review: ["review", "approve", "reject"],
  approved: [],
  rejected: [],
  under_investigation: ["authorize-retest", "dispose"],
  retest_pending: ["requeue-for-retest"],
  disposed: [],
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
  customer_email: string;
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

export const TRAINING_SESSION_STATUS_LABELS: Record<TrainingSessionStatus, string> = {
  scheduled: "Scheduled",
  pending_reschedule: "Pending Reschedule",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** TrainingSession.Status FSM edges (backend/apps/training/models.py) -- which action(s) are legal from each status. */
export const TRAINING_SESSION_ACTIONS_BY_STATUS: Record<TrainingSessionStatus, string[]> = {
  scheduled: ["start-session", "cancel-session"],
  pending_reschedule: ["cancel-session"],
  in_progress: ["complete-session"],
  completed: [],
  cancelled: [],
};

export const ENROLLMENT_STATUS_LABELS: Record<EnrollmentStatus, string> = {
  confirmed: "Confirmed",
  rescheduled: "Rescheduled",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** TRAINING_WRITE_ROLES (backend/apps/training/views.py) -- keep in sync by hand. */
export const TRAINING_WRITE_ROLES: RoleName[] = ["training_coordinator", "lab_supervisor", "system_administrator"];

export type InvoiceStatus = "unpaid" | "partially_paid" | "paid" | "void";

export interface Invoice {
  id: number;
  order: number | null;
  enrollment: number | null;
  customer_email: string | null;
  /** What is owed: the gross. Derived from the lines when there are any. */
  amount: string;
  currency: string;
  status: InvoiceStatus;
  /** Null on an invoice with no lines — a typed figure has no VAT split to report. */
  net_total: string | null;
  vat_total: string | null;
  line_count: number;
  created_at: string;
}

export type PaymentMethod = "cash" | "bank_transfer" | "purchase_order" | "gateway";

export type PaymentStatus = "pending_confirmation" | "confirmed" | "reversed";

export interface Payment {
  id: number;
  invoice: number;
  method: PaymentMethod;
  reference_number: string | null;
  recorded_by: number;
  recorded_by_display_name: string;
  status: PaymentStatus;
  paid_at: string | null;
  notes: string;
}

export interface InvoiceDetail extends Invoice {
  payments: Payment[];
  lines: InvoiceLine[];
}

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  unpaid: "Unpaid",
  partially_paid: "Partially Paid",
  paid: "Paid",
  void: "Void",
};

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: "Cash",
  bank_transfer: "Bank Transfer",
  purchase_order: "Purchase Order",
  gateway: "Payment Gateway",
};

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  pending_confirmation: "Pending Confirmation",
  confirmed: "Confirmed",
  reversed: "Reversed",
};

/** BILLING_WRITE_ROLES (backend/apps/billing/views.py) -- keep in sync by hand. */
export const BILLING_WRITE_ROLES: RoleName[] = ["training_coordinator", "lab_supervisor", "system_administrator"];

// --- Reports (backend/apps/reporting) --------------------------------------

/** Report.Status -- generation-job state, moved by the Celery task, not by staff. */
export type ReportStatus = "pending" | "generating" | "ready" | "failed";

export type ReportType =
  | "failure_analysis_coa"
  | "water_environmental_coa"
  | "training_cpd_certificate"
  | "custom";

export interface Report {
  id: number;
  sample: number | null;
  sample_code: string | null;
  order: number | null;
  report_type: ReportType;
  file_id: string;
  status: ReportStatus;
  failure_reason: string;
  generated_at: string;
  generated_by: number;
  generated_by_display_name: string;
  version: number;
}

export interface ReportDownload {
  url: string;
  expires_in: number;
}

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  pending: "Pending",
  generating: "Generating",
  ready: "Ready",
  failed: "Failed",
};

export const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  failure_analysis_coa: "Failure Analysis COA",
  water_environmental_coa: "Water/Environmental COA",
  training_cpd_certificate: "Training CPD Certificate",
  custom: "Custom",
};

/**
 * Which report types a staff user may generate against a Sample. Training
 * certificates hang off an Order, not a Sample, so they aren't offered from
 * the sample screen.
 */
export const SAMPLE_REPORT_TYPES: ReportType[] = [
  "failure_analysis_coa",
  "water_environmental_coa",
  "custom",
];

/**
 * The ISO/IEC 17025:2017 7.11.3(e) system failure register
 * (backend/apps/audit/models.py SystemFailure).
 *
 * `immediate_action` is what the system did by itself at the moment of
 * failure; `corrective_action` is what a person did so it stops happening.
 * The API refuses to close a failure while the second is empty.
 */
export type SystemFailureComponent =
  | "report_generation"
  | "retention_sweep"
  | "object_storage"
  | "database"
  | "task_broker"
  | "scheduled_task"
  | "api_request";

export type SystemFailureSeverity = "degraded" | "failed";
export type SystemFailureStatus = "open" | "acknowledged" | "closed";

export interface SystemFailure {
  id: number;
  component: SystemFailureComponent;
  component_display: string;
  severity: SystemFailureSeverity;
  summary: string;
  detail: string;
  immediate_action: string;
  immediate_action_display: string;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  status: SystemFailureStatus;
  acknowledged_by: number | null;
  acknowledged_by_display_name: string | null;
  acknowledged_at: string | null;
  corrective_action: string;
  investigation: number | null;
  closed_by: number | null;
  closed_by_display_name: string | null;
  closed_at: string | null;
}

export const SYSTEM_FAILURE_STATUS_LABELS: Record<SystemFailureStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  closed: "Closed",
};

export const SYSTEM_FAILURE_SEVERITY_LABELS: Record<SystemFailureSeverity, string> = {
  degraded: "Degraded",
  failed: "Failed",
};

/** FAILURE_WRITE_ROLES (backend/apps/audit/views.py) -- keep in sync by hand. */
export const SYSTEM_FAILURE_WRITE_ROLES: RoleName[] = ["qa_officer", "lab_supervisor"];

// --- Service catalogue (backend/apps/catalogue) ---------------------------

export type VatTreatment = "exclusive" | "inclusive";

export const SERVICE_LINE_LABELS: Record<ServiceLine, string> = {
  failure_analysis: "Failure Analysis",
  water_environmental: "Water / Environmental",
  training: "Training",
};

export const VAT_TREATMENT_LABELS: Record<VatTreatment, string> = {
  exclusive: "VAT-exclusive (net)",
  inclusive: "VAT-inclusive (gross)",
};

/**
 * A price as published, plus the three figures derived from it. The server
 * computes net/VAT/gross precisely so no screen has to know which way this
 * particular rate was quoted -- see backend/apps/catalogue/models.py.
 */
export interface OfferingPrice {
  id: number;
  offering: number;
  amount: string;
  currency: string;
  vat_treatment: VatTreatment;
  vat_rate_pct: string;
  effective_from: string;
  effective_to: string | null;
  note: string;
  net_amount: string;
  vat_amount: string;
  gross_amount: string;
  is_current: boolean;
  created_at: string;
  created_by: number | null;
  created_by_display_name: string | null;
}

export interface ServiceOffering {
  id: number;
  code: string;
  name: string;
  description: string;
  service_line: ServiceLine;
  test_methods: number[];
  test_method_names: string[];
  turnaround_days: number | null;
  is_accredited: boolean;
  is_active: boolean;
  /** Null for an offering that has never been priced, or is priced from a future date. */
  current_price: OfferingPrice | null;
  created_at: string;
  updated_at: string;
}

export interface ServiceOfferingDetail extends ServiceOffering {
  prices: OfferingPrice[];
}

/** CATALOGUE_WRITE_ROLES (backend/apps/catalogue/views.py) -- keep in sync by hand. */
export const CATALOGUE_WRITE_ROLES: RoleName[] = ["lab_supervisor", "system_administrator"];

/**
 * Training is priced by its own course catalogue, so it is not offered
 * here -- the server refuses it with a check constraint as well as a
 * validator (backend/apps/catalogue/models.py).
 */
export const CATALOGUE_SERVICE_LINES: ServiceLine[] = ["failure_analysis", "water_environmental"];

// --- Order and invoice lines ---------------------------------------------

/**
 * A line of what was ordered. Every price field is a **snapshot** taken
 * when the line was created, not a live read of the rate card — repricing
 * the catalogue must never reprice a sold line. The server owns them; a
 * client can send only the offering, quantity and discount.
 */
export interface OrderItem {
  id: number;
  order: number;
  offering: number;
  offering_code: string;
  offering_name: string;
  quantity: number;
  discount_pct: string;
  unit_amount: string;
  currency: string;
  vat_treatment: VatTreatment;
  vat_rate_pct: string;
  source_price: number | null;
  line_amount: string;
  net_amount: string;
  vat_amount: string;
  gross_amount: string;
  is_invoiced: boolean;
  created_at: string;
}

/** The order's own lines — see the existing `Order` above for the record itself. */
export interface OrderDetail extends Order {
  item_count: number;
  items: OrderItem[];
}

/** A billed line, snapshotted again away from the order line it came from. */
export interface InvoiceLine {
  id: number;
  invoice: number;
  order_item: number | null;
  description: string;
  quantity: number;
  unit_amount: string;
  currency: string;
  vat_treatment: VatTreatment;
  vat_rate_pct: string;
  discount_pct: string;
  line_amount: string;
  net_amount: string;
  vat_amount: string;
  gross_amount: string;
  created_at: string;
}

/** ORDER_ITEM_WRITE_ROLES (backend/apps/samples/views.py) — keep in sync by hand. */
export const ORDER_ITEM_WRITE_ROLES: RoleName[] = ["sample_receiver", "lab_supervisor", "system_administrator"];

// --- Dashboard analytics (backend/apps/analytics) -------------------------

export interface LeadingAnalysis {
  offering_id: number;
  code: string;
  name: string;
  service_line: ServiceLine;
  request_count: number;
  list_value_net: string;
  /** What invoice lines naming this offering actually billed, net of VAT. Exact, where the two figures above are inferred. */
  billed_net: string;
}

/**
 * Requests that could not be credited to one line of the rate card. Reported
 * rather than dropped or spread: the count is the honest measure of how much
 * catalogue mapping is still outstanding.
 */
export interface UnattributedRequests {
  /** The method belongs to no active offering. */
  no_offering: number;
  /** It belongs to several — sold standalone and inside a panel, say. */
  ambiguous: number;
  /** Attributable, but the offering had no price on the day of the request. */
  unpriced: number;
}

export interface TurnaroundSummary {
  sample_count: number;
  median_days: number | null;
  p90_days: number | null;
}

export interface DashboardData {
  /** Which measure ordered `leading_analyses` — and therefore which one the fold into "other" was computed against. */
  rank: "volume" | "value";
  window: { from: string; to: string; days: number; previous_from: string; previous_to: string };
  totals: {
    samples_received: number;
    test_requests: number;
    list_value_net: string;
    billed_net: string;
    invoice_lines: number;
    currency: string;
  };
  previous_totals: { samples_received: number; test_requests: number; list_value_net: string; billed_net: string };
  leading_analyses: LeadingAnalysis[];
  leading_analyses_other: { offering_count: number; request_count: number; list_value_net: string; billed_net: string };
  unattributed_requests: UnattributedRequests;
  service_line_mix: { service_line: ServiceLine; label: string; sample_count: number }[];
  monthly: { month: string; request_count: number; list_value_net: string }[];
  turnaround: TurnaroundSummary & { by_service_line: (TurnaroundSummary & { service_line: ServiceLine })[] };
  quality: {
    results_entered: number;
    out_of_spec: number;
    out_of_spec_pct: number | null;
    open_investigations: number;
    samples_awaiting_review: number;
    instruments_out_of_calibration: number;
    open_system_failures: number;
  };
}

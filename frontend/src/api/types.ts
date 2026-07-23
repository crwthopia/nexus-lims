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

export interface Instrument {
  id: number;
  name: string;
  model: string;
  parent_instrument: number | null;
  calibration_due_date: string | null;
  status: InstrumentStatus;
  custodian: number | null;
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

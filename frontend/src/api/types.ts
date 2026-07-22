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

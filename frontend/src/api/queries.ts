import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "./client";
import type {
  ApprovalAction,
  CalibrationRecord,
  CreditNote,
  DashboardData,
  Document,
  DocumentDetail,
  DocumentVersion,
  Enrollment,
  Instrument,
  InstrumentDetail,
  Invoice,
  InvoiceDetail,
  Investigation,
  Paginated,
  Payment,
  Report,
  ReportDownload,
  ReportType,
  ReviewAction,
  Sample,
  SampleDetail,
  ServiceOffering,
  ServiceOfferingDetail,
  StandardReagent,
  TestMethod,
  TestRequest,
  TestResult,
  TrainingCourse,
  TrainingSession,
  SystemFailure,
} from "./types";

export function useSamples(params: { status?: string; service_line?: string } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.service_line) query.set("service_line", params.service_line);
  const qs = query.toString();

  return useQuery({
    queryKey: ["samples", params],
    queryFn: () => apiGet<Paginated<Sample>>(`/samples/${qs ? `?${qs}` : ""}`),
  });
}

export function useSample(id: number) {
  return useQuery({
    queryKey: ["samples", id],
    queryFn: () => apiGet<SampleDetail>(`/samples/${id}/`),
  });
}

/** GET /review-actions/?sample= and /approval-actions/?sample= (apps/review/views.py) -- the review/approval history for one sample. */
export function useSampleReviewHistory(sampleId: number) {
  const reviewActions = useQuery({
    queryKey: ["review-actions", sampleId],
    queryFn: () => apiGet<Paginated<ReviewAction>>(`/review-actions/?sample=${sampleId}`),
  });
  const approvalActions = useQuery({
    queryKey: ["approval-actions", sampleId],
    queryFn: () => apiGet<Paginated<ApprovalAction>>(`/approval-actions/?sample=${sampleId}`),
  });

  return {
    reviewActions: reviewActions.data?.results ?? [],
    approvalActions: approvalActions.data?.results ?? [],
    isLoading: reviewActions.isLoading || approvalActions.isLoading,
  };
}

/**
 * One mutation for every Sample FSM action (register/receive/.../dispose):
 * they all share the same shape (POST /samples/{id}/{action}/, no body
 * except review/approve/reject which take optional fields the caller
 * passes through) and the same invalidation need, so one hook covers all
 * of them rather than duplicating a useMutation per action.
 */
export function useSampleAction(sampleId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ action, body }: { action: string; body?: Record<string, unknown> }) =>
      apiPost(`/samples/${sampleId}/${action}/`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["samples", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["samples"] });
      queryClient.invalidateQueries({ queryKey: ["review-actions", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["approval-actions", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["test-requests", "for-sample", sampleId] });
    },
  });
}

export function useTestRequestsForSample(sampleId: number) {
  return useQuery({
    queryKey: ["test-requests", "for-sample", sampleId],
    queryFn: () => apiGet<Paginated<TestRequest>>(`/test-requests/?sample=${sampleId}`),
  });
}

/** ?status=assigned,in_progress etc. -- see TestRequestViewSet.get_queryset (apps/testing/views.py). */
export function useTestRequestQueue(statuses: string[]) {
  return useQuery({
    queryKey: ["test-requests", "queue", statuses],
    queryFn: () => apiGet<Paginated<TestRequest>>(`/test-requests/?status=${statuses.join(",")}`),
  });
}

export function useTestRequest(id: number) {
  return useQuery({
    queryKey: ["test-requests", id],
    queryFn: () => apiGet<TestRequest>(`/test-requests/${id}/`),
  });
}

export function useTestMethod(id: number | undefined) {
  return useQuery({
    queryKey: ["test-methods", id],
    queryFn: () => apiGet<TestMethod>(`/test-methods/${id}/`),
    enabled: id !== undefined,
  });
}

export function useTestResults(testRequestId: number) {
  return useQuery({
    queryKey: ["test-results", testRequestId],
    queryFn: () => apiGet<TestResult[]>(`/test-requests/${testRequestId}/results/`),
  });
}

/** One mutation for every TestRequest FSM action (start/submit-for-review/.../complete) -- same reasoning as useSampleAction. */
export function useTestRequestAction(testRequestId: number, sampleId?: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (action: string) => apiPost(`/test-requests/${testRequestId}/${action}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test-requests", testRequestId] });
      queryClient.invalidateQueries({ queryKey: ["test-requests", "queue"] });
      if (sampleId) queryClient.invalidateQueries({ queryKey: ["test-requests", "for-sample", sampleId] });
    },
  });
}

export function useCreateTestResult(testRequestId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: Record<string, unknown>) => apiPost<TestResult>(`/test-requests/${testRequestId}/results/`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test-results", testRequestId] });
    },
  });
}

export function useInstruments(params: { status?: string } = {}) {
  const qs = params.status ? `?status=${params.status}` : "";
  return useQuery({
    queryKey: ["instruments", params],
    queryFn: () => apiGet<Paginated<Instrument>>(`/instruments/${qs}`),
  });
}

export function useInstrument(id: number) {
  return useQuery({
    queryKey: ["instruments", id],
    queryFn: () => apiGet<InstrumentDetail>(`/instruments/${id}/`),
  });
}

export function useCreateInstrument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; model: string; parent_instrument?: number | null }) =>
      apiPost<Instrument>("/instruments/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
}

export function useCalibrationRecordsForInstrument(instrumentId: number) {
  return useQuery({
    queryKey: ["calibration-records", instrumentId],
    queryFn: () => apiGet<Paginated<CalibrationRecord>>(`/calibration-records/?instrument=${instrumentId}`),
  });
}

export function useCreateCalibrationRecord(instrumentId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { performed_at: string; result: string; next_due_date: string }) =>
      apiPost<CalibrationRecord>("/calibration-records/", { ...data, instrument: instrumentId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calibration-records", instrumentId] });
      queryClient.invalidateQueries({ queryKey: ["instruments", instrumentId] });
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });
}

export function useCreateStandardReagent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { name: string; lot_number: string; crm_traceability_reference: string; expiry_date: string }) =>
      apiPost<StandardReagent>("/standard-reagents/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["standard-reagents"] });
    },
  });
}

export function useStandardReagents() {
  return useQuery({
    queryKey: ["standard-reagents"],
    queryFn: () => apiGet<Paginated<StandardReagent>>("/standard-reagents/"),
  });
}

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: () => apiGet<Paginated<Document>>("/documents/"),
  });
}

export function useDocument(id: number) {
  return useQuery({
    queryKey: ["documents", id],
    queryFn: () => apiGet<DocumentDetail>(`/documents/${id}/`),
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { title: string; type: string }) => apiPost<Document>("/documents/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useCreateDocumentVersion(documentId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { version_number: number; file_id: string; effective_date?: string }) =>
      apiPost<DocumentVersion>("/document-versions/", { ...data, document: documentId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", documentId] });
    },
  });
}

export function useApproveDocumentVersion(documentId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (versionId: number) => apiPost<DocumentVersion>(`/document-versions/${versionId}/approve/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", documentId] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useInvestigations(params: { status?: string } = {}) {
  const qs = params.status ? `?status=${params.status}` : "";
  return useQuery({
    queryKey: ["investigations", params],
    queryFn: () => apiGet<Paginated<Investigation>>(`/investigations/${qs}`),
  });
}

export function useInvestigation(id: number) {
  return useQuery({
    queryKey: ["investigations", id],
    queryFn: () => apiGet<Investigation>(`/investigations/${id}/`),
  });
}

/** "Does this sample/result already have an investigation" -- drives the Open Investigation affordance on Sample/Test Request detail. */
export function useInvestigationsForSample(sampleId: number) {
  return useQuery({
    queryKey: ["investigations", "for-sample", sampleId],
    queryFn: () => apiGet<Paginated<Investigation>>(`/investigations/?related_sample=${sampleId}`),
  });
}

export function useInvestigationsForTestResult(testResultId: number) {
  return useQuery({
    queryKey: ["investigations", "for-test-result", testResultId],
    queryFn: () => apiGet<Paginated<Investigation>>(`/investigations/?related_test_result=${testResultId}`),
  });
}

export function useOpenInvestigation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { related_sample?: number; related_test_result?: number; type: string }) =>
      apiPost<Investigation>("/investigations/", data),
    onSuccess: (investigation) => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
      if (investigation.related_sample) {
        queryClient.invalidateQueries({ queryKey: ["investigations", "for-sample", investigation.related_sample] });
      }
      if (investigation.related_test_result) {
        queryClient.invalidateQueries({
          queryKey: ["investigations", "for-test-result", investigation.related_test_result],
        });
      }
    },
  });
}

export function useUpdateInvestigation(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { root_cause?: string; capa_actions?: string; status?: string }) =>
      apiPatch<Investigation>(`/investigations/${id}/`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigations", id] });
    },
  });
}

export function useCloseInvestigation(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiPost<Investigation>(`/investigations/${id}/close/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigations", id] });
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
    },
  });
}

export function useTrainingCourses() {
  return useQuery({
    queryKey: ["training-courses"],
    queryFn: () => apiGet<Paginated<TrainingCourse>>("/training-courses/"),
  });
}

export function useCreateTrainingCourse() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { title: string; description?: string; cpd_units: string; price: string }) =>
      apiPost<TrainingCourse>("/training-courses/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["training-courses"] });
    },
  });
}

export function useTrainingSessions(params: { status?: string } = {}) {
  const qs = params.status ? `?status=${params.status}` : "";
  return useQuery({
    queryKey: ["training-sessions", params],
    queryFn: () => apiGet<Paginated<TrainingSession>>(`/training-sessions/${qs}`),
  });
}

export function useTrainingSession(id: number) {
  return useQuery({
    queryKey: ["training-sessions", id],
    queryFn: () => apiGet<TrainingSession>(`/training-sessions/${id}/`),
  });
}

export function useCreateTrainingSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      course: number;
      start_date: string;
      end_date: string;
      capacity: number;
      min_capacity: number;
      cancellation_threshold_days: number;
    }) => apiPost<TrainingSession>("/training-sessions/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["training-sessions"] });
    },
  });
}

/** One mutation for every TrainingSession FSM action (start-session/complete-session/cancel-session). */
export function useTrainingSessionAction(sessionId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (action: string) => apiPost<TrainingSession>(`/training-sessions/${sessionId}/${action}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["training-sessions", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["training-sessions"] });
    },
  });
}

export function useEnrollmentsForSession(sessionId: number) {
  return useQuery({
    queryKey: ["enrollments", "for-session", sessionId],
    queryFn: () => apiGet<Paginated<Enrollment>>(`/enrollments/?session=${sessionId}`),
  });
}

export function useCreateEnrollment(sessionId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { customer: number }) => apiPost<Enrollment>("/enrollments/", { ...data, session: sessionId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enrollments", "for-session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["training-sessions", sessionId] });
    },
  });
}

/** Covers both Enrollment actions (complete/cancel) -- same reasoning as useSampleAction. */
export function useEnrollmentAction(sessionId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ enrollmentId, action }: { enrollmentId: number; action: string }) =>
      apiPost<Enrollment>(`/enrollments/${enrollmentId}/${action}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enrollments", "for-session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["training-sessions", sessionId] });
    },
  });
}

export function useCreditNotes() {
  return useQuery({
    queryKey: ["credit-notes"],
    queryFn: () => apiGet<Paginated<CreditNote>>("/credit-notes/"),
  });
}

export function useApplyCreditNote() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ creditNoteId, enrollment }: { creditNoteId: number; enrollment: number }) =>
      apiPost<CreditNote>(`/credit-notes/${creditNoteId}/apply/`, { enrollment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credit-notes"] });
    },
  });
}

export function useInvoices(params: { status?: string } = {}) {
  const qs = params.status ? `?status=${params.status}` : "";
  return useQuery({
    queryKey: ["invoices", params],
    queryFn: () => apiGet<Paginated<Invoice>>(`/invoices/${qs}`),
  });
}

export function useInvoice(id: number) {
  return useQuery({
    queryKey: ["invoices", id],
    queryFn: () => apiGet<InvoiceDetail>(`/invoices/${id}/`),
  });
}

export function useCreateInvoice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { order?: number; enrollment?: number; amount: string; currency?: string }) =>
      apiPost<Invoice>("/invoices/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
}

export function useRecordPayment(invoiceId: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { method: string; reference_number?: string; status: string; notes?: string }) =>
      apiPost<Payment>(`/invoices/${invoiceId}/payments/`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invoices", invoiceId] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
}

/**
 * GET /reports/ (apps/reporting/views.py). `refetchInterval` is what makes
 * the Reports screen live: generation is a background job, so a row created
 * as `pending` becomes `ready` without any user action, and without polling
 * the screen would sit on stale rows until a manual refresh. Polling stops
 * once nothing is in flight, so an idle screen is not issuing requests.
 */
export function useReports(params: { sample?: number; status?: string } = {}) {
  const query = new URLSearchParams();
  if (params.sample) query.set("sample", String(params.sample));
  if (params.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query}` : "";

  return useQuery({
    queryKey: ["reports", params],
    queryFn: () => apiGet<Paginated<Report>>(`/reports/${suffix}`),
    refetchInterval: (query) => {
      const rows = query.state.data?.results ?? [];
      const inFlight = rows.some((r) => r.status === "pending" || r.status === "generating");
      return inFlight ? 3000 : false;
    },
  });
}

export function useCreateReport() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { sample?: number; order?: number; report_type: ReportType }) =>
      apiPost<Report>("/reports/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

/**
 * Fetches a presigned URL for a finished report.
 *
 * A mutation rather than a query because it is an action with a side effect
 * in time: the URL expires, so it must be fetched at the moment of the click
 * rather than cached against the row and handed out later, stale.
 */
export function useReportDownloadUrl() {
  return useMutation({
    mutationFn: (reportId: number) => apiGet<ReportDownload>(`/reports/${reportId}/download/`),
  });
}

export function useSystemFailures(params: { status?: string; component?: string } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.component) query.set("component", params.component);
  const qs = query.toString();

  return useQuery({
    queryKey: ["system-failures", params],
    queryFn: () => apiGet<Paginated<SystemFailure>>(`/system-failures/${qs ? `?${qs}` : ""}`),
  });
}

export function useUpdateSystemFailure(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { corrective_action?: string; investigation?: number | null }) =>
      apiPatch<SystemFailure>(`/system-failures/${id}/`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["system-failures"] }),
  });
}

export function useAcknowledgeSystemFailure(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiPost<SystemFailure>(`/system-failures/${id}/acknowledge/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["system-failures"] }),
  });
}

/**
 * The server refuses this while corrective_action is empty
 * (ISO/IEC 17025:2017 7.11.3(e)), so the text is sent with the close rather
 * than saved separately first -- one round trip, and no window where the
 * operator has typed an action into a failure that is still open.
 */
export function useCloseSystemFailure(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (corrective_action: string) =>
      apiPost<SystemFailure>(`/system-failures/${id}/close/`, { corrective_action }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["system-failures"] }),
  });
}

// --- Service catalogue ----------------------------------------------------

export function useServiceOfferings(params: { service_line?: string; active?: string; q?: string } = {}) {
  const query = new URLSearchParams();
  if (params.service_line) query.set("service_line", params.service_line);
  if (params.active) query.set("active", params.active);
  if (params.q) query.set("q", params.q);
  const qs = query.toString();

  return useQuery({
    queryKey: ["service-offerings", params],
    queryFn: () => apiGet<Paginated<ServiceOffering>>(`/service-offerings/${qs ? `?${qs}` : ""}`),
  });
}

export function useServiceOffering(id: number) {
  return useQuery({
    queryKey: ["service-offerings", id],
    queryFn: () => apiGet<ServiceOfferingDetail>(`/service-offerings/${id}/`),
  });
}

export function useCreateServiceOffering() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      code: string;
      name: string;
      service_line: string;
      description?: string;
      turnaround_days?: number | null;
      is_accredited?: boolean;
    }) => apiPost<ServiceOffering>("/service-offerings/", data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["service-offerings"] }),
  });
}

export function useUpdateServiceOffering(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: Partial<Pick<ServiceOffering, "name" | "description" | "turnaround_days" | "is_accredited" | "is_active">>) =>
      apiPatch<ServiceOffering>(`/service-offerings/${id}/`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["service-offerings"] }),
  });
}

/**
 * Prices are superseded, never edited: this posts a new one and the server
 * closes the outgoing price the day before it starts. The response is the
 * whole offering, history included, so the screen re-renders from one
 * round trip rather than refetching.
 */
export function useSetOfferingPrice(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      amount: string;
      vat_treatment: string;
      vat_rate_pct?: string;
      effective_from?: string;
      note?: string;
    }) => apiPost<ServiceOfferingDetail>(`/service-offerings/${id}/set-price/`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["service-offerings"] }),
  });
}

/**
 * The dashboard is one request: the server aggregates, so the browser is
 * never handed a worklist to reduce for itself.
 */
export function useDashboard(params: { from?: string; to?: string; rank?: string } = {}) {
  const query = new URLSearchParams();
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  // Sent to the server rather than sorted here: ranking by value changes
  // which offerings make the top eight, so the fold into "other" has to be
  // computed against the same measure.
  if (params.rank) query.set("rank", params.rank);
  const qs = query.toString();

  return useQuery({
    queryKey: ["analytics-dashboard", params],
    queryFn: () => apiGet<DashboardData>(`/analytics/dashboard/${qs ? `?${qs}` : ""}`),
  });
}

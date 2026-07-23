import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "./client";
import type {
  ApprovalAction,
  CalibrationRecord,
  Document,
  DocumentDetail,
  DocumentVersion,
  Instrument,
  InstrumentDetail,
  Investigation,
  Paginated,
  ReviewAction,
  Sample,
  SampleDetail,
  StandardReagent,
  TestMethod,
  TestRequest,
  TestResult,
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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
import type { ApprovalAction, Paginated, ReviewAction, Sample, SampleDetail } from "./types";

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
    },
  });
}

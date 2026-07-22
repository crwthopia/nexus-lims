import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
import type { Paginated, Sample, SampleDetail } from "./types";

export function useSamples(params: { status?: string; search?: string } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.search) query.set("search", params.search);
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
    },
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
import type { CreditNote, Enrollment, Invoice, Order, Paginated, Sample, TrainingCourse, TrainingSession } from "./types";

export function useMyOrders() {
  return useQuery({
    queryKey: ["my-orders"],
    queryFn: () => apiGet<Paginated<Order>>("/my/orders/"),
  });
}

export function useMySamples() {
  return useQuery({
    queryKey: ["my-samples"],
    queryFn: () => apiGet<Paginated<Sample>>("/my/samples/"),
  });
}

/** Public catalog -- GET /training-courses/ and /training-sessions/ are AllowAny (Blueprint 4.3: browsable before login). */
export function useTrainingCourses() {
  return useQuery({
    queryKey: ["training-courses"],
    queryFn: () => apiGet<Paginated<TrainingCourse>>("/training-courses/"),
  });
}

export function useTrainingSessions() {
  return useQuery({
    queryKey: ["training-sessions"],
    queryFn: () => apiGet<Paginated<TrainingSession>>("/training-sessions/"),
  });
}

export function useMyEnrollments() {
  return useQuery({
    queryKey: ["my-enrollments"],
    queryFn: () => apiGet<Paginated<Enrollment>>("/my/enrollments/"),
  });
}

export function useEnrollInSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (sessionId: number) => apiPost<Enrollment>("/my/enrollments/", { session: sessionId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-enrollments"] });
      queryClient.invalidateQueries({ queryKey: ["training-sessions"] });
    },
  });
}

export function useMyCreditNotes() {
  return useQuery({
    queryKey: ["my-credit-notes"],
    queryFn: () => apiGet<Paginated<CreditNote>>("/my/credit-notes/"),
  });
}

export function useApplyMyCreditNote() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ creditNoteId, enrollment }: { creditNoteId: number; enrollment: number }) =>
      apiPost<CreditNote>(`/my/credit-notes/${creditNoteId}/apply/`, { enrollment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-credit-notes"] });
      queryClient.invalidateQueries({ queryKey: ["my-enrollments"] });
    },
  });
}

export function useMyInvoices() {
  return useQuery({
    queryKey: ["my-invoices"],
    queryFn: () => apiGet<Paginated<Invoice>>("/my/invoices/"),
  });
}

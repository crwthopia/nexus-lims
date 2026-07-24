import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useApplyCreditNote,
  useCreateTrainingCourse,
  useCreateTrainingSession,
  useCreditNotes,
  useTrainingCourses,
  useTrainingSessions,
} from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../api/client";
import { TRAINING_SESSION_STATUS_LABELS, TRAINING_WRITE_ROLES } from "../api/types";

export function TrainingList() {
  const { hasRole } = useAuth();
  const canWrite = hasRole(...TRAINING_WRITE_ROLES);
  const navigate = useNavigate();

  const { data: courses, isLoading: coursesLoading } = useTrainingCourses();
  const { data: sessions, isLoading: sessionsLoading } = useTrainingSessions();
  const { data: creditNotes } = useCreditNotes();

  const createCourse = useCreateTrainingCourse();
  const createSession = useCreateTrainingSession();
  const applyCreditNote = useApplyCreditNote();

  const [courseTitle, setCourseTitle] = useState("");
  const [cpdUnits, setCpdUnits] = useState("");
  const [price, setPrice] = useState("");

  const [sessionCourseId, setSessionCourseId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [capacity, setCapacity] = useState(20);
  const [minCapacity, setMinCapacity] = useState(5);
  const [cancellationThresholdDays, setCancellationThresholdDays] = useState(7);

  const [applyTargets, setApplyTargets] = useState<Record<number, string>>({});

  function submitCourse(e: React.FormEvent) {
    e.preventDefault();
    createCourse.mutate(
      { title: courseTitle, cpd_units: cpdUnits, price },
      {
        onSuccess: () => {
          setCourseTitle("");
          setCpdUnits("");
          setPrice("");
        },
      },
    );
  }

  function submitSession(e: React.FormEvent) {
    e.preventDefault();
    createSession.mutate(
      {
        course: Number(sessionCourseId),
        start_date: startDate,
        end_date: endDate,
        capacity,
        min_capacity: minCapacity,
        cancellation_threshold_days: cancellationThresholdDays,
      },
      { onSuccess: (session) => navigate(`/training-sessions/${session.id}`) },
    );
  }

  function submitApply(creditNoteId: number) {
    const enrollmentId = Number(applyTargets[creditNoteId]);
    if (!enrollmentId) return;
    applyCreditNote.mutate({ creditNoteId, enrollment: enrollmentId });
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Training</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Course catalog, sessions, and credit notes (Blueprint 3.6).
        </p>
      </div>

      <h2 style={{ fontSize: "1.1rem", margin: "0 0 12px" }}>Courses</h2>
      {canWrite && (
        <form
          onSubmit={submitCourse}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1, minWidth: 160 }}>
            New course title
            <input value={courseTitle} onChange={(e) => setCourseTitle(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            CPD units
            <input value={cpdUnits} onChange={(e) => setCpdUnits(e.target.value)} required style={{ ...inputStyle, width: 80 }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Price (PHP)
            <input value={price} onChange={(e) => setPrice(e.target.value)} required style={{ ...inputStyle, width: 100 }} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={createCourse.isPending}>
            Add
          </button>
          {createCourse.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createCourse.error)}</span>
          )}
        </form>
      )}
      <div className="card" style={{ overflow: "hidden", marginBottom: 32 }}>
        {coursesLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {courses && courses.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No courses yet.</div>
        )}
        {courses && courses.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>CPD units</th>
                <th>Price</th>
                <th>Student discount</th>
              </tr>
            </thead>
            <tbody>
              {courses.results.map((c) => (
                <tr key={c.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>{c.title}</td>
                  <td>{c.cpd_units}</td>
                  <td>₱{c.price}</td>
                  <td>{c.student_discount_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2 style={{ fontSize: "1.1rem", margin: "0 0 12px" }}>Sessions</h2>
      {canWrite && (
        <form
          onSubmit={submitSession}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1, minWidth: 160 }}>
            Course
            <select value={sessionCourseId} onChange={(e) => setSessionCourseId(e.target.value)} required style={inputStyle}>
              <option value="">Select a course…</option>
              {courses?.results.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Start
            <input type="datetime-local" value={startDate} onChange={(e) => setStartDate(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            End
            <input type="datetime-local" value={endDate} onChange={(e) => setEndDate(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Capacity
            <input
              type="number"
              min={1}
              value={capacity}
              onChange={(e) => setCapacity(Number(e.target.value))}
              required
              style={{ ...inputStyle, width: 70 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Min. capacity
            <input
              type="number"
              min={0}
              value={minCapacity}
              onChange={(e) => setMinCapacity(Number(e.target.value))}
              required
              style={{ ...inputStyle, width: 70 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Cancellation threshold (days)
            <input
              type="number"
              min={0}
              value={cancellationThresholdDays}
              onChange={(e) => setCancellationThresholdDays(Number(e.target.value))}
              required
              style={{ ...inputStyle, width: 70 }}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={createSession.isPending}>
            Add
          </button>
          {createSession.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createSession.error)}</span>
          )}
        </form>
      )}
      <div className="card" style={{ overflow: "hidden", marginBottom: 32 }}>
        {sessionsLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {sessions && sessions.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No sessions yet.</div>
        )}
        {sessions && sessions.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Course</th>
                <th>Start</th>
                <th>Status</th>
                <th>Enrolled</th>
              </tr>
            </thead>
            <tbody>
              {sessions.results.map((s) => (
                <tr key={s.id} onClick={() => navigate(`/training-sessions/${s.id}`)}>
                  <td style={{ fontWeight: 600 }}>{s.course_title}</td>
                  <td>{new Date(s.start_date).toLocaleString()}</td>
                  <td>{TRAINING_SESSION_STATUS_LABELS[s.status]}</td>
                  <td>
                    {s.confirmed_enrollment_count} / {s.capacity}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2 style={{ fontSize: "1.1rem", margin: "0 0 12px" }}>Credit notes</h2>
      <div className="card" style={{ overflow: "hidden" }}>
        {creditNotes && creditNotes.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No credit notes issued yet.</div>
        )}
        {creditNotes && creditNotes.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Amount</th>
                <th>Status</th>
                <th>Issued</th>
                {canWrite && <th>Apply to enrollment #</th>}
              </tr>
            </thead>
            <tbody>
              {creditNotes.results.map((cn) => (
                <tr key={cn.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>₱{cn.amount}</td>
                  <td style={{ textTransform: "capitalize" }}>{cn.status}</td>
                  <td>{new Date(cn.created_at).toLocaleDateString()}</td>
                  {canWrite && (
                    <td>
                      {cn.status === "available" && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <input
                            type="number"
                            placeholder="Enrollment ID"
                            value={applyTargets[cn.id] ?? ""}
                            onChange={(e) => setApplyTargets((prev) => ({ ...prev, [cn.id]: e.target.value }))}
                            style={{ ...inputStyle, width: 100 }}
                          />
                          <button className="btn" disabled={applyCreditNote.isPending} onClick={() => submitApply(cn.id)}>
                            Apply
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {applyCreditNote.isError && (
          <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", padding: "0 16px 16px" }}>
            {describeApiError(applyCreditNote.error)}
          </p>
        )}
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontFamily: "inherit",
  fontSize: "0.9rem",
} as const;

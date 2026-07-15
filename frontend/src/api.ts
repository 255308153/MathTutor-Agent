import type {
  LearningEventRequest,
  MathTutorEventResponse,
  ProviderHealthResponse,
  StudentMemoryDetailResponse,
  StudentMemoryListResponse,
  TrialFeedbackCreate,
  TrialFeedbackRecord,
  TrialProbeSummary,
  TrialReadinessReport
} from "./types";

const API_BASE = import.meta.env.VITE_MATHTUTOR_API_BASE ?? "";

export async function sendLearningEvent(
  event: LearningEventRequest
): Promise<MathTutorEventResponse> {
  const response = await fetch(`${API_BASE}/api/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event)
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`事件处理失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<MathTutorEventResponse>;
}

export async function fetchStudentMemories(
  studentId: string
): Promise<StudentMemoryListResponse> {
  const response = await fetch(
    `${API_BASE}/api/students/${encodeURIComponent(studentId)}/memories`
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`学生记忆读取失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<StudentMemoryListResponse>;
}

export async function fetchProviderHealth(): Promise<ProviderHealthResponse> {
  const response = await fetch(`${API_BASE}/api/provider-health`);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Provider 状态读取失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<ProviderHealthResponse>;
}

export async function fetchTrialReadiness(): Promise<TrialReadinessReport> {
  const response = await fetch(`${API_BASE}/api/trial-readiness`);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`试用 Readiness 读取失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<TrialReadinessReport>;
}

export async function triggerCanaryProbes(providers: string[] = ["memory", "rag"]) {
  const response = await fetch(`${API_BASE}/api/trial-readiness/probes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      providers,
      canary_token: "mathtutor-canary"
    })
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Canary Probe 失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<TrialProbeSummary[]>;
}

export async function submitTrialFeedback(
  payload: TrialFeedbackCreate
): Promise<TrialFeedbackRecord> {
  const response = await fetch(`${API_BASE}/api/trial-readiness/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`试用反馈写入失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<TrialFeedbackRecord>;
}

export async function updateStudentMemoryControl({
  studentId,
  memoryId,
  action
}: {
  studentId: string;
  memoryId: string;
  action: "enable" | "disable";
}): Promise<StudentMemoryDetailResponse> {
  const memoryUrl =
    `${API_BASE}/api/students/${encodeURIComponent(studentId)}` +
    `/memories/${encodeURIComponent(memoryId)}`;
  const response = await fetch(`${memoryUrl}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      actor: "student",
      reason:
        action === "disable"
          ? "学生在记忆控制面板中禁用该记忆。"
          : "学生在记忆控制面板中重新启用该记忆。"
    })
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`学生记忆控制失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<StudentMemoryDetailResponse>;
}

export async function deleteStudentMemory({
  studentId,
  memoryId
}: {
  studentId: string;
  memoryId: string;
}): Promise<StudentMemoryDetailResponse> {
  const response = await fetch(
    `${API_BASE}/api/students/${encodeURIComponent(studentId)}` +
      `/memories/${encodeURIComponent(memoryId)}`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: "student",
        reason: "学生在记忆控制面板中删除该记忆。"
      })
    }
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`学生记忆删除失败：${response.status} ${errorDetail(body)}`);
  }

  return response.json() as Promise<StudentMemoryDetailResponse>;
}

function errorDetail(body: string) {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (isRecord(parsed.detail)) {
      const message = primitiveText(parsed.detail.message);
      const hint = primitiveText(parsed.detail.actionable_hint);
      return [message, hint].filter(Boolean).join(" ");
    }
  } catch {
    // Fall through to the raw body; it is still more useful than hiding the server response.
  }
  return body;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function primitiveText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

import type { LearningEventRequest, MathTutorEventResponse } from "./types";

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

function errorDetail(body: string) {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Fall through to the raw body; it is still more useful than hiding the server response.
  }
  return body;
}

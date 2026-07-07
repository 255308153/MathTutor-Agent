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
    throw new Error(`事件处理失败：${response.status} ${body}`);
  }

  return response.json() as Promise<MathTutorEventResponse>;
}

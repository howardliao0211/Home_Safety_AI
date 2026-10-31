import { counts, type Assessment, type Photo } from "./model";

export type HistoryItem = {
  id: string;
  title?: string;
  createdAt: string;
  status: Assessment["status"];
  openCount: number | null;
  photo: Photo;
};

export function assessmentTitle(title?: string | null): string {
  const text = title?.trim();
  if (!text) return "Room assessment";
  const words = text.split(/\s+/);
  return words.length > 8 ? `${words.slice(0, 8).join(" ")}…` : text;
}

export function historyItem(assessment: Assessment): HistoryItem {
  return {
    id: assessment.id,
    title: assessment.title,
    createdAt: assessment.createdAt,
    status: assessment.status,
    openCount:
      assessment.status === "complete"
        ? counts(assessment.findings).open
        : null,
    photo: assessment.photo,
  };
}

export function newestFirst(a: HistoryItem, b: HistoryItem) {
  return b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id);
}

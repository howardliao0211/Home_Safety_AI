import type { Assessment, Finding } from "./model";

export type OverviewMask = {
  findingId: string;
  annotationId: string;
  severity: Finding["severity"];
  width: number;
  height: number;
};

const ACTIVE = ["queued", "processing"];

/**
 * The checklist overview draws at most one highlight per open finding: the
 * latest attempt for its current revision, only when it is ready and belongs
 * to the displayed original photo. It never falls back to an older attempt.
 * Order follows the saved findings, so overlaps blend without severity priority.
 */
export function overviewHighlights(assessment: Assessment) {
  const open = assessment.findings.filter((f) => f.status === "open");
  const masks: OverviewMask[] = [];
  for (const finding of open) {
    const a = finding.annotation;
    if (
      a?.id &&
      a.state === "ready" &&
      a.revision === (finding.contentRevision || "initial") &&
      a.photo_kind === "original" &&
      a.photo_id === assessment.photo.id &&
      a.orientation === 1 &&
      !!a.width &&
      !!a.height &&
      !(
        a.image_digest &&
        assessment.photo.digest &&
        a.image_digest !== assessment.photo.digest
      )
    )
      masks.push({
        findingId: finding.id,
        annotationId: a.id,
        severity: finding.severity,
        width: a.width,
        height: a.height,
      });
  }
  return {
    masks,
    openCount: open.length,
    pending: open.some((f) => ACTIVE.includes(f.annotation?.state ?? "")),
  };
}

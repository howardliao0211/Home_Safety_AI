import type { Annotation, Assessment, Finding, Photo } from "../domain/model";
import { sampleSizes } from "../domain/samples";
import { severityColors } from "../components/theme";

type Shape =
  | { kind: "rect"; x: number; y: number; w: number; h: number }
  | { kind: "ellipse"; cx: number; cy: number; rx: number; ry: number };

// Normalized simulated shapes. The cabinet and walkway overlap on purpose so
// translucent colours visibly blend.
const shapes: Record<string, Shape> = {
  furniture: { kind: "rect", x: 0.56, y: 0.14, w: 0.3, h: 0.66 },
  walkway: { kind: "ellipse", cx: 0.55, cy: 0.74, rx: 0.3, ry: 0.11 },
  "small-items": { kind: "rect", x: 0.16, y: 0.56, w: 0.2, h: 0.13 },
};
/** Arrives later than its siblings, to demonstrate progressive availability. */
export const STAGED_FINDING = "walkway";
export const STAGED_DELAY_MS = 4000;
export const isPreviewAnnotation = (a?: Annotation | null) =>
  !!a?.id?.startsWith("preview-");

/** Simulated attempts for sample photos only; other photos have no known source size. */
export function withPreviewHighlights(
  assessment: Assessment,
  findings: Finding[],
): Finding[] {
  const size = assessment.photo.sample
    ? sampleSizes[assessment.photo.sample]
    : undefined;
  return findings.map((finding) => {
    const supported =
      !!size && !!shapes[finding.id] && assessment.scenario !== "uncertain";
    const annotation: Annotation = {
      id: `preview-${assessment.id}-${finding.id}`,
      revision: finding.contentRevision || "initial",
      attempt: 1,
      state: !supported
        ? "unavailable"
        : finding.id === STAGED_FINDING
          ? "processing"
          : "ready",
      reason: supported
        ? null
        : size
          ? "Simulated: no single visible object to highlight for this finding."
          : "Simulated highlights are available for the sample photos only.",
      photo_id: assessment.photo.id,
      photo_kind: "original",
      width: size?.width ?? null,
      height: size?.height ?? null,
      orientation: 1,
    };
    return { ...finding, annotation, annotations: [annotation] };
  });
}

export function previewMaskUri(photo: Photo, finding: Finding) {
  const size = photo.sample ? sampleSizes[photo.sample] : undefined;
  const shape = shapes[finding.id];
  if (!size || !shape) throw new Error("Simulated highlight unavailable.");
  const { width: W, height: H } = size;
  const color = severityColors[finding.severity];
  const line = Math.max(3, Math.round(Math.max(W, H) * 0.006));
  const geometry =
    shape.kind === "rect"
      ? `<rect x="${shape.x * W}" y="${shape.y * H}" width="${shape.w * W}" height="${shape.h * H}" rx="${line * 2.5}"`
      : `<ellipse cx="${shape.cx * W}" cy="${shape.cy * H}" rx="${shape.rx * W}" ry="${shape.ry * H}"`;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    `${geometry} fill="${color.fill}" fill-opacity="0.4" stroke="${color.rim}" stroke-width="${line * 1.8}"/>` +
    `${geometry} fill="none" stroke="${color.fill}" stroke-width="${line}"/></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

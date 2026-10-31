import type { Assessment, Finding, Submission } from "../domain/model";

const base = () => ({ status: "open" as const, note: "", submissions: [] });
export function fixtureFindings(scenario: Assessment["scenario"]): Finding[] {
  if (scenario === "clear") return [];
  const furniture: Finding = {
    ...base(),
    id: "furniture",
    title: "Check the tall cabinet",
    category: "Furniture",
    severity: "High",
    evidence:
      "In the sample scene, a tall cabinet stands beside a frequently used area. Its attachment to the wall is not visible.",
    shortAction: "Check whether the cabinet is secured.",
    recommendation:
      "Keep children from climbing on the cabinet. Check the manufacturer’s guidance and ask a qualified person to inspect or install an appropriate restraint. Do not move heavy furniture alone.",
    uncertainty:
      "A room photo cannot show whether a wall restraint is fitted behind the cabinet.",
    followUp: {
      kind: "photo",
      question:
        "Can you safely photograph the top or side of the cabinet where it meets the wall? Do not climb or move it.",
      state: "available",
    },
  };
  if (scenario === "uncertain") return [furniture];
  return [
    furniture,
    {
      ...base(),
      id: "walkway",
      title: "Give the walkway more room",
      category: "Trips & falls",
      severity: "Medium",
      evidence:
        "In the sample scene, a loose cable crosses the edge of the walking route next to the seating area.",
      shortAction: "Keep loose cables out of the walking route.",
      recommendation:
        "Keep the walking route clear. If it is safe, route the loose cable away from where people walk without pulling on connected equipment. Ask for help if moving furniture would be needed.",
      uncertainty:
        "The photo cannot establish whether this route is used regularly.",
      followUp: {
        kind: "text",
        question:
          "Does your family regularly walk through this area, including at night?",
        state: "available",
      },
    },
    {
      ...base(),
      id: "small-items",
      title: "Put small items out of reach",
      category: "Small objects",
      severity: "Low",
      evidence:
        "In the sample scene, small loose objects are on a low table within easy reach.",
      shortAction: "Store small loose items away from little hands and pets.",
      recommendation:
        "Store loose small objects in a secure place if babies, young children, or pets use this room. Dismiss this finding if the sample concern is not relevant to your household.",
      uncertainty:
        "Object size and who can reach them cannot be confirmed from this view.",
    },
  ];
}
/** Simulated, household-aware priorities; never generated for zero findings. */
export function fixtureSuggestions(
  assessment: Pick<Assessment, "profiles" | "householdContext">,
  findings: Finding[],
): string[] {
  if (!findings.length) return [];
  const details = assessment.householdContext?.trim();
  const who = details
    ? `Keep your household details in mind (“${details.length > 80 ? `${details.slice(0, 77)}…` : details}”) when choosing what to do first.`
    : assessment.profiles.length
      ? `Think about how each ${assessment.profiles.map((p) => p.toLowerCase()).join(", ")} in your home uses this room when choosing what to do first.`
      : "Think about who uses this room most when choosing what to do first.";
  return [
    `Start with “${findings[0].title.toLowerCase()}”, the highest-priority item in this sample.`,
    who,
    "Look at the room again after any changes; a photo can’t confirm a fix.",
  ];
}
export interface AssessmentService {
  assess(assessment: Assessment): Promise<Finding[]>;
  check(
    assessment: Assessment,
    finding: Finding,
    submission: Submission,
  ): Promise<string>;
}
const pause = () => new Promise((resolve) => setTimeout(resolve, 1300));
export const previewService: AssessmentService = {
  async assess(assessment) {
    await pause();
    if (assessment.scenario === "analysis-error" && assessment.attempts === 1) {
      throw new Error(
        "The simulated analysis could not finish. Your photo and profiles are saved.",
      );
    }
    return fixtureFindings(assessment.scenario);
  },
  async check(assessment, _finding, submission) {
    await pause();
    if (assessment.scenario === "update-error" && submission.attempts === 1) {
      throw new Error(
        "The simulated check could not finish. Your input and existing findings are saved.",
      );
    }
    return submission.kind === "review"
      ? "Simulated review: the new photo would provide another view, but it does not prove that the concern is resolved. Review the recommendation, then decide whether to mark the item resolved, dismiss it, or leave it open."
      : submission.photo
        ? "Simulated update: the additional view would help inspect the possible restraint. The attachment and its suitability still need to be checked in person. The recommendation remains to follow the manufacturer’s guidance and seek qualified help."
        : "Simulated update: your answer provides context for how this area is used. Keep the walking route clear, particularly in low light. You decide whether further action is needed.";
  },
};

export const colors = {
  background: "#f7f6f1",
  surface: "#ffffff",
  ink: "#243d35",
  muted: "#56675e",
  accent: "#245c46",
  soft: "#eaf0e7",
  line: "#dce2d7",
  warm: "#eeeadd",
  danger: "#943c30",
  dangerSoft: "#fcf0e9",
  amber: "#80501b",
  amberSoft: "#faf0dc",
};
export const tokens = {
  radius: 18,
  controlRadius: 12,
  space: 20,
  maxWidth: 700,
};
/** Highlight fill and darker outline per finding severity (matches the backend tint). */
export const severityColors = {
  High: { fill: "#dc2626", rim: "#6e0f0f", name: "Red" },
  Medium: { fill: "#facc15", rim: "#644b00", name: "Yellow" },
  Low: { fill: "#16a34a", rim: "#0a461e", name: "Green" },
} as const;

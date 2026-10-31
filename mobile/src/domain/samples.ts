export const roomSources = {
  living: require("../../assets/rooms/living-room.jpg"),
  quiet: require("../../assets/rooms/quiet-room.jpg"),
  portrait: require("../../assets/rooms/portrait-room.jpg"),
};
/** Natural pixel sizes, so simulated highlights share the photo's source canvas. */
export const sampleSizes = {
  living: { width: 1200, height: 900 },
  quiet: { width: 1200, height: 816 },
  portrait: { width: 800, height: 1200 },
};
export const sampleNames = {
  living: "Living room",
  quiet: "Quiet room",
  portrait: "Portrait room",
};
export type Sample = keyof typeof roomSources;

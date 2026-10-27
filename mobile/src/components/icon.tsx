import Svg, { Path, Circle, Rect } from "react-native-svg";
import { colors } from "@/components/theme";

export type IconName =
  | "home"
  | "camera"
  | "image"
  | "arrow"
  | "check"
  | "shield"
  | "plus"
  | "close"
  | "info"
  | "chevron"
  | "refresh"
  | "trash"
  | "eye";
const paths: Partial<Record<IconName, string>> = {
  home: "M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9",
  camera: "M8 6l2-3h4l2 3h5v14H3V6h5",
  image: "m3 17 6-6 4 4 3-3 5 5",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  check: "m5 12 4 4L19 6",
  shield: "M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4",
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M6 18 18 6",
  info: "M12 11v6m0-10v.01",
  chevron: "m9 5 7 7-7 7",
  refresh:
    "M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3",
  trash: "M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12",
};
export function Icon({
  name,
  size = 22,
  color = colors.accent,
}: {
  name: IconName;
  size?: number;
  color?: string;
}) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...(process.env.EXPO_OS === "web"
        ? { "aria-hidden": true }
        : { accessible: false })}
    >
      {name === "image" && <Rect x="3" y="3" width="18" height="18" rx="3" />}
      {name === "info" && <Circle cx="12" cy="12" r="9" />}
      {name === "camera" && <Circle cx="12" cy="12" r="3.5" />}
      {name === "eye" && <Circle cx="12" cy="12" r="3" />}
      <Path d={paths[name]} />
    </Svg>
  );
}

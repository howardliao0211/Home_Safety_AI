import { Redirect, useLocalSearchParams } from "expo-router";

// Old bookmarks return to the finding. Saved evidence is still viewable there.
export default function EvidenceScreen() {
  const { assessmentId, findingId } = useLocalSearchParams<{
    assessmentId: string;
    findingId: string;
  }>();
  return (
    <Redirect
      href={{
        pathname: "/finding/[assessmentId]/[findingId]",
        params: { assessmentId, findingId },
      }}
    />
  );
}

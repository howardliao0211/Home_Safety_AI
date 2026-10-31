import { Redirect, useLocalSearchParams } from "expo-router";
import { AssessmentGate } from "@/components/assessment-gate";
import { RoomConceptViewer } from "@/components/room-concept";
import { usePreview } from "@/hooks/preview-context";

export default function RoomConceptRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <AssessmentGate id={id}>
      <Content id={id} />
    </AssessmentGate>
  );
}

function Content({ id }: { id: string }) {
  const { state } = usePreview();
  const assessment = state.assessments.find((a) => a.id === id);
  if (!assessment || assessment.status !== "complete")
    return <Redirect href="/" />;
  return <RoomConceptViewer key={id} assessment={assessment} />;
}

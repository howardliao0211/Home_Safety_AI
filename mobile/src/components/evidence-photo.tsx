import { useEffect, useState } from "react";
import { Image } from "expo-image";
import { Modal, ScrollView, View, useWindowDimensions } from "react-native";
import { usePreview } from "@/hooks/preview-context";
import { Button, Copy } from "@/components/ui";
import type { Photo } from "@/domain/model";
import { roomSources } from "@/domain/samples";

/** Both layers occupy one source-aspect canvas and receive exactly the same zoom. */
export function EvidencePhoto({
  photo,
  mask,
  dimensions,
}: {
  photo: Photo;
  mask?: string;
  dimensions?: { width: number; height: number };
}) {
  const { loadRemotePhoto } = usePreview();
  const [source, setSource] = useState<string>();
  const [error, setError] = useState(false);
  const [ratio, setRatio] = useState(
    dimensions ? dimensions.width / dimensions.height : 1,
  );
  const [width, setWidth] = useState(300);
  const [zoom, setZoom] = useState(1);
  const [expanded, setExpanded] = useState(false);
  const window = useWindowDimensions();
  useEffect(() => {
    let active = true;
    setSource(undefined);
    setError(false);
    // Saved normalized evidence is essential: a cached camera original can have
    // different orientation/dimensions from the server's source-aligned mask.
    if (photo.remote) {
      void loadRemotePhoto(photo.remote)
        .then((uri) => {
          if (active) setSource(uri);
        })
        .catch(() => {
          if (active) setError(true);
        });
    } else setSource(photo.uri);
    return () => {
      active = false;
    };
  }, [photo.id, photo.remote?.photoId]);
  const imageSource = source
    ? { uri: source }
    : photo.sample
      ? roomSources[photo.sample]
      : undefined;
  const canvas = (canvasWidth: number) => (
    <View style={{ width: canvasWidth, height: canvasWidth / ratio }}>
      {!!imageSource && (
        <Image
          source={imageSource}
          contentFit="contain"
          accessibilityLabel={photo.label}
          style={{ width: "100%", height: "100%" }}
          onLoad={(event) => {
            if (!dimensions) setRatio(event.source.width / event.source.height);
          }}
          onError={() => setError(true)}
        />
      )}
      {!!mask && !error && (
        <Image
          source={{ uri: mask }}
          contentFit="contain"
          accessibilityLabel="Reviewed object highlight"
          pointerEvents="none"
          style={{ position: "absolute", width: "100%", height: "100%" }}
        />
      )}
    </View>
  );
  return (
    <View
      style={{ gap: 8 }}
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
    >
      {error ? (
        <Copy>Photo unavailable. Your finding remains saved.</Copy>
      ) : imageSource ? (
        canvas(width)
      ) : (
        <Copy>Loading saved photo…</Copy>
      )}
      <Copy kind="small">{photo.label}</Copy>
      <Button
        label="Zoom photo"
        variant="secondary"
        disabled={!imageSource || error}
        onPress={() => {
          setZoom(1);
          setExpanded(true);
        }}
      />
      <Modal
        visible={expanded}
        onRequestClose={() => setExpanded(false)}
        animationType="none"
      >
        <View
          style={{
            flex: 1,
            paddingTop: 48,
            paddingBottom: 32,
            gap: 12,
            backgroundColor: "white",
          }}
        >
          <Copy kind="small">
            Scroll to inspect the photo. Photo and highlight zoom together.
          </Copy>
          <ScrollView style={{ flex: 1 }}>
            <ScrollView horizontal>{canvas(window.width * zoom)}</ScrollView>
          </ScrollView>
          <Button
            label="Zoom in"
            variant="secondary"
            disabled={zoom >= 4}
            onPress={() => setZoom((value) => Math.min(4, value + 1))}
          />
          <Button
            label="Zoom out"
            variant="secondary"
            disabled={zoom <= 1}
            onPress={() => setZoom((value) => Math.max(1, value - 1))}
          />
          <Button label="Close photo" onPress={() => setExpanded(false)} />
        </View>
      </Modal>
    </View>
  );
}

import { useEffect, useState } from "react";
import { Image } from "expo-image";
import { View } from "react-native";
import { usePreview } from "@/hooks/preview-context";
import { Copy } from "@/components/ui";
import type { Photo } from "@/domain/model";
import { roomSources } from "@/domain/samples";

/** Both layers occupy one source-aspect canvas, so the mask stays aligned. */
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
  const canvas = (
    <View style={{ width, height: width / ratio }}>
      {!!imageSource && (
        <Image
          cachePolicy="none"
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
          cachePolicy="none"
          source={{ uri: mask }}
          contentFit="contain"
          accessibilityLabel="AI-generated highlight"
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
        canvas
      ) : (
        <Copy>Loading saved photo…</Copy>
      )}
      <Copy kind="small">{photo.label}</Copy>
    </View>
  );
}

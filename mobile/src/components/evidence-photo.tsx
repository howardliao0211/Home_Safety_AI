import { useEffect, useState } from "react";
import { Image } from "expo-image";
import { View } from "react-native";
import { usePreview } from "@/hooks/preview-context";
import { Copy } from "@/components/ui";
import type { Photo } from "@/domain/model";
import { roomSources } from "@/domain/samples";

export type MaskLayer = {
  key: string;
  uri: string;
  /** Source pixel size the mask was made for; must match the displayed photo. */
  width?: number;
  height?: number;
  /** Accessible name; unlabelled layers are decorative. */
  label?: string;
};

/**
 * The photo and every mask occupy one source-aspect canvas with `contain`, so
 * each overlay is fitted to the same image rectangle and stays aligned at any
 * width, after rotation and with text scaling. Portrait photos are never cropped.
 */
export function EvidencePhoto({
  photo,
  masks = [],
  dimensions,
  caption = photo.label,
}: {
  photo: Photo;
  masks?: MaskLayer[];
  dimensions?: { width: number; height: number };
  caption?: string;
}) {
  const { loadRemotePhoto } = usePreview();
  const [source, setSource] = useState<string>();
  const [error, setError] = useState(false);
  const [natural, setNatural] = useState<{ width: number; height: number }>();
  const [width, setWidth] = useState(300);
  useEffect(() => {
    let active = true;
    setSource(undefined);
    setError(false);
    setNatural(undefined);
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
  const size = natural ?? dimensions;
  const ratio = size ? size.width / size.height : 4 / 3;
  // Masks made for another image size would be misaligned; omit them.
  const aligned = natural
    ? masks.filter(
        (m) =>
          !m.width ||
          !m.height ||
          (m.width === natural.width && m.height === natural.height),
      )
    : [];
  const canvas = (
    <View style={{ width, height: width / ratio }}>
      {!!imageSource && (
        <Image
          cachePolicy="none"
          source={imageSource}
          contentFit="contain"
          accessibilityLabel={photo.label}
          style={{ width: "100%", height: "100%" }}
          onLoad={(event) =>
            setNatural({
              width: event.source.width,
              height: event.source.height,
            })
          }
          onError={() => setError(true)}
        />
      )}
      {!error &&
        aligned.map((mask) => (
          <Image
            key={mask.key}
            cachePolicy="none"
            source={{ uri: mask.uri }}
            contentFit="contain"
            accessible={!!mask.label}
            accessibilityLabel={mask.label}
            pointerEvents="none"
            style={{ position: "absolute", width: "100%", height: "100%" }}
          />
        ))}
    </View>
  );
  return (
    <View
      style={{ gap: 8 }}
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
    >
      {error ? (
        <Copy>Photo unavailable. Your findings remain saved.</Copy>
      ) : imageSource ? (
        canvas
      ) : (
        <Copy>Loading saved photo…</Copy>
      )}
      {!!caption && <Copy kind="small">{caption}</Copy>}
    </View>
  );
}

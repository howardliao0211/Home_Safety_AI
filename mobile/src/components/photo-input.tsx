import { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { makeId, type Photo } from "@/domain/model";
import { sampleNames, type Sample } from "@/domain/samples";
import { usePreview } from "@/hooks/preview-context";
import { colors } from "@/components/theme";
import { apiEnabled } from "@/api/config";
import {
  Button,
  Copy,
  Notice,
  PhotoView,
  roomSources,
  styles,
} from "@/components/ui";

export function PhotoInput({
  photo,
  onChange,
  denyCamera = false,
  onInvalid,
  disabled = false,
}: {
  photo?: Photo;
  onChange: (photo: Photo) => Promise<unknown>;
  denyCamera?: boolean;
  onInvalid?: () => void;
  disabled?: boolean;
}) {
  const { busy: working } = usePreview();
  const busy = working || disabled;
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string>();
  const [denied, setDenied] = useState(false);
  async function pick(camera: boolean) {
    if (picking || busy) return;
    // Some browsers never resolve the picker promise on cancellation. Keep the
    // alternate controls usable there; native pickers report cancellation.
    setPicking(process.env.EXPO_OS !== "web");
    setError(undefined);
    setDenied(false);
    try {
      if (camera && denyCamera) {
        setDenied(true);
        setError(
          "Preview scenario: camera permission was declined. Choose a photo or use a sample instead.",
        );
        return;
      }
      if (camera && process.env.EXPO_OS !== "web") {
        const permission = await ImagePicker.requestCameraPermissionsAsync();
        if (!permission.granted) {
          setDenied(true);
          setError(
            "Camera access is off. You can enable it in device settings, choose a photo, or use a sample.",
          );
          return;
        }
      }
      const options: ImagePicker.ImagePickerOptions = {
        mediaTypes: ["images"],
        quality: 0.8,
        allowsEditing: false,
      };
      // On web this call stays in the user-activation handler so the file dialog opens.
      const result = camera
        ? await ImagePicker.launchCameraAsync(options)
        : await ImagePicker.launchImageLibraryAsync(options);
      if (result.canceled) return;
      const asset = result.assets[0];
      if (!asset?.uri || !asset.width || !asset.height)
        throw new Error(
          "This image could not be read. Choose another photo or a sample.",
        );
      if ((asset.fileSize ?? 0) > (apiEnabled ? 10 : 15) * 1024 * 1024)
        throw new Error(
          apiEnabled
            ? "Choose a photo smaller than 10 MiB."
            : "Choose a photo smaller than 15 MB for this local preview.",
        );
      if (apiEnabled && asset.width * asset.height > 20_000_000)
        throw new Error("Choose a photo under 20 megapixels.");
      await onChange({
        id: makeId(),
        label: camera
          ? "Your camera photo"
          : asset.fileName || "Your room photo",
        uri: asset.uri,
      });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The photo could not be opened. Choose a photo or use a sample.",
      );
    } finally {
      setPicking(false);
    }
  }
  return (
    <View style={{ gap: 16 }}>
      {photo && (
        <PhotoView key={photo.id} photo={photo} onInvalid={onInvalid} />
      )}
      <Copy kind="small">
        Take a wide view of the room in good light. Only capture what you’re
        {apiEnabled
          ? "comfortable sending for analysis."
          : "comfortable keeping on this device."}
      </Copy>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
        <View style={{ flex: 1, minWidth: 135 }}>
          <Button
            label="Take photo"
            icon="camera"
            variant="secondary"
            disabled={picking}
            onPress={() => void pick(true)}
          />
        </View>
        <View style={{ flex: 1, minWidth: 135 }}>
          <Button
            label="Choose photo"
            icon="image"
            variant="secondary"
            disabled={picking}
            onPress={() => void pick(false)}
          />
        </View>
      </View>
      {error && (
        <Notice
          title={denied ? "Camera access is off" : "Try another photo"}
          tone="error"
        >
          <Copy>{error}</Copy>
          {denied && !denyCamera && process.env.EXPO_OS !== "web" && (
            <Button
              label="Open device settings"
              variant="text"
              onPress={() =>
                void Linking.openSettings().catch(() =>
                  setError(
                    "Open your device settings manually to enable camera access.",
                  ),
                )
              }
            />
          )}
        </Notice>
      )}
      <Copy kind="eyebrow">OR EXPLORE WITH A SAMPLE</Copy>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
        {(Object.keys(sampleNames) as Sample[]).map((sample) => (
          <Pressable
            key={sample}
            accessibilityRole="button"
            accessibilityLabel={`Use ${sampleNames[sample].toLowerCase()} sample`}
            aria-pressed={photo?.sample === sample}
            aria-disabled={busy || picking}
            accessibilityState={{
              selected: photo?.sample === sample,
              disabled: busy || picking,
            }}
            disabled={busy || picking}
            onPress={() => {
              setError(undefined);
              void onChange({
                id: makeId(),
                label: `${sampleNames[sample]} sample`,
                sample,
              });
            }}
            style={({ pressed }) => ({
              flexGrow: 1,
              flexBasis: 140,
              opacity: pressed ? 0.75 : 1,
              borderRadius: 12,
              borderWidth: 2,
              borderColor:
                photo?.sample === sample ? colors.accent : colors.line,
              padding: 4,
              backgroundColor: "#fff",
            })}
          >
            <Image
              source={roomSources[sample]}
              contentFit="cover"
              style={{ width: "100%", aspectRatio: 1.7, borderRadius: 8 }}
              accessible={false}
            />
            <View
              style={{ minHeight: 48, padding: 8, justifyContent: "center" }}
            >
              <Copy
                kind="small"
                style={{ color: colors.ink, fontWeight: "600" }}
              >
                {sampleNames[sample]}
                {photo?.sample === sample ? " · Selected" : ""}
              </Copy>
            </View>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

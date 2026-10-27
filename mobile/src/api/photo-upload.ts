import { Asset } from "expo-asset";
import type { Photo } from "../domain/model";
import { roomSources } from "../domain/samples";

export async function appendPhoto(form: FormData, photo: Photo) {
  let uri = photo.uri;
  if (photo.sample) {
    const asset = await Asset.fromModule(
      roomSources[photo.sample],
    ).downloadAsync();
    uri = asset.localUri || asset.uri;
  }
  if (!uri)
    throw new Error(
      "The saved photo is unavailable. Choose a new photo to start an assessment.",
    );
  const type = uri.match(/\.png(?:\?|$)/i)
    ? "image/png"
    : uri.match(/\.webp(?:\?|$)/i)
      ? "image/webp"
      : "image/jpeg";
  form.append("photo", {
    uri,
    type,
    name:
      type === "image/png"
        ? "room.png"
        : type === "image/webp"
          ? "room.webp"
          : "room.jpg",
  } as unknown as Blob);
}

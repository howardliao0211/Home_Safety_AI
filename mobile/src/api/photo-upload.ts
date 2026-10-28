import { Asset } from "expo-asset";
import { File } from "expo-file-system";
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
  // SDK 58's default Expo fetch reads file bytes; RN URI descriptors are unsupported.
  form.append("photo", new File(uri));
}

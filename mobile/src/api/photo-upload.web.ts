import { Asset } from "expo-asset";
import type { Photo } from "../domain/model";
import { roomSources } from "../domain/samples";

export async function appendPhoto(form: FormData, photo: Photo) {
  const uri = photo.sample
    ? Asset.fromModule(roomSources[photo.sample]).uri
    : photo.uri;
  if (!uri) throw new Error("The saved photo is unavailable. Choose it again.");
  const response = await fetch(uri);
  if (!response.ok)
    throw new Error("The photo could not be read. Choose it again.");
  const blob = await response.blob();
  if (blob.size > 10 * 1024 * 1024)
    throw new Error("Choose a photo smaller than 10 MiB.");
  form.append("photo", blob, "room.jpg");
}

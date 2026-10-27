import type { Photo } from "../domain/model";
export async function retainPhoto(photo: Photo): Promise<Photo> {
  if (!photo.uri || photo.sample || photo.uri.startsWith("data:")) return photo;
  const response = await fetch(photo.uri);
  if (!response.ok)
    throw new Error("This photo could not be read. Please select it again.");
  const blob = await response.blob();
  const uri = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () =>
      reject(
        new Error("This photo could not be saved. Please select it again."),
      );
    reader.readAsDataURL(blob);
  });
  return { ...photo, uri };
}
export async function cleanPhotos(_retained: Photo[]) {
  /* Photos are stored in the state transaction. */
}

import { Directory, File, Paths } from "expo-file-system";
import type { Photo } from "../domain/model";

export function createPhotoStorage(scope: string) {
  const directory = () =>
    new Directory(
      Paths.document,
      scope === "preview"
        ? "preview-photos"
        : `photos-${encodeURIComponent(scope)}`,
    );
  async function retainPhoto(photo: Photo): Promise<Photo> {
    if (!photo.uri || photo.sample) return photo;
    const folder = directory();
    folder.create({ intermediates: true, idempotent: true });
    const target = new File(folder, `${photo.id}.jpg`);
    new File(photo.uri).copy(target);
    return { ...photo, uri: target.uri };
  }
  async function cleanPhotos(retained: Photo[]) {
    const folder = directory();
    if (!folder.exists) return;
    const keep = new Set(retained.map((p) => p.uri));
    for (const file of folder.list())
      if (file instanceof File && !keep.has(file.uri)) file.delete();
  }

  async function removeLegacyPhotos() {
    for (const item of new Directory(Paths.document).list()) {
      if (item instanceof Directory && item.name.startsWith("api-photos-"))
        item.delete();
    }
  }
  return { retainPhoto, cleanPhotos, removeLegacyPhotos };
}

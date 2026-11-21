import { useEffect, useState } from "react";
import type { PhotoWithUrl } from "../../api/photos";

/** Loads the header photo: prefer the chosen cover, else the first photo. */
export function usePropertyHeaderPhoto(
  propertyId: string,
  loadPhotos: (propertyId: string) => Promise<PhotoWithUrl[]>,
): string | null {
  const [headerPhoto, setHeaderPhoto] = useState<string | null>(null);
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    loadPhotos(propertyId)
      .then((photos) => {
        if (!active) return;
        const chosen = photos.find((p) => p.photo.is_cover) ?? photos[0];
        setHeaderPhoto(chosen?.display_url ?? null);
      })
      .catch(() => {
        if (active) setHeaderPhoto(null);
      });
    return () => {
      active = false;
    };
  }, [loadPhotos, propertyId]);
  return headerPhoto;
}

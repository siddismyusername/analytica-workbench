import type { PutBlobResult } from "@vercel/blob";
import { upload } from "@vercel/blob/client";

export type DatasetUploadProgress = {
  loaded: number;
  total: number;
  percentage: number;
};

export async function uploadDataset(
  file: File,
  onProgress?: (progress: DatasetUploadProgress) => void,
): Promise<PutBlobResult> {
  return upload(`datasets/source/${file.name}`, file, {
    access: "private",
    handleUploadUrl: "/api/uploads",
    multipart: true,
    onUploadProgress: onProgress,
  });
}

import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json()) as HandleUploadBody;

  try {
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        const lower = pathname.toLowerCase();
        if (!lower.endsWith(".csv") && !lower.endsWith(".parquet")) {
          throw new Error("Only CSV and Parquet datasets are supported.");
        }

        return {
          allowedContentTypes: [
            "text/csv",
            "application/csv",
            "application/vnd.apache.parquet",
            "application/octet-stream",
          ],
          addRandomSuffix: true,
          allowOverwrite: false,
        };
      },
      onUploadCompleted: async () => {
        // Dataset registration is explicit: the browser submits the returned
        // private Blob reference to the Python API after upload completes.
      },
    });

    return Response.json(response);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload token request failed.";
    return Response.json({ error: message }, { status: 400 });
  }
}

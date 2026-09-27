import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

const SOURCE_PREFIX = "datasets/source/";

function configuredMaximum(): number | undefined {
  const raw = process.env.ANALYTICA_MAX_UPLOAD_BYTES;
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function uploadSigningEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" ||
    process.env.ANALYTICA_UPLOAD_SIGNING_ENABLED === "true"
  );
}

export async function POST(request: Request): Promise<Response> {
  if (!uploadSigningEnabled()) {
    return Response.json(
      { error: "Upload signing is disabled until production authentication is configured." },
      { status: 503 },
    );
  }

  const body = (await request.json()) as HandleUploadBody;

  try {
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        if (!pathname.startsWith(SOURCE_PREFIX)) {
          throw new Error("Invalid dataset upload path.");
        }
        const relative = pathname.slice(SOURCE_PREFIX.length);
        const segments = relative.split("/");
        if (segments.length !== 2) {
          throw new Error("Invalid dataset upload path.");
        }
        const [format, filename] = segments;
        if (
          !filename ||
          filename.includes("\\") ||
          filename.includes("..")
        ) {
          throw new Error("Invalid dataset filename.");
        }

        const lower = filename.toLowerCase();
        const formatMatches =
          (format === "csv" && lower.endsWith(".csv")) ||
          (format === "parquet" && lower.endsWith(".parquet"));
        if (!formatMatches) {
          throw new Error("Only CSV and Parquet datasets are supported.");
        }

        return {
          allowedContentTypes: [
            "text/csv",
            "application/csv",
            "application/vnd.apache.parquet",
            "application/octet-stream",
          ],
          maximumSizeInBytes: configuredMaximum(),
          addRandomSuffix: true,
          allowOverwrite: false,
        };
      },
      onUploadCompleted: async () => {
        // Registration remains explicit: the browser sends only the returned
        // Blob pathname to FastAPI, which verifies metadata directly in storage.
      },
    });

    return Response.json(response);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload token request failed.";
    return Response.json({ error: message }, { status: 400 });
  }
}

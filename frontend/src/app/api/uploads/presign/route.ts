import { issueSignedToken, presignUrl } from "@vercel/blob";
import { NextResponse } from "next/server";

const UPLOAD_TTL_MS = 15 * 60 * 1000;

type PresignRequest = {
  filename?: unknown;
  size?: unknown;
};

function uploadPolicyEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" ||
    process.env.ANALYTICA_UPLOAD_SIGNING_ENABLED === "true"
  );
}

function sourceKind(filename: string): {
  extension: ".csv" | ".parquet";
  contentType: string;
} | null {
  const normalized = filename.toLowerCase();
  if (normalized.endsWith(".csv")) {
    return { extension: ".csv", contentType: "text/csv" };
  }
  if (normalized.endsWith(".parquet")) {
    return {
      extension: ".parquet",
      contentType: "application/vnd.apache.parquet",
    };
  }
  return null;
}

function configuredMaximum(): number | null {
  const raw = process.env.ANALYTICA_MAX_UPLOAD_BYTES;
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!uploadPolicyEnabled()) {
    return NextResponse.json(
      { error: "Upload signing is disabled until production authentication is configured." },
      { status: 503 },
    );
  }

  let body: PresignRequest;
  try {
    body = (await request.json()) as PresignRequest;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (typeof body.filename !== "string" || body.filename.length === 0) {
    return NextResponse.json({ error: "filename is required." }, { status: 400 });
  }
  if (
    typeof body.size !== "number" ||
    !Number.isSafeInteger(body.size) ||
    body.size <= 0
  ) {
    return NextResponse.json({ error: "size must be a positive integer." }, { status: 400 });
  }

  const kind = sourceKind(body.filename);
  if (!kind) {
    return NextResponse.json(
      { error: "Only CSV and Parquet files are currently supported." },
      { status: 415 },
    );
  }

  const productMaximum = configuredMaximum();
  if (productMaximum !== null && body.size > productMaximum) {
    return NextResponse.json(
      { error: "File exceeds the configured product upload limit." },
      { status: 413 },
    );
  }

  const storageKey = `raw/${crypto.randomUUID()}/source${kind.extension}`;
  const validUntil = Date.now() + UPLOAD_TTL_MS;
  const constraints = {
    allowedContentTypes: [kind.contentType],
    maximumSizeInBytes: body.size,
  };

  try {
    const signedToken = await issueSignedToken({
      pathname: storageKey,
      operations: ["put"],
      validUntil,
      ...constraints,
    });
    const { presignedUrl } = await presignUrl(signedToken, {
      operation: "put",
      pathname: storageKey,
      access: "private",
      validUntil,
      allowOverwrite: false,
      addRandomSuffix: false,
      ...constraints,
    });

    return NextResponse.json({
      uploadUrl: presignedUrl,
      storageKey,
      contentType: kind.contentType,
      expiresAt: new Date(validUntil).toISOString(),
    });
  } catch (error) {
    console.error("Failed to issue private Blob upload URL", error);
    return NextResponse.json(
      { error: "Could not initialize upload." },
      { status: 503 },
    );
  }
}

import { issueSignedToken, presignUrl } from "@vercel/blob";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

type UploadRequest = {
  filename?: unknown;
  size?: unknown;
};

const FIFTEEN_MINUTES_MS = 15 * 60 * 1000;

function classifyFile(filename: string): { contentType: string } | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".csv")) {
    return { contentType: "text/csv" };
  }
  if (lower.endsWith(".parquet")) {
    return { contentType: "application/vnd.apache.parquet" };
  }
  return null;
}

function safeFilename(filename: string): string {
  const basename = filename.split(/[\\/]/).pop() ?? "dataset";
  const normalized = basename.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 160);
  return normalized || "dataset";
}

function configuredUploadLimit(): number | null {
  const raw = process.env.MAX_UPLOAD_BYTES?.trim();
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error("MAX_UPLOAD_BYTES must be a positive integer when configured");
  }
  return value;
}

function signingEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" ||
    process.env.ANALYTICA_UPLOAD_SIGNING_ENABLED === "true"
  );
}

export async function POST(request: NextRequest) {
  if (!signingEnabled()) {
    return NextResponse.json(
      { error: "Upload signing is disabled until production authentication is configured" },
      { status: 503 },
    );
  }

  let body: UploadRequest;
  try {
    body = (await request.json()) as UploadRequest;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (typeof body.filename !== "string" || typeof body.size !== "number") {
    return NextResponse.json(
      { error: "filename and numeric size are required" },
      { status: 400 },
    );
  }
  if (!Number.isSafeInteger(body.size) || body.size <= 0) {
    return NextResponse.json({ error: "size must be a positive integer" }, { status: 400 });
  }

  const filename = safeFilename(body.filename);
  const classification = classifyFile(filename);
  if (!classification) {
    return NextResponse.json(
      { error: "Only CSV and Parquet uploads are currently supported" },
      { status: 415 },
    );
  }

  let limit: number | null;
  try {
    limit = configuredUploadLimit();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Invalid upload configuration";
    return NextResponse.json({ error: message }, { status: 500 });
  }
  if (limit !== null && body.size > limit) {
    return NextResponse.json({ error: "Upload exceeds configured size limit" }, { status: 413 });
  }

  const uploadId = randomUUID();
  const pathname = `raw/${uploadId}/${filename}`;
  const validUntil = Date.now() + FIFTEEN_MINUTES_MS;
  const contentType = classification.contentType;

  if (process.env.NODE_ENV !== "production" && process.env.ANALYTICA_LOCAL_UPLOADS === "true") {
    const apiUrl = process.env.NEXT_PUBLIC_ANALYTICA_API_URL?.trim();
    if (!apiUrl) {
      return NextResponse.json(
        { error: "NEXT_PUBLIC_ANALYTICA_API_URL is required for local uploads" },
        { status: 500 },
      );
    }
    const presignedUrl = new URL(
      `/api/v1/datasets/uploads/local/${uploadId}/${encodeURIComponent(filename)}`,
      apiUrl,
    ).toString();
    return NextResponse.json({ pathname, presignedUrl, expiresAt: null, contentType });
  }

  const signedToken = await issueSignedToken({
    pathname,
    operations: ["put"],
    validUntil,
    allowedContentTypes: [contentType],
    maximumSizeInBytes: body.size,
  });
  const { presignedUrl } = await presignUrl(signedToken, {
    pathname,
    operation: "put",
    access: "private",
    validUntil,
    allowedContentTypes: [contentType],
    maximumSizeInBytes: body.size,
    allowOverwrite: false,
    addRandomSuffix: false,
  });

  return NextResponse.json({
    pathname,
    presignedUrl,
    expiresAt: new Date(validUntil).toISOString(),
    contentType,
  });
}

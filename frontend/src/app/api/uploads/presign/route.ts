import { issueSignedToken, presignUrl } from "@vercel/blob";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

type SourceFormat = "csv" | "parquet";

type UploadRequest = {
  filename?: unknown;
  contentType?: unknown;
  size?: unknown;
};

const FIFTEEN_MINUTES_MS = 15 * 60 * 1000;

function classifyFile(filename: string): {
  sourceFormat: SourceFormat;
  defaultContentType: string;
} | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".csv")) {
    return { sourceFormat: "csv", defaultContentType: "text/csv" };
  }
  if (lower.endsWith(".parquet")) {
    return {
      sourceFormat: "parquet",
      defaultContentType: "application/vnd.apache.parquet",
    };
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

export async function POST(request: NextRequest) {
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

  const requestedType =
    typeof body.contentType === "string" && body.contentType.trim()
      ? body.contentType.trim()
      : classification.defaultContentType;
  const pathname = `raw/${randomUUID()}/${filename}`;
  const validUntil = Date.now() + FIFTEEN_MINUTES_MS;

  const signedToken = await issueSignedToken({
    pathname,
    operations: ["put"],
    validUntil,
    allowedContentTypes: [requestedType],
    maximumSizeInBytes: body.size,
  });
  const { presignedUrl } = await presignUrl(signedToken, {
    pathname,
    operation: "put",
    access: "private",
    validUntil,
    allowedContentTypes: [requestedType],
    maximumSizeInBytes: body.size,
    allowOverwrite: false,
    addRandomSuffix: false,
  });

  return NextResponse.json({
    pathname,
    presignedUrl,
    expiresAt: new Date(validUntil).toISOString(),
    sourceFormat: classification.sourceFormat,
    contentType: requestedType,
  });
}

"""Durable result exports assembled only from saved snapshots and immutable versions."""

import hashlib
import html
import json
import math
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import duckdb

from analytica_api.domain.control_plane import (
    ArtifactRecord,
    JobRecord,
    JobStatus,
    SavedResultRecord,
)
from analytica_api.domain.datasets import DatasetSchema
from analytica_api.queue.contracts import JobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef


class ResultsValidationError(ValueError):
    pass


def _ref(artifact: ArtifactRecord) -> StorageObjectRef:
    return StorageObjectRef(
        key=artifact.storage_key,
        byte_size=artifact.byte_size,
        content_type=artifact.content_type,
        checksum_sha256=artifact.checksum_sha256,
    )


def _text(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _table(rows: list[tuple[Any, Any]]) -> str:
    return (
        "<table><tbody>"
        + "".join(
            f"<tr><th>{_text(label)}</th><td>{_text(value)}</td></tr>" for label, value in rows
        )
        + "</tbody></table>"
    )


def chart_svg(payload: dict[str, Any]) -> str:
    """Render a compact, standalone vector figure from a saved chart snapshot."""
    chart_type = payload.get("chart_type")
    data = payload.get("data", [])[:100]
    title = _text(payload.get("title", "Chart"))
    marks: list[str] = []
    if chart_type in {"bar", "histogram"}:
        values = [
            float(item.get("value" if chart_type == "bar" else "count") or 0) for item in data
        ]
        peak = max([abs(value) for value in values] + [1])
        width = 640 / max(len(values), 1)
        for index, value in enumerate(values):
            height = max(0, 280 * value / peak)
            left = 60 + index * width + 2
            bar_width = max(width - 4, 1)
            marks.append(
                f'<rect x="{left:.2f}" y="{355 - height:.2f}" '
                f'width="{bar_width:.2f}" height="{height:.2f}" fill="#4766d7"/>'
            )
            if len(values) <= 12:
                label = data[index].get("category")
                if chart_type == "histogram":
                    label = f"{float(data[index]['start']):.3g}"
                marks.append(
                    f'<text x="{left + bar_width / 2:.2f}" y="373" '
                    f'text-anchor="middle" font-size="10" fill="#53617e">'
                    f"{_text(label)}</text>"
                )
    elif chart_type in {"line", "scatter", "qq"}:
        points = []
        for index, item in enumerate(data):
            try:
                x = float(item.get("x", index)) if chart_type != "line" else float(index)
                y = float(item["y"])
                if math.isfinite(x) and math.isfinite(y):
                    points.append((x, y))
            except (TypeError, ValueError, KeyError):
                continue
        if points:
            xmin, xmax = min(x for x, _ in points), max(x for x, _ in points)
            ymin, ymax = min(y for _, y in points), max(y for _, y in points)
            coordinates = [
                (
                    60 + (x - xmin) * 640 / (xmax - xmin or 1),
                    355 - (y - ymin) * 280 / (ymax - ymin or 1),
                )
                for x, y in points
            ]
            if chart_type == "line":
                path = " ".join(
                    f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}"
                    for i, (x, y) in enumerate(coordinates)
                )
                marks.append(f'<path d="{path}" fill="none" stroke="#4766d7" stroke-width="2"/>')
            else:
                marks.extend(
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#4766d7"/>'
                    for x, y in coordinates
                )
    elif chart_type == "box":
        boxes = [item for item in data if len(item.get("values", [])) == 5]
        all_values = [float(value) for item in boxes for value in item["values"]]
        if all_values:
            minimum, maximum = min(all_values), max(all_values)

            def scale(value: float) -> float:
                return 355 - (float(value) - minimum) * 280 / (maximum - minimum or 1)

            spacing = 640 / len(boxes)
            for index, item in enumerate(boxes):
                low, q1, median, q3, high = item["values"]
                x = 60 + (index + 0.5) * spacing
                top, bottom = scale(q3), scale(q1)
                marks.extend(
                    [
                        f'<path d="M{x:.2f} {scale(low):.2f}V{scale(high):.2f}" stroke="#4766d7"/>',
                        f'<rect x="{x - min(spacing / 4, 35):.2f}" y="{top:.2f}" '
                        f'width="{min(spacing / 2, 70):.2f}" height="{bottom - top:.2f}" '
                        'fill="#dfe6ff" stroke="#4766d7"/>',
                        f'<path d="M{x - min(spacing / 4, 35):.2f} {scale(median):.2f}'
                        f'H{x + min(spacing / 4, 35):.2f}" stroke="#2748be" stroke-width="2"/>',
                        f'<text x="{x:.2f}" y="373" text-anchor="middle" '
                        f'font-size="10">{_text(item.get("category"))}</text>',
                    ]
                )
    elif chart_type == "heatmap":
        xs = list(dict.fromkeys(str(item.get("x", "")) for item in data))
        ys = list(dict.fromkeys(str(item.get("y", "")) for item in data))
        cell_width = 640 / max(len(xs), 1)
        cell_height = 280 / max(len(ys), 1)
        for item in data:
            value = item.get("value")
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            intensity = min(1, abs(float(value)))
            fill = f"rgb({int(240 - 150 * intensity)},{int(244 - 115 * intensity)},255)"
            x = 60 + xs.index(str(item.get("x", ""))) * cell_width
            y = 75 + ys.index(str(item.get("y", ""))) * cell_height
            marks.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_width:.2f}" '
                f'height="{cell_height:.2f}" fill="{fill}" stroke="white"/>'
            )
            if len(xs) <= 8 and len(ys) <= 8:
                marks.append(
                    f'<text x="{x + cell_width / 2:.2f}" y="{y + cell_height / 2:.2f}" '
                    f'text-anchor="middle" font-size="12">{float(value):.2f}</text>'
                )
    else:
        raise ResultsValidationError("vector export is not available for this chart type")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="420" '
        'viewBox="0 0 760 420" role="img" aria-label="'
        + title
        + '"><rect width="760" height="420" fill="white"/>'
        + f'<text x="60" y="38" fill="#1a2450" '
        f'font-family="sans-serif" font-size="18">{title}</text>'
        + '<path d="M60 75V355H700" fill="none" stroke="#9ba6c0" stroke-width="1"/>'
        + "".join(marks)
        + f'<text x="380" y="397" text-anchor="middle" font-family="sans-serif" '
        f'font-size="12">{_text(payload.get("x_label", ""))}</text>'
        + f'<text x="16" y="215" transform="rotate(-90 16 215)" '
        f'text-anchor="middle" font-family="sans-serif" font-size="12">'
        f"{_text(payload.get('y_label', ''))}</text>" + "</svg>"
    )


def report_html(
    *,
    title: str,
    dataset_name: str,
    version_number: int,
    version_id: UUID,
    results: list[SavedResultRecord],
) -> str:
    sections: list[str] = []
    for index, result in enumerate(results, 1):
        body = result.payload
        rows: list[tuple[Any, Any]] = [
            ("Result ID", str(result.id)),
            ("Result type", result.kind.title()),
            ("Saved", result.created_at.isoformat()),
            ("Dataset version", str(result.dataset_version_id)),
            (
                "Originating job",
                str(result.source_job_id) if result.source_job_id else "Interactive run",
            ),
            ("Configuration", json.dumps(result.configuration, ensure_ascii=False, sort_keys=True)),
        ]
        if result.kind == "analysis":
            rows.extend(
                [
                    ("Method", body.get("test_name")),
                    ("Sample size", body.get("sample_size")),
                    (
                        "Statistic",
                        f"{body.get('statistic', {}).get('name')}: "
                        f"{body.get('statistic', {}).get('value')}",
                    ),
                    ("p-value", body.get("p_value")),
                    ("Effect size", json.dumps(body.get("effect_size"), ensure_ascii=False)),
                    (
                        "Confidence interval",
                        json.dumps(body.get("confidence_interval"), ensure_ascii=False),
                    ),
                    ("Interpretation", body.get("interpretation")),
                ]
            )
            for diagnostic in body.get("diagnostics", []):
                rows.append((f"Diagnostic: {diagnostic.get('name')}", diagnostic.get("message")))
            for warning in body.get("warnings", []):
                rows.append(("Warning", warning))
        elif result.kind == "model":
            rows.extend(
                [
                    ("Best algorithm", body.get("best_algorithm")),
                    ("Validation method", body.get("validation_method")),
                    ("Training / test rows", f"{body.get('train_rows')} / {body.get('test_rows')}"),
                    ("Excluded target rows", body.get("excluded_target_rows")),
                    ("Primary metric", body.get("primary_metric")),
                ]
            )
            for candidate in body.get("candidates", []):
                rows.append(
                    (
                        f"Candidate: {candidate.get('algorithm')}",
                        json.dumps(candidate.get("metrics", {}), ensure_ascii=False),
                    )
                )
            rows.append(
                ("Explanation", json.dumps(body.get("explanation", []), ensure_ascii=False))
            )
            rows.append(("Interpretation note", body.get("explanation_note")))
        elif result.kind == "chart":
            rows.extend(
                [
                    ("Chart type", body.get("chart_type")),
                    ("X axis", body.get("x_label")),
                    ("Y axis", body.get("y_label")),
                    ("Chart data", json.dumps(body.get("data", []), ensure_ascii=False)),
                ]
            )
        figures = []
        charts = (
            body.get("visualizations", [])
            if result.kind == "analysis"
            else ([body] if result.kind == "chart" else [])
        )
        for chart in charts:
            with suppress(ResultsValidationError):
                figures.append(
                    f"<figure>{chart_svg(chart)}"
                    f"<figcaption>{_text(chart.get('title'))}</figcaption></figure>"
                )
        sections.append(
            f"<section><h2>{index}. {_text(result.title)}</h2>"
            f"{_table(rows)}{''.join(figures)}</section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>" + _text(title) + "</title><style>"
        "body{font:15px/1.5 system-ui,sans-serif;color:#17213e;"
        "max-width:920px;margin:48px auto;padding:0 24px}"
        "h1{font-size:32px}h2{margin-top:42px;border-bottom:1px solid #cbd3e8;padding-bottom:8px}"
        "p.meta{color:#58647e}table{border-collapse:collapse;width:100%;table-layout:fixed}"
        "th,td{padding:9px 12px;border-bottom:1px solid #e0e5f0;"
        "text-align:left;vertical-align:top;overflow-wrap:anywhere}"
        "th{width:30%;color:#53617e}figure{margin:25px 0}svg{max-width:100%;height:auto}"
        "@media print{body{margin:0}section{break-inside:avoid}h2{break-after:avoid}}"
        "</style></head><body><h1>" + _text(title) + "</h1>"
        '<p class="meta">Dataset: '
        + _text(dataset_name)
        + " · Version "
        + str(version_number)
        + " · Version ID "
        + _text(version_id)
        + "</p>"
        '<p class="meta">This report uses saved results from the immutable dataset '
        "version shown above. Result IDs, methods and settings are preserved in each section.</p>"
        + "".join(sections)
        + "</body></html>"
    )


class ResultsService:
    def __init__(
        self, *, control_plane: ControlPlaneService, store: ArtifactStore, queue: JobQueue
    ):
        self.control_plane = control_plane
        self.store = store
        self.queue = queue

    def list_results(self, version_id: UUID) -> tuple[SavedResultRecord, ...]:
        """Include completed model runs created before the result registry existed."""
        saved = self.control_plane.list_results(version_id)
        existing_jobs = {item.source_job_id for item in saved}
        for job in self.control_plane.list_jobs_for_version(version_id, "model_train"):
            if job.status != JobStatus.SUCCEEDED or job.id in existing_jobs:
                continue
            artifact = self.control_plane.get_artifact_for_job_kind(job.id, "model_evaluation")
            with TemporaryDirectory(prefix="analytica-model-backfill-") as directory:
                path = self.store.materialize(_ref(artifact), Path(directory) / "evaluation.json")
                evaluation = json.loads(path.read_text(encoding="utf-8"))
            configuration = job.operation_payload["configuration"]
            self.control_plane.save_result(
                version_id=version_id,
                kind="model",
                title=(
                    f"{configuration['problem_type'].title()} · "
                    f"{evaluation['best_algorithm'].replace('_', ' ')}"
                ),
                fingerprint=hashlib.sha256(f"model:{job.id}".encode()).hexdigest(),
                configuration=configuration,
                payload=evaluation,
                source_job_id=job.id,
            )
        return self.control_plane.list_results(version_id)

    async def submit(
        self, version_id: UUID, *, kind: str, title: str = "", result_ids: list[UUID] | None = None
    ) -> JobRecord | ArtifactRecord:
        version = self.control_plane.get_version(version_id)
        if kind == "dataset_parquet":
            return self.control_plane.get_artifact_for_version_kind(version_id, "canonical_dataset")
        if kind not in {"dataset_csv", "report_html", "chart_svg"}:
            raise ResultsValidationError("unsupported export format")
        ids = result_ids or []
        if kind == "report_html":
            if not ids or len(ids) > 30 or len(ids) != len(set(ids)):
                raise ResultsValidationError("select 1 to 30 distinct results")
            if not title.strip() or len(title.strip()) > 160:
                raise ResultsValidationError("report title must contain 1 to 160 characters")
        elif kind == "chart_svg":
            if len(ids) != 1 or self.control_plane.get_result(ids[0]).kind != "chart":
                raise ResultsValidationError("select one saved chart")
        elif ids:
            raise ResultsValidationError("dataset export does not accept result IDs")
        for result_id in ids:
            if self.control_plane.get_result(result_id).dataset_version_id != version_id:
                raise ResultsValidationError("all selected results must belong to this version")
        payload = {
            "kind": kind,
            "title": title.strip(),
            "result_ids": [str(value) for value in ids],
        }
        digest = hashlib.sha256(
            json.dumps([str(version_id), payload], sort_keys=True).encode()
        ).hexdigest()
        job = self.control_plane.create_job(
            kind="results_export",
            idempotency_key=f"export:{digest}",
            dataset_id=version.dataset_id,
            input_version_id=version_id,
            operation_payload=payload,
        )
        if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
            try:
                await self.queue.publish_export(
                    job.id, idempotency_key=f"{job.idempotency_key}:attempt:{job.attempt_count + 1}"
                )
            except Exception:
                if self.control_plane.get_job(job.id).status != JobStatus.FAILED:
                    raise
            job = self.control_plane.get_job(job.id)
        return job


class ExportWorker:
    def __init__(self, *, control_plane: ControlPlaneService, store: ArtifactStore):
        self.control_plane = control_plane
        self.store = store

    def run(self, job_id: UUID) -> None:
        job = self.control_plane.get_job(job_id)
        if job.kind != "results_export" or job.input_version_id is None or job.dataset_id is None:
            raise ResultsValidationError("job is not an export")
        if job.status == JobStatus.SUCCEEDED:
            return
        if job.status == JobStatus.CANCELLED:
            raise ResultsValidationError("cancelled export cannot resume")
        try:
            if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
                job = self.control_plane.transition_job(job_id, JobStatus.RUNNING)
            version = self.control_plane.get_version(job.input_version_id)
            if version.dataset_id != job.dataset_id:
                raise ResultsValidationError("export version does not belong to dataset")
            kind = job.operation_payload["kind"]
            ids = [UUID(value) for value in job.operation_payload.get("result_ids", [])]
            results = [self.control_plane.get_result(value) for value in ids]
            if any(result.dataset_version_id != version.id for result in results):
                raise ResultsValidationError("export contains results from another version")
            with TemporaryDirectory(prefix="analytica-export-") as directory:
                root = Path(directory)
                if kind == "dataset_csv":
                    source = self.control_plane.get_artifact_for_version_kind(
                        version.id, "canonical_dataset"
                    )
                    path = self.store.materialize(_ref(source), root / "dataset.parquet")
                    output = root / "dataset.csv"
                    schema = DatasetSchema.model_validate(version.schema_snapshot)
                    select_columns = ", ".join(
                        '"'
                        + column.physical_name.replace('"', '""')
                        + '" AS "'
                        + column.display_name.replace('"', '""')
                        + '"'
                        for column in schema.columns
                    )
                    escaped_source = str(path).replace("'", "''")
                    escaped_output = str(output).replace("'", "''")
                    with duckdb.connect() as connection:
                        connection.execute(
                            f"COPY (SELECT {select_columns} FROM read_parquet('{escaped_source}')) "
                            f"TO '{escaped_output}' (HEADER, FORMAT CSV)"
                        )
                    filename, content_type = "dataset.csv", "text/csv; charset=utf-8"
                elif kind == "report_html":
                    if not results or len(results) > 30:
                        raise ResultsValidationError("report selection is invalid")
                    dataset = self.control_plane.get_dataset(version.dataset_id)
                    output = root / "report.html"
                    output.write_text(
                        report_html(
                            title=job.operation_payload["title"],
                            dataset_name=dataset.name,
                            version_number=version.version_number,
                            version_id=version.id,
                            results=results,
                        ),
                        encoding="utf-8",
                    )
                    filename, content_type = "report.html", "text/html; charset=utf-8"
                elif kind == "chart_svg":
                    if len(results) != 1 or results[0].kind != "chart":
                        raise ResultsValidationError("chart selection is invalid")
                    output = root / "chart.svg"
                    output.write_text(chart_svg(results[0].payload), encoding="utf-8")
                    filename, content_type = "chart.svg", "image/svg+xml"
                else:
                    raise ResultsValidationError("unsupported export type")
                key = f"datasets/{job.dataset_id}/exports/{job.id}/{filename}"
                try:
                    ref = self.store.put_file(output, key=key, content_type=content_type)
                except StorageError as upload_error:
                    try:
                        ref = self.store.stat(key)
                    except StorageError as stat_error:
                        raise upload_error from stat_error
                self.control_plane.register_job_artifact(job_id=job.id, kind=kind, object_ref=ref)
            self.control_plane.transition_job(job.id, JobStatus.SUCCEEDED)
        except Exception as exc:
            current = self.control_plane.get_job(job_id)
            if current.status == JobStatus.RUNNING:
                self.control_plane.transition_job(
                    job_id,
                    JobStatus.FAILED,
                    error_detail={"type": type(exc).__name__, "message": str(exc)[:2000]},
                )
            raise

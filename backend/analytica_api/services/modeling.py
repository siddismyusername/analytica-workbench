"""Version-bound supervised modeling with durable job and artifact results."""

import hashlib
import json
import math
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from uuid import UUID

import numpy as np
import pandas as pd
import sklearn
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from analytica_api.domain.control_plane import (
    ArtifactRecord,
    DatasetVersionState,
    JobRecord,
    JobStatus,
)
from analytica_api.domain.datasets import DatasetSchema
from analytica_api.queue.contracts import JobQueue
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef

Algorithm = Literal["linear", "decision_tree", "random_forest"]
ProblemType = Literal["regression", "classification"]


class ModelValidationError(ValueError):
    pass


class ModelRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_type: ProblemType
    target_column_id: str = Field(min_length=1)
    feature_column_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    algorithms: tuple[Algorithm, ...] = ("linear", "decision_tree", "random_forest")
    test_fraction: float = Field(default=0.2, ge=0.1, le=0.4)
    random_seed: int = Field(default=42, ge=0, le=2**32 - 1)
    cross_validation: bool = False

    @model_validator(mode="after")
    def validate_columns(self) -> "ModelRunConfig":
        if self.target_column_id in self.feature_column_ids:
            raise ValueError("target cannot also be a predictor")
        if len(self.feature_column_ids) != len(set(self.feature_column_ids)):
            raise ValueError("predictors must be unique")
        if not self.algorithms or len(self.algorithms) != len(set(self.algorithms)):
            raise ValueError("select at least one unique candidate model")
        return self


def _artifact_ref(artifact: ArtifactRecord) -> StorageObjectRef:
    return StorageObjectRef(
        key=artifact.storage_key,
        byte_size=artifact.byte_size,
        content_type=artifact.content_type,
        checksum_sha256=artifact.checksum_sha256,
    )


def _validate_schema(config: ModelRunConfig, schema: DatasetSchema) -> None:
    columns = schema.by_id()
    if config.target_column_id not in columns:
        raise ModelValidationError("target column does not exist in this version")
    if any(column_id not in columns for column_id in config.feature_column_ids):
        raise ModelValidationError("a predictor does not exist in this version")
    target_type = columns[config.target_column_id].data_type
    if config.problem_type == "regression" and target_type not in {"integer", "float"}:
        raise ModelValidationError("regression requires a numeric target")
    if config.problem_type == "classification" and target_type not in {
        "boolean",
        "string",
        "categorical",
        "integer",
    }:
        raise ModelValidationError("classification requires a categorical target")
    if any(
        columns[column_id].data_type not in {"boolean", "integer", "float", "string", "categorical"}
        for column_id in config.feature_column_ids
    ):
        raise ModelValidationError("predictors must be numeric, boolean, or categorical")


def _preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    transforms: list[tuple[str, Any, list[str]]] = []
    if numeric:
        transforms.append(
            (
                "numeric",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                numeric,
            )
        )
    if categorical:
        transforms.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            )
        )
    return ColumnTransformer(transforms)


def _estimator(algorithm: str, problem_type: ProblemType, seed: int) -> Any:
    if algorithm == "baseline":
        return (
            DummyRegressor(strategy="mean")
            if problem_type == "regression"
            else DummyClassifier(strategy="most_frequent")
        )
    if algorithm == "linear":
        return (
            LinearRegression()
            if problem_type == "regression"
            else LogisticRegression(max_iter=1000, random_state=seed)
        )
    if algorithm == "decision_tree":
        return (
            DecisionTreeRegressor(max_depth=8, random_state=seed)
            if problem_type == "regression"
            else DecisionTreeClassifier(max_depth=8, random_state=seed)
        )
    if algorithm == "random_forest":
        return (
            RandomForestRegressor(n_estimators=100, max_depth=12, random_state=seed, n_jobs=1)
            if problem_type == "regression"
            else RandomForestClassifier(n_estimators=100, max_depth=12, random_state=seed, n_jobs=1)
        )
    raise ModelValidationError("unsupported candidate model")


def _metrics(
    problem_type: ProblemType,
    y_true: Any,
    predictions: Any,
    pipeline: Pipeline,
    features: pd.DataFrame,
) -> dict[str, Any]:
    if problem_type == "regression":
        return {
            "mae": float(mean_absolute_error(y_true, predictions)),
            "rmse": float(math.sqrt(mean_squared_error(y_true, predictions))),
            "r2": float(r2_score(y_true, predictions)),
        }
    labels = list(pipeline.named_steps["estimator"].classes_)
    result: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predictions)),
        "macro_f1": float(f1_score(y_true, predictions, average="macro", zero_division=0)),
        "class_labels": [str(label) for label in labels],
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=labels).tolist(),
    }
    if len(labels) == 2 and hasattr(pipeline, "predict_proba") and len(set(y_true)) == 2:
        result["roc_auc"] = float(roc_auc_score(y_true, pipeline.predict_proba(features)[:, 1]))
    return result


def _explanation(pipeline: Pipeline) -> list[dict[str, Any]]:
    estimator = pipeline.named_steps["estimator"]
    names = pipeline.named_steps["preprocess"].get_feature_names_out()
    if hasattr(estimator, "feature_importances_"):
        values = estimator.feature_importances_
    elif hasattr(estimator, "coef_"):
        coefficients = np.asarray(estimator.coef_)
        values = np.mean(np.abs(coefficients), axis=0) if coefficients.ndim > 1 else coefficients
    else:
        return []
    ranked = sorted(
        zip(names, values, strict=True), key=lambda item: abs(float(item[1])), reverse=True
    )
    return [{"feature": str(name), "value": float(value)} for name, value in ranked[:12]]


def train(
    config: ModelRunConfig, schema: DatasetSchema, path: Path, version_id: UUID
) -> tuple[dict[str, Any], Pipeline]:
    """Select candidates on training-only validation, then evaluate on untouched test rows."""
    _validate_schema(config, schema)
    columns = schema.by_id()
    target = columns[config.target_column_id].physical_name
    numeric = [
        columns[column_id].physical_name
        for column_id in config.feature_column_ids
        if columns[column_id].data_type in {"integer", "float"}
    ]
    categorical = [
        columns[column_id].physical_name
        for column_id in config.feature_column_ids
        if columns[column_id].data_type not in {"integer", "float"}
    ]
    feature_names = numeric + categorical
    frame = pd.read_parquet(path, columns=[target, *feature_names])
    total_rows = len(frame)
    if total_rows > 100_000:
        raise ModelValidationError("model runs currently support at most 100,000 rows")
    frame = frame.dropna(subset=[target])
    if len(frame) < 20:
        raise ModelValidationError("at least 20 rows with a target value are required")
    for name in numeric:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype(float)
    for name in categorical:
        frame[name] = (
            frame[name].map(lambda value: str(value) if pd.notna(value) else np.nan).astype(object)
        )
        if frame[name].nunique(dropna=True) > 100:
            raise ModelValidationError(f"predictor {name} has more than 100 categories")
    if any(frame[name].notna().sum() == 0 for name in feature_names):
        raise ModelValidationError("predictors cannot contain only missing values")
    if config.problem_type == "classification":
        frame[target] = frame[target].map(str)
        counts = frame[target].value_counts()
        if len(counts) < 2 or len(counts) > 20:
            raise ModelValidationError("classification requires 2 to 20 observed classes")
        if counts.min() < 2:
            raise ModelValidationError("each class needs at least two rows for a stratified split")
        stratify = frame[target]
    else:
        frame[target] = pd.to_numeric(frame[target], errors="coerce")
        if frame[target].nunique() < 2:
            raise ModelValidationError("regression target must have at least two distinct values")
        stratify = None
    x_train, x_test, y_train, y_test = train_test_split(
        frame[feature_names],
        frame[target],
        test_size=config.test_fraction,
        random_state=config.random_seed,
        stratify=stratify,
    )
    if config.problem_type == "classification" and set(y_train) != set(y_test):
        raise ModelValidationError("each class must appear in both train and test partitions")
    metric = "rmse" if config.problem_type == "regression" else "macro_f1"
    if not config.cross_validation:
        if config.problem_type == "classification" and y_train.value_counts().min() < 2:
            raise ModelValidationError("each class needs two training rows for validation")
        validation_fraction = max(
            0.2,
            len(set(y_train)) / len(y_train) if config.problem_type == "classification" else 0.2,
        )
        try:
            x_fit, x_validation, y_fit, y_validation = train_test_split(
                x_train,
                y_train,
                test_size=validation_fraction,
                random_state=config.random_seed,
                stratify=y_train if config.problem_type == "classification" else None,
            )
        except ValueError as exc:
            raise ModelValidationError("not enough training rows for validation") from exc
    candidates: list[dict[str, Any]] = []
    fitted: dict[str, Pipeline] = {}
    for algorithm in ("baseline", *config.algorithms):
        pipeline = Pipeline(
            [
                ("preprocess", _preprocessor(numeric, categorical)),
                ("estimator", _estimator(algorithm, config.problem_type, config.random_seed)),
            ]
        )
        if config.cross_validation:
            folds = 3
            if config.problem_type == "classification" and y_train.value_counts().min() < folds:
                raise ModelValidationError(
                    "cross-validation needs at least three training rows per class"
                )
            scoring = (
                "neg_root_mean_squared_error" if config.problem_type == "regression" else "f1_macro"
            )
            splitter = (
                KFold(n_splits=folds, shuffle=True, random_state=config.random_seed)
                if config.problem_type == "regression"
                else StratifiedKFold(n_splits=folds, shuffle=True, random_state=config.random_seed)
            )
            scores = cross_val_score(
                pipeline, x_train, y_train, cv=splitter, scoring=scoring, error_score="raise"
            )
            validation_score = float(
                -scores.mean() if config.problem_type == "regression" else scores.mean()
            )
            cv_score = validation_score
        else:
            pipeline.fit(x_fit, y_fit)
            validation_prediction = pipeline.predict(x_validation)
            validation_score = _metrics(
                config.problem_type,
                y_validation,
                validation_prediction,
                pipeline,
                x_validation,
            )[metric]
            cv_score = None
        pipeline.fit(x_train, y_train)
        prediction = pipeline.predict(x_test)
        candidates.append(
            {
                "algorithm": algorithm,
                "metrics": _metrics(config.problem_type, y_test, prediction, pipeline, x_test),
                "cv_score": cv_score,
                "validation_score": validation_score,
            }
        )
        fitted[algorithm] = pipeline
    winner = (
        min(candidates[1:], key=lambda item: item["validation_score"])
        if config.problem_type == "regression"
        else max(candidates[1:], key=lambda item: item["validation_score"])
    )
    best = fitted[winner["algorithm"]]
    result = {
        "version_id": str(version_id),
        "configuration": config.model_dump(mode="json"),
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "excluded_target_rows": total_rows - len(frame),
        "software": {"scikit_learn": sklearn.__version__},
        "primary_metric": metric,
        "validation_method": "3-fold training cross-validation"
        if config.cross_validation
        else "training holdout",
        "candidates": candidates,
        "best_algorithm": winner["algorithm"],
        "explanation": _explanation(best),
        "explanation_note": "Feature associations in this fitted model are not causal effects.",
    }
    return result, best


class DatasetModelService:
    def __init__(
        self, *, control_plane: ControlPlaneService, store: ArtifactStore, queue: JobQueue
    ):
        self.control_plane = control_plane
        self.store = store
        self.queue = queue

    async def submit(self, version_id: UUID, config: ModelRunConfig) -> JobRecord:
        version = self.control_plane.get_version(version_id)
        if version.state != DatasetVersionState.READY:
            raise ModelValidationError("model runs require a ready dataset version")
        if version.row_count > 100_000:
            raise ModelValidationError("model runs currently support at most 100,000 rows")
        _validate_schema(config, DatasetSchema.model_validate(version.schema_snapshot))
        payload = config.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps([str(version_id), payload], sort_keys=True).encode()
        ).hexdigest()
        job = self.control_plane.create_job(
            kind="model_train",
            idempotency_key=f"model:{digest}",
            dataset_id=version.dataset_id,
            input_version_id=version_id,
            operation_payload={"configuration": payload},
        )
        if job.kind != "model_train" or job.input_version_id != version_id:
            raise ControlPlaneError("idempotency key belongs to another operation")
        if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
            try:
                await self.queue.publish_model(
                    job.id, idempotency_key=f"{job.idempotency_key}:attempt:{job.attempt_count + 1}"
                )
            except Exception:
                if self.control_plane.get_job(job.id).status != JobStatus.FAILED:
                    raise
            job = self.control_plane.get_job(job.id)
        return job

    def result(self, job_id: UUID) -> dict[str, Any] | None:
        job = self.control_plane.get_job(job_id)
        if job.kind != "model_train":
            raise ModelValidationError("job is not a model run")
        if job.status != JobStatus.SUCCEEDED:
            return None
        artifact = self.control_plane.get_artifact_for_job_kind(job_id, "model_evaluation")
        with TemporaryDirectory(prefix="analytica-model-result-") as directory:
            path = self.store.materialize(
                _artifact_ref(artifact), Path(directory) / "evaluation.json"
            )
            return json.loads(path.read_text(encoding="utf-8"))


class ModelWorker:
    def __init__(self, *, control_plane: ControlPlaneService, store: ArtifactStore):
        self.control_plane = control_plane
        self.store = store

    def run(self, job_id: UUID) -> None:
        job = self.control_plane.get_job(job_id)
        if job.kind != "model_train" or job.input_version_id is None or job.dataset_id is None:
            raise ModelValidationError("job is not a model run")
        if job.status == JobStatus.SUCCEEDED:
            return
        if job.status == JobStatus.CANCELLED:
            raise ModelValidationError("cancelled model run cannot resume")
        try:
            if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
                job = self.control_plane.transition_job(job_id, JobStatus.RUNNING)
            version = self.control_plane.get_version(job.input_version_id)
            if version.dataset_id != job.dataset_id:
                raise ModelValidationError("model run references another dataset")
            config = ModelRunConfig.model_validate(job.operation_payload["configuration"])
            schema = DatasetSchema.model_validate(version.schema_snapshot)
            artifact = self.control_plane.get_artifact_for_version_kind(
                version.id, "canonical_dataset"
            )
            with TemporaryDirectory(prefix="analytica-model-") as directory:
                root = Path(directory)
                path = self.store.materialize(_artifact_ref(artifact), root / "dataset.parquet")
                evaluation, best_pipeline = train(config, schema, path, version.id)
                evaluation_path = root / "evaluation.json"
                evaluation_path.write_text(
                    json.dumps(evaluation, allow_nan=False), encoding="utf-8"
                )
                model_path = root / "pipeline.pkl"
                model_path.write_bytes(
                    pickle.dumps(best_pipeline, protocol=pickle.HIGHEST_PROTOCOL)
                )
                for kind, source, filename, content_type in (
                    ("model_evaluation", evaluation_path, "evaluation.json", "application/json"),
                    ("model_pipeline", model_path, "pipeline.pkl", "application/octet-stream"),
                ):
                    key = f"datasets/{job.dataset_id}/models/{job.id}/{filename}"
                    try:
                        ref = self.store.put_file(source, key=key, content_type=content_type)
                    except StorageError as upload_error:
                        try:
                            ref = self.store.stat(key)
                        except StorageError as stat_error:
                            raise upload_error from stat_error
                    self.control_plane.register_job_artifact(
                        job_id=job.id, kind=kind, object_ref=ref
                    )
            self.control_plane.save_result(
                version_id=version.id,
                kind="model",
                title=(
                    f"{config.problem_type.title()} · "
                    f"{evaluation['best_algorithm'].replace('_', ' ')}"
                ),
                fingerprint=hashlib.sha256(f"model:{job.id}".encode()).hexdigest(),
                configuration=config.model_dump(mode="json"),
                payload=evaluation,
                source_job_id=job.id,
            )
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

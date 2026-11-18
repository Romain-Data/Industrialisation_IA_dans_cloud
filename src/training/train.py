"""Entraînement du modèle (régression logistique scikit-learn) et journalisation dans MLflow."""

import mlflow
import mlflow.sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import RANDOM_STATE, REGISTERED_MODEL_NAME
from src.domain.evaluation import EVALUATION_PROTOCOL, evaluate
from src.domain.features import (
    CATEGORICAL_FEATURES,
    DATA_SCHEMA_VERSION,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from src.training.registry import configure_mlflow


def train_model(train, holdout, params=None):
    """Entraîne le pipeline, l'évalue sur le jeu d'évaluation commun et l'enregistre dans MLflow.

    `train` et `holdout` viennent de `split_holdout` (src/domain/evaluation.py) : le
    champion sera réévalué sur ce même `holdout` avant toute promotion.
    Retourne (pipeline, métriques, run_id). `params` complète les paramètres du run
    (provenance des données, numéro de snapshot DuckLake...).
    """
    X_train = train[FEATURE_COLUMNS]
    y_train = train[TARGET_COLUMN]

    numeric_transformer = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "scaler",
                StandardScaler()
            ),
        ]
    )

    categorical_transformer = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="most_frequent")
            ),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False
                )
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                numeric_transformer,
                NUMERIC_FEATURES
            ),
            (
                "categorical",
                categorical_transformer,
                CATEGORICAL_FEATURES
            ),
        ]
    )

    classifier = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_STATE
    )

    model_pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )

    configure_mlflow()

    with mlflow.start_run(run_name="logistic-regression-baseline") as run:
        model_pipeline.fit(X_train, y_train)

        metrics = evaluate(model_pipeline, holdout)

        mlflow.log_param("model_type", "LogisticRegression")
        mlflow.log_param("random_state", RANDOM_STATE)
        mlflow.log_param("feature_count", len(FEATURE_COLUMNS))
        # training_rows : toutes les commandes lues (le réentraînement compte les nouvelles).
        mlflow.log_param("training_rows", len(train) + len(holdout))
        mlflow.log_param("holdout_rows", len(holdout))
        mlflow.log_param("evaluation_protocol", EVALUATION_PROTOCOL)
        # Schéma des données (vocabulaire) : la promotion ne compare que des modèles du même schéma.
        mlflow.log_param("data_schema", DATA_SCHEMA_VERSION)
        # Provenance des données (ex. numéro de snapshot DuckLake).
        mlflow.log_params({"data_source": "synthetic", **(params or {})})

        for metric_name, metric_value in metrics.items():
            mlflow.log_metric(metric_name, metric_value)

        mlflow.sklearn.log_model(
            model_pipeline,
            artifact_path="model",
            registered_model_name=REGISTERED_MODEL_NAME,
            skops_trusted_types=["numpy.dtype"]
        )

        mlflow.log_dict(
            {
                "target": TARGET_COLUMN,
                "features": FEATURE_COLUMNS,
                "numeric_features": NUMERIC_FEATURES,
                "categorical_features": CATEGORICAL_FEATURES,
            },
            "features.json",
        )

        run_id = run.info.run_id

    return model_pipeline, metrics, run_id

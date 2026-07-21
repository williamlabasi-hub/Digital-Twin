import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    precision_score,
    recall_score,
    f1_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from health_features import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERICAL_FEATURES



TARGET_COLUMN = "health_status"
BASE_DIR = Path(__file__).resolve().parent



def load_json_file(file_path: Path) -> list[dict]:
    """Load a JSON array of records from a file."""

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            f"Expected {file_path} to contain a JSON array of records."
        )
    
    if not data:
        raise ValueError(f"{file_path} contains no records")
    
    if not all(isinstance(record, dict) for record in data):
        raise ValueError(
            f"Expected all records in {file_path} to be JSON objects."
        )
    
    return data



def integrate_command_history(
        telemetry_df: pd.DataFrame,
        command_df: pd.DataFrame,
)-> pd.DataFrame:
    """Attach the latest preceding command to each telemetry record.
    
    Each telemetrey record recieves the most recent command for the same
    satellite whose timestamp is less than or equal to the telemetry record's timestamp."""

    telemetry_required = {
        "satellite_id",
        "timestamp",
        }
    
    command_required = {
        "satellite_id",
        "command_name",
        "timestamp",
        "command_status",
    }

    missing_telemetry = telemetry_required - set(telemetry_df.columns)
    missing_command = command_required - set(command_df.columns)

    if missing_telemetry:
        raise ValueError(
            f"Telemetry data is missing columns: "
            f"{sorted(missing_telemetry)}"
        )
    
    if missing_command:
        raise ValueError(
            f"Command History is missing columns: "
            f"{sorted(missing_command)}"
        )
    
    telemetry_df = telemetry_df.copy()
    command_df = command_df.copy()

    telemetry_df["timestamp"] = pd.to_datetime(
        telemetry_df["timestamp"], 
        errors="coerce",
        utc=True,
    )

    command_df["timestamp"] = pd.to_datetime(
        command_df["timestamp"], 
        errors="coerce",
        utc=True,
    )

    if telemetry_df["timestamp"].isna().any():
        invalid_count = telemetry_df["timestamp"].isna().sum()
        raise ValueError(
            f"Telemetry data contains {invalid_count} invalid timestamp(s)."
        )

    if command_df["timestamp"].isna().any():
        invalid_count = command_df["timestamp"].isna().sum()
        raise ValueError(
            f"Command history contains {invalid_count} invalid timestamp(s)."
        )
    
    if telemetry_df["satellite_id"].isna().any():
        raise ValueError(
            "Telemetry data contains missing satellite_id values."
        )
    
    if command_df["satellite_id"].isna().any():
        raise ValueError(
            "Command history contains missing satellite_id values."
        )   
    
    command_df = command_df.rename(
        columns={
            "command_name": "recent_command_name",
            "command_status": "recent_command_status",
            "timestamp": "recent_command_timestamp",
        }
    )

    telemetry_df = telemetry_df.sort_values(
        ["timestamp", "satellite_id"]
    ).reset_index(drop=True)

    command_df = command_df.sort_values(
        ["recent_command_timestamp", "satellite_id"]
    ).reset_index(drop=True)

    integrated_df = pd.merge_asof(
        telemetry_df,
        command_df[
            [
                "satellite_id",
                "recent_command_name",
                "recent_command_status",
                "recent_command_timestamp",
            ]
        ],
        left_on="timestamp",
        right_on="recent_command_timestamp",
        by="satellite_id",
        direction="backward",
        allow_exact_matches=True,
    )

    integrated_df["seconds_since_last_command"] = (
        (integrated_df["timestamp"] - integrated_df["recent_command_timestamp"])
        .dt.total_seconds()
    )

    return integrated_df



def load_dataset_from_paths(
    telemetry_path: Path,
    command_history_path: Path,
) -> pd.DataFrame:
    """Load, validate, and integrate telemetry and command-history data."""

    telemetry_records = load_json_file(telemetry_path)
    command_records = load_json_file(command_history_path)

    telemetry_df = pd.DataFrame(telemetry_records)
    command_df = pd.DataFrame(command_records)

    if telemetry_df.empty:
        raise ValueError("Telemetry JSON contains no records.")

    if command_df.empty:
        raise ValueError("Command history JSON contains no records.")

    return integrate_command_history(telemetry_df, command_df)



def parse_args() -> argparse.Namespace:
    """Read command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Train and save a satellite health prediction model."
    )
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=BASE_DIR / "HealthTelemetry1.json",
        help="Path to the telemetry JSON file.",
    )
    parser.add_argument(
        "--command-history",
        type=Path,
        default=BASE_DIR / "CommandHistory1.json",
        help="Path to the command history JSON file.",
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=BASE_DIR / "satellite_health_model.joblib",
        help="Path to save the trained model.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Proportion of the dataset to include in the test split.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--trees",
        type=int,
        default=200,
        help="Number of trees in the random forest.",
    )

    args = parser.parse_args()

    if not 0 < args.test_size < 1:
        parser.error("--test-size must be between 0 and 1.")    

    if args.trees < 1:
        parser.error("--trees must be at least 1.")

    return args



def get_feature_columns() -> tuple[list[str], list[str]]:
    """Return the lists of numerical and categorical feature column names. """
    return list(NUMERICAL_FEATURES), list(CATEGORICAL_FEATURES)



def validate_dataset(dataset: pd.DataFrame) -> None:
    """Validate the dataset for required columns and data types."""

    if dataset.empty:
        raise ValueError("The dataset is empty.")
    
    if TARGET_COLUMN not in dataset.columns:
        raise ValueError(f"Dataset is missing the target column: {TARGET_COLUMN}")
    
    if dataset[TARGET_COLUMN].isna().any():
        missing_count = dataset[TARGET_COLUMN].isna().sum()
        raise ValueError(
            f"Target column '{TARGET_COLUMN}' contains "
            f"{missing_count} missing value(s)."
        )
    
    if dataset[TARGET_COLUMN].nunique() < 2:
        raise ValueError(
            "Target requires at least two unique classes for classification."
        )



def validate_features(
        X: pd.DataFrame,
        numerical_features: list[str],
        categorical_features: list[str],
) -> None:
    """Validate that the dataset contains the required feature columns."""

    missing_numerical = set(numerical_features) - set(X.columns)
    missing_categorical = set(categorical_features) - set(X.columns)

    if missing_numerical:
        raise ValueError(
            f"Dataset is missing numerical feature columns: "
            f"{sorted(missing_numerical)}"
        )
    
    if missing_categorical:
        raise ValueError(
            f"Dataset is missing categorical feature columns: "
            f"{sorted(missing_categorical)}"
        )
    


def build_preprocessor(
    numerical_features: list[str],
    categorical_features: list[str],
) -> ColumnTransformer:
    """Build a preprocessor for numerical and categorical features."""

    numerical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "encoder",
                OneHotEncoder(handle_unknown="ignore"),
            ),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("numerical", numerical_pipeline, numerical_features),
            ("categorical", categorical_pipeline, categorical_features),
        ],
        remainder="drop",
    )


def get_train_test_split(
    X: pd.DataFrame,
    y: pd.Series,
    test_size: float,
    random_state: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Split the dataset into training and testing sets with stratification if possible.
    Stratification is applied only if there are enough samples in each class to support it."""

    if len(X) < 2:
        return X, X, y, y
    
    class_counts = y.value_counts()
    number_of_classes = y.nunique()

    test_sample_count = max(1, round(len(X) * test_size),
    )

    training_sample_count = len(X) - test_sample_count

    can_stratify = (
        not class_counts.empty
        and class_counts.min() >= 2
        and training_sample_count >= number_of_classes
        and test_sample_count >= number_of_classes
    )

    return train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y if can_stratify else None,
    )



def build_model_pipeline(
    preprocessor: ColumnTransformer,
    number_of_trees: int,
    random_state: int,
) -> Pipeline:
    """Build the complete preprocessing and modeling pipeline."""

    random_forest = RandomForestClassifier(
        n_estimators=number_of_trees,
        random_state=random_state,
        class_weight="balanced",
        # A single worker is portable to restricted operational environments.
        # This prototype dataset is small enough that parallelism is unnecessary.
        n_jobs=1,
    )

    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", random_forest),
        ]
    )



def evaluate_model(
    pipeline: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> None:
    """Evaluate the model on the test set and print metrics."""

    y_pred = pipeline.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)

    precision = precision_score(y_test, y_pred, average="weighted", zero_division=0)

    recall = recall_score(y_test, y_pred, average="weighted", zero_division=0)

    f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)

    print("\nModel Evaluation")
    print("----------------")
    print(f"Accuracy:  {accuracy:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1-Score:  {f1:.4f}")

    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, zero_division=0))



def save_model(pipeline: Pipeline, output_path: Path
) -> None:
    """Save the trained model pipeline to a file using joblib."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(pipeline, output_path)
    
    print(f"\nModel saved to: {output_path.resolve()}")



def main() -> None:
    """Run the complete model training and evaluation pipeline."""

    args = parse_args()

    print(f"\nTelemetry file: {args.telemetry}")
    print(f"Command history file: {args.command_history}")

    dataset = load_dataset_from_paths(
        telemetry_path=args.telemetry,
        command_history_path=args.command_history
    )

    validate_dataset(dataset)
    print("\nHealth-status class counts:")
    print(dataset[TARGET_COLUMN].value_counts(dropna=False))
    
    # Fit with exactly the same public feature contract used at inference.
    # Metadata fields such as satellite_id and timestamp must never become part
    # of the estimator's expected input signature.
    X = dataset[MODEL_FEATURES].copy()
    y = dataset[TARGET_COLUMN]

    print("\nIntegrated Features:")
    print(X.head())
    print("\nTarget:")
    print(y.head())

    numerical_features, categorical_features = get_feature_columns()

    print("\nNumerical Features:")
    print(numerical_features)

    print("\nCategorical Features:")
    print(categorical_features)

    validate_features(X=X, numerical_features=numerical_features, categorical_features=categorical_features)

    preprocessor = build_preprocessor(
        numerical_features=numerical_features,
        categorical_features=categorical_features,
    )

    print("\nRandom Forest Settings")
    print("----------------------")
    print(f"Trees: {args.trees}")
    print(f"Random State: {args.random_state}")
    print(f"Test Size: {args.test_size}")

    X_train, X_test, y_train, y_test = get_train_test_split(
        X=X,
        y=y,
        test_size=args.test_size,
        random_state=args.random_state
    )

    print(f"\nTraining samples: {len(X_train)}")
    print(f"Testing samples: {len(X_test)}")

    model_pipeline = build_model_pipeline(
        preprocessor=preprocessor,
        number_of_trees=args.trees,
        random_state=args.random_state,
    )

    model_pipeline.fit(X_train, y_train)

    model_pipeline.health_model_metadata_ = {
        "model_type": "RandomForestClassifier",
        "feature_contract": list(MODEL_FEATURES),
        "health_classes": sorted(str(value) for value in y.unique()),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_record_count": len(dataset),
        "training_data_type": "synthetic_prototype",
        "random_state": args.random_state,
        "number_of_trees": args.trees,
    }

    print("\nTraining complete.")
    print("Evaluating model...")

    evaluate_model(
        pipeline=model_pipeline,
        X_test=X_test,
        y_test=y_test,
    )

    print("Saving model...")

    save_model(
        pipeline=model_pipeline,
        output_path=args.output_model,
    )



import traceback

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nError: {error}")
        traceback.print_exc()

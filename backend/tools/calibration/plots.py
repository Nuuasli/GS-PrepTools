"""Matplotlib visualizations for offline threshold experiments."""

from pathlib import Path

from tools.calibration.models import AnalysisResult, CalibrationError


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise CalibrationError(
            "Plot generation requires matplotlib. Install it with "
            "'pip install -r requirements-calibration.txt' or use --no-plots."
        ) from exc
    return plt


def create_plots(result: AnalysisResult, output_dir: Path) -> None:
    plt = _pyplot()
    output_dir.mkdir(parents=True, exist_ok=True)

    positives = [sample.score for sample in result.samples if sample.is_positive]
    negatives = [sample.score for sample in result.samples if not sample.is_positive]
    figure, axis = plt.subplots(figsize=(8, 5))
    if positives:
        axis.hist(positives, bins="auto", alpha=0.65, label=result.positive_label)
    if negatives:
        axis.hist(negatives, bins="auto", alpha=0.65, label=result.negative_label)
    axis.set_title(f"{result.name.upper()} score distribution")
    axis.set_xlabel("Score")
    axis.set_ylabel("Count")
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_dir / "score_distribution.png", dpi=160)
    plt.close(figure)

    thresholds = [item.threshold for item in result.thresholds]
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.plot(
        thresholds,
        [item.confusion.precision for item in result.thresholds],
        label="Precision",
    )
    axis.plot(
        thresholds,
        [item.confusion.recall for item in result.thresholds],
        label="Recall",
    )
    axis.plot(
        thresholds,
        [item.confusion.f1 for item in result.thresholds],
        label="F1",
    )
    axis.axvline(
        result.selected.threshold,
        color="black",
        linestyle="--",
        alpha=0.6,
        label="Selected for diagnostics",
    )
    axis.set_title(f"{result.name.upper()} threshold metrics")
    axis.set_xlabel("Threshold")
    axis.set_ylabel("Metric")
    axis.set_ylim(0, 1.05)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_dir / "threshold_metrics.png", dpi=160)
    plt.close(figure)

    matrix = result.selected.confusion
    values = [[matrix.tp, matrix.fn], [matrix.fp, matrix.tn]]
    figure, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(values, cmap="Blues")
    axis.set_xticks([0, 1], ["Pred positive", "Pred negative"])
    axis.set_yticks([0, 1], ["Actual positive", "Actual negative"])
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            axis.text(column_index, row_index, str(value), ha="center", va="center")
    axis.set_title(
        f"Confusion matrix at threshold {result.selected.threshold:.6g}"
    )
    figure.colorbar(image, ax=axis)
    figure.tight_layout()
    figure.savefig(output_dir / "confusion_matrix.png", dpi=160)
    plt.close(figure)

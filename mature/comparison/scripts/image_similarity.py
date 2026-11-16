import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


def _bits_to_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Hash vectors must have equal non-zero length.")
    differences = sum(a != b for a, b in zip(left, right))
    return round(1 - differences / len(left), 6)


def _pixel_values(image: Image.Image) -> list[int]:
    get_flattened_data = getattr(image, "get_flattened_data", None)
    if get_flattened_data is not None:
        return list(get_flattened_data())
    return list(image.getdata())


def _average_hash(image: Image.Image, size: int = 16) -> tuple[int, ...]:
    pixels = _pixel_values(image.convert("L").resize((size, size)))
    average = sum(pixels) / len(pixels)
    return tuple(int(value >= average) for value in pixels)


def _difference_hash(image: Image.Image, size: int = 16) -> tuple[int, ...]:
    resized = image.convert("L").resize((size + 1, size))
    pixels = _pixel_values(resized)
    return tuple(
        int(
            pixels[row * (size + 1) + column]
            > pixels[row * (size + 1) + column + 1]
        )
        for row in range(size)
        for column in range(size)
    )


def _histogram_similarity(left: Image.Image, right: Image.Image) -> float:
    left_values = left.convert("RGB").resize((64, 64)).histogram()
    right_values = right.convert("RGB").resize((64, 64)).histogram()
    numerator = sum(min(a, b) for a, b in zip(left_values, right_values))
    denominator = sum(max(a, b) for a, b in zip(left_values, right_values))
    return round(numerator / denominator if denominator else 1.0, 6)


def compare_images(
    source_path: Path, candidate_path: Path
) -> dict[str, float | str]:
    try:
        with Image.open(source_path) as source, Image.open(candidate_path) as candidate:
            ahash = _bits_to_similarity(_average_hash(source), _average_hash(candidate))
            dhash = _bits_to_similarity(
                _difference_hash(source), _difference_hash(candidate)
            )
            histogram = _histogram_similarity(source, candidate)
    except (FileNotFoundError, OSError, UnidentifiedImageError) as error:
        raise ValueError(f"Cannot read comparison image: {error}") from error
    combined = round((ahash + dhash + histogram) / 3, 6)
    return {
        "algorithm_version": "local-image-v1",
        "average_hash_similarity": ahash,
        "difference_hash_similarity": dhash,
        "histogram_similarity": histogram,
        "combined_similarity": combined,
    }


def _local_path(value: Any, base_directory: Path) -> Path:
    text = str(value).strip()
    if not text or text.casefold().startswith(("http://", "https://")):
        raise ValueError("Image paths must be non-empty local filesystem paths.")
    path = Path(text)
    return path if path.is_absolute() else base_directory / path


def compare_batch(document: Any, base_directory: Path) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        raise ValueError("Image batch input must be an object.")
    source = _local_path(document.get("source_image", ""), base_directory)
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Image batch input requires at least one candidate.")
    result: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise ValueError(f"Image candidate {index} must be an object.")
        sku_id = str(candidate.get("sku_id", "")).strip()
        if not sku_id:
            raise ValueError(f"Image candidate {index} is missing sku_id.")
        if sku_id in result:
            raise ValueError(f"Duplicate image candidate SKU: {sku_id}")
        candidate_path = _local_path(
            candidate.get("local_image_path", ""), base_directory
        )
        score = compare_images(source, candidate_path)
        result[sku_id] = {
            **score,
            "source_image": str(source),
            "candidate_image": str(candidate_path),
        }
    return result


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            suffix=".json",
            dir=path.parent,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare already-downloaded local images.")
    commands = parser.add_subparsers(dest="command", required=True)
    batch_parser = commands.add_parser("batch")
    batch_parser.add_argument("--input", required=True)
    batch_parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    input_path = Path(arguments.input)
    try:
        document = json.loads(input_path.read_text(encoding="utf-8"))
        result = compare_batch(document, input_path.parent)
        _write_json_atomic(Path(arguments.output), result)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({"output": arguments.output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

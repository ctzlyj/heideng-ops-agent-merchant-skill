"""Local candidate composition, reviewed publication and hash verification."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import video_publication as publication


def add_commands(commands):
    verify = commands.add_parser("verify-handoff")
    verify.add_argument("package", type=Path)
    publish = commands.add_parser("publish")
    publish.add_argument("package", type=Path)
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--video", required=True, type=Path)
    publish.add_argument("--cover", required=True, type=Path)
    publish.add_argument("--metadata", required=True, type=Path,
                         help="Actual reviewed producer metadata; never fabricate qc/task/voice fields")
    compose = commands.add_parser("compose-local", help="用商品包内指定图片制作无声候选")
    compose.add_argument("package", type=Path)
    compose.add_argument("--image", action="append", required=True, help="按镜头顺序重复传包内图片")
    compose.add_argument("--seconds-per-image", type=float, default=3.0)
    compose.add_argument("--run-id")


def dispatch(command, args, invalid=2):
    if command == "verify-handoff":
        result = publication.verify_handoff(args.package)
    elif command == "compose-local":
        from local_composition import compose
        result = compose(args.package, args.image, args.seconds_per_image, args.run_id)
    else:
        metadata = publication.read(args.metadata)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("voiceReviewRequired"), bool):
            raise publication.PublicationError("Real metadata with explicit voiceReviewRequired is required")
        if metadata.get("mode") == "ai" and not metadata.get("taskId"):
            raise publication.PublicationError("AI output requires the actual external provider taskId")
        result = publication.publish(args.package, args.run_id, args.video, args.cover, metadata)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if command == "compose-local" or result.get("ok") else invalid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_commands(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args()
    return dispatch(args.command, args)


if __name__ == "__main__":
    raise SystemExit(main())

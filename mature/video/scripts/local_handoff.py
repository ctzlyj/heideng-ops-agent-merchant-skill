"""Local-only entrance to the original main-video publication API; no generator."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import video_publication as publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-handoff")
    verify.add_argument("package", type=Path)
    publish = commands.add_parser("publish")
    publish.add_argument("package", type=Path)
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--video", required=True, type=Path)
    publish.add_argument("--cover", required=True, type=Path)
    publish.add_argument("--metadata", required=True, type=Path,
                         help="Actual reviewed producer metadata; never fabricate qc/task/voice fields")
    args = parser.parse_args()
    if args.command == "verify-handoff":
        result = publication.verify_handoff(args.package)
    else:
        metadata = publication.read(args.metadata)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("voiceReviewRequired"), bool):
            raise publication.PublicationError("Real metadata with explicit voiceReviewRequired is required")
        if metadata.get("mode") == "ai" and not metadata.get("taskId"):
            raise publication.PublicationError("AI output requires the actual external provider taskId")
        result = publication.publish(args.package, args.run_id, args.video, args.cover, metadata)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

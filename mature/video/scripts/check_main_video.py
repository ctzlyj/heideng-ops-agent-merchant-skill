"""京东主图视频规范检查。

用法：python check_main_video.py 视频1.mp4 [视频2.mp4 ...]
硬性规则不满足时返回码为 1；建议性问题只给 WARN。
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

ALLOWED_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".flv", ".mkv", ".wmv", ".mpg", ".mpeg", ".3gp"}
MIN_SECONDS = 5.0
MAX_BYTES = 20 * 1024**3
MIN_SHORT_SIDE = 720
MIN_RATIO, MAX_RATIO = Fraction(9, 20), Fraction(20, 9)
RECOMMENDED = {"1:1": Fraction(1, 1), "3:4": Fraction(3, 4)}


@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    seconds: float
    size_bytes: int


def evaluate(info: VideoInfo) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if info.path.suffix.lower() not in ALLOWED_EXTS:
        errors.append(f"格式 {info.path.suffix or '(无扩展名)'} 不是主流视频格式，建议使用 mp4")
    if info.seconds < MIN_SECONDS:
        errors.append(f"时长 {info.seconds:.2f}s，低于 {MIN_SECONDS:.0f}s")
    if info.size_bytes > MAX_BYTES:
        errors.append(f"文件 {info.size_bytes / 1024**3:.2f}GB，超过 20GB")
    if min(info.width, info.height) < MIN_SHORT_SIDE:
        errors.append(f"分辨率 {info.width}x{info.height}，短边低于 720（未达 720P）")
    ratio = Fraction(info.width, info.height)
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        errors.append(f"宽高比 {info.width}:{info.height}≈{float(ratio):.3f}，超出 9:20~20:9")
    elif not any(abs(float(ratio - r)) < 0.01 for r in RECOMMENDED.values()):
        warnings.append(f"宽高比 {float(ratio):.3f} 不是建议的 1:1 或 3:4，前台展示可能会有白边")
    return errors, warnings


def probe(path: Path) -> VideoInfo:
    import imageio_ffmpeg

    res = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = res.stderr
    dur = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    video = re.search(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})", text)
    if not dur or not video:
        raise ValueError(f"无法解析视频信息: {path}")
    seconds = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3])
    width, height = int(video[1]), int(video[2])
    rotate = re.search(r"rotate\s*:\s*(-?\d+)|rotation of (-?[\d.]+)", text)
    if rotate and abs(round(float(rotate[1] or rotate[2]))) % 180 == 90:
        width, height = height, width
    return VideoInfo(path, width, height, seconds, path.stat().st_size)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    failed = False
    for name in argv:
        path = Path(name)
        try:
            info = probe(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {path}: {exc}")
            failed = True
            continue
        errors, warnings = evaluate(info)
        status = "FAIL" if errors else ("WARN" if warnings else "PASS")
        failed |= bool(errors)
        print(f"[{status}] {path.name}: {info.width}x{info.height}, {info.seconds:.2f}s, "
              f"{info.size_bytes / 1024**2:.1f}MB")
        for msg in errors:
            print(f"  ERROR  {msg}")
        for msg in warnings:
            print(f"  WARN   {msg}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
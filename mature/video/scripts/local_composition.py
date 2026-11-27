"""Create a silent review candidate from explicitly selected local product images."""
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from PIL import Image, ImageOps
import imageio_ffmpeg


def compose(package, images, seconds_per_image=3.0, run_id=None):
    import video_publication as publication

    package = Path(package).resolve()
    manifest = package if package.is_file() else package/'manifest.json'
    if not manifest.is_file() or manifest.name != 'manifest.json':
        raise ValueError('需要有效商品包 manifest.json')
    root = manifest.parent
    paths = [Path(image) if Path(image).is_absolute() else root/image for image in images]
    if not paths or not math.isfinite(seconds_per_image) or seconds_per_image <= 0:
        raise ValueError('请选择图片并指定正数展示时长')
    if len(paths) * seconds_per_image < 5:
        raise ValueError('选图总时长低于 5 秒，无法制作合规候选')
    paths = [p.resolve(strict=True) for p in paths]
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError('选择的图片必须在当前商品包内')
    run_id = run_id or uuid.uuid4().hex
    publication.validate_run_id(run_id)
    request = {'images':[{'file':p.relative_to(root).as_posix(), 'sha256':publication.sha256(p)}
                         for p in paths], 'secondsPerImage':seconds_per_image}
    fingerprint = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    candidate = publication.create_run(root, 'material', run_id)/'local-composition'
    candidate.mkdir(exist_ok=True)
    receipt = candidate/'local-composition.json'
    with publication.publication_lock(candidate):
        request_file = candidate/'request.json'
        saved_request = publication.read(request_file)
        if saved_request is not None and saved_request != request:
            raise ValueError('原任务的图片或时长发生变化，请另起候选')
        if saved_request is None:
            publication.save(request_file, request)
        previous = publication.read(receipt)
        if previous:
            if previous['inputSha256'] != fingerprint:
                raise ValueError('原任务的图片或时长发生变化，请另起候选')
            for name, digest in [('video','videoSha256'), ('cover','coverSha256')]:
                if publication.sha256(root/previous[name]) != previous[digest]:
                    raise ValueError('原候选文件已变化，需重新核对')
            return dict(previous, replayed=True)
        # A task with no receipt can be rendered again before anything is offered for review.
        with tempfile.TemporaryDirectory(dir=candidate) as temp:
            stage = Path(temp)
            for i, path in enumerate(paths):
                content = path.read_bytes()
                if sha256(content).hexdigest() != request['images'][i]['sha256']:
                    raise ValueError('商品图片在制作中变化')
                with Image.open(BytesIO(content)) as original:
                    image = ImageOps.exif_transpose(original).convert('RGBA')
                image.thumbnail((720, 720), Image.Resampling.LANCZOS)
                frame = Image.new('RGB', (720, 720), 'white')
                frame.paste(image, ((720-image.width)//2, (720-image.height)//2), image)
                frame.save(stage/f'{i:06d}.png')
                if i == 0:
                    frame.save(stage/'cover.jpg', quality=93)
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([ffmpeg,'-v','error','-nostdin','-framerate',str(1/seconds_per_image),
                            '-i',str(stage/'%06d.png'),'-vf','fps=24','-c:v','libx264',
                            '-pix_fmt','yuv420p','-movflags','+faststart',str(stage/'video.mp4')],
                           check=True, capture_output=True)
            video, cover = candidate/'local-video.mp4', candidate/'local-cover.jpg'
            info = publication.media_info(stage/'video.mp4', publication.probe)
            os.replace(stage/'video.mp4', video)
            os.replace(stage/'cover.jpg', cover)
        result = {'status':'needs-visual-review','runId':run_id,'inputSha256':fingerprint,
                  **request, **info, 'video':video.relative_to(root).as_posix(),
                  'cover':cover.relative_to(root).as_posix(), 'videoSha256':publication.sha256(video),
                  'coverSha256':publication.sha256(cover), 'mode':'material','voiceReviewRequired':False,
                  'technicalCheck':'passed','bindable':False,'manifestWritten':False,'platformWrites':0}
        publication.save(receipt, result)
        return result

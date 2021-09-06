#!/usr/bin/env xonsh
xontrib bashisms
set -e
import typer
from typing import Optional
from pathlib import Path
import json, os, math
from pprint import pformat
import humanize
from loguru import logger as log

class ConvertionError(Exception): pass


MB = int(1e6)


def main(path: Path,
    BIGGER_THAN_THIS_BITRATE_CONVERT: Optional[int] = 20 * MB,




):
    info = get_video_info(path)
    log.info(f'Considering file: {info["format"]["filename"]}')
    log.debug(pformat(info))
    bitrate = int(info['format']['bit_rate'])
    log.info(f'File bitrate: {humanize.naturalsize(bitrate)}/s')
    if bitrate < BIGGER_THAN_THIS_BITRATE_CONVERT:
        log.info('Bitrate is already small. Not worth it to convert')
        return
    stream_types = [s['codec_type'] for s in info['streams']]
    if stream_types != ['video', 'audio']:
        log.info('Found unexpected streams, skipping')
        return
    convert(path)
    new_info = get_video_info(path)
    assert_conversion_ok(info, new_info)

from dictdiffer import diff

def assert_conversion_ok(info, new_info):
    video = info['streams'][0]
    new_video = new_info['streams'][0]
    close(video, new_video, 'start_time', 0.05)
    log.debug('Diferences between original and converted\n' + pformat(list(diff(new_info, info))) )
    assert new_info == info

def close(original, converted, prop, tol):
    if not math.isclose(float(original[prop]), float(converted[prop]), abs_tol=tol):
        raise ConvertionError(f'Error in {prop!r}: {original[prop]=} != {converted[prop]=}')

def convert(path):
    name, _ = os.path.splitext(path)
    new_path = name + '.__to_move__.mkv' # mkv is the best container, open and flexible
    ./vendored/ffmpeg -y -i @(path) -c:v libx265 -crf 28 -preset ultrafast -c:a aac -b:a 160k @(new_path)
    # save old path to someplace
    os.rename(path, f'{path}.bak') # TODO: check exists
    os.rename(new_path, f'{name}.mkv')



def get_video_info(filename):
    probe = $(ffprobe -v quiet -print_format json -show_format -show_streams @(filename))
    return json.loads(probe)




if __name__ == "__main__":
    typer.run(main)

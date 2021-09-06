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
    audio_is_raw = info['streams'][1]['codec_name'].startswith('pcm') # https://trac.ffmpeg.org/wiki/audio%20types
    convert(path, copy_audio=(not audio_is_raw))
    new_info = get_video_info(path)
    assert_conversion_ok(info, new_info)

from dictdiffer import diff, dot_lookup
from unittest.mock import ANY

def assert_conversion_ok(info, new_info):
    TOLERANCE = 1 / 20 # a bit more than one frame
    video = info['streams'][0]
    new_video = new_info['streams'][0]
    log.debug('Diferences between original and converted\n' + pformat(list(diff(info, new_info))) )
    close(info, new_info, 'streams.0.start_time', TOLERANCE)
    close(info, new_info, 'streams.1.start_time', TOLERANCE)
    close(info, new_info, 'format.duration', TOLERANCE)
    close(info, new_info, 'format.start_time', TOLERANCE)
    IRRELEVANT = (
    # We expect these to change as they are related to codecs
    '''
    streams.0.tags.ENCODER
    streams.0.tags.DURATION
    streams.0.profile
    streams.0.codec_time_base
    streams.0.has_b_frames
    streams.0.level
    streams.0.start_pts
    streams.0.codec_name
    streams.0.codec_long_name
    streams.1.tags.DURATION
    streams.1.tags.ENCODER
    streams.1.codec_long_name
    streams.1.codec_name
    streams.1.sample_fmt
    streams.1.bits_per_sample
    streams.1.start_pts
    '''
    # Things that are removed
    '''
    streams.0.color_space
    streams.0.color_transfer
    streams.0.color_primaries
    streams.0.field_order
    streams.0.is_avc
    streams.0.nal_length_size
    streams.0.bits_per_raw_sample
    streams.1.bit_rate
    '''
    # Things that are added
    '''
    streams.1.profile
    streams.1.channel_layout
    '''
    # Actually changed
    '''
    format.size
    format.bit_rate
    '''
    # We check if these are close in the code above
    '''
    format.duration
    format.start_time
    streams.0.start_time
    streams.1.start_time
    ''').split()
    for i in IRRELEVANT:
        dot_lookup(info, i, parent=True)[i.split('.')[-1]] = ANY
        dot_lookup(new_info, i, parent=True)[i.split('.')[-1]] = ANY
    the_diff = list(diff(info, new_info, ))
    assert not the_diff, pformat(the_diff)

def close(original, converted, prop, tol):
    original_prop, converted_prop = dot_lookup(original, prop), dot_lookup(converted, prop)
    if not math.isclose(float(original_prop), float(converted_prop), abs_tol=tol):
        raise ConvertionError(f'Error in {prop!r}: {original_prop=} != {converted_prop=}')

def convert(path, copy_audio=False):
    CRF = 28 # Size/Quality tradeoff. From 0 to 51. Lower is better quality. Default is 28. # https://trac.ffmpeg.org/wiki/Encode/H.265
    PRESET = 'medium' # https://x265.readthedocs.io/en/master/cli.html#cmdoption-preset

    name, _ = os.path.splitext(path)
    new_path = name + '.__to_move__.mkv' # mkv is the best container, open and flexible
    audio = ['-c:a', 'copy'] if copy_audio else ['-c:a', 'libopus', '-b:a', '192k']
    ./vendored/ffmpeg -y -i @(path) -c:v libx265 -crf @(CRF) -preset medium @(audio) @(new_path)
    # save old path to someplace
    os.rename(path, f'{path}.bak') # TODO: check exists
    os.rename(new_path, f'{name}.mkv')


def get_vmaf(): # todo:  further investigate this
    ./vendored/ffmpeg -i in.mkv.bak -i in.mkv -lavfi libvmaf="model_path=vendored/vmaf_v0.6.1.pkl" -f null -


def get_video_info(filename):
    probe = $(./vendored/ffprobe -v quiet -print_format json -show_format -show_streams @(filename))
    return json.loads(probe)




if __name__ == "__main__":
    typer.run(main)

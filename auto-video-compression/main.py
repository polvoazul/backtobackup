#!/usr/bin/env python3

import pprint
from auto_video_compression.ffmpeg import get_video_info, get_vmaf, convert, CONVERT_CONFIG
import typer
from typing import Dict, Optional
from pathlib import Path
import json, os.path, math
from pprint import pformat
import humanize
from loguru import logger as log

class ConvertionError(Exception): pass


MB = int(1e6)

def main(path: Path,
    min_bitrate: int = 20 * MB,
):
    info = get_video_info(path)
    log.info(f'Considering file: {info["format"]["filename"]}')
    log.debug(pformat(info))
    bitrate = int(info['format']['bit_rate'])
    log.info(f'File bitrate: {humanize.naturalsize(bitrate)}/s')
    if bitrate < min_bitrate:
        log.info('Bitrate is already small. Not worth it to convert')
        return
    stream_types = [s['codec_type'] for s in info['streams']]
    if stream_types != ['video', 'audio'] and stream_types != ['video']:
        log.info(f'Found unexpected streams: {stream_types}, skipping')
        return
    import time
    start_time = time.time()
    new_path = convert_video(path, info, stream_types)
    elapsed_time = time.time() - start_time
    score = assert_conversion_ok(path, new_path)
    filesize = path.stat().st_size
    new_filesize = new_path.stat().st_size
    print(f'Conversion complete!\n')
    print(f'Configs: {CONVERT_CONFIG}')
    print(f'Convertion time: {float(info["format"]["duration"])/elapsed_time:.2f}x - {humanize.naturaldelta(elapsed_time)}')
    print(f'Similarity score = {score:.1f}.')
    print(f'Old filesize: {humanize.naturalsize(filesize)}.')
    print(f'New filesize: {humanize.naturalsize(new_filesize)}.')
    print(f'Reduction = {humanize.naturalsize(filesize - new_filesize)} ({100*(filesize - new_filesize)/filesize:.1f})%')
    log.info('Done')

from dictdiffer import diff, dot_lookup
from unittest.mock import ANY

def convert_video(path, info, stream_types):
    has_audio = 'audio' in stream_types
    if has_audio:
        audio_is_raw = info['streams'][1]['codec_name'].startswith('pcm') # https://trac.ffmpeg.org/wiki/audio%20types
        return convert(path, copy_audio=(not audio_is_raw))
    else:
        return convert(path, has_audio=False)

def assert_conversion_ok(path, new_path):
    similarity_score = get_vmaf(path, new_path)
    log.info(f'Simlarity scores: {pprint.pformat(similarity_score)}')
    assert similarity_score['vmaf']['mean'] > 95.0
    assert similarity_score['vmaf']['min'] > 90.0

    return similarity_score['vmaf']['mean']
    # TODO: Check metadata (use code below)

def _check_metadata(path, new_path):
    info = get_video_info(path)
    new_info = get_video_info(new_path)
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

if __name__ == "__main__":
    typer.run(main)

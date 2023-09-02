#!/usr/bin/env python3

import datetime
import difflib, math, pprint, time, typer
import os
os.environ["LOGURU_LEVEL"] = "INFO"

import dictdiffer
import humanize

from auto_video_compression.ffmpeg import get_video_info, get_vmaf, convert, CONVERT_CONFIG
from loguru import logger as log

from pathlib import Path
from pprint import pformat
from typing import Dict, Optional
from unittest.mock import ANY

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
    start_time = time.time()
    new_path = convert_video(path, info, stream_types)
    elapsed_time = time.time() - start_time
    score = assert_conversion_ok(path, new_path)
    filesize = path.stat().st_size
    new_filesize = new_path.stat().st_size
    print(f'Conversion complete!\n')
    print(f'Configs:          {CONVERT_CONFIG}')
    print(f'Convertion time:  {float(info["format"]["duration"])/elapsed_time:.2f}x - {humanize.naturaldelta(elapsed_time)}')
    print(f'Similarity score: {score:.1f}')
    print(f'Reduction:        {100*(filesize - new_filesize)/filesize:.1f}% ({humanize.naturalsize(filesize - new_filesize)})')
    print(f'Old filesize:     {humanize.naturalsize(filesize)}')
    print(f'New filesize:     {humanize.naturalsize(new_filesize)}')
    log.info('Done')


def convert_video(path, info, stream_types):
    has_audio = 'audio' in stream_types
    if has_audio:
        audio_is_raw = info['streams'][1]['codec_name'].startswith('pcm') # https://trac.ffmpeg.org/wiki/audio%20types
        return convert(path, copy_audio=(not audio_is_raw))
    else:
        return convert(path, has_audio=False)

def assert_conversion_ok(path, new_path):
    similarity_score = get_vmaf(path, new_path)
    log.debug(f'Simlarity scores: {pprint.pformat(similarity_score)}')
    assert similarity_score['vmaf']['mean'] > 95.0
    assert similarity_score['vmaf']['min'] > 90.0
    _check_metadata(path, new_path)
    return similarity_score['vmaf']['mean']
    # TODO: Check metadata (use code below)

def _check_metadata(path, new_path):
    log.debug('Checking metadata')
    flat_n_sort = lambda d: dict(sorted((k.lower(), v) for k, v in flatten_dict(d).items()))
    info = flat_n_sort(get_video_info(path))
    new_info = flat_n_sort(get_video_info(new_path))
    # log.debug('Diferences between original and converted\n' + pformat(list(diff(info, new_info))) )
    TOLERANCE = 1 / 20 # a bit more than one frame
    close(info, new_info, 'streams.0.start_time', TOLERANCE)
    close(info, new_info, 'streams.1.start_time', TOLERANCE)
    close(info, new_info, 'format.duration', TOLERANCE)
    close(info, new_info, 'format.start_time', TOLERANCE)
    
    _compare_durations(info, new_info)

    def und_or_same(a, b, p):
        return a.get(p) == 'und' or a.get(p) == b.get(p)
    und_or_same(info, new_info, 'streams.0.tags.language')
    und_or_same(info, new_info, 'streams.1.tags.language')
    IRRELEVANT = (
    # We expect these to change as they are related to codecs/containers
    '''
    format.format_long_name
    format.format_name
    format.tags.encoder
    streams.0.tags.encoder
    streams.0.tags.duration
    streams.0.profile
    streams.0.codec_time_base
    streams.0.level
    streams.0.start_pts
    streams.0.extradata_size
    streams.0.codec_name
    streams.0.codec_long_name
    streams.0.codec_tag
    streams.0.codec_tag_string
    streams.0.refs
    streams.0.has_b_frames
    streams.1.codec_tag
    streams.1.codec_tag_string
    streams.1.tags.encoder
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
    streams.0.id
    streams.1.id
    '''
    # These are removed, but moved under 'tags.*'. We check equality above.
    '''
    streams.0.duration
    streams.0.tags.duration
    streams.1.duration
    streams.1.tags.duration
    streams.0.duration_ts
    streams.1.duration_ts
    '''
    # These are removed cause of https://superuser.com/questions/1523944/whats-the-difference-between-coded-width-and-width-in-ffprobe
    '''
    streams.0.coded_height
    streams.0.coded_width
    '''
    # We are using nb_read_frames. It is more accurate.
    '''
    streams.0.nb_frames
    streams.1.nb_frames
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
    format.filename
    streams.0.bit_rate
    streams.1.bit_rate
    '''
    # We check if these are close in the code above
    '''
    format.duration
    format.start_time
    streams.0.start_time
    streams.1.start_time
    '''
    # We check these in code above
    '''
    streams.0.tags.language 
    streams.1.tags.language 
    '''
    # TODO: this is changing, but i cant make it not :(
    '''
    streams.0.time_base
    streams.1.time_base
    '''
    ).split()
    # for i in IRRELEVANT:
    #     dictdiff.dot_lookup(info, i, parent=True)[i.split('.')[-1]] = ANY
    #     dictdiff.dot_lookup(new_info, i, parent=True)[i.split('.')[-1]] = ANY
    log.debug(f'Info: {pformat(info)}')
    log.debug(f'New Info: {pformat(new_info)}')
    lines = lambda d: [f'{k}: {v}' for k, v in d.items() if k not in IRRELEVANT]
    diff = list(difflib.unified_diff(lines(info), lines(new_info)))
    if diff:
        string_diff = '\n'.join(diff)
        log.error(f"Diff found in metadata.")
        raise ConvertionError(f"Diff found in metadata: {string_diff}")
    log.info("Metadata is ok")
    # the_diff = list(dictdiffer.diff(info, new_info, ))
    # assert not the_diff, pformat(the_diff)

def _compare_durations(info, new_info):
    TOLERANCE = 0.2 # TODO: time_base is being changed. Look into that
    def parse(time):
        obj = datetime.datetime.strptime(time.rstrip('0'), '%H:%M:%S.%f')
        return obj.hour * 3600 + obj.minute * 60 + obj.second + obj.microsecond / 1e6
    if d := info.get('streams.0.duration'):
        new_d = parse(new_info['streams.0.tags.duration'])
        if not math.isclose(float(d), new_d, abs_tol=TOLERANCE):
            raise ConvertionError(f'Error in duration of video: {d=} != {new_d=}')
    if d := info.get('streams.1.duration'):
        new_d = parse(new_info['streams.1.tags.duration'])
        if not math.isclose(float(d), new_d, abs_tol=TOLERANCE):
            raise ConvertionError(f'Error in duration of audio: {d=} != {new_d=}')


def close(original, converted, prop, tol):
    original_prop, converted_prop = original[prop], converted[prop]
    if not math.isclose(float(original_prop), float(converted_prop), abs_tol=tol):
        raise ConvertionError(f'Error in {prop!r}: {original_prop=} != {converted_prop=}')

def old_close(original, converted, prop, tol):
    original_prop, converted_prop = dictdiffer.dot_lookup(original, prop), dictdiffer.dot_lookup(converted, prop)
    if not math.isclose(float(original_prop), float(converted_prop), abs_tol=tol):
        raise ConvertionError(f'Error in {prop!r}: {original_prop=} != {converted_prop=}')

def flatten_dict(dictionary, parent_key=False, separator='.'):
    """
    Turn a nested dictionary into a flattened dictionary
    :param dictionary: The dictionary to flatten
    :param parent_key: The string to prepend to dictionary's keys
    :param separator: The string used to separate flattened keys
    :return: A flattened dictionary
    """

    from collections.abc import MutableMapping
    items = []
    for key, value in dictionary.items():
        new_key = str(parent_key) + separator + key if parent_key else key
        if isinstance(value, MutableMapping):
            if not value.items():
                items.append((new_key, None))
            else:
                items.extend(flatten_dict(value, new_key, separator).items())
        elif isinstance(value, list):
            if len(value):
                for k, v in enumerate(value):
                    items.extend(flatten_dict({str(k): v}, new_key, separator).items())
            else:
                items.append((new_key, None))
        else:
            items.append((new_key, value))
    return dict(items)


if __name__ == "__main__":
    typer.run(main)

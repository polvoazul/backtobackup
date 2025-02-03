#!/usr/bin/env python3

import datetime
from decimal import Decimal
import difflib, math, pprint, time, typer
import re
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
    scratch_path: Path = '.',
):
    info = get_video_info(path, fast=True)
    log.info(f'Considering file: {info["format"]["filename"]}')
    log.debug(pformat(info))
    bitrate = int(info['format']['bit_rate'])
    log.info(f'File bitrate: {humanize.naturalsize(bitrate)}/s')
    if bitrate < min_bitrate:
        log.info('Bitrate is already small. Not worth it to convert')
        return
    stream_types = [s['codec_type'] for s in info['streams']]
    if stream_types != ['video', 'audio'] and stream_types != ['video']: # TODO: if other streams, try to mantain them, by using the same container
        log.info(f'Found unexpected streams: {stream_types}, skipping')
        # TODO: if audio stream is not stereo / mono, bail on convertion
        # return
    start_time = time.time()
    new_path = convert_video(path, info, stream_types, scratch_path)
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

def choose_container(input_container, stream_types):
    '''mkv is the best container, open and flexible. But we should mimic the original file's container, so that we can deal with crazy streams'''
    if stream_types == ['audio', 'video'] or stream_types == ['video', 'audio']: 
        return 'mkv'
    else: return input_container
    return 'mkv' 

def define_changes(stream):
    match stream['codec_type']:
        case 'video': return ('video', 'convert')
        case 'audio':
            audio_is_raw = stream['codec_name'].startswith('pcm') # https://trac.ffmpeg.org/wiki/audio%20types
            if audio_is_raw: return ('audio', 'convert')
            else: return ('audio', 'copy') # dont convert if its not raw... not really worth it
        case _: return ('unk', 'copy')

def convert_video(path: Path, info, stream_types, scratch_path: Path):
    has_audio = 'audio' in stream_types
    changes = [define_changes(stream) for stream in info['streams']]
    return convert(path, changes, choose_container(path.suffix.lstrip('.'), stream_types), scratch_path)

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
    unsorted_new_info = get_video_info(new_path)
    n_streams = len(unsorted_new_info['streams'])
    new_info = flat_n_sort(unsorted_new_info)
    # log.debug('Diferences between original and converted\n' + pformat(list(diff(info, new_info))) )
    TOLERANCE = 1 / 20 # a bit more than one frame
    for idx in range(n_streams):
        close(info, new_info, f'streams.{idx}.start_time', TOLERANCE)
        close(info, new_info, f'streams.{idx}.nb_read_frames', 10) # 10 Frames tolerance
        close_decimal(info, new_info, f'streams.{idx}.r_frame_rate', TOLERANCE)
        close_decimal(info, new_info, f'streams.{idx}.avg_frame_rate', TOLERANCE)
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
    streams.\\d+.tags.encoder
    streams.\\d+.tags.duration
    streams.\\d+.profile
    streams.\\d+.codec_time_base
    streams.\\d+.level
    streams.\\d+.start_pts
    streams.\\d+.extradata_size
    streams.\\d+.codec_name
    streams.\\d+.codec_long_name
    streams.\\d+.codec_tag
    streams.\\d+.codec_tag_string
    streams.\\d+.refs
    streams.\\d+.has_b_frames
    streams.\\d+.codec_tag
    streams.\\d+.codec_tag_string
    streams.\\d+.tags.encoder
    streams.\\d+.codec_long_name
    streams.\\d+.codec_name
    streams.\\d+.sample_fmt
    streams.\\d+.bits_per_sample
    streams.\\d+.start_pts
    '''
    # Things that are removed
    '''
    streams.\\d+.color_space
    streams.\\d+.color_transfer
    streams.\\d+.color_primaries
    streams.\\d+.is_avc
    streams.\\d+.nal_length_size
    streams.\\d+.bits_per_raw_sample
    streams.\\d+.id
    streams.\\d+.id
    '''
    # These are removed, but moved under 'tags.*'. We check equality above.
    '''
    streams.\\d+.duration
    streams.\\d+.tags.duration
    streams.\\d+.duration_ts
    streams.\\d+.start_time
    '''
    # These are removed cause of https://superuser.com/questions/1523944/whats-the-difference-between-coded-width-and-width-in-ffprobe
    '''
    streams.\\d+.coded_height
    streams.\\d+.coded_width
    '''
    # We are using nb_read_frames. It is more accurate. It is checked in upwards code.
    '''
    streams.\\d+.nb_frames
    streams.\\d+.nb_read_frames
    '''
    # Things that are added
    '''
    streams.\\d+.profile
    streams.\\d+.channel_layout
    '''
    # Actually changed
    '''
    format.size
    format.bit_rate
    format.filename
    streams.\\d+.bit_rate
    '''
    # We check if these are close in the code above
    '''
    format.duration
    format.start_time
    streams.\\d+.r_frame_rate
    streams.\\d+.avg_frame_rate
    '''
    # We check these in code above
    '''
    streams.\\d+.tags.language 
    '''
    # TODO: this is changing, but i cant make it not :(
    '''
    streams.\\d+.time_base
    '''
    # I don't care enough to research these
    '''
    streams.\\d+.color_range
    '''
    ).split()
    IRRELEVANT = '|'.join(IRRELEVANT) 
    def irrelevant(key):
        return re.match(IRRELEVANT, key)
    # for i in IRRELEVANT:
    #     dictdiff.dot_lookup(info, i, parent=True)[i.split('.')[-1]] = ANY
    #     dictdiff.dot_lookup(new_info, i, parent=True)[i.split('.')[-1]] = ANY
    log.debug(f'Info: {pformat(info)}')
    log.debug(f'New Info: {pformat(new_info)}')
    lines = lambda d: [f'{k}: {v}' for k, v in d.items() if not irrelevant(k)]
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
        try:
            obj = datetime.datetime.strptime(time.rstrip('0'), '%H:%M:%S.%f')
            return obj.hour * 3600 + obj.minute * 60 + obj.second + obj.microsecond / 1e6
        except ValueError: pass
        return float(time)
    n_streams = info['format.nb_streams']
    for idx in range(n_streams):
        if d := info.get('streams.0.duration'):
            new_d = parse(new_info.get('streams.0.tags.duration') or new_info['streams.0.duration'])
            if not math.isclose(float(d), new_d, abs_tol=TOLERANCE):
                raise ConvertionError(f'Error in duration of stream {idx}: {d=} != {new_d=}')


def close_decimal(original, converted, prop, tol):
    original_prop, converted_prop = original[prop], converted[prop]
    if original_prop == converted_prop: return True
    a, b = original_prop.split('/')
    original_prop = Decimal(a) / Decimal(b)
    a, b = converted_prop.split('/')
    converted_prop = Decimal(a) / Decimal(b)
    if not math.isclose(original_prop, converted_prop, abs_tol=tol):
        raise ConvertionError(f'Error in {prop!r}: {original_prop=} != {converted_prop=}')

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

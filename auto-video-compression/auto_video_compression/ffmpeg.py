from pathlib import Path
from loguru import logger as log
import platform
import json, os.path, math
from typing import Dict, Literal, Optional, List, Tuple, TypedDict
import subprocess
import importlib.resources

BASE = importlib.resources.files('auto_video_compression').parent # type: ignore
BASE = ''

class FfmpegError(Exception): 
    def __init__(self, e: subprocess.CalledProcessError):
        super().__init__(f"Error when calling FFMPEG. {e.stdout=} \n {e.stderr=}")
        
def run(command: List[str], capture=True):
    log.info(f'Calling ffmpeg command: {" ".join(command)}')
    if capture:
        try:
            return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise FfmpegError(e)
    else:
        return subprocess.run(command, check=True)

def get_video_info(filename: Path, fast=False):
    log.info(f'Getting video {filename!r} info')
    assert filename.is_file()
    slow_commands = [
        '-count_frames',            # count frames in nb_read_frames
    ]
    ffprobe_command = [
        f'{BASE}ffprobe',
        '-v', 'quiet',             # Quiet mode
        '-print_format', 'json',    # Output format as JSON
        '-show_format',             # Show format information
        '-show_streams',            # Show stream information
        *([] if fast else slow_commands),
        str(filename),                   # Replace with the actual input file path
    ]
    result = run(ffprobe_command)
    video_info = json.loads(result.stdout)
    return video_info

class _Score(TypedDict):
    harmonic_mean: float
    max: float
    mean: float
    min: float

class Similarity(TypedDict):
    integer_adm2: _Score
    integer_adm_scale0: _Score
    integer_adm_scale1: _Score
    integer_adm_scale2: _Score
    integer_adm_scale3: _Score
    integer_motion2: _Score
    integer_motion: _Score
    integer_vif_scale0: _Score
    integer_vif_scale1: _Score
    integer_vif_scale2: _Score
    integer_vif_scale3: _Score
    psnr_y: _Score
    psnr_cb: _Score
    psnr_cr: _Score
    vmaf: _Score


def get_vmaf(f1: Path, f2: Path) -> Similarity: # todo:  further investigate this
    assert f1.is_file() and f2.is_file()
    log.info(f'Getting similarity score between {f1!r} and {f2!r}')
    import tempfile, json_stream
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', dir='.') as f:
        ffmpeg_command = [
            f'{BASE}ffmpeg',
            '-i', str(f1),   # Input file 1
            '-i', str(f2),   # Input file 2
            '-lavfi', f"[0:v][1:v]libvmaf=feature='name=psnr':log_fmt=json:log_path={Path(f.name).name}:n_subsample=10",  # VMAF filter with PSNR mode and JSON output
            '-f', 'null', '-'  # Null output to display VMAF info
        ]
        try:
            result = run(ffmpeg_command, capture=False)
        except subprocess.CalledProcessError as e:
            raise FfmpegError(e)
        f.seek(0)
        vmaf_info = json_stream.to_standard_types(json_stream.load(f)['pooled_metrics'])
    return vmaf_info


CONVERT_CONFIG = dict(
    CRF = '28', # Size/Quality tradeoff. From 0 to 51. Lower is better quality. Default is 28. # https://trac.ffmpeg.org/wiki/Encode/H.265
    PRESET = 'medium' # https://x265.readthedocs.io/en/master/cli.html#cmdoption-preset # ultrafast superfast veryfast faster fast *medium* slow slower veryslow
)

Change = Tuple[Literal['unk','video', 'audio'], Literal['copy', 'audio']]

def convert(path: Path, changes: List[Change], container, scratch_path: Path) -> Path:
    assert path.is_file()
    name = path.stem
    out_path = scratch_path / Path(str(name) + f'.CONVERTED.{container}') 
    def instruction(index, c: Change):
        match c[0]:
            case 'video': out = [f'-map', f'0:{index}', f'-c:{index}']
            case 'audio': out = [f'-map', f'0:{index}', f'-c:{index}']
            case _:
                assert c[1] == 'copy'
                return ['-map', f'0:{index}', '-c', 'copy']
        match c:
            case (_, 'copy'):
                out += ['copy']
            case ('video', 'convert'):
                out += ['libx265', '-crf', CONVERT_CONFIG['CRF'], '-preset', CONVERT_CONFIG['PRESET'],
                        '-vsync', '0', '-enc_time_base', '-1', '-video_track_timescale', '15360',
                        '-copyts',
                ]
            case ('audio', 'convert'):
                out += choose_audio_codec(index, container)
            case _:
                assert False, f"Instruction unclear: {c!r}"
        return out
    instructions = [instruction(i, c) for i, c in enumerate(changes)]
    # audio = ['-c:a', 'copy'] if copy_audio else ['-c:a', 'libopus', '-b:a', '192k']
    flatten = lambda z: [x for y in z for x in y]
    ffmpeg_command = [
        f'{BASE}ffmpeg', '-y',
        '-i', str(path),
        *flatten(instructions),
        str(out_path),
    ]
    run(ffmpeg_command, capture=False)
    assert out_path.is_file() and path.is_file()
    return out_path

def choose_audio_codec(index, container):
    match container:
        case 'mkv' | 'mka' | 'mp4' | 'webm' | 'mp4' | '.ts':
            return ['libopus', '-b:a', '192k']
        case 'mov' :
            if platform.system() == 'Darwin':
                return ['aac_at', f'-q:{index}', '2'] # ~250kb/s
            else:
                return ['aac', f'-b:{index}', '256kb']
        case _:
            assert False, f"We don't know how to deal with this extension {container=}"

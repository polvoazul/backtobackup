#!/bin/bash -ex
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"/auto-video-compression

which xonsh
which ffmpeg

#!/bin/bash -ex
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/auto-video-compression/"

FILES=("*.py" "auto_video_compression/*.py")
FILES="${FILES[@]}"

(mypy --ignore-missing-imports $FILES || true; echo MYPY done) &
pytype $FILES

rm -f data/*
cp file_example_MP4_1920_18MG.mp4 data/in.mp4
cd data

../main.py in.mp4  --min-bitrate 1000

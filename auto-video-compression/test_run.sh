#!/bin/bash -ex

./main.xsh in.mp4  --min-bitrate 1000
cp in.mkv converted.mkv
cp in.mp4.bak in.mp4

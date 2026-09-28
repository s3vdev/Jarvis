#!/bin/bash
# Finder-friendly name. The real starter is launch.command next to this file.
exec "$(cd "$(dirname "$0")" && pwd)/launch.command"

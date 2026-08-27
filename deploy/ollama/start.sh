#!/usr/bin/env bash
# Render injects $PORT; Ollama takes its bind address from OLLAMA_HOST.
set -euo pipefail
export OLLAMA_HOST="0.0.0.0:${PORT:-11434}"
exec ollama serve

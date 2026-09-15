#!/usr/bin/env bash
# Start default perception servers for FileWizard (recommended profile).
# Requires: llama-server on PATH (llama.cpp).
#
#   ./scripts/start-perception.sh
#   ./scripts/start-perception.sh --ocr-only
#   ./scripts/start-perception.sh --vision-only
#
set -euo pipefail

OCR_PORT="${OCR_PORT:-8080}"
VISION_PORT="${VISION_PORT:-8081}"
OCR_HF="${OCR_HF:-ggml-org/GLM-OCR-GGUF:Q8_0}"
# Override with a concrete GGUF repo you have, e.g. lmstudio-community/Qwen3-VL-2B-Instruct-GGUF
VISION_HF="${VISION_HF:-}"

MODE="${1:-both}"

if ! command -v llama-server >/dev/null 2>&1; then
  echo "llama-server not found on PATH."
  echo "Install llama.cpp, then re-run this script."
  echo "  https://github.com/ggml-org/llama.cpp"
  exit 1
fi

start_ocr() {
  echo "Starting OCR (GLM-OCR) on :${OCR_PORT} …"
  echo "  llama-server -hf ${OCR_HF} --port ${OCR_PORT}"
  exec llama-server -hf "${OCR_HF}" --port "${OCR_PORT}"
}

start_vision() {
  if [[ -z "${VISION_HF}" ]]; then
    echo "VISION_HF is not set."
    echo "Example:"
    echo "  VISION_HF=lmstudio-community/Qwen3-VL-2B-Instruct-GGUF \\"
    echo "    $0 --vision-only"
    exit 1
  fi
  echo "Starting vision (Qwen3-VL) on :${VISION_PORT} …"
  echo "  llama-server -hf ${VISION_HF} --port ${VISION_PORT}"
  exec llama-server -hf "${VISION_HF}" --port "${VISION_PORT}"
}

case "${MODE}" in
  --ocr-only|ocr)
    start_ocr
    ;;
  --vision-only|vision)
    start_vision
    ;;
  both|*)
    echo "Open two terminals:"
    echo "  $0 --ocr-only"
    echo "  VISION_HF=<qwen3-vl-2b-gguf-repo> $0 --vision-only"
    echo ""
    echo "Then:"
    echo "  filewizard perception status"
    echo "  filewizard perception test ./some.png --profile recommended"
    ;;
esac

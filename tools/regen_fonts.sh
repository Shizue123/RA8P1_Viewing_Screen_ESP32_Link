#!/bin/bash
# v0.9.23: 用 lv_font_conv 重生成 sc_14.c + sc_16.c
# 调用方式: bash tools/regen_fonts.sh
set -e

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OTF="$PROJ_DIR/UI/fonts/NotoSansCJKsc-Regular.otf"
CHARS_FILE="$PROJ_DIR/tools/font_chars.txt"
SRC_DIR="$PROJ_DIR/src"

if [ ! -f "$OTF" ]; then
    echo "ERROR: NotoSansCJKsc-Regular.otf not found at $OTF" >&2
    exit 1
fi

if [ ! -f "$CHARS_FILE" ]; then
    echo "ERROR: font_chars.txt not found at $CHARS_FILE" >&2
    exit 1
fi

# lv_font_conv 把 symbols 串当成单字符处理,自动 unicode 化
CHARS=$(cat "$CHARS_FILE")

echo "=== Regenerating ui_font_sc_14.c (bpp=1, size=14) ==="
lv_font_conv \
    --font "$OTF" \
    --size 14 \
    --bpp 1 \
    --format lvgl \
    --no-compress \
    --no-prefilter \
    --symbols "$CHARS" \
    -o "$SRC_DIR/ui_font_sc_14.c"

echo "=== Regenerating ui_font_sc_16.c (bpp=1, size=16) ==="
lv_font_conv \
    --font "$OTF" \
    --size 16 \
    --bpp 1 \
    --format lvgl \
    --no-compress \
    --no-prefilter \
    --symbols "$CHARS" \
    -o "$SRC_DIR/ui_font_sc_16.c"

echo "=== Font regeneration complete ==="
ls -la "$SRC_DIR/ui_font_sc_14.c" "$SRC_DIR/ui_font_sc_16.c"
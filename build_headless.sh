#!/bin/bash
# RA8P1 除ui版 headless build v1
# 策略: 复用 e2 studio GUI 编译好的 .elf.in 参数文件(里面含 600+ .o 列表),
#       手动 gcc 编译 src/*.c(只新改的)+ 直接调 arm-none-eabi-gcc 链接
#
# 流程:
#   1. 写 cfg.h stub (r_sci_b_spi_cfg.h 等)
#   2. 手动 gcc 编译 src/*.c(避免 mk 子 shell PATH 问题)
#   3. sed 改 elf.in: fsp.ld 路径 + D:/Renesas -> F:/
#   4. 调 arm-none-eabi-gcc @"elf.in" 链接
#   5. objcopy -> .srec
set -e
PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
DEBUG_DIR="$PROJ_DIR/Debug"

resolve_toolchain_bin() {
    if [ -n "${ARM_GCC_BIN:-}" ] && [ -x "${ARM_GCC_BIN}/arm-none-eabi-gcc.exe" ]; then
        printf '%s\n' "$ARM_GCC_BIN"
        return 0
    fi

    for candidate in \
        "C:/Program Files (x86)/Arm GNU Toolchain arm-none-eabi/13.2 Rel1/bin" \
        "C:/Program Files/Arm GNU Toolchain arm-none-eabi/13.2 Rel1/bin" \
        "C:/Renesas/e2_studio/Utilities/gcc_arm/bin" \
        "D:/Netease/toolchains/gcc_arm/13.2.rel1/bin"
    do
        if [ -x "${candidate}/arm-none-eabi-gcc.exe" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
        dirname "$(command -v arm-none-eabi-gcc)"
        return 0
    fi

    return 1
}

TOOLCHAIN_BIN="$(resolve_toolchain_bin || true)"
if [ -z "$TOOLCHAIN_BIN" ]; then
    echo "ERROR: arm-none-eabi toolchain not found. Set ARM_GCC_BIN to the toolchain bin directory." >&2
    exit 1
fi

GCC="${TOOLCHAIN_BIN}/arm-none-eabi-gcc.exe"
OBJCOPY="${TOOLCHAIN_BIN}/arm-none-eabi-objcopy.exe"
SIZE="${TOOLCHAIN_BIN}/arm-none-eabi-size.exe"

cd "$DEBUG_DIR"

# 1. 补 stub cfg.h
mkdir -p "$PROJ_DIR/ra_cfg/fsp_cfg"
for cfg in r_sci_b_spi r_iic_master; do
    case $cfg in
        r_sci_b_spi) cat > "$PROJ_DIR/ra_cfg/fsp_cfg/${cfg}_cfg.h" << 'EOF'
#ifndef R_SCI_B_SPI_CFG_H_
#define R_SCI_B_SPI_CFG_H_
#define SCI_B_SPI_CFG_PARAM_CHECKING_ENABLE (0)
#endif
EOF
        ;;
        r_iic_master) cat > "$PROJ_DIR/ra_cfg/fsp_cfg/${cfg}_cfg.h" << 'EOF'
#ifndef R_IIC_MASTER_CFG_H_
#define R_IIC_MASTER_CFG_H_
#define IIC_MASTER_CFG_PARAM_CHECKING_ENABLE (0)
#endif
EOF
        ;;
    esac
done

if [ ! -f "$PROJ_DIR/ra_cfg/fsp_cfg/r_gpt_cfg.h" ]; then
    cat > "$PROJ_DIR/ra_cfg/fsp_cfg/r_gpt_cfg.h" << 'EOF'
/* generated configuration header file - do not edit */
#ifndef R_GPT_CFG_H_
#define R_GPT_CFG_H_
#ifdef __cplusplus
extern "C" {
#endif

#define GPT_CFG_PARAM_CHECKING_ENABLE (BSP_CFG_PARAM_CHECKING_ENABLE)
#define GPT_CFG_OUTPUT_SUPPORT_ENABLE (1)
#define GPT_CFG_WRITE_PROTECT_ENABLE  (0)

#ifndef BSP_CFG_GPT_COUNT_CLOCK_SOURCE
#define GPT_CFG_GPTCLK_BYPASS         (0)
#else
#define GPT_CFG_GPTCLK_BYPASS         (BSP_CFG_GPT_COUNT_CLOCK_SOURCE)
#endif

#ifdef __cplusplus
}
#endif
#endif /* R_GPT_CFG_H_ */
EOF
fi

# 2. 手动编译 src/ 所有 .c
CFLAGS="-mthumb -mfloat-abi=hard -mcpu=cortex-m85+nopacbti -O2 \
-fmessage-length=0 -fsigned-char -ffunction-sections -fdata-sections \
-fno-strict-aliasing -Wno-error -D_RENESAS_RA_ -D_RA_CORE=CPU0 -D_RA_ORDINAL=1 \
-std=c99 -Wno-stringop-overflow -Wno-format-truncation -flax-vector-conversions \
--param=min-pagesize=0 -g -c"

INCS=(
  -I"../"  # v0.9.22: 关键! ui_font_sc_14.c/sc_16.c #include "lvgl/lvgl.h" 需要 -I"../" 才能找到
  -I"../ra_gen" -I.
  -I"../ra_cfg/fsp_cfg/bsp" -I"../ra_cfg/fsp_cfg"
  -I"../src"
  -I"../ra/fsp/inc" -I"../ra/fsp/inc/api" -I"../ra/fsp/inc/instances"
  -I"../ra/arm/CMSIS_6/CMSIS/Core/Include"
  -I"../lvgl"
  -I"../ra_cfg/fsp_cfg/lvgl/lvgl"
  -I"../ra/lvgl/lvgl/src/widgets/tileview"
  -I"../ra/lvgl/lvgl/src/widgets/tabview"
  -I"../ra/lvgl/lvgl/src/widgets/switch"
  -I"../ra/lvgl/lvgl/src/widgets/spinbox"
  -I"../ra/lvgl/lvgl/src/widgets/slider"
  -I"../ra/lvgl/lvgl/src/widgets/roller"
  -I"../ra/lvgl/lvgl/src/widgets/objx_templ"
  -I"../ra/lvgl/lvgl/src/widgets/menu"
  -I"../ra/lvgl/lvgl/src/widgets/list"
  -I"../ra/lvgl/lvgl/src/widgets/led"
  -I"../ra/lvgl/lvgl/src/widgets/keyboard"
  -I"../ra/lvgl/lvgl/src/widgets/image"
  -I"../ra/lvgl/lvgl/src/widgets/checkbox"
  -I"../ra/lvgl/lvgl/src/widgets/canvas"
  -I"../ra/lvgl/lvgl/src/widgets/buttonmatrix"
  -I"../ra/lvgl/lvgl/src/widgets/bar"
  -I"../ra/lvgl/lvgl/src/widgets/animimage"
  -I"../ra/lvgl/lvgl/src/widgets/win"
  -I"../ra/lvgl/lvgl/src/widgets/textarea"
  -I"../ra/lvgl/lvgl/src/widgets/table"
  -I"../ra/lvgl/lvgl/src/widgets/spinner"
  -I"../ra/lvgl/lvgl/src/widgets/span"
  -I"../ra/lvgl/lvgl/src/widgets/scale"
  -I"../ra/lvgl/lvgl/src/widgets/property"
  -I"../ra/lvgl/lvgl/src/widgets/msgbox"
  -I"../ra/lvgl/lvgl/src/widgets/lottie"
  -I"../ra/lvgl/lvgl/src/widgets/line"
  -I"../ra/lvgl/lvgl/src/widgets/label"
  -I"../ra/lvgl/lvgl/src/widgets/imagebutton"
  -I"../ra/lvgl/lvgl/src/widgets/dropdown"
  -I"../ra/lvgl/lvgl/src/widgets/chart"
  -I"../ra/lvgl/lvgl/src/widgets/calendar"
  -I"../ra/lvgl/lvgl/src/widgets/button"
  -I"../ra/lvgl/lvgl/src/widgets/arc"
  -I"../ra/lvgl/lvgl/src/widgets/3dtexture"
  -I"../ra/lvgl/lvgl/src/themes"
  -I"../ra/lvgl/lvgl/src/stdlib"
  -I"../ra/lvgl/lvgl/src/others"
  -I"../ra/lvgl/lvgl/src/osal"
  -I"../ra/lvgl/lvgl/src/misc"
  -I"../ra/lvgl/lvgl/src/libs"
  -I"../ra/lvgl/lvgl/src/layouts"
  -I"../ra/lvgl/lvgl/src/indev"
  -I"../ra/lvgl/lvgl/src/font"
  -I"../ra/lvgl/lvgl/src/drivers"
  -I"../ra/lvgl/lvgl/src/draw"
  -I"../ra/lvgl/lvgl/src/display"
  -I"../ra/lvgl/lvgl/src/core"
  -I"../ra/lvgl/lvgl/src"
  -I"../ra/lvgl/lvgl/examples"
  -I"../ra/lvgl/lvgl/demos"
  -I"../ra/lvgl/lvgl"
)

echo "=== Compiling src/*.c (warning-as-error disabled) ==="
for f in app_ui ui_font_sc_14 ui_font_sc_16 ft6336 lcd_spi \
         lv_port_disp lv_port_indev touch_debug_rtt \
         aht20 bh1750 device_registry esp32_link i2c_bus_s1 sg90_servo platform_ports \
         ui_theme ui_widgets \
         hal_entry hal_warmstart; do
    if [ -f "../src/${f}.c" ]; then
        echo "  ${f}.c"
        "$GCC" $CFLAGS "${INCS[@]}" -o "src/${f}.o" "../src/${f}.c" 2>&1 | grep -v "^Building file" | grep -v "^$" | head -5 || true
    fi
done

# 3. sed 改 elf.in 路径
sed -i 's|-T "fsp.ld"|-T "../script/fsp.ld"|' RA8P1_Viewing_Screen_ESP32_Link.elf.in
sed -i 's|D:\\\\Renesas-Workspace\\\\RA8P1_Viewing_Screen_ESP32_Link|F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版|g' RA8P1_Viewing_Screen_ESP32_Link.elf.in
# 插入 ui_theme.o 和 ui_widgets.o 到链接列表 (在 ui_font_sc_16.o 之后，避免重复)
grep -q "ui_theme.o" RA8P1_Viewing_Screen_ESP32_Link.elf.in || \
    sed -i 's|./src/ui_font_sc_16.o|./src/ui_font_sc_16.o ./src/ui_theme.o ./src/ui_widgets.o|' RA8P1_Viewing_Screen_ESP32_Link.elf.in

# 4. 链接
echo "=== Linking ==="
"$GCC" @"RA8P1_Viewing_Screen_ESP32_Link.elf.in" 2>&1 | tail -3

# 5. objcopy -> srec
echo "=== objcopy -> srec ==="
"$OBJCOPY" -O srec RA8P1_Viewing_Screen_ESP32_Link.elf RA8P1_Viewing_Screen_ESP32_Link.srec

# 6. 报告
echo "=== Build complete ==="
ls -la RA8P1_Viewing_Screen_ESP32_Link.elf RA8P1_Viewing_Screen_ESP32_Link.srec 2>/dev/null
"$SIZE" --format=berkeley RA8P1_Viewing_Screen_ESP32_Link.elf 2>&1 | head -3

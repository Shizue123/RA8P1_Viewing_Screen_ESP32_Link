################################################################################
# Automatically-generated file. Do not edit!
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
C_SRCS += \
../src/aht20.c \
../src/app_ui.c \
../src/bh1750.c \
../src/esp32_link.c \
../src/ft6336.c \
../src/hal_entry.c \
../src/hal_warmstart.c \
../src/i2c_bus_s1.c \
../src/lcd_spi.c \
../src/lv_port_disp.c \
../src/lv_port_indev.c \
../src/platform_ports.c \
../src/sg90_servo.c \
../src/touch_debug_rtt.c \
../src/ui_font_sc_14.c \
../src/ui_font_sc_16.c 

C_DEPS += \
./src/aht20.d \
./src/app_ui.d \
./src/bh1750.d \
./src/esp32_link.d \
./src/ft6336.d \
./src/hal_entry.d \
./src/hal_warmstart.d \
./src/i2c_bus_s1.d \
./src/lcd_spi.d \
./src/lv_port_disp.d \
./src/lv_port_indev.d \
./src/platform_ports.d \
./src/sg90_servo.d \
./src/touch_debug_rtt.d \
./src/ui_font_sc_14.d \
./src/ui_font_sc_16.d 

OBJS += \
./src/aht20.o \
./src/app_ui.o \
./src/bh1750.o \
./src/esp32_link.o \
./src/ft6336.o \
./src/hal_entry.o \
./src/hal_warmstart.o \
./src/i2c_bus_s1.o \
./src/lcd_spi.o \
./src/lv_port_disp.o \
./src/lv_port_indev.o \
./src/platform_ports.o \
./src/sg90_servo.o \
./src/touch_debug_rtt.o \
./src/ui_font_sc_14.o \
./src/ui_font_sc_16.o 

SREC += \
RA8P1_Viewing_Screen_ESP32_Link.srec 

MAP += \
RA8P1_Viewing_Screen_ESP32_Link.map 


# Each subdirectory must supply rules for building sources it contributes
src/%.o: ../src/%.c
	$(file > $@.in,-mthumb -mfloat-abi=hard -mcpu=cortex-m85+nopacbti -O2 -fmessage-length=0 -fsigned-char -ffunction-sections -fdata-sections -fno-strict-aliasing -Wunused -Wuninitialized -Wall -Wextra -Wmissing-declarations -Wconversion -Wpointer-arith -Wshadow -Wlogical-op -Waggregate-return -Wfloat-equal -g -D_RENESAS_RA_ -D_RA_CORE=CPU0 -D_RA_ORDINAL=1 -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra_gen" -I"." -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra_cfg/fsp_cfg/bsp" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra_cfg/fsp_cfg" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/src" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/fsp/inc" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/fsp/inc/api" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/fsp/inc/instances" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/arm/CMSIS_6/CMSIS/Core/Include" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/lvgl" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra_cfg/fsp_cfg/lvgl/lvgl" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/tileview" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/tabview" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/switch" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/spinbox" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/slider" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/roller" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/objx_templ" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/menu" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/list" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/led" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/keyboard" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/image" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/checkbox" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/canvas" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/buttonmatrix" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/bar" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/animimage" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/win" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/textarea" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/table" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/spinner" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/span" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/scale" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/property" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/msgbox" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/lottie" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/line" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/label" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/imagebutton" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/dropdown" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/chart" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/calendar" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/button" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/arc" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/widgets/3dtexture" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/themes" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/stdlib" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/others" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/osal" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/misc" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/libs" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/layouts" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/indev" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/font" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/drivers" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/draw" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/display" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src/core" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/src" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/examples" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl/demos" -I"F:/1234/e2_studio/ddmm0606/RA8P1_除ui,基本完成版/ra/lvgl/lvgl" -std=c99 -Wno-stringop-overflow -Wno-format-truncation -flax-vector-conversions --param=min-pagesize=0 -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" -c -o "$@" -x c "$<")
	@echo Building file: $< && arm-none-eabi-gcc @"$@.in"


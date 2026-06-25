################################################################################
# Automatically-generated file. Do not edit!
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
C_SRCS += \
../ra/lvgl/lvgl/src/core/lv_group.c \
../ra/lvgl/lvgl/src/core/lv_obj.c \
../ra/lvgl/lvgl/src/core/lv_obj_class.c \
../ra/lvgl/lvgl/src/core/lv_obj_draw.c \
../ra/lvgl/lvgl/src/core/lv_obj_event.c \
../ra/lvgl/lvgl/src/core/lv_obj_id_builtin.c \
../ra/lvgl/lvgl/src/core/lv_obj_pos.c \
../ra/lvgl/lvgl/src/core/lv_obj_property.c \
../ra/lvgl/lvgl/src/core/lv_obj_scroll.c \
../ra/lvgl/lvgl/src/core/lv_obj_style.c \
../ra/lvgl/lvgl/src/core/lv_obj_style_gen.c \
../ra/lvgl/lvgl/src/core/lv_obj_tree.c \
../ra/lvgl/lvgl/src/core/lv_refr.c 

C_DEPS += \
./ra/lvgl/lvgl/src/core/lv_group.d \
./ra/lvgl/lvgl/src/core/lv_obj.d \
./ra/lvgl/lvgl/src/core/lv_obj_class.d \
./ra/lvgl/lvgl/src/core/lv_obj_draw.d \
./ra/lvgl/lvgl/src/core/lv_obj_event.d \
./ra/lvgl/lvgl/src/core/lv_obj_id_builtin.d \
./ra/lvgl/lvgl/src/core/lv_obj_pos.d \
./ra/lvgl/lvgl/src/core/lv_obj_property.d \
./ra/lvgl/lvgl/src/core/lv_obj_scroll.d \
./ra/lvgl/lvgl/src/core/lv_obj_style.d \
./ra/lvgl/lvgl/src/core/lv_obj_style_gen.d \
./ra/lvgl/lvgl/src/core/lv_obj_tree.d \
./ra/lvgl/lvgl/src/core/lv_refr.d 

OBJS += \
./ra/lvgl/lvgl/src/core/lv_group.o \
./ra/lvgl/lvgl/src/core/lv_obj.o \
./ra/lvgl/lvgl/src/core/lv_obj_class.o \
./ra/lvgl/lvgl/src/core/lv_obj_draw.o \
./ra/lvgl/lvgl/src/core/lv_obj_event.o \
./ra/lvgl/lvgl/src/core/lv_obj_id_builtin.o \
./ra/lvgl/lvgl/src/core/lv_obj_pos.o \
./ra/lvgl/lvgl/src/core/lv_obj_property.o \
./ra/lvgl/lvgl/src/core/lv_obj_scroll.o \
./ra/lvgl/lvgl/src/core/lv_obj_style.o \
./ra/lvgl/lvgl/src/core/lv_obj_style_gen.o \
./ra/lvgl/lvgl/src/core/lv_obj_tree.o \
./ra/lvgl/lvgl/src/core/lv_refr.o 

SREC += \
RA8P1_Viewing_Screen_ESP32_Link.srec 

MAP += \
RA8P1_Viewing_Screen_ESP32_Link.map 


# Each subdirectory must supply rules for building sources it contributes
ra/lvgl/lvgl/src/core/%.o: ../ra/lvgl/lvgl/src/core/%.c
	$(file > $@.in,-mthumb -mfloat-abi=hard -mcpu=cortex-m85+nopacbti -O2 -fmessage-length=0 -fsigned-char -ffunction-sections -fdata-sections -fno-strict-aliasing -Wunused -Wuninitialized -Wall -Wextra -Wmissing-declarations -Wconversion -Wpointer-arith -Wshadow -Wlogical-op -Waggregate-return -Wfloat-equal -g -D_RENESAS_RA_ -D_RA_CORE=CPU0 -D_RA_ORDINAL=1 -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_gen" -I"." -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/bsp" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/src" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/inc" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/inc/api" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/fsp/inc/instances" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/arm/CMSIS_6/CMSIS/Core/Include" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/lvgl" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra_cfg/fsp_cfg/lvgl/lvgl" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/tileview" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/tabview" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/switch" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/spinbox" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/slider" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/roller" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/objx_templ" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/menu" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/list" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/led" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/keyboard" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/image" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/checkbox" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/canvas" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/buttonmatrix" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/bar" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/animimage" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/win" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/textarea" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/table" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/spinner" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/span" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/scale" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/property" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/msgbox" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/lottie" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/line" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/label" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/imagebutton" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/dropdown" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/chart" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/calendar" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/button" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/arc" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/widgets/3dtexture" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/themes" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/stdlib" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/others" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/osal" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/misc" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/libs" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/layouts" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/indev" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/font" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/drivers" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/draw" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/display" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src/core" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/src" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/examples" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl/demos" -I"D:/Renesas-Workspace/RA8P1_Viewing_Screen_ESP32_Link/ra/lvgl/lvgl" -std=c99 -Wno-stringop-overflow -Wno-format-truncation -w -flax-vector-conversions --param=min-pagesize=0 -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" -c -o "$@" -x c "$<")
	@echo Building file: $< && arm-none-eabi-gcc @"$@.in"


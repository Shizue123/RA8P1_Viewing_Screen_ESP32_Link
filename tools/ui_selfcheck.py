#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_selfcheck.py — v0.9.14 A.4
校验编译产物 ELF 是否含正确字体符号 + 关键 UI 字串 + 不含历史危险引用。

设计: 直接读取 ELF raw 字节搜索 UTF-8 字串，避免依赖外部 grep。

用法:
    python tools/ui_selfcheck.py                    # 默认检查
    python tools/ui_selfcheck.py --date 2026-06-18  # 检查 ELF 含指定 build 日期
    python tools/ui_selfcheck.py --strict           # 任一 FAIL 即非零退出

依赖:
    - Debug/RA8P1_Viewing_Screen_ESP32_Link.elf

退出码:
    0  PASS（或非严格模式下 FAIL 也通过）
    1  FAIL（严格模式）
    2  工具/文件缺失
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 强制 stdout/stderr utf-8（Windows 默认 GBK 会乱码）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 路径（相对工程根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ELF = PROJECT_ROOT / "Debug" / "RA8P1_Viewing_Screen_ESP32_Link.elf"

# ARM strings 候选路径（用于 ASCII/Latin 字串检查）
ARM_BIN_CANDIDATES = [
    os.environ.get("ARM_TOOLCHAIN_BIN"),
    r"C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\13.2 Rel1\bin",
    r"/usr/bin",
    r"/usr/local/bin",
]

def find_tool(name_candidates: list[str]) -> str | None:
    """找第一个可用的工具路径。"""
    for cand in ARM_BIN_CANDIDATES:
        if not cand:
            continue
        for n in name_candidates:
            p = Path(cand) / n
            if p.exists():
                return str(p)
    for n in name_candidates:
        try:
            r = subprocess.run([n, "--version"], capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            return n
    return None


def grep_elf(pattern: str) -> bool:
    """直接在 ELF raw bytes 中搜索 UTF-8 固定字串。"""
    return pattern.encode("utf-8") in ELF.read_bytes()


def check(pattern: str, label: str) -> bool:
    if grep_elf(pattern):
        print(f"  PASS  {label:42s}  含 '{pattern}'")
        return True
    print(f"  FAIL  {label:42s}  缺 '{pattern}'")
    return False


def main():
    if not ELF.exists():
        print(f"FAIL: ELF 不存在: {ELF}", file=sys.stderr)
        print("  请先 bash build_headless_v5.sh 编译", file=sys.stderr)
        sys.exit(2)

    args = sys.argv[1:]
    strict = "--strict" in args
    args = [a for a in args if not a.startswith("--strict")]

    date = None
    if "--date" in args:
        i = args.index("--date")
        date = args[i + 1]
        args = args[:i] + args[i + 2:]

    strings_tool = find_tool(["arm-none-eabi-strings.exe", "arm-none-eabi-strings"])

    print(f"=== UI 自检: {ELF.name} ===")
    print(f"  ELF 大小: {ELF.stat().st_size:,} bytes")
    if strings_tool:
        print(f"  strings: {strings_tool}")
    if date:
        print(f"  目标 build 日期: {date}")
    print()

    # 1. 当前轻量 UI 只要求 14px 中文子集字体进入最终 ELF。
    print("[1] 字体符号（当前轻量 UI 必须有 ui_font_sc_14）")
    font_ok = check("ui_font_sc_14", "字体符号 ui_font_sc_14")
    if grep_elf("ui_font_sc_16"):
        print("  INFO  ui_font_sc_16 也进入最终 ELF")
    else:
        print("  INFO  ui_font_sc_16 未被引用，链接器已正常裁剪")

    # 2. 危险引用检查
    print()
    print("[2] 危险引用（lvgl 库自带 source_han_sans 源码允许链，")
    print("            但 ui_font_sc_14 必须存在且作为 active font）")
    if strings_tool:
        r = subprocess.run(
            [strings_tool, str(ELF)],
            capture_output=True, text=True, encoding="utf-8", errors="ignore"
        )
        rodata = r.stdout
    else:
        rodata = ""
    has_shs = "source_han_sans" in rodata.lower() or "lv_font_source_han" in rodata
    if has_shs:
        print("  WARN  lvgl 库自带 source_han_sans 源码被链（库源码保留，无害）")
        if not font_ok:
            print("  FAIL  ui_font_sc_14 缺失 → 会 fallback 到 source_han_sans → 中文孤岛 bug")
            danger_ok = False
        else:
            print("  PASS  ui_font_sc_14 存在 → 实际渲染走 NotoSansSC")
            danger_ok = True
    else:
        print("  PASS  未发现 source_han_sans 引用")
        danger_ok = True

    # 3. 关键 UI 字串（中文模块名 + 状态字）
    print()
    print("[3] 关键 UI 字串（中文模块名 + 状态）")
    cjk_ok = all([
        check("ILI9488", "硬件名 ILI9488"),
        check("I2C-1", "端口名 I2C-1"),
        check("AHT20", "传感器 AHT20"),
        check("在线", "状态字 在线"),
        check("离线", "状态字 离线"),
        check("未启用", "状态字 未启用"),
        check("通道就绪", "状态字 通道就绪"),
    ])

    # 4. build 日期检查（可选）
    print()
    if date:
        print(f"[4] build 日期（应含 'build {date}'）")
        date_ok = check(f"build {date}", f"banner build {date}")
    else:
        print("[4] build 日期（未指定）")
        # 从 ELF 提取实际 build 日期
        matches = re.findall(rb"build \d{4}-\d{2}-\d{2}", ELF.read_bytes())
        if matches:
            dates = "\n".join(x.decode("ascii") for x in matches)
            print(f"  INFO  ELF banner build 日期: {dates}")
        else:
            print(f"  INFO  ELF banner 未发现 build 日期")
        date_ok = True

    # 5. 当前运行链关键符号。旧调试探针已从交付版裁剪，不再作为失败条件。
    print()
    print("[5] 当前运行链关键符号")
    probe_ok = all([
        check("platform_ports_init", "统一端口状态初始化"),
        check("device_registry_refresh_from_ports", "动态设备注册刷新"),
        check("lv_port_indev_init", "LVGL 触摸输入初始化"),
    ])

    # 汇总
    print()
    all_ok = font_ok and danger_ok and cjk_ok and date_ok and probe_ok
    if all_ok:
        print("=== 总结: PASS ===")
        sys.exit(0)
    else:
        print("=== 总结: FAIL ===")
        print(f"  font={font_ok}  danger={danger_ok}  cjk={cjk_ok}  date={date_ok}  probe={probe_ok}")
        if strict:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()

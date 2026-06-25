from __future__ import annotations

import re


LUA_API_WHITELIST = {
    "aht20_read",
    "ultrasonic_read",
    "gpio_read",
    "servo_set",
    "led_set",
    "led_rgb",
    "buzzer",
    "gpio_write",
    "screen_text",
    "screen_clear",
    "delay",
    "millis",
    "print",
}

LUA_FORBIDDEN_TOKENS = {
    "dofile",
    "load",
    "loadfile",
    "require",
    "io.",
    "os.",
    "debug.",
    "package.",
}

LUA_LANGUAGE_CALLS = {"if", "while", "for"}


def validate_lua_api(lua_code: str) -> dict[str, object]:
    errors: list[str] = []
    for token in sorted(LUA_FORBIDDEN_TOKENS):
        if token in lua_code:
            errors.append(f"dangerous Lua token is forbidden: {token}")

    calls = sorted(set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", lua_code)))
    for call in calls:
        if call not in LUA_API_WHITELIST and call not in LUA_LANGUAGE_CALLS:
            errors.append(f"Lua API is not whitelisted: {call}")

    return {"ok": not errors, "calls": calls, "errors": errors}

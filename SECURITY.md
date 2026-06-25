# Security Policy

## Reporting a Vulnerability

We take the security of this project seriously. If you discover a security
vulnerability, please report it responsibly.

- **Do NOT open a public GitHub issue** for security vulnerabilities.
- Email the maintainer privately, or use
  [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  for this repository.
- Include a clear description of the issue, steps to reproduce, and the
  potential impact.

You should receive an initial response within 72 hours. Please do not
disclose the vulnerability publicly until it has been addressed.

## Credentials & Secrets

**This repository contains NO real credentials.** All WiFi SSIDs/passwords,
MQTT broker credentials, cloud API tokens and server addresses have been
replaced with clearly-marked placeholders before publishing.

Before building and flashing the firmware you must fill in your own
credentials. See [`docs/cloud_integration_setup.md`](docs/cloud_integration_setup.md)
for the full configuration checklist. The relevant placeholder locations are:

| Placeholder              | File                                                      | Description                          |
|--------------------------|-----------------------------------------------------------|--------------------------------------|
| `YOUR_WIFI_SSID`         | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | Built-in WiFi SSID                   |
| `YOUR_WIFI_PASSWORD`     | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | Built-in WiFi password               |
| `your-mqtt-broker-host`  | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | MQTT broker host                     |
| `your-mqtt-username`     | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | MQTT username                        |
| `your-mqtt-password`     | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | MQTT password                        |
| `your-cloud-host`        | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | Cloud HTTP host                      |
| `your-cloud-api-token`   | `esp32-s3-uart-link-arduino/.../esp32_s3_uart_link.ino`   | Cloud API token                      |
| `your-cloud-host`        | `tools/validate_*.py`                                     | Default `--host` argument            |

## Supported Versions

Only the latest release on the `main` branch receives security updates.

## Hardening Recommendations

- Use TLS (MQTT over SSL, port 8883) instead of plaintext MQTT in production.
- Rotate API tokens and MQTT credentials periodically.
- Place the cloud backend behind a reverse proxy with authentication and
  rate limiting.
- Do not flash placeholder builds to devices connected to production networks.

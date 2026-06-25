# Contributing to RA8P1 Viewing Screen ESP32 Link

First off, thanks for taking the time to contribute! 🎉

The following is a set of guidelines for contributing to this project. These
are mostly guidelines, not rules. Use your best judgment, and feel free to
propose changes to this document in a pull request.

## Code of Conduct

By participating in this project you agree to abide by its
[Code of Conduct](CODE_OF_CONDUCT.md). Please be respectful and constructive.

## How Can I Contribute?

- **Reporting Bugs** — open an issue using the *Bug report* template.
- **Suggesting Enhancements** — open an issue using the *Feature request* template.
- **Pull Requests** — follow the PR template and the workflow below.

## Development Workflow

1. **Fork** the repository and create your branch from `main`:
   ```
   git checkout -b feature/your-short-description
   ```
2. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: add SG90 calibration page`
   - `fix: correct I2C channel switch timing`
   - `docs: update wiring summary`
   - `refactor: extract device registry`
3. **Keep commits focused** — one logical change per commit.
4. **Test on real hardware** when the change touches drivers or board behavior.
   This is an embedded project; CI cannot fully validate hardware interactions.
5. **Do not commit secrets.** See [SECURITY.md](SECURITY.md). Never hardcode
   WiFi/MQTT/cloud credentials. Use placeholders and document them.
6. **Open a Pull Request** against `main`, fill in the template, and link
   related issues.

## Code Style

- **C / C++ (RA8P1 & ESP32):**
  - 4-space indentation, no tabs.
  - `snake_case` for functions and variables, `PascalCase` for types,
    `UPPER_SNAKE` or `kCamelCase` for constants (match existing files).
  - Keep functions under ~120 lines where practical.
  - Document public functions with a brief `//` header comment.
- **Python (tools/):** follow [PEP 8](https://peps.python.org/pep-0008/),
  `snake_case` functions.
- **Markdown:** wrap long lines at ~100 chars where reasonable.

## Commit Message Guidelines

```
<type>(<optional scope>): <subject>

<body explaining what and why>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`,
`build`, `ci`.

## Hardware Testing

When your change affects the board, verify on the reference hardware:

- RA8P1 + ILI9488 320x480 LCD + FT6336 touch
- PCA9548A + AHT20 + BH1750 sensor chain
- SG90 servo on PWM-0
- ESP32-S3 UART bridge

Record the test steps and results in your PR description.

## Reporting Security Issues

See [SECURITY.md](SECURITY.md). Do **not** open public issues for security
vulnerabilities.

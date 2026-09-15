# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using `scripts/lint`).
4. Test you contribution.
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [ruff](https://github.com/astral-sh/ruff) to make sure the code follows the style (`scripts/lint` runs `ruff format` and `ruff check --fix` for you).

## Home Assistant versions

Two versions are declared, and they differ on purpose:

- `hacs.json`'s `homeassistant` key is the **lowest** release the code runs on, and
  the one HACS enforces. It is currently `2026.8.0`, the release that introduced
  `via_device_id` and `DeviceRegistry.async_get_device_by_identifier`.
- `requirements.txt` pins the version the tests run **against**, kept at the current
  stable so CI sees new deprecations early.

Raise the floor in `hacs.json` only when the code actually needs a newer API, and
check that the release notes say the same thing. Note that HACS reads `hacs.json`
from the tag being installed, so a change here only reaches users with the next
release.

## Test your code modification

It comes with development environment in a container, easy to launch
if you use Visual Studio Code. With this container you will have a stand alone
Home Assistant instance running and already configured with the included
[`configuration.yaml`](./config/configuration.yaml)
file.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
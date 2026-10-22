# Contributing

Thanks for helping. Bug reports, feature ideas, docs fixes and pull requests are all welcome.
By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting started

```bash
git clone https://github.com/johshea/k8s-manifest-desktop.git && cd k8s-manifest-desktop
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run_tests.sh
```

See [docs/installation.md](docs/installation.md) for platform prerequisites (Tk on macOS / Ubuntu) and
[docs/testing.md](docs/testing.md) for every test option.

## Where things live

- **Generator core**: `manifest_gen.py`, `cluster_config_gen.py`, `clusterplatforms/`,
  `addons_gen.py`, `addons/`, `app_templates.py`, `field_docs.py`, `providers.py` and the core tests.
  This repository is standalone: change the core here and cover it with tests.
- **Front-end**: the Tkinter GUI (`gui_app.py`). It must stay generic over `providers.PROVIDERS`. New kinds, platforms and
  add-ons are added in the core, not here.
- **Help text**: every new field needs an entry in `field_docs.py` (or `addons/docs.py`).
  `tests/test_field_docs.py` rejects fields without real help.

## Pull requests

1. Create a branch from `main`.
2. Add or extend tests: a positive case, negative cases, and the help text for new fields.
3. Run `./run_tests.sh`. All offline suites must pass. Real-tool and kind checks are optional;
   mention in the PR which ones you ran.
4. Update the docs in `docs/`, and `CHANGELOG.md` under **Unreleased**. If you commit regenerated screenshots,
   compress them losslessly first (`oxipng -o 4 --strip safe docs/images/*.png`).
5. Keep pinned versions real. Verify that every image tag, chart version or CLI flag you add exists.

## Style

- Python 3.10+, standard library + PyYAML only for the app.
- Generated YAML must be valid for the targeted API version. Don't use `latest` image tags.
- Never log or echo user values; they can contain secrets.
- Never use real cloud credentials in tests. Cloud outputs are validated offline (schemas, `--help`, dry-run).

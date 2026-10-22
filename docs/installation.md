# Installation

## Prerequisites

- Python **3.10+** (tested 3.10-3.13) with **tkinter / Tk 8.6**
- PyYAML (installed automatically on first run, or via `requirements.txt`)
- Optional: `kubectl` to apply / dry-run the output; `kubeadm`, `kind`, `k3s`, `rke2`
  (and docker) only for the real-tool tests

### macOS

```bash
# Option A - Homebrew Python (most common)
brew install python python-tk          # python-tk provides tkinter for brew's python3
# Option B - python.org installer (https://www.python.org/downloads/macos/) - Tk is bundled

python3 -c "import tkinter; print(tkinter.TkVersion)"   # should print 8.6 (or 9.0)
```

Avoid Apple's `/usr/bin/python3` (Command Line Tools) if it reports Tk **8.5**;
it is deprecated and can render blank windows. pyenv users: `brew install tcl-tk`
then reinstall the Python version.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-tk python3-pip python3-venv
# optional: use the distro PyYAML instead of pip
sudo apt install -y python3-yaml
```

## Running

```bash
cd k8s-manifest-desktop
python3 k8s_manifest_gui.py          # first run installs PyYAML if needed
python3 k8s_manifest_gui.py --check  # just verify dependencies
python3 k8s_manifest_gui.py --no-install   # never pip-install anything
```

### Automatic PyYAML install - what it does

1. In a virtualenv: `python -m pip install pyyaml`
2. Otherwise: `python -m pip install --user pyyaml`
3. If the interpreter is *externally managed* (PEP 668 - Homebrew Python, Ubuntu
   23.04+/24.04): retries `pip install --user --break-system-packages pyyaml`.
   This only writes to your user site (`~/.local/...` or
   `~/Library/Python/3.x/...`), never the system site-packages.
   Set `K8S_GUI_NO_BREAK_SYSTEM=1` to skip this step, or `K8S_GUI_NO_AUTO_INSTALL=1`
   to disable auto-install entirely.
4. If pip is missing: tries `python -m ensurepip --user`, then prints apt/brew/venv
   instructions.

### Virtualenv option (cleanest)

```bash
cd k8s-manifest-desktop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python k8s_manifest_gui.py
```

A venv still uses the interpreter's tkinter, so `python3-tk` (Ubuntu) or
`python-tk` (Homebrew) must be installed system-wide first.

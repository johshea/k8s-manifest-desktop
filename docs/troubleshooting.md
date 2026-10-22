# Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named '_tkinter'` / `tkinter` | Ubuntu: `sudo apt install python3-tk`. macOS: `brew install python-tk` (match your brew Python version, e.g. `python-tk@3.13`) or use python.org Python. |
| `error: externally-managed-environment` | Handled automatically; or use the venv option, or `sudo apt install python3-yaml`. |
| `No module named pip` (Ubuntu) | `sudo apt install python3-pip` (or `python3-venv` for venvs). |
| `_tkinter.TclError: no display name and no $DISPLAY` | You are on SSH/headless: use `ssh -X`, a desktop session, or `xvfb-run` for tests. |
| Blank/black window on macOS | You're on Apple's Tk 8.5 - switch to python.org or Homebrew Python. |
| Tiny / huge fonts on Linux HiDPI | `tk scaling` follows X DPI; try `GDK_SCALE`, or edit font sizes in `gui_app.py` `_style()`. |
| Copy to clipboard empties after closing the app (Linux) | X11 clipboard is owned by the app; paste before closing, or use a clipboard manager. |
| Native sidecar never starts / `restartPolicy` rejected on an initContainer | Cluster is older than 1.29 (or 1.28 without the SidecarContainers gate): use role `sidecar (regular container)` instead. |
| `kubectl apply` says `strict decoding error`/unknown field | Upgrade kubectl/cluster; fields like CronJob `timeZone` need k8s ≥1.27. |
| `kubeadm config validate` says `no kind "InitConfiguration" is registered for version "kubeadm.k8s.io/v1beta4"` | kubeadm older than 1.31 - upgrade kubeadm (v1beta4 is the current API) or migrate with `kubeadm config migrate`. |
| `kind create cluster`: `permission denied ... docker.sock` | Add yourself to the `docker` group (`sudo usermod -aG docker $USER`, re-login) or run with `sudo` (`KIND_SUDO=1` for the tests). |
| k3s exits with `failed to create vxlan device: operation not supported` | Kernel lacks vxlan (common in containers/VMs): choose `flannel-backend: host-gw` or `wireguard-native`. |
| The ⓘ icons show as a box / missing glyph | Run with `K8SGUI_INFO_ICON="(i)"` (or any other text). |
| kubectl ignores `certificate-authority: ~/...` | kubectl doesn't expand `~` in kubeconfig paths - use an absolute path or paste the PEM. |

Keyboard: **Ctrl/Cmd+K** open the resource/config-type selector, **Ctrl/Cmd+S** save,
**Ctrl/Cmd+R** or **F5** refresh.

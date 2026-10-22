# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-21

First public release as a standalone repository.

### Added

- GitHub-style repository layout: `docs/` split by topic, `docs/images/` screenshots, LICENSE (MIT),
  CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CI workflow (Ubuntu + macOS, Python 3.10-3.13), issue / PR
  templates, Dependabot, `.editorconfig`, `pyproject.toml`.
- Development history before 1.0.0 is summarised below as pre-release milestones.

### Fixed

- Test suite runs on Python 3.10 and 3.11 (removed a 3.12-only nested f-string from `tests/test_app_templates.py`).

## [0.9.0] - 2026-10-21 - Networking & Storage

### Added

- **Networking & Storage** mode: CNI add-ons (Calico operator CRs, Cilium Helm values / CLI, Flannel,
  Canal, Antrea, Multus + NetworkAttachmentDefinitions) and CSI StorageClasses for 15 drivers, with
  VolumeSnapshotClass, driver Secret and `install.sh` with pinned, verified versions.
- Manifest kinds **NetworkPolicy** (rule tables + presets), **StorageClass**, **VolumeSnapshotClass**.
- Cross-checks between CNI pod CIDRs and cluster pod subnets; session StorageClass names in PVC /
  StatefulSet dropdowns.
- Add-on tests (generator, `helm template`, server dry-run) and live kind validation.

### Fixed

- Demo NFS server exports a read-write share.

## [0.8.0] - 2026-10 - Desktop / web split

### Changed

- The combined project was split into `k8s-manifest-desktop` (desktop GUI) and `k8s-manifest-web` (browser UI),
  each with its own copy of the generator core.

## [0.7.0] - 2026-10 - Web front-end (combined project)

### Added

- A browser front-end on the same generator core was added to the combined project. It now lives in the
  separate `k8s-manifest-web` repository.

## [0.6.0] - 2026-10 - Hover help

### Added

- ⓘ tooltips for every field, table column, section, template parameter and selector (`field_docs.py`),
  with help-coverage tests.

## [0.5.0] - 2026-10 - Application templates

### Added

- 25 application templates (databases, messaging, web, monitoring, ...) that fill several kinds at once,
  with conflict detection and deploy tests on kind.

## [0.4.0] - 2026-10 - More cluster platforms

### Added

- minikube, k0s, MicroK8s, Talos, Kubespray, Cluster API, OpenShift, EKS, GKE and AKS, grouped in the type
  selector, each validated against the real tool or schema where possible.

## [0.3.0] - 2026-10 - Cluster config mode

### Added

- Mode selector with **Cluster config**: kubeadm (init / join), kind, kubeconfig, k3s / RKE2.

## [0.2.0] - 2026-10 - Multi-container and scheduling

### Added

- Init, sidecar (regular and native) and extra containers in a table editor; tolerations, node / pod
  (anti-)affinity and topology spread tables; collapsible sections.

## [0.1.0] - 2026-10 - Initial release

### Added

- Form-based generator for Deployment, StatefulSet, DaemonSet, Job, CronJob, Service, Ingress, ConfigMap,
  Secret, PersistentVolumeClaim and Namespace with live preview, validation, save / save all / bundles.
  The first version used one tab per kind; it was replaced by a single **Resource type** selector with
  per-kind value caching.

[Unreleased]: https://github.com/johshea/k8s-manifest-desktop/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/johshea/k8s-manifest-desktop/releases/tag/v1.0.0

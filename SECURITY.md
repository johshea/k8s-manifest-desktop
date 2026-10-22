# Security Policy

## Supported versions

Security fixes go into the latest release on `main`.

| Version | Supported |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/johshea/k8s-manifest-desktop/security/advisories/new) (Security tab →
"Report a vulnerability").

Please include the affected version or commit, the steps to reproduce, and the impact. You should get an
acknowledgement within a few days. Once a fix is released the report is credited, unless you'd
rather stay anonymous.

## Scope

In scope:

- the generator and GUI: anything that writes Secrets / kubeconfigs with loose file modes,
  leaks typed values, or generates insecure-by-default output
- the dependency auto-installer (`bootstrap.py`)

Out of scope: the security of clusters you create with the generated files. Review generated configs
before you apply them, especially the demo-only components such as the in-cluster NFS test server.

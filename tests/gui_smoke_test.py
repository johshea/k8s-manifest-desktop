#!/usr/bin/env python3
"""
Headless GUI smoke test.

  xvfb-run -a -s "-screen 0 1400x900x24" python3 tests/gui_smoke_test.py [--screenshot PATH]

Builds the window, drives the resource-type selector through every kind (form rebuilt
each time), checks values persist across switches, parses each preview, exercises
live refresh, validation errors, F5, Save / Save all edited / bundle / Reset (dialogs stubbed), then
switches to 'Cluster config' mode and drives kubeadm / kind / kubeconfig / k3s-RKE2 the same way
(per-type caching, table dialogs, default filenames, chmod 600, no bundle), then 'Networking & Storage'
(every CNI / CSI type, Calico IP-pool dialog, multi-file save, cross-check warnings, session StorageClass
names in the PVC dropdown). Takes optional screenshots
(ImageMagick `import`), then destroys the window.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

import yaml  # noqa: E402

import addons_gen as agen  # noqa: E402
import app_templates as tpl  # noqa: E402
import cluster_config_gen as ccg  # noqa: E402
import gui_app  # noqa: E402
import manifest_gen as gen  # noqa: E402

PEM = "-----BEGIN CERTIFICATE-----\nTUlJQnN6Q0NBVm1nQXdJQkFnSVVRMDEyMzQ1Njc4OQ==\n-----END CERTIFICATE-----"

# Stub modal dialogs so nothing blocks
_dialogs = []
for name in ("showinfo", "showerror", "showwarning"):
    setattr(messagebox, name, lambda title, msg, name=name, **kw: _dialogs.append((name, title, msg)))
messagebox.askyesno = lambda *a, **k: True

fails = 0


def check(cond, msg):
    global fails
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails += 1


def pump(root, n=5):
    for _ in range(n):
        root.update_idletasks()
        root.update()


def capture(win, path) -> bool:
    win.update_idletasks()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    if sys.platform == "darwin":
        cmd = ["screencapture", "-x", f"-R{x},{y},{w},{h}", path]
    elif shutil.which("import"):
        cmd = ["import", "-window", "root", "-crop", f"{w}x{h}+{x}+{y}", "+repage", path]
    else:
        print("  skip screenshot: ImageMagick `import` not found (sudo apt install imagemagick)")
        return True
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("   ", r.stderr.strip())
    return r.returncode == 0 and os.path.exists(path)


def all_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from all_widgets(c)


def main():
    shot = None
    if "--screenshot" in sys.argv:
        shot = sys.argv[sys.argv.index("--screenshot") + 1]
    root = tk.Tk()
    root.geometry("1360x860+0+0")
    app = gui_app.App(root)
    pump(root)
    print(f"Tk {tk.TkVersion}, theme={tk.ttk.Style().theme_use()}")
    check(not any(isinstance(w, tk.ttk.Notebook) for w in all_widgets(root)), "no ttk.Notebook in the window")
    check(str(app.selector.cget("state")) == "readonly", "selector is a readonly Combobox")
    check(list(app.selector.cget("values")) == gen.KINDS, f"selector lists the {len(gen.KINDS)} kinds")
    check(app.kind_var.get() == "Deployment" and app.kind == "Deployment", "default selection is Deployment")
    preview_widget, issues_widget = app.preview, app.issues

    # Drive the selector through every kind (via the real <<ComboboxSelected>> path)
    for kind in gen.KINDS:
        old_form = app.form
        app.kind_var.set(kind)
        app.selector.event_generate("<<ComboboxSelected>>")
        pump(root)
        f = app.form
        rebuilt = (kind == "Deployment" and f is old_form) or (f is not old_form and not old_form.scroll.winfo_exists())
        n_fields = len(f.widgets)
        expect = sum(len(fl) for _, fl in gen.SCHEMA[kind])
        frames = [w for w in app.form_area.winfo_children()]
        text = app.preview.get("1.0", "end-1c")
        doc = yaml.safe_load(text)
        check(rebuilt and f.kind == kind and n_fields == expect and len(frames) == 1
              and doc and doc.get("kind") == kind,
              f"{kind:22s} form rebuilt ({n_fields} fields, 1 form frame) -> preview parses ({len(text.splitlines())} lines)")
    check(app.preview is preview_widget and app.issues is issues_widget, "preview & validation panes stay put")

    # restartPolicy dropdown constrained per kind
    app.select_kind("Job")
    check(list(app.form.widgets["restart_policy"].cget("values")) == ["OnFailure", "Never"],
          "Job restartPolicy dropdown excludes Always")
    app.select_kind("Deployment")
    check(list(app.form.widgets["restart_policy"].cget("values")) == ["Always"],
          "Deployment restartPolicy dropdown is Always only")

    # live refresh on change
    app.form.set("replicas", "5")
    app.form.set("env", "FOO=bar")
    for _ in range(10):
        pump(root, 2)
        root.after(60)
    doc = yaml.safe_load(app.preview.get("1.0", "end-1c"))
    check(doc["spec"]["replicas"] == 5 and doc["spec"]["template"]["spec"]["containers"][0]["env"][0]["name"] == "FOO",
          "live preview reflects edits (replicas=5, env FOO)")

    # value persistence across switches
    app.form.set("name", "web")
    app.form.set("image", "nginx:1.27-alpine")
    app.select_kind("Service")
    app.form.set("service_type", "NodePort")
    app.form._service_type_changed()
    app.form.set("node_port", "30080")
    app.form.set("selector", "app=web")
    app.select_kind("Secret")
    app.form.set("data", "password=hunter2")
    app.select_kind("ConfigMap")       # visit without editing
    app.select_kind("Deployment")
    v = app.form.values()
    check(v["name"] == "web" and v["replicas"] == "5" and v["image"] == "nginx:1.27-alpine" and v["env"] == "FOO=bar",
          "Deployment values restored after switching away and back")
    check(v["labels"] == "app=web", "name->labels auto-sync kept in cache")
    app.select_kind("Service")
    sv = app.form.values()
    check(sv["service_type"] == "NodePort" and sv["node_port"] == "30080"
          and str(app.form.widgets["node_port"].cget("state")) == "normal",
          "Service values (type NodePort, nodePort 30080) restored and nodePort enabled")
    doc = yaml.safe_load(app.preview.get("1.0", "end-1c"))
    check(doc["spec"]["ports"][0]["nodePort"] == 30080, "restored Service renders nodePort")
    app.select_kind("Secret")
    sec = yaml.safe_load(app.preview.get("1.0", "end-1c"))
    check(sec["data"]["password"] == "aHVudGVyMg==", "Secret restored; plaintext base64-encoded")
    check(app.edited_kinds() == ["Deployment", "Service", "Secret"], f"edited kinds = {app.edited_kinds()}")
    check("Deployment, Service, Secret" in app.edited_label.cget("text"), "edited indicator in header")

    # validation error surfaced
    app.select_kind("Deployment")
    app.form.set("name", "Bad_Name")
    app.refresh()
    check("DNS-1123" in app.issues.get("1.0", "end-1c"), "invalid name shows friendly error in Validation pane")
    _dialogs.clear()
    app.validate()
    check(_dialogs and _dialogs[-1][0] == "showerror", "Validate button reports errors via dialog")
    app.form.set("name", "web")
    app.refresh()

    # F5 refresh binding
    app.preview.configure(state="normal"); app.preview.delete("1.0", "end"); app.preview.configure(state="disabled")
    root.event_generate("<F5>"); pump(root)
    check(app.preview.get("1.0", "end-1c").startswith("apiVersion: apps/v1"), "F5 refreshes the preview")

    # Save / save-all-edited / bundle / clipboard
    tmp = tempfile.mkdtemp(prefix="k8sgui-")
    path = app.save(directory=tmp)
    check(path and os.path.basename(path) == "deployment-web.yaml" and os.path.exists(path),
          f"Save -> {path and os.path.basename(path)}")
    os.remove(path)
    saved = app.save_all_edited(directory=tmp)
    files = sorted(os.listdir(tmp))
    check(saved == ["deployment-web.yaml", "service-my-app.yaml", "secret-app-secret.yaml"]
          and "all-in-one.yaml" in files and len(files) == 4, f"Save all edited -> {files}")
    check([d["kind"] for d in yaml.safe_load_all(open(os.path.join(tmp, "all-in-one.yaml")))]
          == ["Deployment", "Service", "Secret"], "all-in-one.yaml is a valid 3-doc file")
    app.add_to_bundle()
    app.select_kind("Service")
    app.add_to_bundle()
    check(len(app.bundle) == 2, "bundle holds 2 docs")
    try:
        app.copy()
        check(root.clipboard_get().startswith("apiVersion: v1\nkind: Service"), "Copy YAML puts manifest on clipboard")
    except tk.TclError as exc:
        print(f"  skip clipboard check ({exc})")

    # Reset clears only the current kind
    app.reset_kind()
    check(app.form.values()["service_type"] == "ClusterIP" and "Service" not in app.edited_kinds(),
          "Reset kind restores Service defaults")
    check("Deployment" in app.edited_kinds() and app.values_for("Deployment")["name"] == "web",
          "Reset leaves other kinds' cached values intact")
    shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------------- multi-container + scheduling
    print("-- containers & scheduling --")
    NATIVE, SIDECAR = gen.ROLE_NATIVE, gen.ROLE_SIDECAR
    for kind in gen.WORKLOAD_KINDS:
        app.select_kind(kind)
        keys = set(app.form.tables)
        check(keys == {"extra_containers", "tolerations", "node_affinity", "pod_affinity", "pod_anti_affinity",
                       "topology_spread"}, f"{kind:12s} has containers + scheduling tables")
        check(all(app.form.sections[t].collapsed for t in gui_app.COLLAPSED_BY_DEFAULT if t in app.form.sections),
              f"{kind:12s} advanced sections start collapsed")
    for kind in ("Service", "ConfigMap"):
        app.select_kind(kind)
        check(not app.form.tables, f"{kind} has no container/scheduling tables")

    app.select_kind("Deployment")
    f = app.form
    f.sections["Init & sidecar containers"].toggle()
    check(not f.sections["Init & sidecar containers"].collapsed, "expand 'Init & sidecar containers' section")
    f.set("volumes", "shared:emptyDir::/shared\nlogs:emptyDir::")
    te = f.tables["extra_containers"]
    dlg = te.add(wait=False)
    pump(root)
    dlg.set("role", NATIVE); dlg.set("name", "Mesh_Proxy"); dlg.set("image", "envoyproxy/envoy:v1.31.0")
    dlg.set("ports", "proxy:15001"); dlg.set("volume_mounts", "shared:/etc/envoy:ro")
    check(dlg.ok() is False and "DNS-1123" in dlg.err_var.get() and dlg.winfo_exists(),
          "row dialog rejects bad container name and stays open")
    dlg.set("name", "mesh-proxy")
    check(dlg.ok() is True and len(te.rows) == 1, "row dialog OK adds native sidecar")
    for role, name, image, mounts in ((SIDECAR, "log-shipper", "fluent/fluent-bit:3.1", "logs:/var/log/app:ro"),
                                      ("init", "init-db", "busybox:1.36", "")):
        d = te.add(wait=False); d.set("role", role); d.set("name", name); d.set("image", image)
        d.set("volume_mounts", mounts)
        if role == "init":
            d.set("command", "sh -c 'until nslookup db; do sleep 2; done'")
        d.ok()
    check([r["name"] for r in te.rows] == ["mesh-proxy", "log-shipper", "init-db"]
          and len(te.tree.get_children()) == 3, "3 containers listed in the Treeview")
    te.tree.selection_set("2"); te.move(-1)
    check([r["name"] for r in te.rows] == ["mesh-proxy", "init-db", "log-shipper"], "▲ reorders rows")
    te.tree.selection_set("2")
    d = te.edit(wait=False)
    check(d.values()["name"] == "log-shipper", "Edit… opens dialog pre-filled with the selected row")
    d.set("image", "fluent/fluent-bit:3.1.9"); d.ok()
    te.tree.selection_set("0"); te.duplicate()
    check(te.rows[1]["name"] == "mesh-proxy-copy", "Duplicate copies a row with -copy suffix")
    te.tree.selection_set("1"); te.remove()
    check(len(te.rows) == 3, "Remove deletes the selected row")
    app.refresh()
    ps = yaml.safe_load(app.preview.get("1.0", "end-1c"))["spec"]["template"]["spec"]
    check([c["name"] for c in ps["initContainers"]] == ["mesh-proxy", "init-db"]
          and ps["initContainers"][0]["restartPolicy"] == "Always"
          and [c["name"] for c in ps["containers"]] == ["web", "log-shipper"]
          and ps["containers"][1]["image"] == "fluent/fluent-bit:3.1.9", "preview: initContainers + containers correct")

    # scheduling tables through dialogs
    for title in ("Tolerations", "Node affinity", "Pod affinity / anti-affinity", "Topology spread"):
        f.sections[title].toggle()
    rows = {
        "tolerations": [{"key": "dedicated", "operator": "Equal", "value": "web", "effect": "NoSchedule"},
                        {"key": "node.kubernetes.io/unreachable", "operator": "Exists", "effect": "NoExecute",
                         "toleration_seconds": "60"}],
        "node_affinity": [{"type": "required", "key": "kubernetes.io/os", "operator": "In", "values": "linux"},
                          {"type": "preferred", "key": "topology.kubernetes.io/zone", "operator": "In",
                           "values": "us-west-2a", "weight": "40"}],
        "pod_affinity": [{"type": "preferred", "key": "app", "operator": "In", "values": "cache",
                          "topology_key": "topology.kubernetes.io/zone", "weight": "50"}],
        "pod_anti_affinity": [{"type": "required", "key": "app", "operator": "In", "values": "web",
                               "topology_key": "kubernetes.io/hostname"}],
        "topology_spread": [{"max_skew": "1", "topology_key": "topology.kubernetes.io/zone",
                             "when_unsatisfiable": "ScheduleAnyway"}],
    }
    for key, rlist in rows.items():
        for r in rlist:
            d = f.tables[key].add(wait=False)
            for k, v in r.items():
                d.set(k, v)
            check(d.ok(), f"dialog adds {key} row {r.get('key') or r.get('topology_key')}")
    d = f.tables["tolerations"].add(wait=False)
    d.set("key", "x"); d.set("operator", "Exists"); d.set("value", "y")
    check(not d.ok() and "value must be empty" in d.err_var.get(), "toleration dialog shows friendly error")
    d.destroy()
    check(list(f.widgets["tolerations"].tree.heading("effect").values()) and
          f.tables["node_affinity"].field.columns[2].options == gen.NODE_OPERATORS, "operator dropdowns prefilled")
    topo_opts = [c for c in f.tables["pod_anti_affinity"].field.columns if c.key == "topology_key"][0].options
    check(topo_opts[:3] == ["kubernetes.io/hostname", "topology.kubernetes.io/zone", "topology.kubernetes.io/region"],
          "topologyKey combobox prefilled")
    app.refresh()
    ps = yaml.safe_load(app.preview.get("1.0", "end-1c"))["spec"]["template"]["spec"]
    check(len(ps["tolerations"]) == 2 and ps["tolerations"][1]["tolerationSeconds"] == 60
          and "nodeAffinity" in ps["affinity"] and "podAffinity" in ps["affinity"]
          and "podAntiAffinity" in ps["affinity"] and ps["topologySpreadConstraints"][0]["maxSkew"] == 1,
          "preview: tolerations, node/pod (anti-)affinity, topologySpreadConstraints")

    # mount referencing undefined volume -> Validation pane
    d = te.add(wait=False); d.set("name", "bad-mount"); d.set("volume_mounts", "nope:/nope"); d.ok()
    app.refresh()
    check("not defined in Volumes" in app.issues.get("1.0", "end-1c"), "undefined volumeMount reported in Validation pane")
    te.tree.selection_set(str(len(te.rows) - 1)); te.remove(); app.refresh()

    # persistence of table data + collapse state across switches
    before = app.form.values()
    app.select_kind("Service"); app.select_kind("StatefulSet"); app.select_kind("Deployment")
    after = app.form.values()
    check(after["extra_containers"] == before["extra_containers"] and after["tolerations"] == before["tolerations"]
          and after["node_affinity"] == before["node_affinity"] and after["topology_spread"] == before["topology_spread"],
          "table rows restored after switching kinds")
    check(len(app.form.tables["extra_containers"].tree.get_children()) == 3, "restored Treeview shows 3 containers")
    check(not app.form.sections["Init & sidecar containers"].collapsed and app.form.sections["Probes"].collapsed,
          "section expand/collapse state remembered per kind")
    check("Deployment" in app.edited_kinds(), "table edits count as edited")
    tmp = tempfile.mkdtemp(prefix="k8sgui-")
    path = app.save(directory=tmp)
    saved = yaml.safe_load(open(path))
    check(len(saved["spec"]["template"]["spec"]["initContainers"]) == 2, "saved file contains initContainers")
    shutil.rmtree(tmp, ignore_errors=True)
    # Job gets its own (separate) tables
    app.select_kind("Job")
    check(app.form.values()["extra_containers"] == [], "other kinds keep their own empty tables")

    # ------------------------------------------------------------ Cluster config mode
    print("-- cluster config mode")
    check(list(app.mode_selector.cget("values")) == ["Manifests", "Cluster config", "Networking & Storage"] and
          str(app.mode_selector.cget("state")) == "readonly", "mode selector: Manifests / Cluster config / N&S")
    manifest_kind_before = app.kind
    app.mode_var.set("Cluster config")
    app.mode_selector.event_generate("<<ComboboxSelected>>")
    pump(root)
    check(app.mode == "Cluster config" and app.kind == ccg.CONFIG_TYPES[0] == "kind",
          "switching mode opens the first type (kind)")
    want_vals = ["── Local ──", "kind", "minikube", "k3s / RKE2", "k0s", "MicroK8s",
                 "── Self-managed ──", "kubeadm", "Talos", "Kubespray", "Cluster API", "OpenShift",
                 "── Managed cloud ──", "EKS", "GKE", "AKS", "── Access ──", "kubeconfig"]
    check(list(app.selector.cget("values")) == want_vals, f"grouped type dropdown: {app.selector.cget('values')}")
    app.kind_var.set("── Managed cloud ──")
    app.selector.event_generate("<<ComboboxSelected>>")
    pump(root)
    check(app.kind == "EKS" and app.kind_var.get() == "EKS", "picking a group header jumps to its first type")
    app.select_kind("kubeadm")
    check(app.type_label.cget("text") == "Config type:", "type label changes with the mode")
    check(app.buttons["Copy YAML"].cget("text") == "Copy", "Copy button relabelled (scripts / JSON too)")
    check(all(app.buttons[b].instate(["disabled"]) for b in ("Add to bundle", "Save bundle…", "Clear bundle")),
          "bundle buttons disabled in Cluster config mode")
    check(app.preview is preview_widget and app.issues is issues_widget, "same preview & validation panes")
    for ctype in ccg.CONFIG_TYPES:
        app.select_kind(ctype)
        pump(root)
        expect = sum(len(fs) for _, fs in ccg.SCHEMA[ctype])
        check(app.form.kind == ctype and len(app.form.getters) == expect,
              f"{ctype}: form rebuilt with {expect} fields")
    app.select_kind("kubeadm")
    check(app.form.sections["JoinConfiguration"].collapsed and not app.form.sections["InitConfiguration"].collapsed,
          "kubeadm: JoinConfiguration collapsed by default")
    app.form.set("advertise_address", "10.0.0.11")
    app.form.set("bootstrap_token", "abcdef.0123456789abcdef")
    app.form.set("control_plane_endpoint", "k8s-api.lab:6443")
    app.form.set("include_kube_proxy", True)
    app.form.set("proxy_mode", "nftables")
    text = app.refresh()
    docs = [d for d in yaml.safe_load_all(text) if d]
    check([d["kind"] for d in docs] == ["InitConfiguration", "ClusterConfiguration", "KubeletConfiguration",
                                        "KubeProxyConfiguration"], "kubeadm preview: 4 documents")
    check(text.startswith("# kubeadm init --config kubeadm-config.yaml") or text.startswith("#"),
          "kubeadm preview has usage header")
    check(docs[0]["localAPIEndpoint"]["advertiseAddress"] == "10.0.0.11", "kubeadm preview reflects form")
    check("kubeadm.k8s.io/v1beta4" in app.api_label.cget("text"), "header shows kubeadm API version")
    check("kubeadm-config.yaml" in app.preview_title.cget("text"), "preview title shows target filename")
    tmpc = tempfile.mkdtemp(prefix="k8sgui-cluster-")
    p = app.save(directory=tmpc)
    check(p and os.path.basename(p) == "kubeadm-config.yaml" and (os.stat(p).st_mode & 0o777) == 0o600,
          "Save -> kubeadm-config.yaml (0600, contains a bootstrap token)")
    app.form.set("advertise_address", "10.0.0.999")
    app.refresh()
    check("not a valid" in app.issues.get("1.0", "end-1c"), "kubeadm: bad IP reported in Validation pane")
    app.form.set("advertise_address", "10.0.0.11")

    app.select_kind("kind")
    te = app.form.tables["nodes"]
    check(len(te.rows) == 2, "kind: nodes table pre-filled (1 control-plane + 2 workers)")
    d = te.add(wait=False)
    d.set("role", "worker")
    d.set("count", "x")
    check(d.ok() is False and "count" in d.err_var.get().lower(), "kind node dialog uses cluster check_row")
    d.set("count", "1")
    d.set("labels", "zone=b")
    check(d.ok() is True and len(te.rows) == 3, "kind node dialog OK adds a row")
    pd = app.form.tables["port_mappings"].add(wait=False)
    pd.set("host_port", "8080")
    check(pd.ok() is True, "kind port-mapping dialog OK")
    app.form.set("name", "lab")
    text = app.refresh()
    cfg = yaml.safe_load(text)
    check(cfg["kind"] == "Cluster" and len(cfg["nodes"]) == 4 and cfg["name"] == "lab", "kind preview: 4 nodes")
    check(cfg["nodes"][0]["extraPortMappings"][0]["hostPort"] == 8080, "kind preview: port mapping on control-plane")
    p = app.save(directory=tmpc)
    check(p and os.path.basename(p) == "kind-config.yaml", "Save -> kind-config.yaml")

    app.select_kind("kubeconfig")
    app.refresh()
    check("token" in app.issues.get("1.0", "end-1c").lower(), "kubeconfig defaults ask for a token")
    app.form.set("cluster_name", "lab")
    app.form.set("ca", PEM)
    app.form.set("token", "abc.def")
    app.form.set("namespace", "apps")
    text = app.refresh()
    kc = yaml.safe_load(text)
    import base64
    check(kc["clusters"][0]["cluster"]["certificate-authority-data"] == base64.b64encode((PEM + "\n").encode()).decode(),
          "kubeconfig: pasted PEM -> base64 certificate-authority-data")
    check(kc["current-context"] == "admin@lab" and kc["contexts"][0]["context"]["namespace"] == "apps",
          "kubeconfig: context + namespace")
    p = app.save(directory=tmpc)
    check(p and os.path.basename(p) == "lab.kubeconfig" and (os.stat(p).st_mode & 0o777) == 0o600,
          "Save -> lab.kubeconfig (0600)")
    app.form.set("auth_method", "exec plugin")
    app.form.set("exec_command", "kubelogin")
    app.form.set("exec_args", "get-token\n--server-id\nabc")
    kc = yaml.safe_load(app.refresh())
    check(kc["users"][0]["user"]["exec"]["args"] == ["get-token", "--server-id", "abc"], "kubeconfig: exec plugin")

    app.select_kind("k3s / RKE2")
    app.form.set("distro", "rke2")
    app.form.set("token", "s3cret")
    app.form.set("cni", "cilium")
    app.form.set("rke2_disable_rke2_coredns", False)
    app.form.set("rke2_disable_rke2_metrics_server", True)
    text = app.refresh()
    c = yaml.safe_load(text)
    check(text.startswith("# rke2 server config - save as /etc/rancher/rke2/config.yaml"), "rke2 path hint header")
    check(c == {"token": "s3cret", "cni": "cilium", "disable": ["rke2-metrics-server"]}, f"rke2 preview {c}")
    p = app.save(directory=tmpc)
    check(p and os.path.basename(p) == "config.yaml" and (os.stat(p).st_mode & 0o777) == 0o600,
          "Save -> config.yaml (0600)")
    app.form.set("role", "agent")
    app.refresh()
    issues = app.issues.get("1.0", "end-1c").lower()
    check("server" in issues and "agent" in issues, "rke2 agent: server URL required, server-only options rejected")
    app.form.set("server_url", "https://10.0.0.11:9345")
    app.form.set("cni", "")
    app.form.set("rke2_disable_rke2_metrics_server", False)
    app.refresh()
    check(not app.generate().errors, f"rke2 agent valid once server-only options cleared: {app.generate().errors}")

    # caching across types and modes
    app.select_kind("kubeadm")
    check(app.form.values()["advertise_address"] == "10.0.0.11" and app.form.values()["proxy_mode"] == "nftables",
          "kubeadm values cached across type switches")
    app.select_kind("k3s / RKE2")
    app.select_mode("Manifests")
    check(app.kind == manifest_kind_before and app.mode == "Manifests" and
          list(app.selector.cget("values")) == gen.KINDS, f"back to Manifests -> last kind {manifest_kind_before}")
    check(app.buttons["Add to bundle"].instate(["!disabled"]), "bundle buttons re-enabled in Manifests mode")
    check(app.values_for("Deployment")["name"] == "web", "manifest values survive the mode switch")
    app.select_mode("Cluster config")
    v = app.form.values()
    check(app.kind == "k3s / RKE2" and v["distro"] == "rke2" and v["role"] == "agent" and
          v["server_url"] == "https://10.0.0.11:9345", "back to Cluster config -> last type with its values")
    check(app.edited_kinds() == [t for t in ccg.CONFIG_TYPES if t in ("kubeadm", "kind", "kubeconfig", "k3s / RKE2")],
          f"edited cluster types = {app.edited_kinds()}")
    check("Deployment" not in app.edited_label.cget("text") and "kubeadm" in app.edited_label.cget("text"),
          "edited indicator is per mode")
    # ---- new platforms: forms, per-type cache, multi-file save + modes
    print("-- cluster platforms")
    app.select_kind("minikube")
    check(app.form.widgets["mk_driver"].cget("values") and "kvm2" in app.form.widgets["mk_driver"].cget("values"),
          "minikube driver dropdown")
    check(app.form.sections["Start options"].collapsed and not app.form.sections["Machine"].collapsed,
          "minikube: Start options collapsed by default")
    app.form.set("mk_profile", "lab")
    app.form.set("mk_cpus", "4")
    app.form.set("mk_addons", "metrics-server\ningress")
    app.form.set("mk_cni", "cilium")
    text = app.refresh()
    check("# ===== config.json =====" in text and "# ===== start-minikube.sh =====" in text, "minikube preview: 2 files")
    check("config.json + start-minikube.sh" in app.preview_title.cget("text") and
          app.preview_title.cget("text").startswith("Preview - minikube"), f"title {app.preview_title.cget('text')}")
    tmpm = tempfile.mkdtemp(prefix="k8sgui-mk-")
    p = app.save(directory=tmpm)
    sh = os.path.join(tmpm, "start-minikube.sh")
    cj = json.load(open(os.path.join(tmpm, "config.json")))
    check(p and len(app.last_saved) == 2 and (os.stat(sh).st_mode & 0o777) == 0o755 and cj["cpus"] == "4",
          f"Save minikube -> config.json + executable start-minikube.sh {app.last_saved}")
    check("--addons=metrics-server,ingress" in open(sh).read() and "--cni=cilium" in open(sh).read(),
          "start script carries the flag-only settings")
    app.form.set("mk_cpus", "1")
    app.refresh()
    check("cpus" in app.issues.get("1.0", "end-1c").lower(), "minikube: cpus 1 reported")
    app.form.set("mk_cpus", "4")
    app.form.set("mk_output", "config.json")
    app.refresh()
    check("cannot hold" in app.issues.get("1.0", "end-1c"), "config.json-only warns about flag-only settings")
    app.form.set("mk_output", "both (config.json + start-minikube.sh)")

    app.select_kind("Kubespray")
    te = app.form.tables["ks_hosts"]
    check(len(te.rows) == 5, "kubespray hosts table pre-filled (3 cp+etcd, 2 nodes)")
    d = te.add(wait=False)
    d.set("name", "Node_6")
    d.set("ansible_host", "192.168.10.16")
    check(d.ok() is False and "hostname" in d.err_var.get().lower(), "kubespray host dialog uses module check_row")
    d.set("name", "node6")
    d.set("roles", "node")
    check(d.ok() is True and len(te.rows) == 6, "kubespray host dialog OK adds a row")
    app.form.set("ks_plugin", "cilium")
    app.refresh()
    p = app.save(directory=tmpm)
    inv = os.path.join(tmpm, "inventory.ini")
    kcl = os.path.join(tmpm, "group_vars", "k8s_cluster", "k8s-cluster.yml")
    check(os.path.exists(inv) and os.path.exists(kcl) and "node6" in open(inv).read() and
          yaml.safe_load(open(kcl))["kube_network_plugin"] == "cilium", "Save Kubespray -> inventory + group_vars/")

    app.select_kind("OpenShift")
    app.form.set("oc_name", "lab")
    app.form.set("oc_platform", "baremetal")
    app.refresh()
    check("worker" in app.issues.get("1.0", "end-1c"), "openshift baremetal: 3 workers but no worker hosts reported")
    app.form.set("oc_workers", "0")
    app.refresh()
    check(app.generate().ok, f"openshift baremetal defaults valid: {app.generate().errors}")
    p = app.save(directory=tmpm)
    check(p and os.path.basename(p) == "install-config.yaml" and (os.stat(p).st_mode & 0o777) == 0o600,
          "Save OpenShift -> install-config.yaml (0600, pull secret)")
    app.form.set("oc_platform", "gcp")
    app.refresh()
    check("projectid" in app.issues.get("1.0", "end-1c").lower(), "openshift gcp asks for projectID")
    app.form.set("oc_gcp_project", "lab-project-1")
    app.form.set("oc_region", "us-central1")

    app.select_kind("Talos")
    app.form.set("tl_nameservers", "1.1.1.1")
    app.form.set("tl_schedule_cp", True)
    text = app.refresh()
    check("talos-patch.yaml" in app.preview_title.cget("text") and "ResolverConfig" in text, "talos patch preview")
    p = app.save(directory=tmpm)
    check((os.stat(os.path.join(tmpm, "talos-gen-config.sh")).st_mode & 0o777) == 0o755, "talos script 0755")

    for t, key, val in (("k0s", "k0_provider", "calico"), ("MicroK8s", "m8_channel", "1.35/stable"),
                        ("Cluster API", "ca_cp_replicas", "3"), ("EKS", "ek_region", "eu-west-1"),
                        ("GKE", "gk_mode", "Autopilot"), ("AKS", "ak_tier", "standard")):
        app.select_kind(t)
        expect = sum(len(fs) for _, fs in ccg.SCHEMA[t])
        check(app.form.kind == t and len(app.form.getters) == expect, f"{t}: form with {expect} fields")
        app.form.set(key, val)
        app.refresh()
        check(app.generate().ok, f"{t} edited ({key}={val}) valid: {app.generate().errors}")
    app.select_kind("GKE")
    check("create-auto" in app.refresh(), "GKE Autopilot preview")
    check("--no-ssh-key" in ccg.render(app.generate("AKS")), "AKS script never generates ssh keys")
    app.select_kind("minikube")
    check(app.form.values()["mk_profile"] == "lab" and app.form.values()["mk_cni"] == "cilium",
          "minikube values cached across type switches")
    check(app.values_for("Cluster API")["ca_cp_replicas"] == "3", "Cluster API cached")
    shutil.rmtree(tmpm, ignore_errors=True)
    app.select_kind("k3s / RKE2")
    check(app.edited_kinds() == ccg.CONFIG_TYPES, f"edited cluster types (all 14) = {app.edited_kinds()}")

    n = len(app.bundle)
    _dialogs.clear()
    app.add_to_bundle()
    check(len(app.bundle) == n and _dialogs and _dialogs[-1][0] == "showinfo", "no bundling of cluster configs")
    tmpa = tempfile.mkdtemp(prefix="k8sgui-cluster-all-")
    saved = app.save_all_edited(directory=tmpa)
    want = {"kubeadm-config.yaml", "kind-config.yaml", "lab.kubeconfig", "config.yaml", "minikube/config.json",
            "minikube/start-minikube.sh", "kubespray/inventory.ini", "kubespray/group_vars/k8s_cluster/k8s-cluster.yml",
            "install-config.yaml", "talos/talos-gen-config.sh", "talos/talos-patch.yaml", "capi-capd-demo.yaml",
            "eksctl-demo-eks.yaml", "create-gke-demo-gke.sh", "create-aks-demo-aks.sh", "microk8s-config.yaml"}
    check(want <= set(saved) and not os.path.exists(os.path.join(tmpa, "all-in-one.yaml")),
          f"Save all edited (cluster) -> separate files / per-type folders, no all-in-one: {sorted(set(want) - set(saved))}")
    check((os.stat(os.path.join(tmpa, "minikube", "start-minikube.sh")).st_mode & 0o777) == 0o755 and
          (os.stat(os.path.join(tmpa, "install-config.yaml")).st_mode & 0o777) == 0o600, "save-all keeps file modes")
    app.select_kind("kind")
    app.reset_kind()
    check(len(app.form.values()["nodes"]) == 2 and app.form.values()["name"] == "dev" and
          "kind" not in app.edited_kinds(), "Reset kind restores kind defaults only")
    check(app.values_for("kubeadm")["advertise_address"] == "10.0.0.11", "reset leaves other types alone")
    app.validate()
    check(_dialogs[-1][0] == "showinfo" and "kind config is valid" in _dialogs[-1][2], "Validate (cluster) OK dialog")
    shutil.rmtree(tmpc, ignore_errors=True)
    shutil.rmtree(tmpa, ignore_errors=True)
    app.select_mode("Manifests")

    # ------------------------------------------------------------ App templates (Manifests mode)
    print("App templates:")
    app.select_mode("Manifests")
    pump(root)
    app.cache[app.kind] = app.form.values()
    saved_cache = {k: dict(v) for k, v in app.cache.items()}
    saved_edited = app.edited_kinds()

    def wait_ms(ms):
        root.after(ms, root.quit)
        root.mainloop()
        pump(root)

    tv = list(app.tpl_selector.cget("values"))
    check(app.tpl_row.winfo_manager() == "pack" and app.tpl_var.get() == tpl.NONE_CHOICE,
          "Template: dropdown shown in Manifests mode, default 'None / blank'")
    check(str(app.tpl_selector.cget("state")) == "readonly", "template dropdown is readonly")
    want = [tpl.NONE_CHOICE] + [x for g, ts in tpl.grouped().items() for x in [app.TEMPLATE_HEADER.format(g), *ts]]
    check(tv == want and len(tpl.titles()) >= 20, f"template dropdown grouped: {len(tpl.titles())} templates, "
          f"{len(tpl.grouped())} group headers")
    check(not app.tpl_panel.winfo_manager(), "parameter panel hidden until a template is picked")
    app.tpl_var.set("PostgreSQL")
    app.tpl_selector.event_generate("<<ComboboxSelected>>")
    pump(root)
    check(app.kind == "StatefulSet" and app.kind_var.get() == "StatefulSet",
          "applying PostgreSQL switches the selector to its primary kind (StatefulSet)")
    check(app.tpl_panel.winfo_manager() == "pack", "parameter panel shown")
    check(set(app.tpl_vars) == {"name", "namespace", "storage_size", "storage_class"},
          f"PostgreSQL parameters: {sorted(app.tpl_vars)}")
    check(set(app.edited_kinds()) >= {"StatefulSet", "Service", "Secret", "ConfigMap"},
          f"related kinds marked edited: {app.edited_kinds()}")
    check("template: PostgreSQL" in app.edited_label.cget("text"), "edited label names the template")
    sv = app.values_for("StatefulSet")
    check(sv["image"] == tpl.POSTGRES_IMAGE and sv["vct_mount"] == "/var/lib/postgresql" and
          sv["service_name"] == "postgres-headless", "StatefulSet form filled (image, VCT, serviceName)")
    text = app.preview.get("1.0", "end-1c")
    check("pg_isready" in text and "volumeClaimTemplates" in text and "PGDATA" in text,
          "preview shows pg_isready probes, PGDATA and the volumeClaimTemplate")
    check("POSTGRES_PASSWORD=" in app.values_for("Secret")["data"], "Secret form holds the generated password")
    pw1 = app.tpl_applied["secrets"]["password"]
    check("headless" in app.tpl_summary.cget("text"), f"summary lists the extra objects: {app.tpl_summary.cget('text')!r}")
    # parameter change -> automatic re-render (no hand edits yet)
    app.tpl_vars["name"].set("db1")
    wait_ms(900)
    check(app.values_for("StatefulSet")["name"] == "db1" and app.values_for("Service")["name"] == "db1"
          and app.values_for("Secret")["name"] == "db1-secret",
          "changing the app name re-renders the whole set")
    check(app.tpl_applied["secrets"]["password"] == pw1, "re-render keeps the generated password")
    # hand edit -> auto re-render is held back, Apply asks before overwriting
    app.form.set("memory_limit", "2Gi")
    pump(root)
    app.tpl_vars["storage_size"].set("20Gi")
    wait_ms(900)
    check(app.values_for("StatefulSet")["vct_size"] == "8Gi" and "edited by hand" in app.tpl_summary.cget("text"),
          "auto re-render skipped when it would overwrite hand edits")
    asked = []
    messagebox.askyesno = lambda *a, **k: (asked.append(a[0]), False)[1]
    r = app.apply_template()
    check(r is None and asked == ["Overwrite edited forms?"] and app.values_for("StatefulSet")["memory_limit"] == "2Gi",
          "Apply asks before overwriting edits; 'No' keeps them")
    messagebox.askyesno = lambda *a, **k: (asked.append(a[0]), True)[1]
    r = app.apply_template()
    check(r is not None and app.values_for("StatefulSet")["vct_size"] == "20Gi"
          and app.values_for("StatefulSet")["memory_limit"] == "1Gi", "'Yes' re-renders over the edits")
    # Save template set (with a hand edit after applying -> it flows into the saved files)
    app.select_kind("StatefulSet")
    app.form.set("memory_limit", "3Gi")
    pump(root)
    tmpt = tempfile.mkdtemp(prefix="k8sgui-tpl-")
    _dialogs.clear()
    paths = app.save_template_set(tmpt)
    folder = os.path.join(tmpt, "db1")
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    check(names == sorted(["all-in-one.yaml", "configmap-db1-config.yaml", "secret-db1-secret.yaml",
                           "service-db1.yaml", "service-db1-headless.yaml", "statefulset-db1.yaml"]),
          f"Save template set wrote <app>/ files + all-in-one.yaml: {names}")
    docs = list(yaml.safe_load_all(open(os.path.join(folder, "all-in-one.yaml"))))
    check([d["kind"] for d in docs] == ["Secret", "ConfigMap", "Service", "Service", "StatefulSet"],
          "all-in-one.yaml has the 5 objects in apply order")
    stsd = yaml.safe_load(open(os.path.join(folder, "statefulset-db1.yaml")))
    check(stsd["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] == "3Gi",
          "form edits made after applying flow into the saved set")
    check(oct(os.stat(os.path.join(folder, "secret-db1-secret.yaml")).st_mode & 0o777) == "0o600" and
          oct(os.stat(os.path.join(folder, "all-in-one.yaml")).st_mode & 0o777) == "0o600",
          "Secret file and all-in-one.yaml are 0600")
    check(len(paths) == 6 and _dialogs and _dialogs[-1][1] == "Save template set", "save reports the files")
    asked.clear()
    app.save_template_set(tmpt)
    check(asked == ["Overwrite?"], "saving again asks before overwriting")
    # header jumps to the group's first template; switching templates resets untouched leftovers
    app.tpl_var.set(app.TEMPLATE_HEADER.format("Web / proxy"))
    app.tpl_selector.event_generate("<<ComboboxSelected>>")
    pump(root)
    check(app.tpl_var.get() == "nginx" and app.kind == "Deployment", "group header jumps to nginx -> Deployment")
    check("Secret" not in app.edited_kinds() and "ConfigMap" in app.edited_kinds(),
          "untouched PostgreSQL leftovers (Secret) reset; nginx kinds filled")
    check("StatefulSet" in app.edited_kinds(), "hand-edited StatefulSet kept when switching templates")
    check("default.conf" == app.values_for("ConfigMap")["file_key"] and
          app.values_for("Deployment")["replicas"] == "2", "nginx: ConfigMap default.conf + 2 replicas")
    app.tpl_vars["ingress"].set(True)
    app.tpl_vars["host"].set("www.example.org")
    wait_ms(900)
    check(app.values_for("Ingress")["host"] == "www.example.org" and "Ingress" in app.edited_kinds(),
          "'Expose via Ingress' adds the Ingress form")
    tset = app.tpl_applied["set"]
    check([r.item.kind for r in tset.items] == ["ConfigMap", "Service", "Deployment", "Ingress"], "nginx set")
    bad = app.tpl_vars["name"]
    _dialogs.clear()
    bad.set("Bad Name")
    wait_ms(900)
    check(app.values_for("Deployment")["name"] == "nginx" and "App name" in app.tpl_summary.cget("text"),
          "invalid app name: set not re-rendered, error shown")
    r = app.apply_template()
    check(r is None and _dialogs and _dialogs[-1][0] == "showerror", "Apply with an invalid name shows an error")
    bad.set("nginx")
    wait_ms(900)
    # every template applies cleanly through the GUI
    bad_t = []
    for title in tpl.titles():
        app.select_template(title)
        pump(root, 2)
        t = tpl.get(title)
        res = app.generate()
        if not (app.tpl_applied and app.tpl_applied["title"] == title and app.kind == t.primary and res.ok):
            bad_t.append(title)
    check(not bad_t, f"all {len(tpl.titles())} templates apply via the GUI with a valid primary form: {bad_t}")
    app.select_kind("kind")
    pump(root)
    check(not app.tpl_row.winfo_manager() and not app.tpl_panel.winfo_manager(),
          "template bar hidden in Cluster config mode")
    app.select_mode("Manifests")
    pump(root)
    check(app.tpl_row.winfo_manager() == "pack" and app.tpl_panel.winfo_manager() == "pack",
          "template bar back in Manifests mode")
    app.select_template(tpl.NONE_CHOICE)
    pump(root)
    check(app.tpl_applied is None and not app.tpl_panel.winfo_manager(), "'None / blank' detaches the template")
    shutil.rmtree(tmpt, ignore_errors=True)

    # ---- hover help: an ⓘ icon (with tooltip text from field_docs) for every field, column, section, selector
    import field_docs
    missing, wrong, ncols, nfields, nsecs = [], [], 0, 0, 0
    for kind in gen.KINDS + ccg.CONFIG_TYPES:
        app.select_kind(kind)
        pump(root, 1)
        form = app.form
        for title, fields in form.provider.schema(kind):
            nsecs += 1
            sec = form.sections[title]
            if not (sec.icon.winfo_exists() and field_docs.section_help(kind, title) in sec.icon.tooltip.text):
                missing.append(f"{kind}/section {title}")
            for f in fields:
                nfields += 1
                ic = form.icons.get(f.key)
                if ic is None:
                    missing.append(f"{kind}.{f.key}")
                elif ic.tooltip.text != field_docs.tooltip(f) or not f.description:
                    wrong.append(f"{kind}.{f.key}")
                if f.kind == "table":
                    d = form.tables[f.key].open_dialog(None, wait=False)
                    pump(root, 1)
                    for c in f.columns:
                        ncols += 1
                        ci = d.icons.get(c.key)
                        if ci is None or not c.description or c.description not in ci.tooltip.text:
                            missing.append(f"{kind}.{f.key}.{c.key}")
                    d.destroy()
    check(not missing and not wrong, f"ⓘ icons with the right tooltip text: {nfields} fields, {ncols} table-dialog "
                                     f"columns, {nsecs} section headers across {len(gen.KINDS + ccg.CONFIG_TYPES)} "
                                     f"forms (missing {missing[:5]}, wrong {wrong[:5]})")
    check(all(k in app.top_icons for k in ("mode", "kind", "template")) and
          "Manifests" in app.top_icons["mode"].tooltip.text, "ⓘ icons on the Mode / type / Template selectors")
    app.select_mode("Manifests")
    app.select_template("PostgreSQL")
    pump(root, 2)
    ps = tpl.params_for("PostgreSQL")
    check(all(p.key in app.tpl_icons and p.description and p.description in app.tpl_icons[p.key].tooltip.text
              for p in ps), f"ⓘ icons on all {len(ps)} template parameters")
    check("PostgreSQL" in app.top_icons["template"].tooltip.text, "Template tooltip names the selected template")
    app.select_template(tpl.NONE_CHOICE)
    # hover: Enter -> tooltip after ~400 ms with the field's text; Leave hides it; scroll/click hide it too
    app.select_kind("Deployment")
    pump(root, 3)
    ic = app.form.icons["image_pull_policy"]
    app.form.scroll.canvas.yview_moveto(0)
    pump(root, 3)
    ic.event_generate("<Enter>", x=2, y=2)
    pump(root, 1)
    check(gui_app.Tooltip.current is None, "tooltip not shown before the delay")
    wait_ms(550)
    tip = gui_app.Tooltip.current
    shown = tip is not None and tip.win is not None and tip.win.winfo_ismapped()
    check(shown and tip.widget is ic and "Always" in tip.shown_text and "IfNotPresent" in tip.shown_text
          and "imagePullPolicy" in tip.shown_text, "hover over imagePullPolicy ⓘ shows its tooltip")
    if shown:
        tw = tip.win
        x, y = tw.winfo_rootx(), tw.winfo_rooty()
        check(0 <= x and x + tw.winfo_reqwidth() <= tw.winfo_screenwidth() and 0 <= y and
              y + tw.winfo_reqheight() <= tw.winfo_screenheight(),
              f"tooltip placed on screen ({x},{y} {tw.winfo_reqwidth()}x{tw.winfo_reqheight()} of "
              f"{tw.winfo_screenwidth()}x{tw.winfo_screenheight()})")
        check(int(tip.label.cget("wraplength")) == 380, "tooltip wraps at 380 px")
    ic.event_generate("<Leave>")
    pump(root, 2)
    check(gui_app.Tooltip.current is None and (tip is None or tip.win is None), "Leave hides the tooltip")
    ic.event_generate("<Enter>", x=2, y=2)
    ic.event_generate("<Leave>")
    wait_ms(550)
    check(gui_app.Tooltip.current is None, "quick pass-over (Enter then Leave before 400 ms) shows nothing")
    ic.event_generate("<Enter>", x=2, y=2)
    wait_ms(550)
    ic.event_generate("<ButtonPress-1>", x=2, y=2)
    pump(root, 2)
    check(gui_app.Tooltip.current is None, "click hides the tooltip")
    ic.event_generate("<Enter>", x=2, y=2)
    wait_ms(550)
    app.form.scroll._on_wheel(type("E", (), {"widget": app.form.scroll.canvas, "num": 5, "delta": -120})())
    pump(root, 2)
    check(gui_app.Tooltip.current is None, "mouse-wheel scroll hides the tooltip")
    sec_ic = app.form.sections["Metadata"].icon
    sec_ic.event_generate("<Enter>", x=2, y=2)
    wait_ms(550)
    check(gui_app.Tooltip.current is not None and "metadata" in gui_app.Tooltip.current.shown_text,
          "section header ⓘ tooltip")
    sec_ic.event_generate("<Leave>")
    pump(root, 2)
    os.environ["K8SGUI_INFO_ICON"] = "(i)"
    check(gui_app.info_glyph(root) == "(i)", "K8SGUI_INFO_ICON overrides the glyph")
    del os.environ["K8SGUI_INFO_ICON"]

    # ------------------------------------------------------------ Networking & Storage mode
    print("-- networking & storage mode")
    keep_cache = {k: v for k, v in app.cache.items()}
    app.cache = {}
    app.form.destroy()
    app.form = None
    app.select_mode("Networking & Storage")
    pump(root)
    check(app.kind == "Calico" and app.type_label.cget("text") == "Add-on type:", "N&S mode opens Calico")
    want = []
    for g, ts in agen.GROUPS.items():
        want += [f"── {g} ──"] + ts
    check(list(app.selector.cget("values")) == want, f"grouped add-on dropdown ({len(want)} entries)")
    app.kind_var.set("── CSI - on-prem ──")
    app.selector.event_generate("<<ComboboxSelected>>")
    pump(root)
    check(app.kind == "vSphere", "add-on group header jumps to its first type")
    check(all(app.buttons[b].instate(["disabled"]) for b in ("Add to bundle", "Save bundle…", "Clear bundle")),
          "bundle buttons disabled in N&S mode")
    for atype in agen.ADDON_TYPES:
        app.select_kind(atype)
        pump(root, 2)
        n = sum(len(fs) for _, fs in agen.SCHEMA[atype])
        txt = app.refresh()
        check(app.form.kind == atype and len(app.form.getters) == n and "install.sh" in txt,
              f"{atype}: {len(app.form.getters)}/{n} widgets, preview has install.sh")
        check(all(app.form.sections[t].collapsed == (t in gui_app.providers.collapsed_sections(atype))
                  for t in app.form.sections), f"{atype}: collapsed sections")
    app.select_kind("Calico")
    te = app.form.tables["cal_pools"]
    d = te.add(wait=False)
    pump(root)
    d.set("name", "bad"); d.set("cidr", "10.0.0.1/16")
    check(d.ok() is False and "CIDR" in d.err_var.get(), f"IP pool dialog shows CIDR error ({d.err_var.get()})")
    d.set("name", "pool-b"); d.set("cidr", "10.245.0.0/16"); d.set("encapsulation", "VXLAN")
    check(d.ok() is True and len(te.rows) == 2, "IP pool dialog adds a pool")
    app.refresh()
    check("pool-b" in app.preview.get("1.0", "end-1c") and "custom-resources.yaml" in app.preview_title.cget("text"),
          "Calico preview shows the new pool + target files")
    tmp = tempfile.mkdtemp(prefix="gui-addons-")
    first = app.save(tmp)
    names = sorted(os.listdir(tmp))
    check(first and names == ["custom-resources.yaml", "install.sh"] and
          os.stat(os.path.join(tmp, "install.sh")).st_mode & 0o777 == 0o755, f"Calico save: {names}")
    # cross-check with the kind cluster form (both in this session)
    app.select_mode("Cluster config")
    app.select_kind("kind")
    app.form.set("disable_default_cni", False)
    app.form.set("pod_subnet", "10.244.0.0/16")
    app.refresh()
    iss = app.issues.get("1.0", "end-1c")
    check("Cross-check" in iss and "kindnet" in iss and "192.168.0.0/16" in iss and "minikube" not in iss,
          "kind form warns about Calico pool + kindnet (only edited forms count)")
    app.form.set("disable_default_cni", True)
    app.form.set("pod_subnet", "192.168.0.0/16")
    app.refresh()
    iss = app.issues.get("1.0", "end-1c")
    check("kindnet" not in iss and "10.245.0.0/16" in iss, "disableDefaultCNI ticked; only the extra pool-b mismatches")
    app.select_kind("Calico")
    te = app.form.tables["cal_pools"]
    te.set(te.get()[:1])
    app.refresh()
    check("Cross-check" not in app.issues.get("1.0", "end-1c"), "matching pool + podSubnet: no warning on Calico")
    te.set(te.get() + [{"name": "pool-b", "cidr": "10.245.0.0/16", "encapsulation": "VXLAN", "nat_outgoing": "Enabled",
                        "block_size": "26", "node_selector": "all()"}])
    app.refresh()
    check("Cross-check" in app.issues.get("1.0", "end-1c"), "Calico form sees the kind form too")
    # session StorageClasses in the PVC dropdown
    app.select_kind("NFS CSI")
    app.form.set("name", "nfs-gui")
    app.refresh()
    app.select_kind("Nutanix")
    app.form.set("nx_create_secret", True)
    app.form.set("nx_prism", "10.0.0.5")
    app.form.set("nx_password", "pw")
    app.refresh()
    tmp2 = tempfile.mkdtemp(prefix="gui-addons-")
    app.save(tmp2)
    check(os.stat(os.path.join(tmp2, "secret.yaml")).st_mode & 0o777 == 0o600, "Nutanix secret.yaml saved 0600")
    app.select_mode("Manifests")
    app.select_kind("PersistentVolumeClaim")
    opts = list(app.form.widgets["storage_class"].cget("values"))
    check("nfs-gui" in opts and "nutanix-volume" in opts, f"PVC storageClass dropdown has session classes: {opts[-3:]}")
    app.select_kind("StatefulSet")
    check("nfs-gui" in list(app.form.widgets["vct_storage_class"].cget("values")), "StatefulSet VCT dropdown too")
    app.select_kind("NetworkPolicy")
    app.form.set("np_default_deny", "all")
    app.form.set("pod_selector", "")
    txt = app.refresh()
    check("policyTypes" in txt and "Egress" in txt, "NetworkPolicy default-deny preset in the GUI")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    addon_cache = app.session()
    app.form.destroy()
    app.form = None
    app.cache = keep_cache
    app.select_kind("Deployment")
    pump(root)

    # restore the earlier forms for the screenshots
    app.form.destroy()
    app.form = None
    app.cache = saved_cache
    app.select_kind("Deployment")
    pump(root)
    check(app.edited_kinds() == saved_edited, "earlier manifest forms restored after the template tests")

    if shot:
        app.select_kind("Deployment")
        app.form.set("replicas", "3")
        app.refresh()
        root.lift()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        # scroll the form to the containers section and the preview to initContainers
        sf = app.form.scroll
        sec = app.form.sections["Init & sidecar containers"]
        total = max(sf.inner.winfo_height(), 1)
        sf.canvas.yview_moveto(max(sec.winfo_y() - 4, 0) / total)
        idx = app.preview.search("initContainers:", "1.0")
        if idx:
            app.preview.yview(f"{idx} - 1 lines")
        app.form.tables["extra_containers"].tree.selection_set("0")
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(capture(root, shot), f"screenshot saved to {shot}")
        # second screenshot: the container editor dialog
        dshot = os.path.join(os.path.dirname(shot), "desktop-container-dialog.png")
        d = app.form.tables["extra_containers"].edit(wait=False)
        d.geometry("680x640+340+110")
        for _ in range(15):
            pump(root, 2)
            root.after(30)
        check(capture(d, dshot), f"dialog screenshot saved to {dshot}")
        d.destroy()
        # cluster config screenshots
        cshot = os.path.join(os.path.dirname(shot), "desktop-cluster-kubeadm.png")
        app.select_kind("kubeadm")
        app.form.set("include_kube_proxy", True)
        app.form.set("cert_sans", "k8s-api.lab, 10.0.0.100")
        app.refresh()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(capture(root, cshot), f"cluster config screenshot saved to {cshot}")
        kshot = os.path.join(os.path.dirname(shot), "desktop-cluster-kind.png")
        app.select_kind("kind")
        app.form.set("kube_proxy_mode", "nftables")
        app.form.tables["port_mappings"].set([{"container_port": "80", "host_port": "8080", "listen_address": "127.0.0.1",
                                               "protocol": "TCP"}])
        app.refresh()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(capture(root, kshot), f"kind screenshot saved to {kshot}")
        mshot = os.path.join(os.path.dirname(shot), "desktop-cluster-minikube.png")
        app.select_kind("minikube")
        app.form.set("mk_addons", "metrics-server\ningress\ndashboard")
        app.refresh()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(capture(root, mshot), f"minikube screenshot saved to {mshot}")
        gshot = os.path.join(os.path.dirname(shot), "desktop-cluster-types.png")
        app.select_kind("EKS")
        app.refresh()
        root.tk.call("ttk::combobox::Post", app.selector)
        for _ in range(15):
            pump(root, 2)
            root.after(30)
        check(capture(root, gshot), f"grouped type dropdown screenshot saved to {gshot}")
        root.tk.call("ttk::combobox::Unpost", app.selector)
        # Networking & Storage screenshots
        saved_c = dict(app.cache)
        app.form.destroy()
        app.form = None
        app.cache = {k: v for k, v in addon_cache.items() if k in agen.SCHEMA}
        app.cache["kind"] = {**ccg.defaults("kind"), "disable_default_cni": True, "pod_subnet": "192.168.0.0/16"}
        app.cache["NetworkPolicy"] = {**gen.defaults("NetworkPolicy"), "name": "web-policy", "policy_egress": True,
                                      "np_allow_dns": True, "ingress_rules": [
            {"peer": "pods (podSelector)", "pod_labels": "app=frontend", "ns_labels": "", "cidr": "",
             "except_cidrs": "", "ports": "80/TCP, 443", "rule": "1"},
            {"peer": "ipBlock (CIDR)", "pod_labels": "", "ns_labels": "", "cidr": "10.0.0.0/8",
             "except_cidrs": "10.1.0.0/16", "ports": "8080/TCP", "rule": ""}]}
        for name, atype, setup in (
                ("desktop-addons-calico.png", "Calico", None),
                ("desktop-addons-cilium.png", "Cilium", {"cil_hubble": True, "cil_relay": True, "cil_ui": True}),
                ("desktop-addons-nutanix.png", "Nutanix", None),
                ("desktop-networkpolicy.png", "NetworkPolicy", None)):
            app.select_kind(atype)
            for k, v in (setup or {}).items():
                app.form.set(k, v)
            app.refresh()
            for _ in range(10):
                pump(root, 2)
                root.after(30)
            p_ = os.path.join(os.path.dirname(shot), name)
            check(capture(root, p_), f"{atype} screenshot saved to {p_}")
        app.select_kind("Longhorn")
        app.refresh()
        root.tk.call("ttk::combobox::Post", app.selector)
        for _ in range(15):
            pump(root, 2)
            root.after(30)
        p_ = os.path.join(os.path.dirname(shot), "desktop-addons-types.png")
        check(capture(root, p_), f"add-on dropdown screenshot saved to {p_}")
        root.tk.call("ttk::combobox::Unpost", app.selector)
        app.form.destroy()
        app.form = None
        app.cache = saved_c
        app.select_kind("Deployment")
        # application templates: PostgreSQL applied + the template dropdown open
        app.select_mode("Manifests")
        app.select_template("PostgreSQL")
        app.refresh()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        tshot = os.path.join(os.path.dirname(shot), "desktop-templates.png")
        root.tk.call("ttk::combobox::Post", app.tpl_selector)
        for _ in range(15):
            pump(root, 2)
            root.after(30)
        check(capture(root, tshot), f"template dropdown screenshot saved to {tshot}")
        root.tk.call("ttk::combobox::Unpost", app.tpl_selector)
        nshot = os.path.join(os.path.dirname(shot), "desktop-template-nginx.png")
        app.select_template("nginx")
        app.tpl_vars["ingress"].set(True)
        root.after(900, root.quit)
        root.mainloop()
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(capture(root, nshot), f"nginx template screenshot saved to {nshot}")
        # tooltip screenshot: hovering the imagePullPolicy ⓘ
        ttshot = os.path.join(os.path.dirname(shot), "desktop-tooltip.png")
        app.select_template(tpl.NONE_CHOICE)
        app.select_kind("Deployment")
        for _ in range(5):
            pump(root, 2)
        ic = app.form.icons["image_pull_policy"]
        sf = app.form.scroll
        sf.canvas.yview_moveto(max(ic.master.master.master.winfo_y() - 4, 0) / max(sf.inner.winfo_height(), 1))
        for _ in range(5):
            pump(root, 2)
        ic.event_generate("<Enter>", x=2, y=2)
        wait_ms(600)
        for _ in range(10):
            pump(root, 2)
            root.after(30)
        check(gui_app.Tooltip.current is not None and capture(root, ttshot), f"tooltip screenshot saved to {ttshot}")
        gui_app.Tooltip.hide_all()
    root.destroy()
    print(f"\nGUI SMOKE RESULT: {'PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

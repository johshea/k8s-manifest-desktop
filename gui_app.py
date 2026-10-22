"""
gui_app.py - Tkinter/ttk front-end for manifest_gen.

Run via k8s_manifest_gui.py (which checks tkinter / installs PyYAML first).
"""
from __future__ import annotations

import copy
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import app_templates as tpl
import cluster_config_gen as ccg
import field_docs
import manifest_gen as gen

IS_MAC = sys.platform == "darwin"
MOD = "Command" if IS_MAC else "Control"
APP_TITLE = "Kubernetes Manifest Generator"
# Sections that start collapsed (click the ▸ header to expand). State is remembered per kind.
from providers import COLLAPSED_BY_DEFAULT  # noqa: E402  (generator core)


from providers import (GROUP_HEADER, MODE_OF, MODES, PRIVATE_TYPES, PROVIDERS, ClusterProvider,  # noqa: E402,F401
                       ManifestProvider, check_row_any, output_files, provider_for, row_defaults_any,
                       save_all_plan, template_conflicts, template_set_plan, template_stale, template_summary)
import providers  # noqa: E402


# --------------------------------------------------------------------------- #
# Hover help: an "ⓘ" icon next to every field / section / selector; hovering shows a tooltip
# --------------------------------------------------------------------------- #
INFO_GLYPH = "\u24d8"          # ⓘ  (set K8SGUI_INFO_ICON="(i)" if your font renders it badly)
INFO_FALLBACK = "(i)"


def info_glyph(widget) -> str:
    env = os.environ.get("K8SGUI_INFO_ICON")
    if env:
        return env
    try:   # some Tk builds draw a 0-width / tofu box for missing glyphs
        f = tkfont.nametofont("TkDefaultFont")
        if f.measure(INFO_GLYPH) <= 0 or f.measure(INFO_GLYPH) > 3 * f.measure("M"):
            return INFO_FALLBACK
    except tk.TclError:
        return INFO_FALLBACK
    return INFO_GLYPH


class Tooltip:
    """One tooltip at a time: a borderless Toplevel shown DELAY ms after the pointer enters a widget,
    hidden on leave / click / mouse wheel, kept on-screen near edges."""
    DELAY = 400
    WRAP = 380
    current: "Tooltip | None" = None      # the visible tooltip (tests read .text / .win)

    def __init__(self, widget, text):
        self.widget, self._text = widget, text
        self.win: tk.Toplevel | None = None
        self._after = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<MouseWheel>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    @property
    def text(self) -> str:
        return self._text() if callable(self._text) else self._text

    def _enter(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.DELAY, self.show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def show(self):
        self._after = None
        if Tooltip.current is not None and Tooltip.current is not self:
            Tooltip.current.hide()
        if self.win is not None or not self.widget.winfo_exists():
            return
        tw = self.win = tk.Toplevel(self.widget)
        tw.withdraw()
        tw.wm_overrideredirect(True)
        if IS_MAC:
            try:
                tw.tk.call("::tk::unsupported::MacWindowStyle", "style", tw._w, "help", "noActivates")
            except tk.TclError:
                pass
        try:
            tw.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.shown_text = text = self.text
        head, _, body = text.partition("\n")
        frame = tk.Frame(tw, background="#ffffe6", highlightthickness=1, highlightbackground="#8a8a6a")
        frame.pack()
        base = tkfont.nametofont("TkDefaultFont")
        bold = base.copy()
        bold.configure(weight="bold")
        self._bold = bold                         # keep a reference while shown
        self.title_label = tk.Label(frame, text=head, justify="left", anchor="w", wraplength=self.WRAP,
                                    background="#ffffe6", foreground="#1a4f8b", font=bold, padx=8, pady=0)
        self.title_label.pack(fill="x", pady=(5, 0))
        self.label = tk.Label(frame, text=body, justify="left", anchor="w", wraplength=self.WRAP,
                              background="#ffffe6", foreground="#202020", font=base, padx=8, pady=0)
        self.label.pack(fill="x", pady=(1, 5))
        for w in (frame, self.title_label, self.label):
            w.bind("<Enter>", self.hide)          # never trap the pointer
        tw.update_idletasks()
        tw.wm_geometry(self._place(max(tw.winfo_reqwidth(), frame.winfo_reqwidth() + 2),
                                   max(tw.winfo_reqheight(), frame.winfo_reqheight() + 2)))
        tw.deiconify()
        tw.update_idletasks()                     # re-clamp with the real size once mapped
        tw.wm_geometry(self._place(max(tw.winfo_width(), tw.winfo_reqwidth()),
                                   max(tw.winfo_height(), tw.winfo_reqheight())))
        Tooltip.current = self

    def _place(self, w: int, h: int) -> str:
        """Below-right of the widget; flipped left / above when it would leave the screen."""
        wd = self.widget
        sw, sh = wd.winfo_screenwidth(), wd.winfo_screenheight()
        x = wd.winfo_rootx() + wd.winfo_width() + 6
        y = wd.winfo_rooty() + wd.winfo_height() + 4
        if x + w > sw - 4:
            x = wd.winfo_rootx() - w - 6
        if y + h > sh - 4:
            y = wd.winfo_rooty() - h - 4
        x = min(max(4, x), max(4, sw - w - 4))
        y = min(max(4, y), max(4, sh - h - 4))
        return f"+{x}+{y}"

    def hide(self, _e=None):
        self._cancel()
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
        if Tooltip.current is self:
            Tooltip.current = None

    @classmethod
    def hide_all(cls, _e=None):
        if cls.current is not None:
            cls.current.hide()


def info_icon(parent, text) -> ttk.Label:
    """Small "ⓘ" label with a hover Tooltip (text may be a callable). The tooltip is ``icon.tooltip``."""
    ic = ttk.Label(parent, text=info_glyph(parent), style="Info.TLabel", cursor="question_arrow", takefocus=0)
    ic.tooltip = Tooltip(ic, text)
    return ic


def labelled(parent, text, help_text, style=None) -> tuple[ttk.Frame, ttk.Label]:
    """Frame holding a label followed by its info icon (grid the frame where the label used to go)."""
    box = ttk.Frame(parent)
    ttk.Label(box, text=text, **({"style": style} if style else {})).pack(side="left")
    ic = info_icon(box, help_text)
    ic.pack(side="left", padx=(3, 0))
    return box, ic


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame (Canvas + inner Frame) with mouse-wheel support."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _e=None):
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self, _e=None):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_wheel(self, e):
        Tooltip.hide_all()
        # Let multi-line Text widgets scroll themselves
        if isinstance(e.widget, (tk.Text, ttk.Treeview)):
            return
        if getattr(e, "num", None) == 4:
            step = -3
        elif getattr(e, "num", None) == 5:
            step = 3
        elif IS_MAC:
            step = -int(e.delta) or (-1 if e.delta > 0 else 1)
        else:
            step = -int(e.delta / 120) * 3
        self.canvas.yview_scroll(step, "units")


def make_field_widget(parent, f: gen.Field, value, mono, on_change):
    """Create the input widget for a scalar Field. Returns (widget, getter, setter, var|None)."""
    if f.kind == "text":
        w = tk.Text(parent, height=f.height, width=40, wrap="none", font=mono, undo=True,
                    borderwidth=1, relief="solid")
        w.insert("1.0", str(value))
        w.edit_modified(False)

        def _mod(e, w=w):
            if w.edit_modified():
                w.edit_modified(False)
                on_change()
        w.bind("<<Modified>>", _mod)
        return w, (lambda: w.get("1.0", "end-1c")), (lambda v: (w.delete("1.0", "end"), w.insert("1.0", v))), None
    if f.kind == "check":
        var = tk.BooleanVar(value=bool(value))
        w = ttk.Checkbutton(parent, variable=var, command=on_change)
        return w, var.get, (lambda v: var.set(bool(v))), None
    var = tk.StringVar(value=str(value))
    if f.kind in ("combo", "ecombo"):
        w = ttk.Combobox(parent, textvariable=var, values=f.options,
                         state="readonly" if f.kind == "combo" else "normal")
        w.bind("<<ComboboxSelected>>", lambda e: on_change())
    else:
        w = ttk.Entry(parent, textvariable=var)
    var.trace_add("write", lambda *a: on_change())
    return w, var.get, (lambda v: var.set(str(v))), var


class RowDialog(tk.Toplevel):
    """Add/Edit dialog for one row of a table Field (container, toleration, affinity rule...)."""

    def __init__(self, editor: "TableEditor", index: int | None):
        super().__init__(editor.winfo_toplevel())
        self.editor, self.index = editor, index
        fld = editor.field
        self.title(f"{'Add' if index is None else 'Edit'} - {fld.label}")
        row = row_defaults_any(fld.key)
        if index is not None:
            row.update(editor.rows[index])
        self.getters, self.setters, self.widgets = {}, {}, {}
        self.icons: dict[str, ttk.Label] = {}
        many = len(fld.columns) > 8
        self._sf = None
        if many:
            self.geometry("680x640")
            sf = self._sf = ScrollFrame(self)
            sf.pack(fill="both", expand=True)
            body = sf.inner
        else:
            body = ttk.Frame(self)
            body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        r = 0
        for f in fld.columns:
            box, self.icons[f.key] = labelled(body, f.label + (" *" if f.required else ""), field_docs.tooltip(f))
            box.grid(row=r, column=0, sticky="nw", padx=(10, 6), pady=2)
            w, g, st, _ = make_field_widget(body, f, row.get(f.key, f.default), editor.app.mono_font, lambda: None)
            w.grid(row=r, column=1, sticky="ew", padx=(0, 10), pady=2)
            self.getters[f.key], self.setters[f.key], self.widgets[f.key] = g, st, w
            r += 1
            if f.help:
                ttk.Label(body, text=f.help, style="Help.TLabel", wraplength=440, justify="left").grid(
                    row=r, column=1, sticky="w", padx=(0, 10), pady=(0, 3))
                r += 1
        self.err_var = tk.StringVar()
        ttk.Label(self, textvariable=self.err_var, foreground="#c62828", wraplength=640, justify="left").pack(
            fill="x", padx=10)
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="OK", command=self.ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())

    def values(self) -> dict:
        return {k: g() for k, g in self.getters.items()}

    def set(self, key, value):
        self.setters[key](value)

    def destroy(self):
        if self._sf is not None:
            self._sf._unbind_wheel()   # don't leave global wheel bindings pointing at a dead canvas
        super().destroy()

    def ok(self) -> bool:
        vals = self.values()
        errs = check_row_any(self.editor.field.key, vals)
        if errs:
            self.err_var.set("✖ " + "\n✖ ".join(errs))
            return False
        self.editor._commit(self.index, vals)
        self.destroy()
        return True

    def wait(self):
        self.transient(self.editor.winfo_toplevel())
        self.wait_visibility()
        self.grab_set()
        self.focus_set()
        self.wait_window()


class TableEditor(ttk.Frame):
    """List (Treeview) + Add/Edit/Duplicate/Remove/Up/Down for a table Field."""

    def __init__(self, master, app, field: gen.Field, rows, on_change):
        super().__init__(master)
        self.app, self.field, self.on_change = app, field, on_change
        self.rows: list[dict] = copy.deepcopy(list(rows or []))
        labels = {c.key: c.label for c in field.columns}
        self.tree = ttk.Treeview(self, columns=field.summary, show="headings", height=4, selectmode="browse")
        for col in field.summary:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=90, minwidth=50, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.columnconfigure(0, weight=1)
        btns = ttk.Frame(self)
        btns.grid(row=0, column=1, sticky="n", padx=(6, 0))
        for text, cmd in (("Add…", self.add), ("Edit…", self.edit), ("Duplicate", self.duplicate),
                          ("Remove", self.remove), ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1))):
            ttk.Button(btns, text=text, width=9, command=cmd).pack(fill="x", pady=1)
        self._render()

    def _render(self, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            vals = []
            for col in self.field.summary:
                v = str(r.get(col, ""))
                v = v.splitlines()[0] if v else ""
                vals.append(v if len(v) <= 40 else v[:37] + "…")
            self.tree.insert("", "end", iid=str(i), values=vals)
        if select is not None and 0 <= select < len(self.rows):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def _selected(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def get(self) -> list[dict]:
        return copy.deepcopy(self.rows)

    def set(self, rows):
        self.rows = copy.deepcopy(list(rows or []))
        self._render()
        self.on_change()

    def open_dialog(self, index: int | None = None, wait: bool = True) -> RowDialog:
        dlg = RowDialog(self, index)
        if wait:
            dlg.wait()
        return dlg

    def add(self, wait=True):
        return self.open_dialog(None, wait)

    def edit(self, wait=True):
        i = self._selected()
        if i is None:
            if self.rows:
                i = 0
            else:
                return self.add(wait)
        return self.open_dialog(i, wait)

    def _commit(self, index, row):
        if index is None:
            self.rows.append(row)
            index = len(self.rows) - 1
        else:
            self.rows[index] = row
        self._render(index)
        self.on_change()

    def duplicate(self):
        i = self._selected()
        if i is None:
            return
        r = copy.deepcopy(self.rows[i])
        if "name" in r and r["name"]:
            r["name"] = f"{r['name']}-copy"[:63]
        self.rows.insert(i + 1, r)
        self._render(i + 1)
        self.on_change()

    def remove(self):
        i = self._selected()
        if i is None:
            return
        del self.rows[i]
        self._render(min(i, len(self.rows) - 1))
        self.on_change()

    def move(self, delta):
        i = self._selected()
        if i is None or not 0 <= i + delta < len(self.rows):
            return
        self.rows[i], self.rows[i + delta] = self.rows[i + delta], self.rows[i]
        self._render(i + delta)
        self.on_change()


class Section(ttk.LabelFrame):
    """A LabelFrame whose header (▾/▸ title) collapses/expands the body."""

    def __init__(self, master, title, collapsed, on_toggle, help_text=""):
        self.title_text, self.on_toggle = title, on_toggle
        self.headbox = ttk.Frame(master)
        self.header = ttk.Label(self.headbox, text="", style="Section.TLabel", cursor="hand2")
        self.header.pack(side="left")
        self.icon = info_icon(self.headbox, f"{title}\n{help_text}" if help_text else title)
        self.icon.pack(side="left", padx=(4, 0))
        super().__init__(master, labelwidget=self.headbox, padding=(8, 4))
        self.body = ttk.Frame(self)
        self.body.columnconfigure(0, minsize=200)
        self.body.columnconfigure(1, weight=1)
        self.body.grid(row=0, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.header.bind("<Button-1>", lambda e: self.toggle())
        self.collapsed = False
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool):
        self.collapsed = collapsed
        if collapsed:
            self.body.grid_remove()
        else:
            self.body.grid()
        self.header.configure(text=("▸ " if collapsed else "▾ ") + self.title_text)

    def toggle(self):
        self.set_collapsed(not self.collapsed)
        self.on_toggle(self.title_text, self.collapsed)


class KindForm:
    """The widgets for ONE resource kind. Built on demand when the kind is selected and
    destroyed when another kind is picked (values are cached by App between switches)."""

    def __init__(self, app: "App", parent, kind: str, initial: dict | None = None):
        self.app, self.kind = app, kind
        self.provider = provider_for(kind)
        init = self.provider.defaults(kind)
        init.update(initial or {})
        self.getters: dict[str, callable] = {}
        self.setters: dict[str, callable] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self.vars: dict[str, tk.StringVar] = {}
        self.scroll = ScrollFrame(parent)
        self.tables: dict[str, TableEditor] = {}
        self.sections: dict[str, Section] = {}
        self.icons: dict[str, ttk.Label] = {}      # field key -> its ⓘ icon (tooltip = icon.tooltip)
        body = self.scroll.inner
        body.columnconfigure(0, weight=1)
        mono = app.mono_font
        collapsed = app.collapsed_for(kind)
        for r, (title, fields) in enumerate(self.provider.schema(kind)):
            sec = Section(body, title, title in collapsed, app.section_toggled, field_docs.section_help(kind, title))
            sec.grid(row=r, column=0, sticky="ew", padx=6, pady=4)
            self.sections[title] = sec
            lf = sec.body
            row = 0
            for f in fields:
                if f.kind == "table":
                    box, self.icons[f.key] = labelled(lf, f.label, field_docs.tooltip(f), "Title.TLabel")
                    box.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
                    row += 1
                    if f.help:
                        ttk.Label(lf, text=f.help, style="Help.TLabel", wraplength=560, justify="left").grid(
                            row=row, column=0, columnspan=2, sticky="w")
                        row += 1
                    te = TableEditor(lf, app, f, init[f.key], app.schedule_refresh)
                    te.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 6))
                    self.tables[f.key] = te
                    self.getters[f.key], self.setters[f.key], self.widgets[f.key] = te.get, te.set, te
                    row += 1
                    continue
                lbl = f.label + (" *" if f.required else "")
                box, self.icons[f.key] = labelled(lf, lbl, field_docs.tooltip(f))
                box.grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=2)
                w, g, st, var = make_field_widget(lf, f, init[f.key], mono, app.schedule_refresh)
                if var is not None:
                    self.vars[f.key] = var
                self.getters[f.key], self.setters[f.key] = g, st
                w.grid(row=row, column=1, sticky="ew", pady=2)
                self.widgets[f.key] = w
                row += 1
                if f.help:
                    ttk.Label(lf, text=f.help, style="Help.TLabel", justify="left", wraplength=520).grid(
                        row=row, column=1, sticky="w", pady=(0, 3))
                    row += 1
        # Keep the default "app=<name>" label (and Service selector / StatefulSet serviceName) in step with Name
        self._prev_name = str(init.get("name", ""))
        if "name" in self.vars:
            self.vars["name"].trace_add("write", lambda *a: self._name_changed())

        # Show/hide-ish behaviour: Service type drives which fields matter
        if kind == "Service":
            self.widgets["service_type"].bind("<<ComboboxSelected>>", self._service_type_changed, add="+")
            self._service_type_changed(clear=False)

    def _name_changed(self, _e=None):
        new = self.getters["name"]().strip()
        old = self._prev_name
        if new == old:
            return
        for key, fmt in (("labels", "app={}"), ("selector", "app={}"), ("service_name", "{}"),
                         ("backend_service", "{}")):
            if key in self.getters and self.getters[key]().strip() == fmt.format(old):
                self.setters[key](fmt.format(new))
        self._prev_name = new

    def _service_type_changed(self, _e=None, clear=True):
        t = self.getters["service_type"]()
        self.widgets["node_port"].configure(state="normal" if t in ("NodePort", "LoadBalancer") else "disabled")
        self.widgets["external_name"].configure(state="normal" if t == "ExternalName" else "disabled")
        self.widgets["external_traffic_policy"].configure(
            state="readonly" if t in ("NodePort", "LoadBalancer") else "disabled")
        if clear and t not in ("NodePort", "LoadBalancer"):
            self.setters["node_port"]("")
            self.setters["external_traffic_policy"]("")

    def values(self) -> dict:
        return {k: g() for k, g in self.getters.items()}

    def set(self, key, value):
        self.setters[key](value)

    def destroy(self):
        self.scroll._unbind_wheel()
        self.scroll.destroy()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.bundle: list[dict] = []
        self.last_dir = os.path.expanduser("~")
        self.last_saved: list[str] = []
        self._after_id = None
        self.live = tk.BooleanVar(value=True)
        root.title(APP_TITLE)
        root.geometry("1360x860")
        root.minsize(980, 600)
        self._style()

        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        left = ttk.Frame(paned)
        top = ttk.Frame(left, padding=(2, 2, 2, 6))
        top.pack(fill="x")
        self.top_icons: dict[str, ttk.Label] = {}
        ttk.Label(top, text="Mode:", style="Title.TLabel").pack(side="left")
        self.top_icons["mode"] = info_icon(top, field_docs.top_help("mode"))
        self.top_icons["mode"].pack(side="left", padx=(3, 0))
        self.mode = MODES[0]
        self.mode_var = tk.StringVar(value=self.mode)
        self.mode_selector = ttk.Combobox(top, textvariable=self.mode_var, values=MODES, state="readonly", width=20)
        self.mode_selector.pack(side="left", padx=(6, 12))
        self.mode_selector.bind("<<ComboboxSelected>>", lambda e: self.select_mode(self.mode_var.get()))
        self.type_label = ttk.Label(top, text=ManifestProvider.label, style="Title.TLabel")
        self.type_label.pack(side="left")
        self.top_icons["kind"] = info_icon(top, lambda: field_docs.top_help("kind") + self._kind_blurb())
        self.top_icons["kind"].pack(side="left", padx=(3, 0))
        self.kind_var = tk.StringVar(value=gen.KINDS[0])
        self.selector = ttk.Combobox(top, textvariable=self.kind_var, values=gen.KINDS, state="readonly",
                                     width=22, height=len(gen.KINDS))
        self.selector.pack(side="left", padx=(6, 10))
        self.last_kind = {p.mode: p.kinds[0] for p in PROVIDERS.values()}
        self.selector.bind("<<ComboboxSelected>>", lambda e: self._on_selector(self.kind_var.get()))
        self.api_label = ttk.Label(top, text="", style="Help.TLabel")
        self.api_label.pack(side="left")
        self._build_template_bar(left)
        ttk.Separator(left, orient="horizontal").pack(fill="x")
        self.edited_label = ttk.Label(left, text="", style="Help.TLabel", anchor="w")
        self.edited_label.pack(fill="x", padx=4)
        self.form_area = ttk.Frame(left)
        self.form_area.pack(fill="both", expand=True, pady=(4, 0))
        self.kind = gen.KINDS[0]          # Deployment
        self.cache: dict[str, dict] = {}  # kind -> field values entered so far (in memory only)
        self.collapsed: dict[str, set] = {}  # kind -> titles of collapsed sections
        self.form: KindForm | None = None
        self._build_form(self.kind)
        paned.add(left, weight=3)

        right = ttk.Frame(paned)
        hdr = ttk.Frame(right)
        hdr.pack(fill="x")
        ttk.Checkbutton(hdr, text="Live preview", variable=self.live).pack(side="right")
        self.preview_title = ttk.Label(hdr, text="Preview", style="Title.TLabel")
        self.preview_title.pack(side="left", fill="x", expand=True)
        pv = ttk.Frame(right)
        pv.pack(fill="both", expand=True, pady=(4, 4))
        self.preview = tk.Text(pv, wrap="none", font=self.mono_font, borderwidth=1, relief="solid",
                               background="#1e1e1e", foreground="#d4d4d4", insertbackground="#d4d4d4")
        ys = ttk.Scrollbar(pv, orient="vertical", command=self.preview.yview)
        xs = ttk.Scrollbar(pv, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        pv.rowconfigure(0, weight=1)
        pv.columnconfigure(0, weight=1)
        ttk.Label(right, text="Validation", style="Title.TLabel").pack(anchor="w")
        self.issues = tk.Text(right, height=7, wrap="word", font=self.mono_font, borderwidth=1, relief="solid")
        self.issues.tag_configure("err", foreground="#c62828")
        self.issues.tag_configure("warn", foreground="#b26a00")
        self.issues.tag_configure("ok", foreground="#2e7d32")
        self.issues.pack(fill="x")
        paned.add(right, weight=2)

        bar = ttk.Frame(root, padding=(6, 6))
        bar.pack(fill="x")
        buttons = [
            ("Refresh", self.refresh), ("Validate", self.validate), ("Copy YAML", self.copy),
            ("Save…", self.save), ("Save all edited…", self.save_all_edited),
            ("Add to bundle", self.add_to_bundle), ("Save bundle…", self.save_bundle),
            ("Clear bundle", self.clear_bundle), ("Reset kind", self.reset_kind),
        ]
        self.buttons = {}
        for text, cmd in buttons:
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=2)
            self.buttons[text] = b
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, relief="sunken", anchor="w", padding=(6, 2)).pack(fill="x")

        # Give the form pane a bit more than half the window on first layout
        self.paned = paned
        self._sash_done = False
        paned.bind("<Configure>", self._place_sash, add="+")

        root.bind(f"<{MOD}-s>", lambda e: self.save())
        root.bind(f"<{MOD}-r>", lambda e: self.refresh())
        root.bind("<F5>", lambda e: self.refresh())
        root.bind(f"<{MOD}-k>", lambda e: (self.selector.focus_set(), self.selector.event_generate("<Down>")))
        self.refresh()

    def _kind_blurb(self) -> str:
        k = getattr(self, "kind", "")
        return f"\nNow editing: {k}" if k else ""

    def _tpl_blurb(self) -> str:
        t = self.tpl_var.get() if hasattr(self, "tpl_var") else ""
        try:
            d = tpl.get(t).description.splitlines()[0] if t and t != tpl.NONE_CHOICE else ""
        except (KeyError, IndexError, AttributeError):
            d = ""
        return f"\nSelected: {t} - {d}" if d else ""

    def _place_sash(self, _e=None):
        if self._sash_done:
            return
        total = self.paned.winfo_width()
        if total < 400:
            return
        self.paned.sashpos(0, max(min(int(total * 0.56), total - 420), 480))
        self._sash_done = True

    # ------------------------------------------------------- app templates
    TEMPLATE_HEADER = "── {} ──"

    def _template_values(self) -> list[str]:
        vals = [tpl.NONE_CHOICE]
        for g, ts in tpl.grouped().items():
            vals.append(self.TEMPLATE_HEADER.format(g))
            vals += ts
        return vals

    def _build_template_bar(self, parent):
        """'Template:' dropdown + parameter panel (Manifests mode only)."""
        self.tpl_applied: dict | None = None   # {title, params, secrets, set, values{kind: values}}
        self.tpl_title: str | None = None
        self.tpl_vars: dict[str, tk.Variable] = {}
        self._tpl_after = None
        self._tpl_loading = False
        self.tpl_row = ttk.Frame(parent, padding=(2, 0, 2, 6))
        ttk.Label(self.tpl_row, text="Template:", style="Title.TLabel").pack(side="left")
        self.top_icons["template"] = info_icon(self.tpl_row, lambda: field_docs.top_help("template") + self._tpl_blurb())
        self.top_icons["template"].pack(side="left", padx=(3, 0))
        self.tpl_var = tk.StringVar(value=tpl.NONE_CHOICE)
        vals = self._template_values()
        self.tpl_selector = ttk.Combobox(self.tpl_row, textvariable=self.tpl_var, values=vals, state="readonly",
                                         width=22, height=min(len(vals), 36))
        self.tpl_selector.pack(side="left", padx=(6, 10))
        self.tpl_selector.bind("<<ComboboxSelected>>", lambda e: self._on_template_selector(self.tpl_var.get()))
        self.tpl_desc = ttk.Label(self.tpl_row, text="apply a ready-made app (Postgres, nginx, ...) as a set "
                                                     "of related kinds", style="Help.TLabel")
        self.tpl_desc.pack(side="left", fill="x", expand=True)
        self.tpl_row.pack(fill="x")
        self.tpl_panel = ttk.LabelFrame(parent, text="Template parameters", padding=(6, 2, 6, 4))
        self.tpl_fields = ttk.Frame(self.tpl_panel)
        self.tpl_fields.pack(fill="x")
        btns = ttk.Frame(self.tpl_panel)
        btns.pack(fill="x", pady=(4, 0))
        self.tpl_buttons = {}
        for text, cmd in (("Apply / re-render", lambda: self.apply_template()),
                          ("Save template set…", lambda: self.save_template_set())):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            self.tpl_buttons[text] = b
        self.tpl_summary = ttk.Label(btns, text="", style="Help.TLabel", anchor="w", wraplength=520,
                                     justify="left")
        self.tpl_summary.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._tpl_parent = parent

    def _show_template_bar(self, show: bool):
        if show:
            if not self.tpl_row.winfo_manager():
                self.tpl_row.pack(fill="x", before=self._sep_after_templates())
            if self.tpl_title and not self.tpl_panel.winfo_manager():
                self.tpl_panel.pack(fill="x", padx=2, pady=(0, 6), after=self.tpl_row)
        else:
            self.tpl_row.pack_forget()
            self.tpl_panel.pack_forget()

    def _sep_after_templates(self):
        kids = self._tpl_parent.pack_slaves()
        return next((w for w in kids if isinstance(w, ttk.Separator)), kids[-1])

    def _on_template_selector(self, value: str):
        for g, ts in tpl.grouped().items():
            if value == self.TEMPLATE_HEADER.format(g):
                value = ts[0]
                self.tpl_var.set(value)
                break
        self.select_template(value)

    def select_template(self, title: str, apply: bool = True):
        """Pick a template in the dropdown: build its parameter panel and (by default) apply it."""
        if title == tpl.NONE_CHOICE or not title:
            self.tpl_title = None
            self.tpl_applied = None
            self.tpl_var.set(tpl.NONE_CHOICE)
            self.tpl_panel.pack_forget()
            self.tpl_desc.configure(text="no template - forms keep their values (use Reset kind to clear)")
            self.refresh()
            return None
        t = tpl.get(title)
        self.tpl_title = title
        self.tpl_var.set(title)
        self.tpl_desc.configure(text=f"{t.image}")
        params = (self.tpl_applied["params"] if self.tpl_applied and self.tpl_applied["title"] == title
                  else tpl.default_params(title))
        self._build_template_params(title, params)
        self._show_template_bar(True)
        if apply:
            return self.apply_template()
        return None

    def _build_template_params(self, title: str, params: dict):
        for w in self.tpl_fields.winfo_children():
            w.destroy()
        self.tpl_vars = {}
        self.tpl_icons: dict[str, ttk.Label] = {}
        self._tpl_loading = True
        cols = 2
        for i, prm in enumerate(tpl.params_for(title)):
            r, c = divmod(i, cols)
            box, self.tpl_icons[prm.key] = labelled(self.tpl_fields, prm.label + ":", field_docs.tooltip(prm))
            box.grid(row=r, column=2 * c, sticky="w", padx=(0, 4), pady=1)
            val = params.get(prm.key, prm.default)
            if prm.type == "check":
                var = tk.BooleanVar(value=bool(val))
                w = ttk.Checkbutton(self.tpl_fields, variable=var)
            else:
                var = tk.StringVar(value=str(val))
                if prm.type in ("combo", "ecombo"):
                    w = ttk.Combobox(self.tpl_fields, textvariable=var, values=prm.options, width=16,
                                     state="readonly" if prm.type == "combo" else "normal")
                else:
                    w = ttk.Entry(self.tpl_fields, textvariable=var, width=18)
            w.grid(row=r, column=2 * c + 1, sticky="w", padx=(0, 12), pady=1)
            var.trace_add("write", lambda *_: self._template_param_changed())
            self.tpl_vars[prm.key] = var
        self._tpl_loading = False
        self._update_host_state()

    def _update_host_state(self):
        if "ingress" not in self.tpl_vars:
            return
        on = bool(self.tpl_vars["ingress"].get())
        for w in self.tpl_fields.grid_slaves():
            name = str(w.cget("textvariable")) if "textvariable" in w.keys() else ""
            for key in ("host", "ingress_class"):
                if key in self.tpl_vars and name == str(self.tpl_vars[key]):
                    w.state(["!disabled"] if on else ["disabled"])

    def template_params(self) -> dict:
        return {k: v.get() for k, v in self.tpl_vars.items()}

    def _template_param_changed(self):
        if self._tpl_loading:
            return
        self._update_host_state()
        if self._tpl_after:
            self.root.after_cancel(self._tpl_after)
        self._tpl_after = self.root.after(600, lambda: self.apply_template(auto=True))

    def _template_conflicts(self, tset) -> list[str]:
        """Kinds whose current values were edited by hand and would be overwritten by *tset*."""
        return template_conflicts(tset, self.values_for, (self.tpl_applied or {}).get("values", {}))

    def apply_template(self, title: str | None = None, params: dict | None = None, auto: bool = False):
        """Render the selected template and load its objects into the per-kind forms.

        Returns the TemplateSet, or None when cancelled / invalid. *auto* = triggered by a parameter
        change: never asks, and skips the re-render if it would overwrite hand edits."""
        self._tpl_after = None
        title = title or self.tpl_title
        if not title:
            return None
        if title != self.tpl_title:
            return self.select_template(title)
        params = params if params is not None else self.template_params()
        same = self.tpl_applied and self.tpl_applied["title"] == title
        tset = tpl.render(title, params, secrets=self.tpl_applied["secrets"] if same else None)
        if tset.errors:
            self.tpl_summary.configure(text="✖ " + tset.errors[0])
            if not auto:
                messagebox.showerror("Template", f"{title} has {len(tset.errors)} problem(s):\n\n• " +
                                     "\n• ".join(tset.errors[:10]), parent=self.root)
            return None
        conflicts = self._template_conflicts(tset)
        if conflicts:
            if auto:
                self.tpl_summary.configure(text="⚠ forms were edited by hand: " + ", ".join(conflicts) +
                                           " - click 'Apply / re-render' to overwrite them")
                return None
            if not messagebox.askyesno(
                    "Overwrite edited forms?",
                    f"Applying the {title} template replaces the values you entered for:\n\n• " +
                    "\n• ".join(conflicts) + "\n\nOverwrite them?", parent=self.root):
                self.status.set(f"{title} template not applied (kept your edits).")
                return None
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        pv = tset.primary_values()
        keep = self.kind if (auto and self.kind in pv) else None
        if self.form is not None:
            if self.kind not in pv:
                self.cache[self.kind] = self.form.values()
            self.form.destroy()
            self.form = None
        # kinds the previous template filled but this one doesn't: reset them if untouched since
        prev = (self.tpl_applied or {}).get("values", {})
        stale = template_stale(tset, lambda k: {**gen.defaults(k), **self.cache.get(k, {})}, prev)
        for kind in stale:
            self.cache.pop(kind, None)
        for kind, values in pv.items():
            self.cache[kind] = copy.deepcopy(values)
        self.tpl_applied = {"title": title, "params": dict(tset.params), "secrets": dict(tset.secrets),
                            "set": tset, "values": copy.deepcopy(pv)}
        self.select_kind(keep or tset.primary_kind)
        counts: dict[str, int] = {}
        for r in tset.items:
            counts[r.item.kind] = counts.get(r.item.kind, 0) + 1
        parts = [k if n == 1 else f"{k}×{n}" for k, n in counts.items()]
        self.tpl_summary.configure(text=template_summary(tset))
        self.status.set(f"Applied {title} template '{tset.name}': {len(tset.items)} objects "
                        f"({', '.join(parts)}).")
        return tset

    def template_set_files(self) -> list[tuple[str, dict]]:
        """(filename, manifest) for the applied set, with the forms' current values for primary items."""
        if not self.tpl_applied:
            return []
        out, errs = [], []
        for r in self.tpl_applied["set"].items:
            res = gen.generate(r.item.kind, self.values_for(r.item.kind)) if r.primary else r.result
            if not res.ok:
                errs.append(f"{r.item.kind}/{r.values.get('name')}: {res.errors[0]}")
                continue
            out.append((gen.filename_for(res.manifest), res.manifest))
        if errs:
            raise ValueError("\n• ".join(errs))
        return out

    def save_template_set(self, directory: str | None = None) -> list[str]:
        """Write every object of the applied set + all-in-one.yaml into <directory>/<app name>/."""
        if not self.tpl_applied:
            messagebox.showinfo("Save template set", "Pick a template first (Template: dropdown).",
                                parent=self.root)
            return []
        try:
            files = template_set_plan(self.tpl_applied["set"], self.values_for)
        except ValueError as exc:
            messagebox.showerror("Save template set", f"Fix these first:\n\n• {exc}", parent=self.root)
            return []
        directory = directory or self._ask_dir()
        if not directory:
            return []
        target = os.path.join(directory, self.tpl_applied["set"].name)
        paths = [os.path.join(directory, n) for n, _, _ in files]
        existing = [q for q in paths if os.path.exists(q)]
        if existing and not messagebox.askyesno(
                "Overwrite?", f"{len(existing)} file(s) already exist in {target}:\n• " +
                "\n• ".join(os.path.basename(q) for q in existing) + "\n\nOverwrite?", parent=self.root):
            return []
        try:
            os.makedirs(target, exist_ok=True)
            for (_name, text, mode), path in zip(files, paths):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                if mode is not None:
                    os.chmod(path, mode)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return []
        self.last_saved = paths
        self.status.set(f"Saved {len(files) - 1} manifests + all-in-one.yaml to {target}")
        messagebox.showinfo("Save template set", f"Saved to {target}:\n• " +
                            "\n• ".join(os.path.basename(q) for q in paths) +
                            "\n\nApply with:  kubectl apply -f " + os.path.join(target, "all-in-one.yaml"),
                            parent=self.root)
        return paths

    # ----------------------------------------------------------------- style
    def _style(self):
        style = ttk.Style(self.root)
        if not IS_MAC and "clam" in style.theme_names():
            style.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        self.mono_font = tkfont.Font(family="Menlo" if IS_MAC else "DejaVu Sans Mono",
                                     size=12 if IS_MAC else 10)
        help_font = base.copy()
        help_font.configure(size=max(base.cget("size") - 1, 8) if base.cget("size") > 0 else base.cget("size"))
        style.configure("Help.TLabel", foreground="#666666", font=help_font)
        title_font = base.copy()
        title_font.configure(weight="bold")
        style.configure("Title.TLabel", font=title_font)
        style.configure("Section.TLabel", font=title_font, foreground="#1a4f8b")
        style.configure("Info.TLabel", foreground="#1f6fd1")

    # ----------------------------------------------------------------- core
    # ---------------------------------------------------- kind selection
    @property
    def current_kind(self) -> str:
        return self.kind

    @property
    def provider(self):
        return provider_for(self.kind)

    def collapsed_for(self, kind: str) -> set:
        return self.collapsed.setdefault(
            kind, {t for t, _ in provider_for(kind).schema(kind)
                   if t in COLLAPSED_BY_DEFAULT or t in provider_for(kind).collapsed(kind)})

    def section_toggled(self, title: str, collapsed: bool):
        st = self.collapsed_for(self.kind)
        (st.add if collapsed else st.discard)(title)

    def _build_form(self, kind: str):
        self.form = KindForm(self, self.form_area, kind, self.cache.get(kind))
        self.form.scroll.pack(fill="both", expand=True)
        self._apply_dynamic_options()
        self.api_label.configure(text=provider_for(kind).info(kind))

    def _on_selector(self, value: str):
        """Selector callback: a group header ('── Local ──') jumps to that group's first type."""
        p = self.provider
        for g, ts in p.group_of.items():
            if value == GROUP_HEADER.format(g):
                value = ts[0]
                break
        self.select_kind(value)

    def select_kind(self, kind: str):
        """Cache the current form's values, destroy it, and build the form for *kind*."""
        if kind not in MODE_OF:
            raise ValueError(f"unknown kind {kind!r}")
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self.form is not None and kind != self.kind:
            self.cache[self.kind] = self.form.values()
            self.form.destroy()
            self.form = None
        if self.form is None:
            self.kind = kind
            self._build_form(kind)
        p = provider_for(kind)
        self.mode = p.mode
        self.last_kind[p.mode] = kind
        self.mode_var.set(p.mode)
        self.type_label.configure(text=p.label)
        if list(self.selector.cget("values")) != list(p.selector_values):
            self.selector.configure(values=p.selector_values, height=min(len(p.selector_values), 20))
        self.buttons["Reset kind"].configure(text="Reset kind" if p.bundle else "Reset type")
        self.buttons["Copy YAML"].configure(text="Copy YAML" if p.bundle else "Copy")
        for b in ("Add to bundle", "Save bundle…", "Clear bundle"):
            self.buttons[b].state(["!disabled"] if p.bundle else ["disabled"])
        self._show_template_bar(p.bundle)
        self.kind_var.set(kind)
        self.root.update_idletasks()
        self.refresh()

    def select_mode(self, mode: str):
        """Switch between 'Manifests', 'Cluster config' and 'Networking & Storage' (returns to the last type
        used in that mode)."""
        if mode not in PROVIDERS:
            raise ValueError(f"unknown mode {mode!r}")
        self.select_kind(self.last_kind[mode])

    def values_for(self, kind: str) -> dict:
        if kind == self.kind and self.form is not None:
            return self.form.values()
        return {**provider_for(kind).defaults(kind), **self.cache.get(kind, {})}

    @staticmethod
    def _norm(d: dict) -> dict:
        return providers.norm(d)

    def edited_kinds(self, mode: str | None = None) -> list[str]:
        """Kinds/types of *mode* (default: current) whose values differ from the defaults."""
        p = PROVIDERS[mode or self.mode]
        return [k for k in p.kinds if self._norm(self.values_for(k)) != self._norm(p.defaults(k))]

    def session(self) -> dict:
        """kind -> values of every form opened in this session (cross-checks, StorageClass dropdowns)."""
        out = dict(self.cache)
        if self.form is not None:
            out[self.kind] = self.form.values()
        return out

    def generate(self, kind: str | None = None):
        kind = kind or self.kind
        return providers.generate_in_session(kind, self.values_for(kind), self.session())

    def _apply_dynamic_options(self):
        """Extend dropdowns with session values (StorageClass names created in this session for PVCs...)."""
        if self.form is None:
            return
        for key, opts in providers.dynamic_options(self.kind, self.session()).items():
            w = self.form.widgets.get(key)
            if w is not None and isinstance(w, ttk.Combobox):
                w.configure(values=opts)

    def render(self, res, kind: str | None = None) -> str:
        return provider_for(kind or self.kind).render(res)

    def schedule_refresh(self):
        if not self.live.get():
            return
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(300, self.refresh)

    def _show_issues(self, res: gen.Result, verbose_ok: bool = False):
        self.issues.configure(state="normal")
        self.issues.delete("1.0", "end")
        for e in res.errors:
            self.issues.insert("end", f"✖ {e}\n", "err")
        for w in res.warnings:
            self.issues.insert("end", f"⚠ {w}\n", "warn")
        if res.ok:
            ready = "ready to save / kubectl apply" if self.provider.bundle else "ready to save"
            self.issues.insert("end", f"✔ Valid - {ready}.\n" if verbose_ok or not res.warnings
                               else "✔ No errors.\n", "ok")
        self.issues.configure(state="disabled")

    def refresh(self) -> str:
        self._after_id = None
        res = self.generate()
        text = ""
        if res.manifest is not None:
            try:
                text = self.render(res)
            except Exception as exc:
                res.errors.append(f"YAML rendering failed: {exc}")
        if res.errors:
            text = "# ⚠ Fix the errors below before saving\n" + text
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")
        self._show_issues(res)
        p = self.provider
        names = [n for n, _, _ in p.files(res)] if res.manifest else []
        bundle = (f"   (bundle: {len(self.bundle)} doc{'s' if len(self.bundle) != 1 else ''})" if p.bundle
                  else f"   -> {' + '.join(names)}" if names else "")
        self.preview_title.configure(text=f"Preview - {self.current_kind}{bundle}")
        self.api_label.configure(text=p.info(self.kind, res))
        self.status.set(f"{self.current_kind}: {len(res.errors)} error(s), {len(res.warnings)} warning(s)")
        edited = self.edited_kinds()
        what = "kinds" if p.bundle else ("add-on types" if p is providers.AddonProvider else "config types")
        label = (f"edited {what}: " + ", ".join(edited)) if edited else f"no {what} edited yet"
        if p.bundle and self.tpl_applied:
            label += f"   ·   template: {self.tpl_applied['title']} ({self.tpl_applied['set'].name})"
        self.edited_label.configure(text=label)
        return text

    def _valid_or_warn(self) -> gen.Result | None:
        res = self.generate()
        self._show_issues(res, verbose_ok=True)
        if not res.ok:
            messagebox.showerror("Validation failed",
                                 f"{self.current_kind} has {len(res.errors)} error(s):\n\n• " +
                                 "\n• ".join(res.errors[:12]), parent=self.root)
            return None
        return res

    def validate(self):
        res = self.generate()
        self._show_issues(res, verbose_ok=True)
        if res.ok:
            msg = "Manifest is valid." if self.provider.bundle else f"{self.kind} config is valid."
            if res.warnings:
                msg += "\n\nWarnings:\n• " + "\n• ".join(res.warnings)
            messagebox.showinfo("Validate", msg, parent=self.root)
        else:
            messagebox.showerror("Validate", "Please fix:\n\n• " + "\n• ".join(res.errors[:15]), parent=self.root)
        return res

    def copy(self):
        res = self._valid_or_warn()
        if not res:
            return
        text = self.render(res)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.status.set(f"Copied {len(text.splitlines())} lines to the clipboard.")

    def _ask_dir(self) -> str | None:
        d = filedialog.askdirectory(parent=self.root, initialdir=self.last_dir, title="Choose output folder",
                                    mustexist=True)
        if not d:
            return None
        self.last_dir = d
        return d

    def _write(self, path: str, text: str, confirm=True) -> bool:
        if confirm and os.path.exists(path) and not messagebox.askyesno(
                "Overwrite?", f"{path} already exists. Overwrite it?", parent=self.root):
            return False
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return True

    def _write_files(self, directory: str, kind: str, res, confirm=True) -> list[str] | None:
        """Write every output file of *res* (sub-folders created; scripts 0755, secrets 0600)."""
        return self._write_plan(directory, output_files(kind, res), confirm)

    def _write_plan(self, directory: str, files, confirm=True) -> list[str] | None:
        paths = [os.path.join(directory, n) for n, _, _ in files]
        existing = [q for q in paths if os.path.exists(q)]
        if confirm and existing and not messagebox.askyesno(
                "Overwrite?", "Already exists:\n• " + "\n• ".join(existing) + "\n\nOverwrite?", parent=self.root):
            return None
        for (_name, text, mode), path in zip(files, paths):
            os.makedirs(os.path.dirname(path) or directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            if mode is not None:
                os.chmod(path, mode)
        return paths

    def save(self, directory: str | None = None) -> str | None:
        """Save the current type; returns the first path (all paths in self.last_saved)."""
        res = self._valid_or_warn()
        if not res:
            return None
        directory = directory or self._ask_dir()
        if not directory:
            return None
        try:
            paths = self._write_files(directory, self.kind, res)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return None
        if not paths:
            return None
        self.last_saved = paths
        self.status.set(f"Saved {paths[0]}" if len(paths) == 1 else
                        f"Saved {len(paths)} files to {directory}: " + ", ".join(os.path.relpath(q, directory)
                                                                             for q in paths))
        return paths[0]

    def save_all_edited(self, directory: str | None = None):
        """Save every kind/type whose form differs from the defaults (+ all-in-one.yaml for manifests).

        Cluster config types each get their own sub-folder when they produce several files."""
        kinds = self.edited_kinds()
        if not kinds:
            messagebox.showinfo("Save all edited",
                                "No kinds have been edited yet - use Save… for the current kind, "
                                "or the bundle for a hand-picked multi-doc file.", parent=self.root)
            return []
        results = {k: self.generate(k) for k in kinds}
        directory = directory or self._ask_dir()
        if not directory:
            return []
        files, bad = save_all_plan(self.mode, results)
        paths = self._write_plan(directory, files, confirm=False)
        saved = [os.path.relpath(q, directory) for q in paths]
        n_all = 1 if self.provider.bundle and saved and saved[-1] == "all-in-one.yaml" else 0
        extra = " + all-in-one.yaml" if n_all else ""
        msg = f"Saved {len(saved) - n_all} file(s){extra} to {directory}:\n• " + "\n• ".join(saved[:len(saved) - n_all])
        if bad:
            msg += "\n\nSkipped (fix errors first):\n• " + "\n• ".join(bad)
        self.status.set(f"Saved {len(saved) - n_all} file(s) for {len(results) - len(bad)} edited type(s) to {directory}")
        messagebox.showinfo("Save all edited", msg, parent=self.root)
        return saved[:len(saved) - n_all]

    def add_to_bundle(self):
        if not self.provider.bundle:
            messagebox.showinfo("Bundle", "Bundles combine Kubernetes manifests; cluster config files are "
                                "saved individually.", parent=self.root)
            return
        res = self._valid_or_warn()
        if not res:
            return
        self.bundle.append(res.manifest)
        self.refresh()
        self.status.set(f"Added {res.manifest['kind']}/{res.manifest['metadata']['name']} "
                        f"to bundle ({len(self.bundle)} docs).")

    def save_bundle(self):
        if not self.bundle:
            messagebox.showinfo("Bundle", "The bundle is empty - use 'Add to bundle' first.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=self.last_dir,
                                            initialfile="bundle.yaml", defaultextension=".yaml",
                                            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*")])
        if not path:
            return
        self.last_dir = os.path.dirname(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(gen.to_multi_yaml(self.bundle))
        self.status.set(f"Saved {len(self.bundle)}-document bundle to {path}")

    def clear_bundle(self):
        self.bundle.clear()
        self.refresh()

    def reset_kind(self):
        """Discard the current kind's entered values and rebuild its form from defaults."""
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.cache.pop(self.kind, None)
        if self.form is not None:
            self.form.destroy()
            self.form = None
        self._build_form(self.kind)
        self.refresh()
        self.status.set(f"{self.kind} reset to defaults.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

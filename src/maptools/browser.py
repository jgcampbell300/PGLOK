from pathlib import Path
import base64
import io
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image

from src.config.ui_theme import UI_COLORS
from src.maptools.wiki_sync import update_marked_maps


class MapToolsBrowser(ttk.Frame):
    def __init__(self, parent, maps_dir: Path, status_callback=None, selected_map="", on_map_change=None):
        super().__init__(parent, style="App.Panel.TFrame")
        self.maps_dir = Path(maps_dir)
        self.status_callback = status_callback
        self.selected_map_var = tk.StringVar(value=str(selected_map or ""))
        self.on_map_change = on_map_change
        self.map_combo = None
        self.canvas = None
        self.update_button = None
        self._image_id = None
        self._image_obj = None
        self._source_image = None
        self._zoom_factor = 1.0
        self._fit_mode = True
        self._rendered_size = (0, 0)
        self._render_after_id = None
        self._wheel_render_after_id = None
        self._pending_anchor = None
        self._pending_old_zoom = None
        self._image_cache = {}
        self._pan_active = False
        self.zoom_var = tk.StringVar(value="100%")
        self._map_files = {}
        self._build()
        self.refresh_maps()

    def _build(self):
        top = ttk.Frame(self, style="App.Card.TFrame", padding=10)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Map File:", style="App.TLabel").pack(side="left")
        self.map_combo = ttk.Combobox(
            top,
            textvariable=self.selected_map_var,
            state="readonly",
            width=52,
            style="App.TCombobox",
        )
        self.map_combo.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.map_combo.bind("<<ComboboxSelected>>", self._on_map_selected)
        ttk.Button(top, text="Refresh", command=self.refresh_maps, style="App.Secondary.TButton").pack(side="right")
        self.update_button = ttk.Button(
            top,
            text="Update Wiki Maps",
            command=self._update_wiki_maps_async,
            style="App.Primary.TButton",
        )
        self.update_button.pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Fit", command=self._fit_to_window, style="App.Secondary.TButton").pack(side="right", padx=(6, 0))
        ttk.Button(top, text="+", command=lambda: self._change_zoom(1.25), style="App.Secondary.TButton", width=3).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(top, text="-", command=lambda: self._change_zoom(0.8), style="App.Secondary.TButton", width=3).pack(
            side="right", padx=(6, 0)
        )
        ttk.Label(top, textvariable=self.zoom_var, style="App.Status.TLabel").pack(side="right", padx=(8, 2))

        display_wrap = ttk.Frame(self, style="App.Card.TFrame", padding=8)
        display_wrap.pack(fill="both", expand=True)

        y_scroll = ttk.Scrollbar(display_wrap, orient="vertical", style="App.Vertical.TScrollbar")
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(display_wrap, orient="horizontal", style="App.Horizontal.TScrollbar")
        x_scroll.pack(side="bottom", fill="x")

        self.canvas = tk.Canvas(
            display_wrap,
            bg=UI_COLORS["entry_bg"],
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            relief="solid",
            bd=0,
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        y_scroll.configure(command=self.canvas.yview)
        x_scroll.configure(command=self.canvas.xview)
        self._image_id = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._change_zoom(1.1, anchor=(e.x, e.y)))
        self.canvas.bind("<Button-5>", lambda e: self._change_zoom(0.9, anchor=(e.x, e.y)))
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_pan_end)

    def _set_status(self, message: str):
        if self.status_callback is not None:
            self.status_callback(message)

    def refresh_maps(self):
        if not self.maps_dir.exists():
            self._map_files = {}
            self.map_combo["values"] = []
            self.selected_map_var.set("")
            self._clear_canvas()
            self._set_status(f"Map directory not found: {self.maps_dir}")
            return

        files = []
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            files.extend(self.maps_dir.glob(pattern))
        files = [p for p in files if "old" not in p.name.lower()]
        files = sorted({p.resolve() for p in files}, key=lambda p: p.name.lower())
        self._map_files = {path.name: path for path in files}
        self.map_combo["values"] = list(self._map_files.keys())

        if not files:
            self.selected_map_var.set("")
            self._clear_canvas()
            self._set_status("No map images found in src/data/maps.")
            return

        selected = self.selected_map_var.get().strip()
        if selected not in self._map_files:
            self.selected_map_var.set(files[0].name)
        self._show_selected_map()

    def _on_map_selected(self, _event=None):
        if self.on_map_change is not None:
            try:
                self.on_map_change(self.selected_map_var.get().strip())
            except Exception:
                pass
        self._show_selected_map()

    def _show_selected_map(self):
        name = self.selected_map_var.get().strip()
        path = self._map_files.get(name)
        if path is None:
            self._clear_canvas()
            return
        try:
            self._source_image = Image.open(path)
            self._fit_mode = True
            self._render_current_image()
            self._set_status(f"Loaded map: {name}")
        except Exception as exc:
            self._clear_canvas()
            self._set_status(f"Error loading map '{name}': {exc}")

    def _on_canvas_resize(self, _event=None):
        if self._fit_mode:
            self._schedule_render()

    def _on_mousewheel(self, event):
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return
        steps = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        factor = 1.1 ** steps
        self._change_zoom(factor, anchor=(event.x, event.y), defer_for_wheel=True)

    def _fit_to_window(self):
        self._fit_mode = True
        self._schedule_render()

    def _on_pan_start(self, event):
        if self.canvas is None or self._image_obj is None:
            return
        self._pan_active = True
        self.canvas.configure(cursor="fleur")
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_drag(self, event):
        if self.canvas is None or not self._pan_active:
            return
        # Canvas scan drag provides smoother and faster panning than scrollbar stepping.
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_pan_end(self, _event=None):
        if self.canvas is None:
            return
        self._pan_active = False
        self.canvas.configure(cursor="")

    def _change_zoom(self, factor, anchor=None, defer_for_wheel=False):
        if self._source_image is None:
            return
        old_zoom = self._zoom_factor
        self._fit_mode = False
        self._zoom_factor = max(0.1, min(8.0, self._zoom_factor * float(factor)))
        if defer_for_wheel:
            # Wheel events can arrive in bursts; render once after motion settles.
            self._pending_old_zoom = old_zoom if self._pending_old_zoom is None else self._pending_old_zoom
            self._pending_anchor = anchor
            self._schedule_wheel_render()
        else:
            self._pending_old_zoom = old_zoom
            self._pending_anchor = anchor
            self._schedule_render()

    def _schedule_wheel_render(self):
        if self.canvas is None:
            return
        if self._wheel_render_after_id is not None:
            try:
                self.after_cancel(self._wheel_render_after_id)
            except tk.TclError:
                pass
        self._wheel_render_after_id = self.after(55, self._run_wheel_render)

    def _run_wheel_render(self):
        self._wheel_render_after_id = None
        self._run_scheduled_render()

    def _schedule_render(self):
        if self.canvas is None:
            return
        if self._render_after_id is not None:
            try:
                self.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
        self._render_after_id = self.after(25, self._run_scheduled_render)

    def _run_scheduled_render(self):
        self._render_after_id = None
        old_zoom = self._pending_old_zoom
        anchor = self._pending_anchor
        self._pending_old_zoom = None
        self._pending_anchor = None
        self._render_current_image()
        if old_zoom is not None:
            self._recenter_view_after_zoom(old_zoom, self._zoom_factor, anchor)

    def _recenter_view_after_zoom(self, old_zoom, new_zoom, anchor):
        if self.canvas is None:
            return
        if anchor is None:
            return
        x, y = anchor
        canvas_w = max(1, int(self.canvas.winfo_width()))
        canvas_h = max(1, int(self.canvas.winfo_height()))
        rendered_w, rendered_h = self._rendered_size
        if rendered_w <= 0 or rendered_h <= 0 or old_zoom <= 0 or new_zoom <= 0:
            return

        logical_x = self.canvas.canvasx(x) / old_zoom
        logical_y = self.canvas.canvasy(y) / old_zoom
        new_canvas_x = logical_x * new_zoom
        new_canvas_y = logical_y * new_zoom
        left = new_canvas_x - x
        top = new_canvas_y - y

        x_denom = max(1, rendered_w - canvas_w)
        y_denom = max(1, rendered_h - canvas_h)
        self.canvas.xview_moveto(max(0.0, min(1.0, left / x_denom)))
        self.canvas.yview_moveto(max(0.0, min(1.0, top / y_denom)))

    def _render_current_image(self):
        if self._source_image is None or self.canvas is None:
            return
        src_w, src_h = self._source_image.size
        if src_w <= 0 or src_h <= 0:
            return

        canvas_w = max(1, int(self.canvas.winfo_width()))
        canvas_h = max(1, int(self.canvas.winfo_height()))
        if self._fit_mode:
            scale_w = canvas_w / float(src_w)
            scale_h = canvas_h / float(src_h)
            self._zoom_factor = max(0.05, min(8.0, min(scale_w, scale_h)))

        target_w = max(1, int(round(src_w * self._zoom_factor)))
        target_h = max(1, int(round(src_h * self._zoom_factor)))

        cache_key = (target_w, target_h)
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            self._image_obj = cached
        else:
            # Faster than LANCZOS during wheel zoom while still preserving readability.
            resample = Image.Resampling.BILINEAR if self._zoom_factor <= 2.0 else Image.Resampling.NEAREST
            resized = self._source_image.resize((target_w, target_h), resample)
            try:
                ppm_buffer = io.BytesIO()
                resized.save(ppm_buffer, format="PPM")
                self._image_obj = tk.PhotoImage(
                    data=base64.b64encode(ppm_buffer.getvalue()).decode("ascii"),
                    format="PPM",
                )
            except tk.TclError:
                # Fallback for images Tk fails to decode in PPM path.
                png_buffer = io.BytesIO()
                resized.save(png_buffer, format="PNG")
                self._image_obj = tk.PhotoImage(data=base64.b64encode(png_buffer.getvalue()).decode("ascii"))
            self._image_cache[cache_key] = self._image_obj
            if len(self._image_cache) > 8:
                # Keep cache small to avoid memory growth.
                oldest = next(iter(self._image_cache))
                self._image_cache.pop(oldest, None)

        self.canvas.itemconfigure(self._image_id, image=self._image_obj)
        self.canvas.coords(self._image_id, 0, 0)
        self.canvas.configure(scrollregion=(0, 0, target_w, target_h))
        self._rendered_size = (target_w, target_h)
        self.zoom_var.set(f"{int(round(self._zoom_factor * 100))}%")

    def _clear_canvas(self):
        if self._render_after_id is not None:
            try:
                self.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
            self._render_after_id = None
        if self._wheel_render_after_id is not None:
            try:
                self.after_cancel(self._wheel_render_after_id)
            except tk.TclError:
                pass
            self._wheel_render_after_id = None
        self._image_obj = None
        self._source_image = None
        self._zoom_factor = 1.0
        self._fit_mode = True
        self._rendered_size = (0, 0)
        self._pending_anchor = None
        self._pending_old_zoom = None
        self._image_cache = {}
        self.zoom_var.set("100%")
        if self.canvas is not None and self._image_id is not None:
            self.canvas.itemconfigure(self._image_id, image="")
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            self.canvas.configure(cursor="")

    def _update_wiki_maps_async(self):
        if self.update_button is not None:
            self.update_button.configure(state="disabled")
        self._set_status("Downloading wiki marked maps...")

        def worker():
            try:
                result = update_marked_maps(self.maps_dir)

                def done():
                    self.refresh_maps()
                    self._set_status(
                        f"Wiki maps updated ({result.get('source', 'unknown')}). Found: {result['found']}  Downloaded: {result['downloaded']}  "
                        f"Skipped: {result['skipped']}  Failed: {result['failed']}"
                    )
                    if self.update_button is not None:
                        self.update_button.configure(state="normal")

                self.after(0, done)
            except Exception as exc:
                def fail():
                    self._set_status(f"Wiki map update failed: {exc}")
                    if self.update_button is not None:
                        self.update_button.configure(state="normal")

                self.after(0, fail)

        threading.Thread(target=worker, daemon=True).start()

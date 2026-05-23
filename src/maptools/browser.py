from pathlib import Path
import base64
import io
import json
import threading
import tkinter as tk
from tkinter import ttk, simpledialog

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

        # Marker state: canvas item id -> marker metadata (logical coords in image space)
        self._markers = {}  # item_id -> {"x": float, "y": float}
        self._drag_data = None  # {'item': id, 'start_x': float, 'start_y': float}

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
        # Marker controls
        self.add_marker_button = ttk.Button(top, text="Add Marker", command=self._add_marker_at_view_center, style="App.Secondary.TButton")
        self.add_marker_button.pack(side="right", padx=(6, 0))
        self.clear_markers_button = ttk.Button(top, text="Clear Markers", command=self._clear_markers, style="App.Secondary.TButton")
        self.clear_markers_button.pack(side="right", padx=(6, 0))

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
        # double-click to place marker
        self.canvas.bind("<Double-1>", self._on_canvas_double_click)
        # shift+drag to create marker by dragging
        self.canvas.bind("<Shift-ButtonPress-1>", self._on_canvas_shift_press)
        self.canvas.bind("<Shift-B1-Motion>", self._on_canvas_shift_motion)
        self.canvas.bind("<Shift-ButtonRelease-1>", self._on_canvas_shift_release)
        # marker editor panel on the right
        try:
            self._build_marker_panel(display_wrap)
        except Exception:
            pass

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
            # load saved markers for this map (if any)
            try:
                self._load_markers()
                # ensure marker positions match current zoom
                self._refresh_marker_positions()
            except Exception:
                pass
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
        # reposition any markers after the image changes
        try:
            self._refresh_marker_positions()
        except Exception:
            pass

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
        # Clear markers
        try:
            for item in list(self._markers.keys()):
                try:
                    self.canvas.delete(item)
                except Exception:
                    pass
            self._markers = {}
        except Exception:
            pass

        if self.canvas is not None and self._image_id is not None:
            self.canvas.itemconfigure(self._image_id, image="")
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            self.canvas.configure(cursor="")

    # --- Marker management -------------------------------------------------
    def _icon_path_for_map(self, map_name: str) -> Path:
        icons = self.maps_dir / "icons"
        return icons / (Path(map_name).stem + ".png")

    def _overlay_path_for_map(self, map_name: str) -> Path:
        overlays = self.maps_dir / "overlays"
        return overlays / (Path(map_name).stem + ".json")

    def _ensure_icon_for_map(self, map_name: str):
        # copy from /tmp/pg_maps_icons if present, otherwise do nothing
        dst = self._icon_path_for_map(map_name)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path('/tmp/pg_maps_icons') / (Path(map_name).stem + '.png')
            if tmp.exists() and not dst.exists():
                try:
                    dst.write_bytes(tmp.read_bytes())
                except Exception:
                    pass
        except Exception:
            pass

    def _load_markers(self):
        # remove existing visuals
        if self.canvas is None:
            return
        for item in list(self._markers.keys()):
            try:
                # delete both marker and possible label
                meta = self._markers.get(item, {})
                lbl = meta.get('label_item')
                if lbl:
                    try:
                        self.canvas.delete(lbl)
                    except Exception:
                        pass
                self.canvas.delete(item)
            except Exception:
                pass
        self._markers = {}

        name = self.selected_map_var.get().strip()
        if not name:
            return
        path = self._overlay_path_for_map(name)
        # ensure icon exists in project folder if available
        try:
            self._ensure_icon_for_map(name)
        except Exception:
            pass

        if not path.exists():
            # refresh panel to empty
            try:
                self._refresh_marker_panel()
            except Exception:
                pass
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            for m in data.get('markers', []):
                x = float(m.get('x', 0.0))
                y = float(m.get('y', 0.0))
                label = m.get('label')
                note = m.get('note')
                self._create_marker_visual(x, y, label=label, note=note)
            # update panel listing
            try:
                self._refresh_marker_panel()
            except Exception:
                pass
        except Exception:
            pass

    def _save_markers(self):
        name = self.selected_map_var.get().strip()
        if not name:
            return
        overlays_dir = self.maps_dir / "overlays"
        try:
            overlays_dir.mkdir(parents=True, exist_ok=True)
            data = {"markers": []}
            for meta in self._markers.values():
                data["markers"].append({
                    "x": float(meta.get("x", 0.0)),
                    "y": float(meta.get("y", 0.0)),
                    "label": meta.get('label'),
                    "note": meta.get('note'),
                })
            self._overlay_path_for_map(name).write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _add_marker_at_view_center(self):
        if self._source_image is None or self.canvas is None:
            return
        # center of visible area
        cw = max(1, int(self.canvas.winfo_width()))
        ch = max(1, int(self.canvas.winfo_height()))
        cx = (self.canvas.canvasx(cw // 2))
        cy = (self.canvas.canvasy(ch // 2))
        logical_x = cx / max(0.0001, self._zoom_factor)
        logical_y = cy / max(0.0001, self._zoom_factor)
        self._create_marker_visual(logical_x, logical_y)
        self._save_markers()
        try:
            self._refresh_marker_panel()
        except Exception:
            pass

    def _on_canvas_double_click(self, event):
        # add marker at clicked logical position
        if self.canvas is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        logical_x = cx / max(0.0001, self._zoom_factor)
        logical_y = cy / max(0.0001, self._zoom_factor)
        self._create_marker_visual(logical_x, logical_y)
        self._save_markers()
        try:
            self._refresh_marker_panel()
        except Exception:
            pass

    # shift+drag create flow
    def _on_canvas_shift_press(self, event):
        if self.canvas is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        logical_x = cx / max(0.0001, self._zoom_factor)
        logical_y = cy / max(0.0001, self._zoom_factor)
        # create a temporary marker and mark as creating
        item = self._create_marker_visual(logical_x, logical_y)
        if item:
            self._drag_data = {'creating': True, 'item': item, 'start_x': cx, 'start_y': cy}

    def _on_canvas_shift_motion(self, event):
        if not self._drag_data or not self._drag_data.get('creating'):
            return
        item = self._drag_data['item']
        new_x = self.canvas.canvasx(event.x)
        new_y = self.canvas.canvasy(event.y)
        dx = new_x - self._drag_data['start_x']
        dy = new_y - self._drag_data['start_y']
        try:
            self.canvas.move(item, dx, dy)
            meta = self._markers.get(item)
            if meta is not None:
                bbox = self.canvas.bbox(item)
                if bbox:
                    cx = (bbox[0] + bbox[2]) / 2.0
                    cy = (bbox[1] + bbox[3]) / 2.0
                    meta['x'] = cx / max(0.0001, self._zoom_factor)
                    meta['y'] = cy / max(0.0001, self._zoom_factor)
        except Exception:
            pass
        self._drag_data['start_x'] = new_x
        self._drag_data['start_y'] = new_y

    def _on_canvas_shift_release(self, event):
        if not self._drag_data or not self._drag_data.get('creating'):
            self._drag_data = None
            return
        self._drag_data = None
        self._save_markers()
        try:
            self._refresh_marker_panel()
        except Exception:
            pass

    def _get_default_marker_icon(self):
        # create and cache a small beige triangular marker similar to in-game marker
        if hasattr(self, '_default_marker_icon') and self._default_marker_icon is not None:
            return self._default_marker_icon
        try:
            size = (28, 28)
            from PIL import ImageDraw
            img = Image.new('RGBA', size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            w, h = size
            # triangle pointing up (beige)
            tri = [(w*0.5, h*0.15), (w*0.85, h*0.85), (w*0.15, h*0.85)]
            fill = (230, 215, 165, 255)  # beige-ish
            outline = (120, 100, 60, 255)
            draw.polygon(tri, fill=fill, outline=outline)
            # subtle inner smaller triangle for contrast
            tri2 = [(w*0.5, h*0.28), (w*0.78, h*0.78), (w*0.22, h*0.78)]
            draw.polygon(tri2, fill=(245, 240, 220, 255))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            self._default_marker_icon = tk.PhotoImage(data=b64)
            return self._default_marker_icon
        except Exception:
            return None

    def _create_marker_visual(self, logical_x: float, logical_y: float, label: str = None, note: str = None):
        # convert logical to canvas coords
        if self.canvas is None:
            return None
        cx = logical_x * self._zoom_factor
        cy = logical_y * self._zoom_factor
        name = self.selected_map_var.get().strip()
        icon = None
        try:
            icon_path = self._icon_path_for_map(name)
            if icon_path.exists():
                icon = tk.PhotoImage(file=str(icon_path))
        except Exception:
            icon = None

        if icon is None:
            # fallback to generated triangle marker to match map's style
            icon = self._get_default_marker_icon()

        if icon is not None:
            item = self.canvas.create_image(cx, cy, image=icon, anchor='center', tags=('marker',))
            self._markers[item] = {"x": logical_x, "y": logical_y, "thumb": icon, 'label': label, 'note': note}
        else:
            r = 10
            item = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill='#ff5555', outline='#aa0000', tags=('marker',))
            self._markers[item] = {"x": logical_x, "y": logical_y, 'label': label, 'note': note}

        # create label text
        if label:
            try:
                lbl = self.canvas.create_text(cx, cy + 16, text=label, anchor='n', fill='#ffffff', font=('TkDefaultFont', 9), tags=('marker_label',))
                self._markers[item]['label_item'] = lbl
            except Exception:
                pass

        # bind events for the marker
        try:
            self.canvas.tag_bind(item, '<ButtonPress-1>', self._on_marker_press)
            self.canvas.tag_bind(item, '<B1-Motion>', self._on_marker_move)
            self.canvas.tag_bind(item, '<ButtonRelease-1>', self._on_marker_release)
            # right click to delete
            self.canvas.tag_bind(item, '<Button-3>', self._on_marker_right_click)
            # double click to edit label/note
            self.canvas.tag_bind(item, '<Double-1>', self._on_marker_double_click)
        except Exception:
            pass
        try:
            self._refresh_marker_panel()
        except Exception:
            pass
        return item

    def _on_marker_press(self, event):
        try:
            item = int(self.canvas.find_withtag('current')[0])
        except Exception:
            return
        # if this marker was being created, do not treat as drag of existing
        self._drag_data = {
            'item': item,
            'start_x': self.canvas.canvasx(event.x),
            'start_y': self.canvas.canvasy(event.y),
            'creating': False,
        }
        try:
            self.canvas.configure(cursor='fleur')
        except Exception:
            pass

    def _on_marker_move(self, event):
        if not self._drag_data:
            return
        item = self._drag_data['item']
        if item not in self._markers:
            return
        new_x = self.canvas.canvasx(event.x)
        new_y = self.canvas.canvasy(event.y)
        dx = new_x - self._drag_data['start_x']
        dy = new_y - self._drag_data['start_y']
        try:
            self.canvas.move(item, dx, dy)
            # move label if present
            meta = self._markers.get(item)
            lbl = meta.get('label_item')
            if lbl:
                self.canvas.move(lbl, dx, dy)
        except Exception:
            pass
        # update start for continuous motion
        self._drag_data['start_x'] = new_x
        self._drag_data['start_y'] = new_y
        # update logical coords
        bbox = self.canvas.bbox(item)
        if bbox:
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            self._markers[item]['x'] = cx / max(0.0001, self._zoom_factor)
            self._markers[item]['y'] = cy / max(0.0001, self._zoom_factor)

    def _on_marker_release(self, _event=None):
        self._drag_data = None
        try:
            self.canvas.configure(cursor='')
        except Exception:
            pass
        self._save_markers()
        try:
            self._refresh_marker_panel()
        except Exception:
            pass

    def _on_marker_double_click(self, event):
        # edit label and note
        try:
            item = int(self.canvas.find_withtag('current')[0])
        except Exception:
            return
        meta = self._markers.get(item, {})
        current_label = meta.get('label') or ''
        current_note = meta.get('note') or ''
        try:
            new_label = simpledialog.askstring('Marker Label', 'Label:', initialvalue=current_label)
            if new_label is None:
                new_label = current_label
            # use multi-line note editor
            new_note = self._edit_note_dialog(item, current_note)
            if new_note is None:
                new_note = current_note
            meta['label'] = new_label
            meta['note'] = new_note
            # update label visual
            lbl = meta.get('label_item')
            bbox = self.canvas.bbox(item)
            if lbl:
                try:
                    if new_label:
                        self.canvas.itemconfigure(lbl, text=new_label)
                    else:
                        self.canvas.delete(lbl)
                        meta['label_item'] = None
                except Exception:
                    pass
            else:
                if new_label and bbox:
                    try:
                        cx = (bbox[0] + bbox[2]) / 2.0
                        cy = (bbox[1] + bbox[3]) / 2.0
                        lbl = self.canvas.create_text(cx, cy + 16, text=new_label, anchor='n', fill='#ffffff', font=('TkDefaultFont', 9), tags=('marker_label',))
                        meta['label_item'] = lbl
                    except Exception:
                        pass
            self._save_markers()
            try:
                self._refresh_marker_panel()
            except Exception:
                pass
        except Exception:
            pass

    def _on_marker_right_click(self, event):
        try:
            item = int(self.canvas.find_withtag('current')[0])
        except Exception:
            return
        try:
            meta = self._markers.get(item, {})
            lbl = meta.get('label_item')
            if lbl:
                try:
                    self.canvas.delete(lbl)
                except Exception:
                    pass
            self.canvas.delete(item)
        except Exception:
            pass
        try:
            if item in self._markers:
                del self._markers[item]
        except Exception:
            pass
        self._save_markers()
        try:
            self._refresh_marker_panel()
        except Exception:
            pass

    def _clear_markers(self):
        try:
            for item in list(self._markers.keys()):
                try:
                    self.canvas.delete(item)
                except Exception:
                    pass
            self._markers = {}
            # remove overlay file
            name = self.selected_map_var.get().strip()
            if name:
                p = self._overlay_path_for_map(name)
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            try:
                self._refresh_marker_panel()
            except Exception:
                pass
        except Exception:
            pass

    def _refresh_marker_positions(self):
        # Reposition markers after zoom/resize
        if self.canvas is None:
            return
        for item, meta in list(self._markers.items()):
            try:
                lx = meta.get('x', 0.0)
                ly = meta.get('y', 0.0)
                cx = lx * self._zoom_factor
                cy = ly * self._zoom_factor
                bbox = self.canvas.bbox(item)
                if bbox and 'thumb' in meta:
                    # image: set coords
                    self.canvas.coords(item, cx, cy)
                    lbl = meta.get('label_item')
                    if lbl:
                        self.canvas.coords(lbl, cx, cy + 16)
                elif bbox:
                    # oval: compute half size
                    w = (bbox[2] - bbox[0]) / 2.0
                    h = (bbox[3] - bbox[1]) / 2.0
                    self.canvas.coords(item, cx - w, cy - h, cx + w, cy + h)
                    lbl = meta.get('label_item')
                    if lbl:
                        self.canvas.coords(lbl, cx, cy + 16)
            except Exception:
                pass

    # --- end marker management --------------------------------------------

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

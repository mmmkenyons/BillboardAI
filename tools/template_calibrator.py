#!/usr/bin/env python3
"""Template Calibration Utility — Developer tool for registering billboard quads.

Click four corners of a billboard in a scene image to calibrate the
billboard_quad for a template JSON file.  Produces coordinates in the
template's reference_size coordinate system.

Usage:
    # Existing-template calibration (JSON input):
    python tools/template_calibrator.py assets/templates/cart_corral.json

    # New-template creation directly from a scene image:
    python tools/template_calibrator.py assets/cart_nose.jpg

Click order: top-left → top-right → bottom-right → bottom-left
"""

import json
import math
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageTk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_id_from_filename(filepath: str) -> str:
    """Extract a template id from an image filename.

    Example: 'assets/cart_nose.jpg' → 'cart_nose'
    """
    stem = Path(filepath).stem
    return stem.lower().replace(" ", "_")


def _derive_name_from_id(template_id: str) -> str:
    """Convert a template id into a human-readable default name.

    Example: 'cart_nose' → 'Cart Nose'
    """
    return template_id.replace("_", " ").title()


def _calculate_artwork_aspect(quad: List[Tuple[int, int]]) -> float:
    """Calculate artwork aspect ratio from a quadrilateral.

    Uses average width / average height to handle perspective skew.

    Args:
        quad: List of 4 (x, y) tuples in TL, TR, BR, BL order.

    Returns:
        Positive float: average_width / average_height.
    """
    tl, tr, br, bl = quad

    # Edge lengths
    top_width = math.hypot(tr[0] - tl[0], tr[1] - tl[1])
    bottom_width = math.hypot(br[0] - bl[0], br[1] - bl[1])
    left_height = math.hypot(bl[0] - tl[0], bl[1] - tl[1])
    right_height = math.hypot(br[0] - tr[0], br[1] - tr[1])

    avg_width = (top_width + bottom_width) / 2.0
    avg_height = (left_height + right_height) / 2.0

    if avg_height == 0:
        return 0.0

    return avg_width / avg_height


def _calculate_default_artwork_size(
    artwork_aspect: float,
    working_height: int = 400,
) -> Tuple[int, int]:
    """Generate a useful working-resolution default_artwork_size.

    Args:
        artwork_aspect: width / height ratio.
        working_height: Fixed working height in pixels (default 400).

    Returns:
        (width, height) tuple of positive integers.
    """
    working_width = max(1, round(working_height * artwork_aspect))
    return (working_width, working_height)


def _validate_quad(
    quad: List[Tuple[int, int]],
    ref_size: Tuple[int, int],
) -> Optional[str]:
    """Validate a quadrilateral before saving.

    Returns None if valid, or an error message string if invalid.
    """
    if len(quad) != 4:
        return "Exactly 4 points are required."

    w, h = ref_size
    for i, (x, y) in enumerate(quad):
        if x < 0 or y < 0 or x > w or y > h:
            return (
                f"Point {i + 1} ({x}, {y}) is outside image bounds "
                f"({w}×{h})."
            )

    # Check for degenerate quad (all points collinear or zero area)
    # Use shoelace formula for area
    area = 0.0
    n = 4
    for i in range(n):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0

    if area < 1.0:
        return "Quadrilateral is degenerate (near-zero area)."

    aspect = _calculate_artwork_aspect(quad)
    if aspect <= 0:
        return f"Calculated aspect ratio must be positive, got {aspect:.3f}."

    return None


def load_template(template_path: str) -> dict:
    with open(template_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_template(
    template_path: str,
    template: dict,
    quad: List[List[int]],
    ref_size: Tuple[int, int],
) -> None:
    """Update *only* billboard_quad and reference_size; preserve everything else."""
    template["billboard_quad"] = quad
    template["reference_size"] = list(ref_size)
    with open(template_path, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)
    print(f"\nSaved to {template_path}")
    print(f"  billboard_quad:  {json.dumps(quad)}")
    print(f"  reference_size:  {list(ref_size)}")


def _checkerboard_overlay(
    scene: Image.Image,
    quad: List[Tuple[int, int]],
    cell: int = 24,
) -> Image.Image:
    """Return a new RGBA image: *scene* with a semi-transparent checkerboard
    pattern filling the polygon defined by *quad*."""
    result = scene.copy().convert("RGBA")

    # Polygon mask
    mask = Image.new("L", scene.size, 0)
    ImageDraw.Draw(mask).polygon(quad, fill=255)

    # Bounding box for the quad
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Draw checkerboard inside the bounding box
    overlay = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for x in range(min_x, max_x, cell):
        for y in range(min_y, max_y, cell):
            col = (x - min_x) // cell
            row = (y - min_y) // cell
            color = (255, 0, 255, 150) if (col + row) % 2 == 0 else (0, 255, 255, 150)
            ov_draw.rectangle([x, y, x + cell, y + cell], fill=color)

    # Clip overlay to polygon
    overlay.putalpha(
        Image.composite(
            overlay.getchannel("A"),
            Image.new("L", scene.size, 0),
            mask,
        )
    )

    return Image.alpha_composite(result, overlay)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class TemplateCalibrator:
    """Tkinter application: display scene, collect 4 corner clicks, preview, save."""

    CORNER_LABELS = ["TL", "TR", "BR", "BL"]
    MARKER_COLORS = ["#FF0000", "#00CC00", "#0088FF", "#FF00FF"]  # R, G, B, M

    def __init__(
        self,
        template_path: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> None:
        """Initialise the calibrator.

        Args:
            template_path: Path to an existing template JSON (JSON workflow).
            image_path: Path to a scene image (new-template workflow).
        """
        # ---- Determine mode ----
        self._mode: str  # "json" or "image"
        self.template_path: str = ""
        self.output_json_path: str = ""
        self.template: dict = {}

        if template_path is not None:
            self._mode = "json"
            self.template_path = template_path
            self.template = load_template(template_path)

            # Resolve scene image from template
            self.scene_path = self.template.get(
                "scene_path", "assets/cart_corral.jpg"
            )
            if not Path(self.scene_path).exists():
                print(f"Error: scene image not found: {self.scene_path}")
                sys.exit(1)

            # Reference size — the coordinate system we calibrate in
            ref = self.template.get("reference_size")
            if isinstance(ref, (list, tuple)) and len(ref) == 2:
                self.ref_size = (int(ref[0]), int(ref[1]))
            else:
                # Fall back to the image's natural size
                with Image.open(self.scene_path) as im:
                    self.ref_size = im.size
                print(
                    f"Note: reference_size missing; using image size {self.ref_size}"
                )

        elif image_path is not None:
            self._mode = "image"
            self.scene_path = image_path

            if not Path(self.scene_path).exists():
                print(f"Error: scene image not found: {self.scene_path}")
                sys.exit(1)

            # Detect native pixel dimensions
            with Image.open(self.scene_path) as im:
                self.ref_size = im.size

            # Derive template id and name
            template_id = _derive_id_from_filename(image_path)
            template_name = _derive_name_from_id(template_id)

            # Determine output JSON path
            self.output_json_path = os.path.join(
                "assets", "templates", f"{template_id}.json"
            )

            # Check for overwrite
            if Path(self.output_json_path).exists():
                print(
                    f"WARNING: Output template already exists: {self.output_json_path}"
                )
                print("Use the JSON workflow to recalibrate an existing template,")
                print("or delete/rename the existing file first.")
                print()
                # We'll still open the UI but warn on save too
                self._overwrite_warning_shown = True
            else:
                self._overwrite_warning_shown = False

            # Build a minimal in-memory template
            self.template = {
                "id": template_id,
                "name": template_name,
                "scene_path": self.scene_path,
            }
            self.template_path = ""  # No file yet

        else:
            print("Error: must provide either template_path or image_path.")
            sys.exit(1)

        # Load & resize scene to reference_size
        self.scene_pil = Image.open(self.scene_path).convert("RGB")
        if self.scene_pil.size != self.ref_size:
            print(
                f"Resizing scene from {self.scene_pil.size} → {self.ref_size}"
            )
            self.scene_pil = self.scene_pil.resize(
                self.ref_size, Image.Resampling.LANCZOS
            )

        # State
        self.points: List[Tuple[int, int]] = []
        self._marker_ids: List[int] = []
        self._line_ids: List[int] = []
        self._label_ids: List[int] = []
        self._preview_image_id: Optional[int] = None
        self._preview_tk: Optional[ImageTk.PhotoImage] = None
        self._aspect_var: Optional[tk.StringVar] = None

        # ---- Build UI ----
        self.root = tk.Tk()

        if self._mode == "json":
            title = f"Template Calibrator — {Path(self.template_path).name}"
        else:
            title = f"Template Calibrator — NEW: {Path(self.scene_path).name}"
        self.root.title(title)
        self.root.resizable(False, False)

        # ---- Info bar (top) ----
        info_frame = tk.Frame(self.root, bd=1, relief=tk.SUNKEN)
        info_frame.pack(side=tk.TOP, fill=tk.X)

        scene_label = os.path.basename(self.scene_path)
        dims_label = f"{self.ref_size[0]}×{self.ref_size[1]}"
        info_text = (
            f"Scene: {scene_label}    "
            f"Dimensions: {dims_label}    "
            f"Order: TL → TR → BR → BL"
        )
        tk.Label(
            info_frame,
            text=info_text,
            anchor=tk.W,
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, fill=tk.X)

        # ---- Status bar (bottom) ----
        self._status_var = tk.StringVar(value="Click top-left corner (TL)")
        tk.Label(
            self.root,
            textvariable=self._status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,
        ).pack(side=tk.BOTTOM, fill=tk.X)

        # ---- Button bar ----
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=6)

        self._reset_btn = tk.Button(
            btn_frame, text="Reset", command=self._reset
        )
        self._reset_btn.pack(side=tk.LEFT, padx=4)

        self._save_btn = tk.Button(
            btn_frame,
            text="Save",
            command=self._save,
            state=tk.DISABLED,
        )
        self._save_btn.pack(side=tk.LEFT, padx=4)

        # Aspect ratio display (right side of button bar)
        self._aspect_var = tk.StringVar(value="Aspect: —")
        tk.Label(
            btn_frame,
            textvariable=self._aspect_var,
            font=("TkDefaultFont", 9, "bold"),
        ).pack(side=tk.RIGHT, padx=6)

        # Output path display
        if self._mode == "image":
            output_label = f"Output: {self.output_json_path}"
        else:
            output_label = f"Output: {self.template_path}"
        tk.Label(
            btn_frame,
            text=output_label,
            font=("TkDefaultFont", 8),
            fg="gray",
        ).pack(side=tk.RIGHT, padx=6)

        # ---- Canvas ----
        self._tk_photo = ImageTk.PhotoImage(self.scene_pil)
        self.canvas = tk.Canvas(
            self.root,
            width=self.ref_size[0],
            height=self.ref_size[1],
            highlightthickness=0,
        )
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_photo)
        self.canvas.bind("<Button-1>", self._on_click)

        # Keyboard shortcuts
        self.root.bind("<Escape>", lambda _e: self._reset())
        self.root.bind("<Control-s>", lambda _e: self._save())

        print(f"Mode:        {'NEW from image' if self._mode == 'image' else 'Recalibrate JSON'}")
        print(f"Scene:       {self.scene_path}")
        print(f"Ref size:    {self.ref_size[0]}×{self.ref_size[1]}")
        if self._mode == "image":
            print(f"Output:      {self.output_json_path}")
            print(f"Template ID: {self.template['id']}")
            print(f"Name:        {self.template['name']}")
        print("Click the four corners: TL → TR → BR → BL\n")

        self.root.mainloop()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_click(self, event: tk.Event) -> None:
        if len(self.points) >= 4:
            return

        x, y = event.x, event.y
        self.points.append((x, y))
        idx = len(self.points) - 1

        # Marker circle
        r = 7
        color = self.MARKER_COLORS[idx]
        m = self.canvas.create_oval(
            x - r,
            y - r,
            x + r,
            y + r,
            fill=color,
            outline="white",
            width=2,
        )
        self._marker_ids.append(m)

        # Text label
        lbl = self.canvas.create_text(
            x + 14,
            y - 14,
            text=f"{self.CORNER_LABELS[idx]}  ({x}, {y})",
            fill=color,
            anchor=tk.W,
            font=("TkDefaultFont", 10, "bold"),
        )
        self._label_ids.append(lbl)

        # Connecting line from previous point
        if idx > 0:
            px, py = self.points[idx - 1]
            ln = self.canvas.create_line(
                px,
                py,
                x,
                y,
                fill="yellow",
                width=2,
                dash=(5, 3),
            )
            self._line_ids.append(ln)

        # Fourth point → close polygon, show preview, print coords
        if len(self.points) == 4:
            # Close the loop
            ln = self.canvas.create_line(
                x,
                y,
                self.points[0][0],
                self.points[0][1],
                fill="yellow",
                width=2,
                dash=(5, 3),
            )
            self._line_ids.append(ln)

            self._show_preview()
            self._print_quad()
            self._update_aspect_display()
            self._status_var.set(
                "All 4 corners set — review preview, then Save or Reset."
            )
            self._save_btn.config(state=tk.NORMAL)
        else:
            self._status_var.set(
                f"Click {self.CORNER_LABELS[idx + 1]} corner"
            )

    def _show_preview(self) -> None:
        """Overlay a checkerboard test pattern inside the selected polygon."""
        quad = [(int(p[0]), int(p[1])) for p in self.points]
        preview_pil = _checkerboard_overlay(self.scene_pil, quad)
        self._preview_tk = ImageTk.PhotoImage(preview_pil)

        if self._preview_image_id is not None:
            self.canvas.delete(self._preview_image_id)

        self._preview_image_id = self.canvas.create_image(
            0,
            0,
            anchor=tk.NW,
            image=self._preview_tk,
        )
        # Keep markers / lines / labels on top
        for item_id in self._marker_ids + self._line_ids + self._label_ids:
            self.canvas.tag_raise(item_id)

    def _update_aspect_display(self) -> None:
        """Update the aspect ratio display after 4 points are placed."""
        quad = [(int(p[0]), int(p[1])) for p in self.points]
        aspect = _calculate_artwork_aspect(quad)
        size = _calculate_default_artwork_size(aspect)
        self._aspect_var.set(
            f"Aspect: {aspect:.3f}  →  artwork: {size[0]}×{size[1]}"
        )

    def _print_quad(self) -> None:
        quad = [[int(p[0]), int(p[1])] for p in self.points]
        aspect = _calculate_artwork_aspect(
            [(int(p[0]), int(p[1])) for p in self.points]
        )
        art_size = _calculate_default_artwork_size(aspect)
        print("\n" + "=" * 52)
        print("CALIBRATED billboard_quad:")
        print(json.dumps(quad, indent=2))
        print(f"  artwork_aspect:       {aspect:.3f}")
        print(f"  default_artwork_size: {list(art_size)}")
        print("=" * 52 + "\n")

    def _reset(self) -> None:
        self.points.clear()
        for iid in self._marker_ids + self._line_ids + self._label_ids:
            self.canvas.delete(iid)
        self._marker_ids.clear()
        self._line_ids.clear()
        self._label_ids.clear()
        if self._preview_image_id is not None:
            self.canvas.delete(self._preview_image_id)
            self._preview_image_id = None
        self._preview_tk = None
        self._aspect_var.set("Aspect: —")
        self._status_var.set("Click top-left corner (TL)")
        self._save_btn.config(state=tk.DISABLED)

    def _save(self) -> None:
        if len(self.points) != 4:
            return

        quad = [(int(p[0]), int(p[1])) for p in self.points]

        # Validate
        error = _validate_quad(quad, self.ref_size)
        if error is not None:
            messagebox.showerror("Validation Error", error)
            print(f"Validation error: {error}")
            return

        # Calculate geometry
        aspect = _calculate_artwork_aspect(quad)
        art_size = _calculate_default_artwork_size(aspect)

        quad_list = [[p[0], p[1]] for p in quad]

        if self._mode == "json":
            # Update existing template
            tp: str = self.template_path  # type: str at runtime in json mode
            self.template["billboard_quad"] = quad_list
            self.template["reference_size"] = list(self.ref_size)
            self.template["artwork_aspect"] = round(aspect, 3)
            self.template["default_artwork_size"] = list(art_size)

            with open(tp, "w", encoding="utf-8") as fh:
                json.dump(self.template, fh, indent=2)

            print(f"\nSaved to {tp}")
            print(f"  billboard_quad:       {json.dumps(quad_list)}")
            print(f"  reference_size:       {list(self.ref_size)}")
            print(f"  artwork_aspect:       {round(aspect, 3)}")
            print(f"  default_artwork_size: {list(art_size)}")

            self._status_var.set(
                f"Saved — {Path(tp).name} updated."
            )

        else:
            # Image mode — create new JSON
            out: str = self.output_json_path  # type: str at runtime in image mode

            # Check overwrite
            if Path(out).exists():
                result = messagebox.askyesno(
                    "Overwrite Confirmation",
                    f"Template already exists:\n\n"
                    f"{out}\n\n"
                    f"Overwrite it?",
                )
                if not result:
                    print("Save cancelled — output file already exists.")
                    self._status_var.set(
                        "Save cancelled — file already exists."
                    )
                    return

            # Ensure output directory exists
            out_dir = os.path.dirname(out)
            os.makedirs(out_dir, exist_ok=True)

            new_template = {
                "id": self.template["id"],
                "name": self.template["name"],
                "scene_path": self.scene_path,
                "reference_size": list(self.ref_size),
                "billboard_quad": quad_list,
                "quad_order": "TL-TR-BR-BL",
                "artwork_aspect": round(aspect, 3),
                "default_artwork_size": list(art_size),
            }

            with open(out, "w", encoding="utf-8") as fh:
                json.dump(new_template, fh, indent=2)

            print(f"\nSaved to {out}")
            print(f"  id:                   {new_template['id']}")
            print(f"  name:                 {new_template['name']}")
            print(f"  scene_path:           {new_template['scene_path']}")
            print(f"  reference_size:       {new_template['reference_size']}")
            print(f"  billboard_quad:       {json.dumps(quad_list)}")
            print(f"  artwork_aspect:       {new_template['artwork_aspect']}")
            print(f"  default_artwork_size: {new_template['default_artwork_size']}")

            self._status_var.set(
                f"Saved — {os.path.basename(out)} created."
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _is_image_file(filepath: str) -> bool:
    """Check if a filepath appears to be an image based on extension."""
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
    return Path(filepath).suffix.lower() in image_exts


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python tools/template_calibrator.py assets/templates/cart_corral.json")
        print("  python tools/template_calibrator.py assets/cart_nose.jpg")
        sys.exit(1)

    arg = sys.argv[1]

    if not Path(arg).exists():
        print(f"Error: file not found: {arg}")
        sys.exit(1)

    if _is_image_file(arg):
        # New-template workflow from image
        TemplateCalibrator(image_path=arg)
    else:
        # Existing JSON workflow
        TemplateCalibrator(template_path=arg)


if __name__ == "__main__":
    main()
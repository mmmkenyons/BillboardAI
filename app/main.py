import threading
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine.config as config
from engine.batch_processor import run_batch
from engine.scraper.site import WebsiteScraper


class BillboardAIApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BillboardAI Desktop")
        self.root.geometry("720x520")
        self.root.resizable(False, False)

        self.url_var = tk.StringVar()
        self.batch_file_var = tk.StringVar()
        self.output_folder_var = tk.StringVar(value=str(config.OUTPUT_DIR))
        self.hero_image_var = tk.StringVar()
        self.template_var = tk.StringVar(value="auto")
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.task_thread = None

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Website URL:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.url_var, width=60).grid(row=0, column=1, columnspan=2, sticky=tk.W)

        ttk.Label(frame, text="Batch URLs file:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=self.batch_file_var, width=44).grid(row=1, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(frame, text="Browse...", command=self.choose_batch_file).grid(row=1, column=2, sticky=tk.W, pady=(10, 0))

        ttk.Label(frame, text="Hero / Background Image:").grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=self.hero_image_var, width=44).grid(row=2, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(frame, text="Browse...", command=self.choose_hero_image).grid(row=2, column=2, sticky=tk.W, pady=(10, 0))

        ttk.Label(frame, text="Output folder:").grid(row=3, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Entry(frame, textvariable=self.output_folder_var, width=44).grid(row=3, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(frame, text="Browse...", command=self.choose_output_folder).grid(row=3, column=2, sticky=tk.W, pady=(10, 0))

        ttk.Label(frame, text="Template:").grid(row=4, column=0, sticky=tk.W, pady=(10, 0))
        ttk.Combobox(frame, textvariable=self.template_var, values=["contractor", "dentist", "realtor", "auto"], state="readonly", width=18).grid(row=4, column=1, sticky=tk.W, pady=(10, 0))

        self.generate_button = ttk.Button(frame, text="Generate Mockups", command=self.start_generation)
        self.generate_button.grid(row=5, column=0, columnspan=3, pady=(20, 0), sticky=tk.EW)

        ttk.Label(frame, text="Status:").grid(row=6, column=0, sticky=tk.W, pady=(20, 0))
        ttk.Label(frame, textvariable=self.status_var).grid(row=6, column=1, columnspan=2, sticky=tk.W, pady=(20, 0))

        self.log_text = tk.Text(frame, width=80, height=14, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.grid(row=7, column=0, columnspan=3, pady=(10, 0), sticky=tk.NSEW)
        frame.grid_rowconfigure(7, weight=1)

    def choose_batch_file(self):
        path = filedialog.askopenfilename(title="Select batch URLs file", filetypes=[("Text files", "*.txt"), ("All files", "*")])
        if path:
            self.batch_file_var.set(path)

    def choose_hero_image(self):
        path = filedialog.askopenfilename(title="Select hero/background image", filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All files", "*")])
        if path:
            self.hero_image_var.set(path)

    def choose_output_folder(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_folder_var.set(path)
            self._patch_config_paths(path)

    def _patch_config_paths(self, base_folder: str) -> None:
        config.OUTPUT_FOLDER = base_folder
        config.IMAGE_FOLDER = os.path.join(base_folder, "images")
        config.HTML_FOLDER = os.path.join(base_folder, "html")
        config.CSS_FOLDER = os.path.join(base_folder, "css")
        config.ASSETS_FOLDER = os.path.join(base_folder, "assets")
        config.JSON_FOLDER = os.path.join(base_folder, "json")
        config.BATCH_STATUS_FILE = os.path.join(base_folder, "batch_status.json")

    def _log(self, message: str) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_generation(self):
        if self.task_thread and self.task_thread.is_alive():
            messagebox.showinfo("BillboardAI", "A generation task is already running.")
            return

        url = self.url_var.get().strip()
        batch_file = self.batch_file_var.get().strip()
        if not url and not batch_file:
            messagebox.showwarning("BillboardAI", "Please enter a website URL or select a batch file.")
            return

        self.generate_button.config(state=tk.DISABLED)
        self.status_var.set("Starting generation...")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

        self.task_thread = threading.Thread(target=self._run_generation, daemon=True)
        self.task_thread.start()
        self.root.after(100, self._poll_thread)

    def _poll_thread(self):
        if self.task_thread and self.task_thread.is_alive():
            self.root.after(100, self._poll_thread)
            return
        self.generate_button.config(state=tk.NORMAL)
        self.status_var.set("Ready")

    def _run_generation(self):
        try:
            self._patch_config_paths(self.output_folder_var.get())
            if self.batch_file_var.get().strip():
                self._run_batch()
            else:
                self._run_single()
        except Exception as exc:
            self._log(f"Error: {exc}")
            self.status_var.set("Failed")
        else:
            self.status_var.set("Complete")

    def _run_batch(self):
        batch_file = self.batch_file_var.get().strip()
        output_csv = os.path.join(self.output_folder_var.get(), "smartlead.csv")
        self._log(f"Running batch: {batch_file}")
        results = run_batch(batch_file, output_csv, template=self.template_var.get(), upload=False)
        self._log(f"Batch complete. CSV saved to {output_csv}")
        for url, info in results.items():
            self._log(f"{url}: {info.get('image', info.get('error'))}")

    def _run_single(self):
        url = self.url_var.get().strip()
        hero_path = self.hero_image_var.get().strip() or None
        self._log(f"Scraping website: {url}")

        scraper = WebsiteScraper(url)
        data = scraper.run()
        if hero_path:
            data["hero_path"] = hero_path
            scraper.last_data = data

        output_file = os.path.join(self.output_folder_var.get(), f"{scraper.filename_base}_{self.template_var.get()}.png")
        self._log(f"Rendering billboard to {output_file}")
        rendered_path = scraper.render_billboard(self.template_var.get(), output_file)
        self._log(f"Rendered image: {rendered_path}")
        if scraper.last_data.get("regenerated"):
            self._log("A better auto template was generated after quality analysis.")


def main():
    root = tk.Tk()
    app = BillboardAIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

import os
import threading
import tkinter as tk

from app.main import BillboardAIApp


def test_app_initial_state(monkeypatch, tmp_path):
    root = tk.Tk()
    root.withdraw()
    app = BillboardAIApp(root)

    assert app.url_var.get() == ""
    assert app.batch_file_var.get() == ""
    assert app.template_var.get() == "auto"
    assert "BillboardAI" in app.root.title()

    app.root.destroy()

"""Prueft den Tab-Aufbau von create_ui() ohne WanGP.

Warum ein eigenes Skript: dev/ui_preview.py baut den Plugin-Tab selbst nach
(Wortregler + Modell-Check) und fuehrt create_ui() NICHT aus. Die Vorlagenkarte
und die Prompt-Werkstatt entstehen aber genau dort - ohne diesen Lauf waeren sie
ungetestet.

Aufruf aus dem WanGP-Ordner:
    ./.venv/bin/python ~/git/wan2gp-local-enhance/dev/check_template_ui.py
Erwartung: "OK" am Ende, vier Karten mit class le-card, keine Ausnahme.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/stefan/git/wan2gp-local-enhance")
sys.path.insert(0, "/home/stefan/git/Wan2GP")

import gradio as gr  # noqa: E402
import plugin  # noqa: E402

main = sys.modules["__main__"]
# Eigener, leerer Prompt-Ordner: das Skript schreibt nie nach ~/Prompts.
prompt_dir = tempfile.mkdtemp(prefix="le-prompts-")
main.server_config = {
    "local_enhance_template": plugin._TEMPLATE_SHEET,
    "local_enhance_min_words": 0,
    "local_enhance_max_words": 1500,
    "llm_engines": {"deepy": "qwen35_4b"},
    "enhancer_enabled": 5,
    "local_enhance_prompt_dir": prompt_dir,
    "local_enhance_prompt_migrated": True,
}
main.models_def = {}
main.get_model_handler = lambda model_type, *a, **k: None

p = plugin.LocalEnhancePlugin()
# Was sonst der PluginManager setzt:
p.state = gr.State({})
p.refresh_form_trigger = gr.Textbox(visible=False)
p.prompt = gr.Textbox()
p.prompt_enhancer = gr.Textbox(visible=False)
p.prompt_enhancer_btn = gr.Button()
p.get_current_model_settings = lambda state: {"prompt": "a fox walking in fresh snow"}
p.get_state_model_type = lambda state: "krea2_turbo"
p.get_model_def = lambda model_type: {}
p.get_model_settings = lambda state, model_type: {}
p.get_prompt_enhancer_choices = lambda *a, **k: ["T"]
for name in plugin._IMAGE_INPUT_NAMES:
    setattr(p, name, None)
# WanGPs LoRA-Auswahl: das Plugin traegt hier die Bypass-LoRA nach.
p.activated_loras = gr.CheckboxGroup(
    choices=["a"], value=["krea2/Bara_Style.safetensors"], label="LoRAs"
)

with gr.Blocks() as demo:
    with gr.Row():
        gr.Button("eingebaut")
        gr.Textbox(visible=False)
        gr.Dropdown(choices=["T"], show_label=False)
        p._think_checkbox = gr.Checkbox(label="Think")
        p.create_inline_button()
    p.create_ui(None)


def alle(block, out):
    out.append(block)
    for kind in getattr(block, "children", []) or []:
        alle(kind, out)
    return out


alle(demo, knoten := [])
karten = [k for k in knoten if "le-card" in (getattr(k, "elem_classes", None) or [])]
labels = [str(getattr(k, "label", "")) for k in knoten if getattr(k, "label", None)]
typen = {}
for k in knoten:
    typen[type(k).__name__] = typen.get(type(k).__name__, 0) + 1

print("Komponenten:", len(knoten))
print("Karten (le-card):", len(karten))
print("Labels:", labels)
print("Typen:", typen)

assert len(karten) == 4, f"erwartet 4 Karten, gefunden {len(karten)}"
assert "Prompt folder" in labels, "Ordner-Feld fehlt"
assert "Name (max. 64 chars)" in labels, "Namensfeld fehlt"
assert "System prompt (sent to the local model)" in labels, "Prompt-Textfeld fehlt"
assert "Prompt" in labels and "Enhanced prompt" in labels, "Prompt-Werkstatt fehlt"
assert "Min words" in labels and "Max words" in labels, "Wortgrenzen fehlen"
ids = [getattr(k, "elem_id", None) for k in knoten if getattr(k, "elem_id", None)]
assert len(ids) == len(set(ids)), f"doppelte elem_id: {ids}"
# Ordnerzeile und Eintragszeile: ausgerichtet, ohne gr.Form-Wrapper.
lib_row = next(
    (k for k in knoten if getattr(k, "elem_id", None) == "local_enhance_library_row"),
    None,
)
entry_row = next(
    (k for k in knoten if getattr(k, "elem_id", None) == "local_enhance_entry_row"),
    None,
)
assert lib_row is not None and entry_row is not None, "Bibliotheks-Zeilen fehlen"
zeile = [type(k).__name__ for k in (lib_row.children or [])]
eintrag = [type(k).__name__ for k in (entry_row.children or [])]
print("Bibliotheks-Zeile:", zeile)
print("Eintrags-Zeile:", eintrag)
assert zeile == ["Textbox", "Button", "Button", "UploadButton"], zeile
assert eintrag == ["Textbox", "Button", "Number", "Number"], eintrag
# Import ist als Upload verdrahtet (der Klick schreibt eine Datei in den Ordner).
konfiguration = demo.get_config_file()
uploads = [
    dependency
    for dependency in konfiguration.get("dependencies", [])
    if any(
        isinstance(target, (list, tuple)) and len(target) > 1 and target[1] == "upload"
        for target in (dependency.get("targets") or [])
    )
]
assert uploads, "Import-Upload ist nicht verdrahtet"
print("OK: vier Karten, eine Bibliotheks-Zeile, Import verdrahtet, Modell-Check, Prompt-Werkstatt.")

# --- Bypass-LoRA: Nachtragen in WanGPs LoRA-Auswahl -------------------------
print("--- Bypass-LoRA ---")
p.on_tab_outputs = []
p._current_model_line = lambda state: "**Current model:** krea2_turbo"
p.get_current_model_settings = lambda state: {"prompt": "a fox"}
werte = p.on_tab_select({})
print("Rueckgaben:", len(werte), "| LoRA-Auswahl:", werte[-1])
assert len(werte) == 3, f"erwartet 3 Ausgaben, {len(werte)}"
auswahl = werte[-1].get("value") if isinstance(werte[-1], dict) else getattr(werte[-1], "value", None)
assert auswahl and any("bypass" in str(x) for x in auswahl), f"Bypass fehlt: {auswahl}"
assert any("Bara_Style" in str(x) for x in auswahl), "eigene LoRA verloren"
print("gemischt:", p._with_bypass_lora(["krea2/Bara_Style.safetensors", "krea2/krea2bypass_balanced.safetensors"]))
print("OK: Bypass-LoRA wird ergaenzt, ohne die eigene Auswahl zu veraendern.")

# --- Prompt-Bibliothek: Helfer ---------------------------------------------
print("--- Prompt-Bibliothek ---")
main.server_config["local_enhance_prompt_dir"] = tempfile.mkdtemp(prefix="le-lib-")
main.server_config["local_enhance_template"] = "default"

assert p._prompt_name_ok("Mein Prompt")
assert p._prompt_name_ok("x" * 64) and not p._prompt_name_ok("x" * 65)
for bad in ("", "..", "../x", ".hidden", "a/b", "a\\b", "default"):
    assert not p._prompt_name_ok(bad), bad

assert p._write_prompt_entry("Mein Prompt", "hello")
assert p._read_prompt_entry("Mein Prompt").strip() == "hello"
assert p._list_prompt_names() == ["Mein Prompt"]
# Leere Datei wird uebersprungen.
Path(p._prompt_dir(), "leer.txt").write_text("   \n", encoding="utf-8")
assert p._list_prompt_names() == ["Mein Prompt"]
assert p._prompt_choices() == ["default", "Mein Prompt"]
# Gespeicherter Name gilt, Unbekanntes faellt auf default.
assert p._template_choice("Mein Prompt") == "Mein Prompt"
assert p._template_choice("gibt es nicht") == "default"
p._save_template("Mein Prompt")
assert main.server_config["local_enhance_template"] == "Mein Prompt"
assert "hello" in p._template_instructions(True, False, 0, 150)
p._save_template("default")
assert p._template_instructions(True, False, 0, 150) is None
print("OK: Bibliothek, Namensregel, leere Dateien, default-Fallback.")

# --- Migration -------------------------------------------------------------
print("--- Migration ---")
mig = tempfile.mkdtemp(prefix="le-mig-")
main.server_config["local_enhance_prompt_dir"] = mig
main.server_config.pop("local_enhance_prompt_migrated", None)
main.server_config["local_enhance_template"] = plugin._TEMPLATE_CUSTOM
p._migrate_library()
assert Path(mig, "photograf.txt").is_file(), "photograf.txt fehlt"
assert Path(mig, "sheet.txt").is_file(), "sheet.txt fehlt"
assert main.server_config["local_enhance_template"] == "photograf"
assert main.server_config["local_enhance_prompt_migrated"] is True
p._migrate_library()
assert Path(mig, "photograf.txt").read_text(encoding="utf-8").strip()
print("OK: Migration einmalig, photograf + sheet geschrieben.")

# --- Import ----------------------------------------------------------------
print("--- Import ---")
quelle = Path(tempfile.mkdtemp(prefix="le-import-"), "My Import.txt")
quelle.write_text("imported text", encoding="utf-8")
name, fehler = p._import_prompt_file(quelle)
assert fehler is None and name == "My Import", (name, fehler)
assert p._read_prompt_entry("My Import").strip() == "imported text"
name2, fehler2 = p._import_prompt_file(quelle)
assert fehler2 is None and name2 == "My Import 2", (name2, fehler2)
leer = quelle.parent / "Leer.txt"
leer.write_text("  ", encoding="utf-8")
assert p._import_prompt_file(leer)[0] is None, "leere Datei darf nicht importiert werden"
print("OK: Import uebernimmt Text, Kollision bekommt Zaehler, leere Datei wird abgelehnt.")



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

sys.path.insert(0, "/home/stefan/git/wan2gp-local-enhance")
sys.path.insert(0, "/home/stefan/git/Wan2GP")

import gradio as gr  # noqa: E402
import plugin  # noqa: E402

main = sys.modules["__main__"]
main.server_config = {
    "local_enhance_template": plugin._TEMPLATE_SHEET,
    "local_enhance_min_words": 0,
    "local_enhance_max_words": 1500,
    "llm_engines": {"deepy": "qwen35_4b"},
    "enhancer_enabled": 5,
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

assert len(karten) == 5, f"erwartet 5 Karten, gefunden {len(karten)}"
assert "Vorlage" in labels, "Vorlagen-Dropdown fehlt"
assert "Eigener Vorlagentext" in labels, "Vorlagen-Textfeld fehlt"
assert "Prompt" in labels and "Erweiterter Prompt" in labels, "Prompt-Werkstatt fehlt"
assert "Min words" in labels and "Max words" in labels, "Wortgrenzen fehlen"
ids = [getattr(k, "elem_id", None) for k in knoten if getattr(k, "elem_id", None)]
assert len(ids) == len(set(ids)), f"doppelte elem_id: {ids}"
print("OK: vier Karten, Vorlage, Wortgrenzen, Modell-Check, Prompt-Werkstatt.")

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

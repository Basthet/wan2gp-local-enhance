"""Vorschau der Enhancer-Zeile - ohne WanGP zu starten.

Baut genau die Umgebung nach, in der create_inline_button() laeuft:

    gr.Row -> [eingebauter Knopf, verstecktes gr.Text, Dropdown, Think-Checkbox]

Danach dieselbe insert_after-Mechanik wie shared/utils/plugins.py:1659.
Das Skript gibt den Komponentenbaum, die Zahl der Klick-Eingaben und die URL
der Vorschau aus. Die Vorschau laeuft, bis der Prozess beendet wird.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/ui_preview.py [port]
    # http://127.0.0.1:7899/?__theme=dark

PREVIEW_MIN/PREVIEW_MAX setzen die Startwerte der Wortgrenze: der Default
(0/1500) ergibt den Custom-Fall mit sichtbaren Zahlenfeldern, PREVIEW_MAX=150
den Preset-Fall ("short - 150 words", Felder versteckt).

Screenshot ohne Browserfenster (aus dem Plugin-Ordner):

    env -u DISPLAY chromium --headless=new --no-sandbox --disable-gpu \
      --disable-dev-shm-usage --hide-scrollbars --user-data-dir=.ui-shots/prof \
      --force-device-scale-factor=2 --virtual-time-budget=9000 \
      --window-size=780,300 \
      --screenshot=.ui-shots/minmax.png "http://127.0.0.1:7899/?__theme=dark"

Das Bild zeigt nur die Zeile in einem Nahbau der Umgebung: die Knopfreihe wird
hier von .btn_centered-Regeln aus WanGPs eigenem CSS gestuetzt, die WanGP-Theme
selbst (Farben, Abstaende) fehlt.
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import gradio as gr  # noqa: E402
import plugin as P  # noqa: E402

# _word_range() liest die Grenzen aus __main__.server_config; hier stehen
# Beispielwerte (0 = keine Untergrenze). Ueber PREVIEW_MIN/PREVIEW_MAX laesst
# sich ein Preset statt "custom" einstellen, z. B. PREVIEW_MAX=150.
server_config = {
    "local_enhance_min_words": int(os.environ.get("PREVIEW_MIN", 0)),
    "local_enhance_max_words": int(os.environ.get("PREVIEW_MAX", 1500)),
}

port = int(sys.argv[1]) if len(sys.argv) > 1 else 7899

p = P.LocalEnhancePlugin()

with gr.Blocks(title="Enhancer-Zeile") as demo:
    state = gr.State()
    prompt = gr.Textbox(label="Prompt", value="a cat sitting on a windowsill", lines=3)
    p.state = state
    p.prompt = prompt

    with gr.Row() as parent:
        builtin = gr.Button(
            "Enhance Prompt", visible=False, size="lg", scale=1,
            elem_classes="btn_centered",
        )
        hidden = gr.Text(visible=False)
        # show_label=False wie WanGP im On-Demand-Modus (wgp.py:12176) - nur so
        # zeigt die Vorschau denselben Versatz, den das Plugin ausgleicht.
        dropdown = gr.Dropdown(
            choices=["Based on Text Prompt", "Based on Image"],
            value="Based on Text Prompt",
            label="Enhance Prompt using a LLM",
            show_label=False,
            scale=5,
        )
        think = gr.Checkbox(
            label="Think", value=False, scale=1, elem_classes="cbx_centered",
        )

    with parent:
        p.create_inline_button()

    # insert_after: das zuletzt erzeugte Kind hinter den Zielknopf schieben
    target_index = parent.children.index(builtin)
    newly_added = parent.children.pop(-1)
    parent.children.insert(target_index + 1, newly_added)

    css = getattr(P, "_UI_CSS", "")
    # WanGP haelt .btn_centered in shared/gradio/ui_studio.css schmal; ohne diese
    # zwei Regeln zerdruecken die Knoepfe in Zeile 1 das Bild.
    css += (
        "#local_enhance_row .btn_centered{"
        "flex:0 0 auto !important;min-width:0 !important;width:max-content !important;}"
        "#local_enhance_row .cbx_centered{"
        "flex:0 0 auto !important;min-width:0 !important;width:max-content !important;}"
    )
    gr.HTML("<style>" + css + "</style>")

    def _dump(component, depth=0):
        classes = getattr(component, "elem_classes", None) or []
        if isinstance(classes, str):
            classes = [classes]
        print(
            "  " * depth
            + f"{type(component).__name__} "
            f"id={getattr(component, 'elem_id', None) or ''!r} "
            f"classes={list(classes)} label={getattr(component, 'label', None)!r} "
            f"show_label={getattr(component, 'show_label', None)!r}"
        )
        for child in getattr(component, "children", None) or []:
            _dump(child, depth + 1)

    print("=== Komponentenbaum ===")
    _dump(parent)
    controls = p._control_components()
    print("=== Regler ===")
    print(
        "controls:", [type(c).__name__ for c in controls],
        "-> click-inputs:", 2 + len(controls),
    )

demo.launch(
    server_name="127.0.0.1", server_port=port, quiet=True, prevent_thread_lock=True,
)
print(f"[dev/ui_preview] http://127.0.0.1:{port}/?__theme=dark", flush=True)
while True:
    time.sleep(1)

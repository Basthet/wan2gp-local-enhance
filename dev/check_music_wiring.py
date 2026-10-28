"""Prueft die Verdrahtung der Inline-Knoepfe fuer Modelle mit Alt-Text.

YuE2 hat zwei Textfelder: `prompt` (Lyrics) und `alt_prompt` (Music Style).
Das Plugin haengt das zweite Feld als Klick-Eingabe an alle drei Knoepfe und
schreibt es bei Ketten wie `T1,B2O` zurueck. Geprueft wird die Zahl der
Eingaben und Ausgaben in der Gradio-Konfiguration - ohne WanGP-Start.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.venv/bin/python ~/git/wan2gp-local-enhance/dev/check_music_wiring.py
"""

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import gradio as gr  # noqa: E402

import plugin as P  # noqa: E402

server_config = {
    "local_enhance_prompt_dir": tempfile.mkdtemp(prefix="le-music-wiring-"),
    "local_enhance_prompt_migrated": True,
}

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"PASS  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


def build(with_alt):
    p = P.LocalEnhancePlugin()
    with gr.Blocks() as demo:
        state = gr.State({"model_type": "yue2"})
        prompt = gr.Textbox(label="Lyrics")
        alt = gr.Textbox(label="Music Style") if with_alt else None
        p.state = state
        p.prompt = prompt
        if alt is not None:
            p.alt_prompt = alt
        with gr.Row() as parent:
            builtin = gr.Button("Enhance Prompt")
            hidden = gr.Text(value="", visible=False)
            gr.Dropdown(choices=["Lyrics"], value="Lyrics")
            gr.Checkbox(label="Think", value=False)
            p.prompt_enhancer = hidden
            # Wie insert_after() im Host: create_inline_button() laeuft im
            # Elterncontainer der fremden Zeile.
            p.create_inline_button()
    return p, demo


def dependency_for(config, elem_id):
    registry = {component["id"]: component for component in config["components"]}
    target = next(
        component["id"]
        for component in config["components"]
        if component.get("props", {}).get("elem_id") == elem_id
    )
    return next(
        dependency
        for dependency in config["dependencies"]
        if any(
            isinstance(item, (list, tuple))
            and len(item) > 1
            and item[0] == target
            and item[1] == "click"
            for item in (dependency.get("targets") or [])
        )
    )


p, demo = build(with_alt=True)
config = demo.get_config_file()

remote = dependency_for(config, "local_enhance_remote_btn")
local = dependency_for(config, "local_enhance_local_btn")
api = dependency_for(config, "local_enhance_local_api_btn")

# state + prompt + mode + Think + Min + Max + alt = 7 (ohne Bilder).
check("Remote-Knopf: 7 Eingaben mit Alt-Text", len(remote["inputs"]) == 7, f"-> {len(remote['inputs'])}")
check("Lokaler Knopf: 7 Eingaben ohne Bild-Eingaben", len(local["inputs"]) == 7, f"-> {len(local['inputs'])}")
check("Local-API-Knopf: 7 Eingaben mit Alt-Text", len(api["inputs"]) == 7, f"-> {len(api['inputs'])}")
check("Remote-Knopf: Prompt + Alt als Ausgaben", len(remote["outputs"]) == 2, f"-> {len(remote['outputs'])}")
check("Lokaler Knopf: Prompt + Alt als Ausgaben", len(local["outputs"]) == 2, f"-> {len(local['outputs'])}")
check("Local-API-Knopf: Prompt + Alt + Knopf", len(api["outputs"]) == 3, f"-> {len(api['outputs'])}")

p2, demo2 = build(with_alt=False)
config2 = demo2.get_config_file()
remote2 = dependency_for(config2, "local_enhance_remote_btn")
local2 = dependency_for(config2, "local_enhance_local_btn")
api2 = dependency_for(config2, "local_enhance_local_api_btn")
check("ohne Alt: Remote 6 Eingaben", len(remote2["inputs"]) == 6, f"-> {len(remote2['inputs'])}")
check("ohne Alt: Lokal 6 Eingaben", len(local2["inputs"]) == 6, f"-> {len(local2['inputs'])}")
check("ohne Alt: Local-API 6 Eingaben", len(api2["inputs"]) == 6, f"-> {len(api2['inputs'])}")
check("ohne Alt: Remote nur Prompt", len(remote2["outputs"]) == 1, f"-> {len(remote2['outputs'])}")
check("ohne Alt: Lokal nur Prompt", len(local2["outputs"]) == 1, f"-> {len(local2['outputs'])}")
check("ohne Alt: Local-API Prompt + Knopf", len(api2["outputs"]) == 2, f"-> {len(api2['outputs'])}")

print(f"\n{PASS} PASS, {FAIL} FAIL")
if FAIL:
    raise SystemExit(1)

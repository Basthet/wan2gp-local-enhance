"""Prueft den Music-Style-Tag-Baukasten ohne GPU und ohne WanGP.

Geprueft wird:
  * `_compose_music_style` (Reihenfolge, Dedupe, instrumental-Regel),
  * `_music_style_visible` (YuE2/ACE ja, TTS/Image nein),
  * die Tag-Datei im Prompt-Ordner (eigene Listen schlagen die Defaults),
  * die Karte in `create_ui`: fuenf Karten, Tag-Dropdowns, Vorschau, Buttons,
  * `on_tab_select` blendet die Karte je nach Modell ein/aus.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.venv/bin/python ~/git/wan2gp-local-enhance/dev/check_music_tags.py
"""

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import gradio as gr  # noqa: E402
import plugin  # noqa: E402

main = sys.modules["__main__"]
prompt_dir = tempfile.mkdtemp(prefix="le-tags-")
main.server_config = {
    "local_enhance_template": "default",
    "local_enhance_min_words": 0,
    "local_enhance_max_words": 1500,
    "llm_engines": {"deepy": "qwen35_4b"},
    "enhancer_enabled": 5,
    "local_enhance_prompt_dir": prompt_dir,
    "local_enhance_prompt_migrated": True,
}
main.models_def = {
    "yue2": {
        "name": "Music YuE2 3B",
        "audio_only": True,
        "prompt_class": "Lyrics",
        "alt_prompt": {"label": "Music Style"},
    },
    "ace_step": {
        "name": "Music ACE-Step",
        "audio_only": True,
        "prompt_class": "Lyrics",
        "alt_prompt": {"label": "Music Caption"},
    },
    "moss_tts": {
        "name": "TTS Moss",
        "audio_only": True,
        "prompt_class": "Speech",
        "alt_prompt": {"label": "Spoken Language"},
    },
    "krea2": {"name": "Krea 2", "image_outputs": True},
}
main.get_model_handler = lambda model_type, *a, **k: None

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


# 1. Komposition: Reihenfolge und Inhalt.
text = plugin.LocalEnhancePlugin._compose_music_style(
    "German", ["acoustic pop"], "warm male vocal", ["piano", "strings"],
    ["hopeful"], "90 BPM", ["clean"], "analog tape",
)
check(
    "Komposition in fester Reihenfolge",
    text == (
        "German, warm male vocal, acoustic pop, piano, strings, hopeful, "
        "90 BPM, clean, analog tape"
    ),
    f"-> {text!r}",
)

# 2. Instrumental: Sprache/Gesang fallen weg, instrumental steht vorn.
text = plugin.LocalEnhancePlugin._compose_music_style(
    "German", ["ambient"], "instrumental (no vocals)", ["piano"], [], "60 BPM", [], "",
)
check(
    "instrumental entfernt Sprache und Gesang",
    text == "instrumental, ambient, piano, 60 BPM" and "German" not in text,
    f"-> {text!r}",
)

# 3. Dedupe ohne Ruecksicht auf Gross-/Kleinschreibung.
text = plugin.LocalEnhancePlugin._compose_music_style(
    "", ["pop", "Pop"], "", ["piano", "Piano"], [], "", [], "",
)
check("doppelte Tags werden entfernt", text == "pop, piano", f"-> {text!r}")

# 4. Vorschau leer, wenn nichts gewaehlt ist.
text = plugin.LocalEnhancePlugin._compose_music_style("", [], "", [], [], "", [], "")
check("leere Auswahl ergibt leeren Text", text == "", f"-> {text!r}")

# 5. Sichtbarkeit: Musik ja, TTS/Image nein.
check(
    "YuE2 zeigt die Karte",
    plugin.LocalEnhancePlugin._music_style_visible(main.models_def["yue2"]),
)
check(
    "ACE-Step zeigt die Karte",
    plugin.LocalEnhancePlugin._music_style_visible(main.models_def["ace_step"]),
)
check(
    "TTS 'Spoken Language' zeigt die Karte nicht",
    not plugin.LocalEnhancePlugin._music_style_visible(main.models_def["moss_tts"]),
)
check(
    "Bildmodell zeigt die Karte nicht",
    not plugin.LocalEnhancePlugin._music_style_visible(main.models_def["krea2"]),
)

# 6. Tag-Datei im Prompt-Ordner: eigene Listen gewinnen, kaputte Datei nicht.
tag_path = Path(prompt_dir) / plugin._MUSIC_TAG_FILE
tag_path.write_text(
    json.dumps({"genre": ["my genre", "my genre", "other"]}), encoding="utf-8"
)
groups = plugin.LocalEnhancePlugin._music_tag_groups()
check(
    "eigene Tag-Datei wird gelesen und dedupliziert",
    groups["genre"] == ["my genre", "other"] and groups["mood"],
    f"-> {groups['genre']}",
)
tag_path.write_text("{kaputt", encoding="utf-8")
groups = plugin.LocalEnhancePlugin._music_tag_groups()
check(
    "kaputte Tag-Datei faellt auf Defaults zurueck",
    groups["genre"] == plugin._MUSIC_TAG_DEFAULT["genre"],
    f"-> {groups['genre'][:2]}",
)
tag_path.unlink()


# 7. Apply/Append/Clear: Feld schreiben, anhaengen, leeren.
applied = plugin.LocalEnhancePlugin._music_style_apply("pop, piano")
check("Apply schreibt den Text", applied.get("value") == "pop, piano", f"-> {applied}")
appended = plugin.LocalEnhancePlugin._music_style_append("old style", "pop, piano")
check(
    "Append haengt mit Komma an",
    appended.get("value") == "old style, pop, piano",
    f"-> {appended}",
)
appended = plugin.LocalEnhancePlugin._music_style_append("", "pop")
check("Append auf leeres Feld setzt den Text", appended.get("value") == "pop", f"-> {appended}")
cleared = plugin.LocalEnhancePlugin._music_style_clear()
check("Clear leert neun Komponenten", len(cleared) == 9, f"-> {len(cleared)}")

# 8. Karte in create_ui: mit alt_prompt und Audio-Modell.
def build_tab():
    p = plugin.LocalEnhancePlugin()
    p.state = gr.State({"model_type": "yue2"})
    p.refresh_form_trigger = gr.Textbox(visible=False)
    p.prompt = gr.Textbox()
    p.alt_prompt = gr.Textbox(label="Music Style")
    p.prompt_enhancer = gr.Textbox(visible=False)
    p.prompt_enhancer_btn = gr.Button()
    p.get_current_model_settings = lambda state: {
        "prompt": "song idea", "alt_prompt": "current style",
    }
    p.get_state_model_type = lambda state: (
        state.get("model_type", "yue2") if isinstance(state, dict) else "yue2"
    )
    p.get_model_def = lambda model_type: main.models_def.get(model_type, {})
    p.get_model_settings = lambda state, model_type: {}
    p.get_prompt_enhancer_choices = lambda *a, **k: (
        [("Lyrics", "T1")], "", None
    )
    p.activated_loras = None
    for name in plugin._IMAGE_INPUT_NAMES:
        setattr(p, name, None)
    with gr.Blocks() as demo:
        with gr.Row():
            gr.Button("eingebaut")
            gr.Textbox(visible=False)
            gr.Dropdown(choices=["T1"], show_label=False)
            p._think_checkbox = gr.Checkbox(label="Think")
            p.create_inline_button()
        p.create_ui(None)
    return p, demo


p, demo = build_tab()


def alle(block, out):
    out.append(block)
    for child in getattr(block, "children", None) or []:
        alle(child, out)
    return out


nodes = alle(demo, [])
cards = [
    node for node in nodes
    if "le-card" in (getattr(node, "elem_classes", None) or [])
]
labels = [str(getattr(node, "label", "")) for node in nodes if getattr(node, "label", None)]
buttons = [
    str(getattr(node, "value", ""))
    for node in nodes
    if type(node).__name__ in ("Button", "UploadButton")
]
check("fuenf Karten mit Music Style", len(cards) == 5, f"-> {len(cards)}")
for label in (
    "Language", "Genre", "Vocals", "Instruments", "Mood", "Tempo",
    "Production", "Extra style notes", "Finished Music Style",
):
    check(f"Label {label!r} vorhanden", label in labels)
for button in ("Apply to Music Style", "Append", "Clear tags"):
    check(f"Knopf {button!r} vorhanden", button in buttons)

# 8. on_tab_select: Karte bei YuE2 sichtbar, bei Krea 2 verborgen.
werte = p.on_tab_select({"model_type": "yue2"})
check(
    "on_tab_select liefert drei Ausgaben (Prompt, Modell, Karte)",
    len(werte) == 3 and werte[-1].get("visible") is True,
    f"-> {len(werte)} / {werte[-1] if werte else None}",
)
werte = p.on_tab_select({"model_type": "krea2"})
check(
    "on_tab_select verbirgt die Karte bei einem Bildmodell",
    len(werte) == 3 and werte[-1].get("visible") is False,
    f"-> {werte[-1] if werte else None}",
)

print(f"\n{PASS} PASS, {FAIL} FAIL")
if FAIL:
    raise SystemExit(1)

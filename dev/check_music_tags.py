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
        "audio_prompt_type_sources": {
            "selection": ["0", "A", "C"],
            "labels": {"0": "New Composition", "A": "Use Score from Audio",
                       "C": "Cover (Score from Audio, fixed tempo)"},
            "letters_filter": "012AC",
        },
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

# 8. Lyrics-Struktur aus ABC und als Kontext vor den Lyrics.
abc = """X:1
% intro
% verse
% chorus
% verse and pre-chorus
% chorus
% fade-out
"""
structure = plugin.LocalEnhancePlugin._parse_abc_structure(abc)
check(
    "ABC-Struktur wird zu YuE2-Sections",
    structure == "[Intro]\n[Verse]\n[Chorus]\n[Verse]\n[Pre-Chorus]\n"
                 "[Chorus]\n[Outro]",
    f"-> {structure!r}",
)
lyrics = plugin.LocalEnhancePlugin._with_lyrics_structure(
    "a song about the sea", structure
)
check(
    "Struktur wird vor die Lyrics gelegt",
    lyrics.startswith("Write the lyrics for exactly this section structure")
    and "[Intro]\n[Verse]" in lyrics
    and lyrics.endswith("a song about the sea"),
    f"-> {lyrics[:80]!r}",
)
check(
    "ohne Struktur bleibt der Prompt unveraendert",
    plugin.LocalEnhancePlugin._with_lyrics_structure("a song", "") == "a song",
)
check(
    "_mode_writes_lyrics erkennt T1 und T1,B2O, nicht B2O",
    plugin.LocalEnhancePlugin._mode_writes_lyrics("T1")
    and plugin.LocalEnhancePlugin._mode_writes_lyrics("T1,B2O")
    and not plugin.LocalEnhancePlugin._mode_writes_lyrics("B2O"),
)

# 9. Cover: Label, Dauer aus der Quelle, versteckter Source-Text.
check(
    "_is_lyrics_model erkennt YuE2, nicht TTS/Image",
    plugin.LocalEnhancePlugin._is_lyrics_model(main.models_def["yue2"])
    and not plugin.LocalEnhancePlugin._is_lyrics_model(main.models_def["moss_tts"])
    and not plugin.LocalEnhancePlugin._is_lyrics_model(main.models_def["krea2"]),
)
check(
    "Zeile heisst bei YuE2 Enhance Lyrics",
    "Enhance Lyrics" in plugin.LocalEnhancePlugin._row_label_html(main.models_def["yue2"])
    and "Enhance Prompt" in plugin.LocalEnhancePlugin._row_label_html(main.models_def["krea2"]),
)
import wave

wav_path = Path(prompt_dir) / "source.wav"
with wave.open(str(wav_path), "wb") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(16000)
    handle.writeframes(b"\x00\x00" * 32000)
duration = plugin.LocalEnhancePlugin._source_audio_duration(str(wav_path))
check("Dauer der Quelldatei wird gelesen", duration is not None and abs(duration - 2.0) < 0.1, f"-> {duration}")

instance = plugin.LocalEnhancePlugin()
instance.get_state_model_type = lambda state: "yue2"
instance.audio_prompt_type = gr.Text(value="A2")
check(
    "versteckter Source-Text wird auf A gesetzt",
    instance._source_hidden_value("A", {"model_type": "yue2"}) == "A",
    f"-> {instance._source_hidden_value('A', {'model_type': 'yue2'})!r}",
)
check(
    "versteckter Source-Text wird auf 0 gesetzt",
    instance._source_hidden_value("0", {"model_type": "yue2"}) == "0",
    f"-> {instance._source_hidden_value('0', {'model_type': 'yue2'})!r}",
)
check(
    "versteckter Source-Text wird auf C gesetzt",
    instance._source_hidden_value("C", {"model_type": "yue2"}) == "C",
    f"-> {instance._source_hidden_value('C', {'model_type': 'yue2'})!r}",
)

# 10. Karte in create_ui: mit alt_prompt und Audio-Modell.
def build_tab():
    p = plugin.LocalEnhancePlugin()
    p.state = gr.State({"model_type": "yue2"})
    p.refresh_form_trigger = gr.Textbox(visible=False)
    p.prompt = gr.Textbox()
    p.alt_prompt = gr.Textbox(label="Music Style")
    p.prompt_enhancer = gr.Textbox(visible=False)
    p.audio_prompt_type_sources = gr.Dropdown(
        choices=[
            ("New Composition", "0"),
            ("Use Score from Audio", "A"),
            ("Cover (Score from Audio, fixed tempo)", "C"),
        ],
        value="0",
    )
    p.audio_prompt_type = gr.Text(value="0", visible=False)
    p.audio_guide = gr.Audio(type="filepath")
    p.duration_seconds = gr.Slider(1, 600, value=120)
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
    "Section plan (optional)", "Load from ABC", "Create Cover",
):
    check(f"Label {label!r} vorhanden", label in labels)
for button in ("Apply to Music Style", "Append", "Clear tags"):
    check(f"Knopf {button!r} vorhanden", button in buttons)

cover_updates = p._cover_mode_update(True, {"model_type": "yue2"}, str(wav_path))
check(
    "Cover setzt Quelle C, Dauer 2s und versteckt Tempo",
    len(cover_updates) == 6
    and cover_updates[1].get("value") == "C"
    and cover_updates[2].get("value") == "C"
    and cover_updates[3].get("value") == 2
    and cover_updates[4].get("visible") is False,
    f"-> {cover_updates}",
)

# 11. on_tab_select: Karte bei YuE2 sichtbar, bei Krea 2 verborgen.
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

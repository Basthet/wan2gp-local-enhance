"""Prueft das zweite Textfeld (YuE2: Music Style) ohne GPU und ohne WanGP.

Der Host legt fuer Modelle mit getrennten Eingaben ein zweites Feld `alt_prompt`
an (wgp.py:12672-12692). Bei YuE2 stehen die Lyrics in `prompt`, der Music
Style in `alt_prompt`; die Enhancer-Auswahl kennt `T1` (Lyrics), `B2O` (Music
Style) und `T1,B2O` (beide nacheinander, models/TTS/yue2/yue2_handler.py:270).

Geprueft wird:
  * `_effective_mode` verwirft einen veralteten Modus des vorigen Modells und
    nimmt den Modell-Default (sonst fehlt YuE2 das Profil `1` und statt Lyrics
    entsteht eine allgemeine Audio-Stilbeschreibung),
  * `_run_enhance_steps` schreibt genau das Feld, das der Modus nennt,
  * die Kette `T1,B2O` reicht die neuen Lyrics als JSON an den Style-Schritt,
  * `_split_alt_input` trennt den Alt-Text von den Reglern,
  * `_field_note` nennt die geschriebenen Felder.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.venv/bin/python ~/git/wan2gp-local-enhance/dev/check_music_fields.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import plugin as P  # noqa: E402
from shared.prompt_enhancer import chaining  # noqa: E402

# `_main()` liest aus dem laufenden Hauptmodul - hier ist das dieses Skript.
# Die echte Chaining-Klasse wird direkt gesetzt, damit der Test dieselben
# Regeln benutzt wie der Host (wgp.py:133).
prompt_enhancer_chaining = chaining

YU_E2 = {
    "audio_only": True,
    "prompt_class": "Lyrics",
    "alt_prompt": {"label": "Music Style"},
    "alt_prompt_inherits_prompt_paragraphs": True,
    "prompt_enhancer_def": {
        "selection": ["T1", "B2O", "T1,B2O", "B3", "B4O", "B3,B4O"],
        "labels": {
            "T1": "Lyrics",
            "B2O": "Music Style",
            "T1,B2O": "Lyrics then Music Style",
            "B3": "Instrumental Section Plan",
            "B4O": "Instrumental Music Style",
            "B3,B4O": "Instrumental Plan then Music Style",
        },
        "default": "",
    },
}


def get_prompt_enhancer_choices(model_def, audio_only=False, image_mode=0, include_disabled=True, **_kwargs):
    """Stub wie WanGP: Disabled + Labels aus prompt_enhancer_def."""
    model_def = model_def if isinstance(model_def, dict) else {}
    choices = [("Disabled", "")] if include_disabled else []
    definition = model_def.get("prompt_enhancer_def")
    if definition is not None:
        choices += [
            (label, key) for key, label in (definition.get("labels") or {}).items()
        ]
        return choices, definition.get("default") or "", definition
    selection = model_def.get(
        "prompt_enhancer_choices_allowed", ["T"] if audio_only else ["T", "TI"]
    )
    choices += [(value, value) for value in selection]
    return choices, "", None


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


# 1. Veralteter Live-Modus: "T" passt nicht zu YuE2 -> T1 (Lyrics).
stale = P.LocalEnhancePlugin._effective_mode("T", YU_E2, True, 0)
check("veralteter Modus faellt auf T1 (Lyrics) zurueck", stale == "T1", f"-> {stale!r}")

# 2. Leerer Live-Wert -> Modell-Default, ebenfalls T1.
empty = P.LocalEnhancePlugin._effective_mode("", YU_E2, True, 0)
check("leerer Live-Wert ergibt T1", empty == "T1", f"-> {empty!r}")

# 3. Gueltige Kette bleibt erhalten, Denken bleibt erhalten.
chain_mode = P.LocalEnhancePlugin._effective_mode("T1,B2O", YU_E2, True, 0)
think_mode = P.LocalEnhancePlugin._effective_mode("T1K", YU_E2, True, 0)
check(
    "gueltiger Modus bleibt, K bleibt",
    chain_mode == "T1,B2O" and think_mode == "T1K",
    f"-> {chain_mode!r} / {think_mode!r}",
)

# 4. Feldnamen fuer die Statuszeile.
check(
    "_field_labels liest Lyrics/Music Style",
    P.LocalEnhancePlugin._field_labels(YU_E2) == ("Lyrics", "Music Style"),
    f"-> {P.LocalEnhancePlugin._field_labels(YU_E2)}",
)

# 5. _split_alt_input: Alt-Text ist die letzte Eingabe vor den Bildern, hier
#    ohne Bilder also das letzte Element.
instance = P.LocalEnhancePlugin()
instance.alt_prompt = object()
alt_value, rest = instance._split_alt_input((True, 100, 350, "warm pop"))
check(
    "_split_alt_input trennt den Alt-Text",
    alt_value == "warm pop" and tuple(rest) == (True, 100, 350),
    f"-> {alt_value!r} / {rest}",
)
no_alt = P.LocalEnhancePlugin()
alt_empty, rest_empty = no_alt._split_alt_input((True, 100, 350))
check(
    "_split_alt_input ohne Komponente laesst alles stehen",
    alt_empty == "" and tuple(rest_empty) == (True, 100, 350),
    f"-> {alt_empty!r} / {rest_empty}",
)

# 6. _run_enhance_steps: Einzelschritt T1 schreibt nur den Prompt.
calls = []


def fake_process(model_type, model_def, mode, values, *args, **kwargs):
    calls.append((mode, list(values), kwargs))
    if mode.startswith("T"):
        return ["[Verse]\nNew lyrics"]
    return ["warm pop, 90 BPM"]


prompt_out, alt_out = P.LocalEnhancePlugin._run_enhance_steps(
    fake_process,
    "yue2",
    YU_E2,
    "T1",
    "a song about the sea",
    "warm pop",
    False,
    True,
    None,
    "instructions",
    1536,
    {},
)
check(
    "T1 schreibt nur den Prompt",
    prompt_out.startswith("[Verse]") and alt_out == ""
    and len(calls) == 1
    and calls[0][0] == "T1"
    and calls[0][1] == ["a song about the sea"],
    f"-> {prompt_out!r} / {alt_out!r} / {calls}",
)

# 7. B2O schreibt nur den Music Style und bekommt beide Felder als JSON.
calls.clear()
prompt_out, alt_out = P.LocalEnhancePlugin._run_enhance_steps(
    fake_process,
    "yue2",
    YU_E2,
    "B2O",
    "[Verse]\nOld lyrics",
    "warm pop",
    False,
    True,
    None,
    "instructions",
    384,
    {},
)
payload = json.loads(calls[0][1][0]) if calls else {}
check(
    "B2O schreibt nur den Music Style",
    prompt_out == "" and alt_out == "warm pop, 90 BPM",
    f"-> {prompt_out!r} / {alt_out!r}",
)
check(
    "B2O bekommt prompt + alt_prompt als JSON",
    payload.get("prompt") == "[Verse]\nOld lyrics"
    and payload.get("alt_prompt") == "warm pop"
    and payload.get("requested_output") == "alt_prompt",
    f"-> {payload!r}",
)

# 8. Kette T1,B2O: erst Lyrics, dann Style mit den NEUEN Lyrics als Kontext.
calls.clear()


def chain_process(model_type, model_def, mode, values, *args, **kwargs):
    calls.append((mode, list(values), kwargs))
    if mode.startswith("T"):
        return ["[Verse]\nFresh lyrics"]
    return ["warm pop, 92 BPM"]


prompt_out, alt_out = P.LocalEnhancePlugin._run_enhance_steps(
    chain_process,
    "yue2",
    YU_E2,
    "T1,B2O",
    "a song about the sea",
    "warm pop",
    False,
    True,
    None,
    "instructions",
    1536,
    {},
)
style_payload = json.loads(calls[1][1][0]) if len(calls) > 1 else {}
check(
    "Kette T1,B2O schreibt beide Felder",
    prompt_out == "[Verse]\nFresh lyrics" and alt_out == "warm pop, 92 BPM",
    f"-> {prompt_out!r} / {alt_out!r}",
)
check(
    "Kette reicht die neuen Lyrics an B2O weiter",
    [call[0] for call in calls] == ["T1", "B2O"]
    and style_payload.get("prompt") == "[Verse]\nFresh lyrics"
    and style_payload.get("alt_prompt") == "warm pop",
    f"-> {[call[0] for call in calls]} / {style_payload!r}",
)
check(
    "B2O-Schritt bekommt batch_images=True (wie der Host)",
    len(calls) > 1 and calls[1][2].get("batch_images") is True,
    f"-> {calls[1][2] if len(calls) > 1 else None}",
)

# 9. Statuszeile nennt die geschriebenen Felder.
note = P.LocalEnhancePlugin._field_note(YU_E2, True, True)
check("_field_note nennt Lyrics + Music Style", note == ", fields: Lyrics + Music Style", f"-> {note!r}")

print(f"\n{PASS} PASS, {FAIL} FAIL")
if FAIL:
    raise SystemExit(1)

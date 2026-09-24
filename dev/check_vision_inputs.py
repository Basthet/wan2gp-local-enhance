"""Prueft die Bild-Aufbereitung des lokalen Enhancers - ohne GPU und ohne WanGP.

Der Test taeuscht die WanGP-Helfer vor, die das Plugin ueber _main() holt: dieses
Skript ist beim Start das Modul __main__, also findet _main() die Funktionen hier.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/check_vision_inputs.py

Geprueft werden die Faelle aus AGENTS.md ("Bilder"): Modus ohne "I", Startbild,
Endbild, zwei Referenzen, nur Control Image, fake_start_image (On-Demand-Paritaet),
Fenstermodell, Fallback bei mehreren Startbildern, fehlendes convert_image sowie
die Bild-Anweisungen (IT2I/IT2V), die Trennung der Klick-Eingaben - mit und ohne
Think-Checkbox - und die Modus-Eingabe (_effective_mode/_split_mode_input).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import plugin as P  # noqa: E402

# --- WanGP-Helfer, die das Plugin per _main() erwartet -----------------------


def convert_image(value):
    return ("IMG", value)


def get_computed_fps(*_args):
    return 16


def get_base_model_type(_model_type):
    return "test"


def estimate_first_window_overlap_frames(image_start, *_args):
    return 1 if image_start is not None else 0


def prompt_enhancer_outputs_multiple_prompts(mode):
    return "M" in str(mode)


def get_prompt_enhancer_choices(model_def, audio_only, image_mode, include_disabled=True, **_kwargs):
    """Stub wie WanGP (wgp.py:10876-10889).

    Nachgebaut ist nur, was _resolve_mode() braucht: eine eigene
    `prompt_enhancer_def` im model_def liefert deren `default` und ihre Labels,
    sonst zaehlt `prompt_enhancer_choices_allowed` (Default "T", bei audio_only
    nur "T"). `include_disabled` stellt "Disabled" voran - _resolve_mode() ruft
    ohne diesen Eintrag auf."""
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
    labels = {
        "T": "Based on Text Prompt Content",
        "TI": "Based on Text Prompt and Images",
    }
    choices += [(labels.get(value, value), value) for value in selection]
    return choices, "", None


_BASE_SETTINGS = {
    "image_mode": 1,
    "multi_prompts_gen_type": "FG",
    "multi_images_gen_type": 0,
    "image_prompt_type": [],
    "video_prompt_type": [],
    "image_start": None,
    "image_end": None,
    "image_refs": None,
    "image_guide": None,
    "video_length": 1,
    "sliding_window_size": 0,
    "sliding_window_overlap": 0,
    "sliding_window_discard_last_frames": 0,
    "frames_positions": "",
    "force_fps": "auto",
    "video_guide": None,
    "video_source": None,
    "keep_frames_video_source": "",
}

_FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        _FAILURES.append(name)


def images_for(mode, live, model_def=None, settings=None):
    return P.LocalEnhancePlugin._enhancer_images(
        settings if settings is not None else dict(_BASE_SETTINGS),
        model_def or {"image_mode": 1},
        "test_model_type",
        mode,
        False,
        "a cat",
        live,
    )


def main():
    # 1. Modus ohne "I": Bilder bleiben unberuehrt.
    result = images_for("T", {"image_start": [("start.png",)], "image_prompt_type": ["S"]})
    check(
        "Textmodus ignoriert Bilder",
        result.image_start is None and result.image_refs is None
        and result.labels == () and result.kwargs == {},
        f"-> {result}",
    )

    # 2. Startbild -> Kontext mit Label.
    result = images_for("TI", {"image_start": [("start.png",)], "image_prompt_type": ["S"]})
    check(
        "Startbild wird zum Kontext",
        result.labels == ("start image",)
        and "image_contexts" in result.kwargs
        and result.image_start is None
        and len(result.kwargs["image_contexts"][0].images) == 1,
        f"-> {result}",
    )

    # 3. Endbild als Ersatz, wenn kein Startbild aktiv ist.
    result = images_for("TI", {"image_end": [("end.png",)], "image_prompt_type": ["E"]})
    check(
        "Endbild als Anker",
        result.labels == ("end image",) and "image_contexts" in result.kwargs,
        f"-> {result}",
    )

    # 4. Zwei Referenzen: beide mit eigenem Label.
    result = images_for(
        "TI",
        {"image_refs": [("r1.png",), ("r2.png",)], "video_prompt_type": ["I"]},
    )
    check(
        "Zwei Referenzen mit Labels",
        result.labels == ("Image reference no 1", "Image reference no 2"),
        f"-> {result.labels}",
    )

    # 5. Nur Control Image (Bildmodelle mit "V").
    result = images_for("TI", {"image_guide": "PIL-LIKE", "video_prompt_type": ["V"]})
    check(
        "Control Image allein",
        result.labels == ("Control Image",)
        and len(result.kwargs["image_contexts"][0].images) == 1,
        f"-> {result}",
    )

    # 6. fake_start_image: der On-Demand-Pfad filtert ihn NICHT (wgp.py:6633 und
    #    images.py:233 nutzen das Bild); nur der Auto-Pfad verwirft ihn
    #    (wgp.py:7540). Der Test dokumentiert diese Paritaet mit WanGP.
    result = images_for(
        "TI",
        {"image_start": [("start.png",)], "image_prompt_type": ["S"]},
        model_def={"image_mode": 1, "fake_start_image": True},
    )
    check(
        "fake_start_image wie im WanGP-On-Demand-Pfad",
        result.labels == ("start image",),
        f"-> {result.labels}",
    )

    # 7. Fenstermodell: prepare_manual nimmt den ersten Fensteranker.
    sliding_settings = dict(
        _BASE_SETTINGS,
        image_mode=0,
        video_length=25,
        sliding_window_size=25,
        sliding_window_overlap=4,
    )
    result = images_for(
        "TI",
        {"image_start": [("a.png",), ("b.png",)], "image_prompt_type": ["S"]},
        model_def={
            "image_mode": 0,
            "sliding_window": True,
            "frames_minimum": 5,
            "frames_steps": 4,
            "latent_size": 16,
            "frames_offset": 1,
            "prompt_slash_commands": [],
        },
        settings=sliding_settings,
    )
    check(
        "Fenstermodell nimmt den ersten Anker",
        result.labels == ("start image",) and "image_contexts" in result.kwargs,
        f"-> {result}",
    )

    # 8. Fallback im Fenstermodell: dort haelt er sich an prepare_manuals
    #    fake_start_image-Regel (images.py:201) - kein Bild, kein Label.
    from shared.prompt_enhancer import images as shared_images

    saved_prepare = shared_images.prepare_manual

    def _broken_prepare_manual(*_args, **_kwargs):
        raise RuntimeError("prepare_manual failed")

    shared_images.prepare_manual = _broken_prepare_manual
    try:
        result = images_for(
            "TI",
            {"image_start": [("a.png",)], "image_prompt_type": ["S"]},
            model_def={
                "image_mode": 0,
                "sliding_window": True,
                "fake_start_image": True,
                "frames_minimum": 5,
                "frames_steps": 4,
                "latent_size": 16,
                "frames_offset": 1,
                "prompt_slash_commands": [],
            },
            settings=sliding_settings,
        )
    finally:
        shared_images.prepare_manual = saved_prepare
    check(
        "Fallback verwirft fake_start_image im Fenstermodell",
        result.labels == () and result.image_start is None,
        f"-> {result}",
    )

    # 9. Mehrere Startbilder (Nicht-Fenster-Modell): prepare_manual wirft
    #    ("Multiple Start Images require matching images and text prompts",
    #    images.py:232) -> Fallback auf das erste Bild, ohne Kontexte.
    result = images_for(
        "TI",
        {"image_start": [("a.png",), ("b.png",)], "image_prompt_type": ["S"]},
    )
    check(
        "Fallback ohne Kontexte",
        result.labels == ("start image",)
        and result.image_start == [("IMG", "a.png")]
        and "image_contexts" not in result.kwargs,
        f"-> {result}",
    )

    # 10. Ohne convert_image() bleibt der Klick text-only statt zu crashen.
    saved = globals()["convert_image"]
    globals()["convert_image"] = None
    try:
        result = images_for("TI", {"image_start": [("start.png",)], "image_prompt_type": ["S"]})
    finally:
        globals()["convert_image"] = saved
    check(
        "fehlendes convert_image degradiert",
        result.labels == () and result.kwargs == {},
        f"-> {result}",
    )

    # 11. Bild-Anweisungen (IT2x) und Wortgrenze.
    with_images = P.LocalEnhancePlugin._fallback_instructions(
        True, False, 0, 300, with_images=True
    )
    without_images = P.LocalEnhancePlugin._fallback_instructions(
        True, False, 0, 300, with_images=False
    )
    check(
        "IT2I-Anweisungen mit Bildern",
        "caption of an image" in with_images and "Keep within 300 words." in with_images,
        "-> IT2I-Text fehlt",
    )
    check(
        "T2I-Anweisungen ohne Bilder",
        "caption of an image" not in without_images
        and "Keep within 300 words." in without_images,
        "-> T2I-Text falsch",
    )

    # 12. Status-Hinweis.
    note = P.LocalEnhancePlugin._image_note
    check(
        "_image_note",
        note(()) == ""
        and note(("start image",)) == ", images: start image"
        and note(("a", "b", "c", "d")) == ", 4 images",
        f"-> {note(('a',))!r}",
    )

    # 13. Positions-Trennung der Klick-Eingaben (Regler zuerst, dann Bilder).
    #     Vor den Bildern stehen nur die real moeglichen Regler: Think, Min, Max.
    instance = P.LocalEnhancePlugin()
    instance._think_checkbox = "think"
    instance._min_words_field = "min"
    instance._max_words_field = "max"
    instance.image_start = "IMG-START"
    instance.video_prompt_type = "FLAGS"
    controls, images = instance._split_image_inputs(
        ("think", "min", "max", "IMG-START", "FLAGS")
    )
    check(
        "Klick-Eingaben werden getrennt",
        list(controls) == ["think", "min", "max"]
        and images == {"image_start": "IMG-START", "video_prompt_type": "FLAGS"},
        f"-> {controls} / {images}",
    )

    # 13b. Die eigentliche Staerke der Trennung: WanGP legt die Think-Checkbox
    #      nur fuer lokale Enhancer an - fehlt sie, haengen die Bilder trotzdem
    #      richtig, weil von rechts ueber die bekannte Bild-Liste getrennt wird.
    without_think = P.LocalEnhancePlugin()
    without_think._min_words_field = "min"
    without_think._max_words_field = "max"
    without_think.image_start = "IMG-START"
    without_think.video_prompt_type = "FLAGS"
    controls, images = without_think._split_image_inputs(
        ("min", "max", "IMG-START", "FLAGS")
    )
    check(
        "Trennung ohne Think-Checkbox",
        list(controls) == ["min", "max"]
        and images == {"image_start": "IMG-START", "video_prompt_type": "FLAGS"},
        f"-> {controls} / {images}",
    )

    #      Mit echten Werten gelesen muss dabei dasselbe herauskommen: kein
    #      Denken, Min 0, Max 300.
    numeric_controls, numeric_images = without_think._split_image_inputs(
        (0, 300, "IMG-START", "FLAGS")
    )
    check(
        "Trennung ohne Think-Checkbox liest die Regler richtig",
        P.LocalEnhancePlugin._read_controls(numeric_controls) == (False, 0, 300)
        and numeric_images
        == {"image_start": "IMG-START", "video_prompt_type": "FLAGS"},
        f"-> {P.LocalEnhancePlugin._read_controls(numeric_controls)} / {numeric_images}",
    )

    # 14. _effective_mode: leerer Live-Wert -> Modell-Default. Ohne eigene
    #     Enhancer-Definition bleibt der erste erlaubte Modus; eine echte
    #     `prompt_enhancer_def` liefert ihren eigenen default, und eine
    #     eingeschraenkte `prompt_enhancer_choices_allowed` ihren ersten Wert -
    #     bei ["TI"] also "TI" (die Modelle, bei denen der alte Code die Bilder
    #     zufaellig mitschickte).
    fallback = P.LocalEnhancePlugin._effective_mode("", {"image_mode": 1}, False, 1)
    explicit = P.LocalEnhancePlugin._effective_mode(
        "",
        {"prompt_enhancer_def": {"labels": {"T": "Text", "V": "Video"}, "default": "V"}},
        False,
        1,
    )
    allowed = P.LocalEnhancePlugin._effective_mode(
        "", {"prompt_enhancer_choices_allowed": ["TI"], "image_mode": 1}, False, 1
    )
    check(
        "_effective_mode faellt auf den Modell-Default zurueck",
        fallback == "T" and explicit == "V" and allowed == "TI",
        f"-> {fallback!r} / {explicit!r} / {allowed!r}",
    )

    # 15. _effective_mode: ein gesetzter Live-Wert gewinnt gegen den Default.
    live = P.LocalEnhancePlugin._effective_mode("TI", {"image_mode": 1}, False, 1)
    live_think = P.LocalEnhancePlugin._effective_mode(" TIK ", {"image_mode": 1}, False, 1)
    check(
        "_effective_mode nimmt den Live-Wert",
        live == "TI" and live_think == "TIK",
        f"-> {live!r} / {live_think!r}",
    )

    # 16. _split_mode_input: mit Modus-Komponente wandert die erste Eingabe in
    #     den Modus, der Rest bleibt in der Reihenfolge der Verdrahtung.
    mode_instance = P.LocalEnhancePlugin()
    mode_instance.prompt_enhancer = "MODE"
    mode_value, rest = mode_instance._split_mode_input(("TI", "think", "min", "max"))
    empty_value, empty_rest = mode_instance._split_mode_input(())
    check(
        "_split_mode_input zieht den Modus ab",
        mode_value == "TI"
        and tuple(rest) == ("think", "min", "max")
        and (empty_value, tuple(empty_rest)) == (None, ())
        and len(mode_instance._mode_components()) == 1,
        f"-> {mode_value!r} / {rest}",
    )

    # 17. Ohne Modus-Komponente bleiben die Eingaben unangetastet: ein Modell
    #     ohne Enhancer-Zeile darf die Regler nicht um eins verschieben.
    plain_instance = P.LocalEnhancePlugin()
    plain_instance.prompt_enhancer = None
    mode_value, rest = plain_instance._split_mode_input(("think", "min"))
    check(
        "_split_mode_input ohne Komponente laesst alles stehen",
        mode_value is None
        and tuple(rest) == ("think", "min")
        and plain_instance._mode_components() == [],
        f"-> {mode_value!r} / {rest}",
    )

    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} Fall/Faelle fehlgeschlagen: {', '.join(_FAILURES)}")
        return 1
    print("Alle Faelle bestanden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Transcribe episodios a subtítulos (ASS/SRT) de forma 100% local.

1. ffmpeg extrae la pista de audio.
2. Demucs (htdemucs_ft) aísla la voz de la música y los efectos.
3. Whisper transcribe solo la voz.

Uso:
    python transcribir.py "episodio 01.mkv"
    python transcribir.py (Get-ChildItem *.mkv).FullName --formato srt

Los modelos se descargan la primera vez; después funciona sin internet.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(t, ass):
    """Segundos -> marca de tiempo ASS (H:MM:SS.cc) o SRT (HH:MM:SS,mmm).

    >>> ts(59.999, True), ts(3661.5, False)
    ('0:01:00.00', '01:01:01,500')
    """
    unit = 100 if ass else 1000
    h, n = divmod(round(t * unit), 3600 * unit)
    m, n = divmod(n, 60 * unit)
    s, f = divmod(n, unit)
    return f"{h}:{m:02}:{s:02}.{f:02}" if ass else f"{h:02}:{m:02}:{s:02},{f:03}"


def escribir(out, segs):
    """Guarda [(inicio, fin, texto)] como .ass o .srt según la extensión de `out`."""
    ass = out.lower().endswith(".ass")
    with open(out, "w", encoding="utf-8-sig") as f:
        if ass:
            f.write(ASS_HEADER)
        for n, (a, b, text) in enumerate(segs, 1):
            if ass:
                text = text.replace("\n", r"\N")
                f.write(f"Dialogue: 0,{ts(a, True)},{ts(b, True)},Default,,0,0,0,,{text}\n")
            else:
                f.write(f"{n}\n{ts(a, False)} --> {ts(b, False)}\n{text}\n\n")


def elegir_pista(src, pista):
    """Índice (entre las pistas de audio) a usar: `pista` si se indicó; si no, la predeterminada del archivo."""
    streams = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-of", "json",
         "-show_entries", "stream_disposition=default:stream_tags=language,title", src],
        capture_output=True, check=True).stdout)["streams"]
    if pista is None:
        pista = next((i for i, s in enumerate(streams) if s["disposition"]["default"]), 0)
    if not 0 <= pista < len(streams):
        sys.exit(f"{src}: no existe la pista de audio {pista} (tiene {len(streams)})")
    tags = streams[pista].get("tags", {})
    print(f"{os.path.basename(src)}: pista de audio {pista} [{tags.get('language', '?')}] {tags.get('title', '')}")
    return pista


def main():
    p = argparse.ArgumentParser(description="Transcribe video/audio a subtítulos, separando antes la voz.")
    p.add_argument("entrada", nargs="+", help="archivo(s) de video o audio")
    p.add_argument("--formato", choices=["ass", "srt"], default="ass")
    p.add_argument("--idioma", default="ja", help="idioma hablado: ja, en, es... (por defecto ja)")
    p.add_argument("--modelo", default="large-v3-turbo",
                   help="modelo Whisper: large-v3-turbo (rápido, cabe en 8 GB), large-v3 (más preciso, ~4x más lento) o ruta a un .pt")
    p.add_argument("--pista", type=int,
                   help="pista de audio a usar (0 = la primera); si se omite, usa la marcada como predeterminada")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # evita errores al imprimir japonés redirigido a archivo

    with tempfile.TemporaryDirectory() as tmp:
        # 1-2. Extraer audio y separar voces. Demucs corre en su propio proceso para
        #      que libere la VRAM antes de cargar Whisper.
        audios = []
        for i, src in enumerate(args.entrada):
            wav = os.path.join(tmp, f"{i}.flac")
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
                            "-map", f"0:a:{elegir_pista(src, args.pista)}", "-ac", "2", "-ar", "44100", wav], check=True)
            audios.append(wav)
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs_ft",
                        "--flac", "-o", tmp, *audios], check=True)

        # 3. Transcribir
        import torch
        import whisper

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # fp16 solo rinde desde Volta (7.0); en Maxwell/Pascal fp32 es ~2.5x más rápido
        fp16 = device == "cuda" and torch.cuda.get_device_capability() >= (7, 0)
        model = whisper.load_model(args.modelo, device=device)
        for i, src in enumerate(args.entrada):
            vocals = os.path.join(tmp, "htdemucs_ft", str(i), "vocals.flac")
            # hallucination_silence_threshold descarta texto inventado en silencios (requiere word_timestamps)
            r = model.transcribe(vocals, language=args.idioma, fp16=fp16, verbose=True,
                                 condition_on_previous_text=False, word_timestamps=True,
                                 hallucination_silence_threshold=2)
            out = f"{os.path.splitext(src)[0]}.{args.idioma}.{args.formato}"
            escribir(out, [(s["start"], s["end"], s["text"].strip()) for s in r["segments"]])
            print(f"-> {out}")


if __name__ == "__main__":
    main()

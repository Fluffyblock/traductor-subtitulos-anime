"""Traduce los subtítulos japoneses de transcribir.py a español latino con Claude.

Con --en, los subtítulos oficiales en inglés son la base: se usan sus tiempos y se
traducen todas sus líneas, incluidas las que Whisper se saltó. El sentido, el registro
y los honoríficos salen del audio japonés transcrito; el inglés corrige los errores de
Whisper y fija cómo se escriben los nombres. Sin --en se traduce solo el japonés, con
los tiempos de Whisper.

Con --adaptar, la entrada son subtítulos en español de España y se adaptan a español
latino con sus mismos tiempos. Si además das --en (subtítulos en inglés que conserven
los honoríficos), se usan para recuperar los honoríficos que quitó la versión de España.

Con --estilos (solo ASS) se traducen únicamente las líneas de esos estilos; el resto del
archivo (cabecera, estilos, carteles, etiquetas) queda intacto.

Uso:
    python traducir.py "episodio 01.ja.ass" --en "episodio 01.mkv" --api-key sk-ant-...
    python traducir.py (Get-ChildItem *.ja.ass).FullName --en (Get-ChildItem *.mkv).FullName
    python traducir.py "episodio 01.mkv" --pista 1 --adaptar --en "episodio 01.mkv" --pista-en 0 --estilos Default Italics

La entrada y --en aceptan .ass/.srt/.vtt o un video (se extrae la pista de subtítulos
--pista / --pista-en; 0 = la primera). Sin --api-key usa la variable ANTHROPIC_API_KEY.
Salida: "episodio 01.es.ass", o "episodio 01.es-419.ass" con --adaptar.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

import anthropic

from transcribir import escribir, ts

MODELO = "claude-opus-5"
LOTE = 120  # líneas por petición

SISTEMA = """\
Eres un traductor profesional de anime del japonés al español latinoamericano neutro. Recibirás una de tres cosas:
A) Líneas de los subtítulos oficiales en inglés para traducir, junto con la transcripción automática (Whisper) \
del audio japonés del mismo tramo.
B) Solo líneas en japonés transcritas con Whisper para traducir.
C) Líneas de subtítulos en español de España para adaptar a español latino, a veces con los subtítulos en \
inglés del mismo tramo como referencia.

En el caso A:
- Cada traducción debe corresponder al contenido de su línea en inglés, porque se mostrará con los tiempos de esa \
línea. No adelantes ni juntes texto de líneas vecinas.
- Para cada línea, localiza en la transcripción japonesa lo que realmente se dijo en ese momento y traduce el \
sentido del japonés: de ahí salen el tono, el registro y los honoríficos. El inglés oficial suele quitar o adaptar \
honoríficos y localizar expresiones; en eso no lo sigas.
- Whisper comete errores (nombres mal escritos, homófonos equivocados, palabras inventadas, frases cortadas) y a \
veces se salta líneas. El inglés se hizo sobre el guion real: úsalo para corregir esos errores y escribe los nombres \
de personajes, lugares, técnicas y términos tal como aparecen en inglés.
- Los tiempos de ambas fuentes son aproximados y no coinciden una a una: una línea japonesa puede abarcar varias \
inglesas o solo parte de una. Ignora el japonés que no corresponda a ninguna línea en inglés.
- Si una línea en inglés no tiene japonés correspondiente (Whisper no la captó), tradúcela desde el inglés y usa \
los honoríficos que esos personajes usan entre sí en el japonés que tienes a la vista; si no se ven, no inventes.

En el caso B:
- Traduce el japonés, corrigiendo por contexto los errores evidentes de Whisper.
- Deja la traducción vacía ("") solo si la línea es claramente una alucinación de Whisper (por ejemplo \
ご視聴ありがとうございました, チャンネル登録をお願いします, créditos de subtítulos o repeticiones sin sentido).

En el caso C:
- Es una adaptación, no una retraducción: conserva el sentido, el tono y la redacción, y cambia solo lo que suene \
a España o no se use en Latinoamérica.
- Cambia vosotros por ustedes con sus verbos y pronombres ("¿Os vais?" → "¿Se van?", "vuestro" → "su" o \
"de ustedes"), el vocabulario peninsular (vale → está bien o de acuerdo, tío/tía → amigo, viejo o lo que corresponda, \
coger → agarrar o tomar, móvil → celular, ordenador → computadora, gafas → lentes, conducir → manejar, \
gilipollas → idiota, mola → está genial, etc.) y el leísmo ("le vi" referido a un hombre → "lo vi").
- Usa el pretérito simple donde en Latinoamérica suena más natural ("¿Qué pasó?" en vez de "¿Qué ha pasado?").
- Conserva los honoríficos y términos japoneses que ya traiga el texto.
- Si recibes subtítulos en inglés de referencia, úsalos para recuperar los honoríficos y tratamientos que la \
versión de España quitó o tradujo y que el inglés conserva: "señor Tanaka" o "Tanaka" → "Tanaka-san", "hermano" \
usado para llamar a alguien → "onii-chan", "profesor" → "sensei". No retraduzcas desde el inglés: la base sigue \
siendo el texto en español. Los tiempos del inglés pueden no coincidir exactamente con los del español.

Honoríficos (consérvalos tal como se dicen en japonés):
- Sufijos unidos al nombre con guion: -san, -kun, -chan, -sama, -dono, -senpai, -sensei, -tan, -han, etc. \
Ejemplo: 田中さん → Tanaka-san, aunque el inglés diga "Mr. Tanaka" o solo "Tanaka".
- Tratamientos usados para llamar a alguien, en romaji: senpai, sensei, onii-chan, onee-san, nii-san, \
ojou-sama, bocchan, etc.
- No agregues honoríficos que no estén en el japonés ni quites los que sí están. Si alguien llama a otro por \
el nombre a secas, déjalo a secas.

Español latino:
- Neutro y natural, sin regionalismos marcados (nada de "vosotros", "vale", "tío", "coger", "móvil"; tampoco \
"wey", "che" o "chido").
- Usted/ustedes para el habla formal (keigo) y tú para el habla casual, según la relación entre personajes.
- Mantén la personalidad de cada personaje (rudo, tímido, arrogante, infantil) y sus muletillas si aportan carácter.
- Usa signos de apertura ¿ ¡ e interjecciones naturales: ¿Eh?, ¡Ah!, Oye, Bueno...

Formato:
- Frases concisas y fáciles de leer: idealmente menos de 42 caracteres por renglón y máximo dos renglones \
(sepáralos con un salto de línea).
- Sin notas del traductor, explicaciones ni comillas añadidas.
- Si una línea trae etiquetas ASS entre llaves ({\\i1}, {\\an8}, etc.) o saltos \\N, consérvalas en el lugar \
equivalente del texto traducido.
- Devuelve exactamente una traducción por cada id recibido, sin fusionar ni omitir líneas. Si una frase está \
partida en varias líneas, tradúcela en fragmentos que se lean bien en ese orden.
- En letras de canción (opening/ending), traduce la letra de forma natural, apoyándote en el inglés si lo hay.

Las "líneas anteriores" son solo contexto para dar continuidad; no las traduzcas de nuevo."""

ESQUEMA = {
    "type": "object",
    "properties": {"lineas": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "es": {"type": "string"}},
        "required": ["id", "es"], "additionalProperties": False}}},
    "required": ["lineas"], "additionalProperties": False,
}


def seg(t):
    """Marca de tiempo ASS/SRT/VTT -> segundos.

    >>> seg("0:01:02.50"), seg("01:01:01,500"), seg("01:02.250")
    (62.5, 3661.5, 62.25)
    """
    return sum(float(x) * 60 ** i for i, x in enumerate(reversed(t.strip().replace(",", ".").split(":"))))


def limpiar(t):
    """Quita etiquetas ASS/HTML y deja el texto en un solo renglón."""
    t = re.sub(r"\{[^}]*\}|<[^>]+>", "", t)
    return " ".join(t.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ").split())


def leer(path):
    """.ass/.ssa/.srt/.vtt -> [(inicio, fin, texto plano)] ordenado por tiempo."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        raw = f.read()
    subs = []
    if path.lower().endswith((".ass", ".ssa")):
        for line in raw.splitlines():
            if line.startswith("Dialogue:"):
                c = line.split(":", 1)[1].split(",", 9)
                if not re.search(r"\\(pos|move|p[1-9])", c[9]):  # descarta carteles y dibujos
                    subs.append((seg(c[1]), seg(c[2]), limpiar(c[9])))
    else:
        for block in re.split(r"\n\s*\n", raw.replace("\r", "")):
            lines = block.strip().split("\n")
            for i, line in enumerate(lines):
                if "-->" in line:
                    a, b = line.split("-->")
                    subs.append((seg(a), seg(b.split()[0]), limpiar(" ".join(lines[i + 1:]))))
                    break
    return sorted(set(s for s in subs if s[2]))  # set: quita líneas duplicadas (capas de efectos)


def leer_ass(path, estilos):
    """ASS -> (renglones del archivo, [(n.º de renglón, inicio, fin, texto con etiquetas)] de `estilos`, por tiempo)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        raw = f.read().splitlines()
    subs, vistos = [], Counter()
    for n, line in enumerate(raw):
        if line.startswith("Dialogue:"):
            c = line.split(",", 9)
            vistos[c[3]] += 1
            if c[3] in estilos and limpiar(c[9]):
                subs.append((n, seg(c[1]), seg(c[2]), c[9]))
    faltan = set(estilos) - set(vistos)
    if faltan:
        raise SystemExit(f"Estilos no encontrados: {', '.join(faltan)}. Estilos del archivo (líneas): {dict(vistos)}")
    return raw, sorted(subs, key=lambda s: s[1:3])


def escribir_ass(out, raw, subs, textos):
    """Guarda el ASS cambiando solo el texto de los renglones de `subs`; el resto queda idéntico."""
    for (n, *_), t in zip(subs, textos):
        c = raw[n].split(",", 9)
        raw[n] = ",".join(c[:9] + [t.replace("\n", r"\N") or c[9]])
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(raw) + "\n")


def extraer(path, pista, destino):
    """Si `path` es un video, extrae su pista de subtítulos n.º `pista` a `destino` (.ass) y lo devuelve."""
    if path.lower().endswith((".ass", ".ssa", ".srt", ".vtt")):
        return path
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"s:{pista}", "-show_entries",
                           "stream_tags=language,title", "-of", "csv=p=0", path],
                          capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    print(f"  {os.path.basename(path)}, pista de subtítulos {pista}: {info or '?'}")
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path,
                    "-map", f"0:s:{pista}", destino], check=True)
    return destino


def armar(base, idioma, ctx, ref, es, ids):
    """Mensaje para Claude: líneas previas ya traducidas, referencia del tramo (`ctx`) y las líneas `ids` de `base`."""
    partes = []
    prev = [j for j in range(max(0, ids[0] - 8), ids[0]) if es.get(j)]
    if prev:
        partes.append("Líneas anteriores (ya traducidas):\n" + "\n".join(f"{base[j][2]} => {es[j]}" for j in prev))
    a, b = base[ids[0]][0] - 15, base[ids[-1]][1] + 15  # margen por desfase entre ambas fuentes
    cerca = [c for c in ctx if c[1] > a and c[0] < b]
    if cerca:
        partes.append(f"{ref}:\n" + "\n".join(f"[{ts(s, True)}] {t}" for s, _, t in cerca))
    partes.append(f"Traduce estas líneas (id | inicio-fin | {idioma}):\n"
                  + "\n".join(f"{j} | {ts(base[j][0], True)}-{ts(base[j][1], True)} | {base[j][2]}" for j in ids))
    return "\n\n".join(partes)


def pedir(client, mensaje):
    """Una petición a Claude -> {id: texto en español}."""
    # fallbacks="default": si el filtro de seguridad rechaza el lote (violencia en anime, p. ej.),
    # la API lo reintenta sola con el modelo alternativo recomendado.
    with client.beta.messages.stream(
        model=MODELO, max_tokens=64000, system=SISTEMA,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": mensaje}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude se detuvo ({msg.stop_reason}): {getattr(msg, 'stop_details', None)}")
    data = json.loads("".join(b.text for b in msg.content if b.type == "text"))
    return {d["id"]: d["es"] for d in data["lineas"]}


def traducir(client, base, idioma, ctx=(), ref=""):
    """Traduce `base` [(inicio, fin, texto)] usando `ctx` (titulado `ref`) como referencia.

    Devuelve un texto en español por línea de `base`; "" = alucinación de Whisper a descartar.
    """
    es = {}
    for i in range(0, len(base), LOTE):
        pend = list(range(i, min(i + LOTE, len(base))))
        for _ in range(3):  # reintenta las líneas que el modelo omita
            got = pedir(client, armar(base, idioma, ctx, ref, es, pend))
            es.update((k, v) for k, v in got.items() if k in pend)
            pend = [j for j in pend if j not in es]
            if not pend:
                break
        if pend:
            raise RuntimeError(f"Claude no devolvió las líneas {pend}")
        print(f"  {len(es)}/{len(base)}")
    return [es[j].strip() for j in range(len(base))]


def main():
    p = argparse.ArgumentParser(description="Traduce subtítulos japoneses a español latino con Claude.")
    p.add_argument("entrada", nargs="+",
                   help="subtítulo(s) japonés(es) de transcribir.py, o en español de España con --adaptar (o un video)")
    p.add_argument("--pista", type=int, default=0, help="pista de subtítulos a extraer si la entrada es un video, 0 = la primera")
    p.add_argument("--en", nargs="+", default=[],
                   help="subtítulos en inglés (o videos que los traigan), uno por entrada y en el mismo orden")
    p.add_argument("--pista-en", type=int, default=0, help="pista de subtítulos a extraer si --en es un video, 0 = la primera")
    p.add_argument("--adaptar", action="store_true", help="la entrada está en español de España: adaptarla a español latino")
    p.add_argument("--estilos", nargs="+",
                   help="solo ASS: estilos a traducir (p. ej. Default Italics); el resto del archivo queda intacto")
    p.add_argument("--api-key", help="clave de la API de Anthropic; si no se da, usa la variable ANTHROPIC_API_KEY")
    args = p.parse_args()
    if args.en and len(args.en) != len(args.entrada):
        p.error("--en necesita un archivo por cada entrada")
    sys.stdout.reconfigure(encoding="utf-8")

    client = anthropic.Anthropic(api_key=args.api_key)  # None -> ANTHROPIC_API_KEY
    with tempfile.TemporaryDirectory() as tmp:
        for i, src in enumerate(args.entrada):
            print(src)
            sub = extraer(src, args.pista, os.path.join(tmp, f"{i}.ass"))
            en = extraer(args.en[i], args.pista_en, os.path.join(tmp, f"{i}.en.ass")) if args.en else None
            root = os.path.splitext(src)[0]
            if args.adaptar:
                # la base es el español de España; el inglés, si lo hay, aporta los honoríficos
                out = re.sub(r"[.]es(-es)?$", "", root, flags=re.I) + ".es-419"  # nunca pisa la entrada
                base, idioma, ctx, ref = sub, "español de España", leer(en) if en else [], "Subtítulos en inglés de este tramo"
            elif en:
                # el inglés pone los tiempos y las líneas; el japonés, el sentido y los honoríficos
                out = re.sub(r"[.]ja$", "", root) + ".es"
                base, idioma, ctx, ref = en, "inglés oficial", leer(sub), "Audio japonés de este tramo, transcrito por Whisper"
            else:
                out = re.sub(r"[.]ja$", "", root) + ".es"
                base, idioma, ctx, ref = sub, "japonés", [], ""

            if args.estilos:
                if not base.lower().endswith((".ass", ".ssa")):
                    p.error("--estilos solo sirve con subtítulos ASS")
                raw, subs = leer_ass(base, args.estilos)
                print(f"  {len(subs)} líneas de {', '.join(args.estilos)} a traducir, {len(ctx)} de referencia")
                out += ".ass"
                escribir_ass(out, raw, subs, traducir(client, [s[1:] for s in subs], idioma, ctx, ref))
            else:
                lineas = leer(base)
                print(f"  {len(lineas)} líneas a traducir, {len(ctx)} de referencia")
                out += os.path.splitext(sub)[1]
                textos = traducir(client, lineas, idioma, ctx, ref)
                escribir(out, [(a, b, t) for (a, b, _), t in zip(lineas, textos) if t])
            print(f"-> {out}")


if __name__ == "__main__":
    main()

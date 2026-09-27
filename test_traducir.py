"""Prueba sin red ni API: python test_traducir.py"""
import os
import tempfile

import traducir

d = tempfile.mkdtemp()


def archivo(nombre, texto):
    p = os.path.join(d, nombre)
    with open(p, "w", encoding="utf-8") as f:
        f.write(texto)
    return p


# leer(): ASS con etiquetas, capas duplicadas, carteles y comentarios; SRT; VTT
assert traducir.leer(archivo("en.ass", (
    "[Events]\n"
    "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}Hello,\\Nworld{\\i0}\n"
    "Dialogue: 1,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\bord3}Hello,\\Nworld\n"
    "Dialogue: 0,0:00:01.00,0:00:05.00,Sign,,0,0,0,,{\\pos(10,10)}CAFE\n"
    "Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,nota\n"))) == [(1.0, 2.5, "Hello, world")]
assert traducir.leer(archivo("en.srt", (
    "1\n00:00:01,000 --> 00:00:02,500\n<i>Hi</i>\nthere\n\n"
    "2\n00:01:00,000 --> 00:01:01,000 X1:0\n{\\an8}Top\n"))) == [(1.0, 2.5, "Hi there"), (60.0, 61.0, "Top")]
assert traducir.leer(archivo("en.vtt", "WEBVTT\n\n00:01.000 --> 00:02.000 align:start\nYo\n")) == [(1.0, 2.0, "Yo")]

# traducir(): inglés como base (sus tiempos), japonés como contexto, lotes, reintento de omitidas
# y descarte de líneas vacías, con Claude simulado
en = [(i, i + 1, f"en{i}") for i in range(traducir.LOTE + 5)]
llamadas = []


def falso(client, mensaje):
    ids = [int(l.split(" | ")[0]) for l in mensaje.rsplit("):\n", 1)[1].splitlines()]
    llamadas.append((ids, mensaje))
    return {j: "" if j == 3 else f"es{j}" for j in ids if not (len(llamadas) == 1 and j == 7)}


traducir.pedir = falso
out = traducir.traducir(None, en, "inglés oficial", [(0, 2, "こんにちは")], "Audio japonés")
assert "(id | inicio-fin | inglés oficial)" in llamadas[0][1] and "0 | 0:00:00.00-0:00:01.00 | en0" in llamadas[0][1]
assert "Audio japonés:\n[0:00:00.00] こんにちは" in llamadas[0][1] and "こんにちは" not in llamadas[2][1]  # solo en su tramo
assert [ids for ids, _ in llamadas][1] == [7] and len(llamadas) == 3  # lote 1, reintento de la 7, lote 2
assert "en119 => es119" in llamadas[2][1]  # el lote 2 recibe el final del lote 1 como contexto
assert len(out) == len(en) and out[0] == "es0" and out[3] == ""

# leer_ass() + escribir_ass(): solo cambian los estilos elegidos; cabecera, carteles y comentarios intactos
ass = archivo("es.ass", (
    "[Script Info]\nTitle: prueba\n\n[V4+ Styles]\nStyle: Default,Arial,60\nStyle: Cartel,Arial,40\n\n[Events]\n"
    "Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,¿Os vais ya?\n"
    "Dialogue: 0,0:00:01.00,0:00:02.00,Italics,,0,0,0,,{\\i1}Vale, tío{\\i0}\n"
    "Dialogue: 0,0:00:01.00,0:00:09.00,Cartel,,0,0,0,,{\\pos(1,1)}Cafetería\n"
    "Comment: 0,0:00:01.00,0:00:09.00,Default,,0,0,0,,nota\n"))
raw, subs = traducir.leer_ass(ass, ["Default", "Italics"])
assert [s[1:] for s in subs] == [(1.0, 2.0, "{\\i1}Vale, tío{\\i0}"), (5.0, 6.0, "¿Os vais ya?")]  # por tiempo
traducir.escribir_ass(ass + ".out", raw, subs, ["{\\i1}Está bien,\namigo{\\i0}", "¿Ya se van?"])
with open(ass, encoding="utf-8") as f1, open(ass + ".out", encoding="utf-8-sig") as f2:
    antes, despues = f1.read().splitlines(), f2.read().splitlines()
assert [(a, b) for a, b in zip(antes, despues) if a != b] == [
    ("Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,¿Os vais ya?",
     "Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,¿Ya se van?"),
    ("Dialogue: 0,0:00:01.00,0:00:02.00,Italics,,0,0,0,,{\\i1}Vale, tío{\\i0}",
     "Dialogue: 0,0:00:01.00,0:00:02.00,Italics,,0,0,0,,{\\i1}Está bien,\\Namigo{\\i0}"),
] and len(antes) == len(despues)
try:
    traducir.leer_ass(ass, ["Default", "Dfault"])
    raise AssertionError("debió fallar")
except SystemExit as e:
    assert "Dfault" in str(e) and "'Cartel': 1" in str(e)  # dice qué estilos existen

# escribir() + leer(): ida y vuelta con salto de línea en ASS
p = os.path.join(d, "x.es.ass")
traducir.escribir(p, [(1.0, 2.5, "Hola,\nTanaka-san")])
assert traducir.leer(p) == [(1.0, 2.5, "Hola, Tanaka-san")]
print("ok")

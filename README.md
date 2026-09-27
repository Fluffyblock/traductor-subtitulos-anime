# Transcriptor y traductor de subtítulos de anime

Dos scripts para pasar anime en japonés a subtítulos en **español latino**, respetando los honoríficos:

| Script | Qué hace | Dónde corre |
|---|---|---|
| `transcribir.py` | Video → subtítulos en japonés. Aísla la voz con Demucs y transcribe con Whisper. | 100 % local |
| `traducir.py` | Subtítulos → español latino con Claude. Usa los subtítulos oficiales en inglés para corregir a Whisper, y también adapta subtítulos de español de España a latino. | API de Anthropic (internet, con costo por uso) |

---

## Requisitos

- **Windows** con PowerShell (probado en Windows; en Linux/macOS debería funcionar pero no está probado).
- **Python 3.9 o superior** (probado con 3.9.13).
- **FFmpeg** (`ffmpeg` y `ffprobe`) en el PATH.
- **Para transcribir:** GPU NVIDIA con CUDA recomendada. El modelo `large-v3-turbo` cabe en 8 GB de VRAM (probado en una Quadro M5000). Sin GPU funciona en CPU, pero mucho más lento.
- **Para traducir:** una clave de la API de Anthropic, que se crea en [console.anthropic.com](https://console.anthropic.com).

## Instalación

1. **FFmpeg** (después, abre una terminal nueva para que se actualice el PATH):

   ```powershell
   winget install Gyan.FFmpeg
   ```

2. **PyTorch con CUDA.** Sin GPU NVIDIA, quita `--index-url ...` para instalar la versión de CPU:

   ```powershell
   python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
   ```

3. **El resto de dependencias** (Whisper, Demucs y el SDK de Anthropic):

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. **Clave de la API** (solo para traducir). Puedes pasarla en cada comando con `--api-key sk-ant-...`, o guardarla en la sesión actual de PowerShell:

   ```powershell
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   ```

   Para que quede guardada en las terminales nuevas: `setx ANTHROPIC_API_KEY "sk-ant-..."`.
   Ten en cuenta que PowerShell guarda en su historial los comandos que escribes, incluida la clave.

5. **Comprobar** que todo quedó bien (no usa la API):

   ```powershell
   python test_traducir.py
   ```

   Debe terminar con `ok`. Los modelos de Whisper y Demucs se descargan la primera vez que transcribes; después funcionan sin internet.

---

## Uso

### 1. Transcribir el audio japonés

```powershell
python transcribir.py "episodio 01.mkv"
python transcribir.py (Get-ChildItem *.mkv).FullName --formato srt
```

Genera `episodio 01.ja.ass` (o `.ja.srt`) junto al video.

| Opción | Por defecto | Descripción |
|---|---|---|
| `--formato` | `ass` | `ass` o `srt` |
| `--idioma` | `ja` | Idioma hablado (`ja`, `en`, `es`...) |
| `--modelo` | `large-v3-turbo` | `large-v3-turbo` (rápido), `large-v3` (más preciso, ~4x más lento) o ruta a un `.pt` |
| `--pista` | `0` | Pista de **audio** a usar (útil en videos con audio dual) |

### 2. Traducir japonés a español latino

**Con los subtítulos oficiales en inglés (recomendado):**

```powershell
python traducir.py "episodio 01.ja.ass" --en "episodio 01.mkv" --pista-en 0
```

- El inglés pone los **tiempos** y las **líneas**. Se traducen todas, incluidas las que Whisper no captó.
- El japonés pone el **sentido**, el trato de usted o tú y los **honoríficos** (-san, -kun, -chan, senpai, onii-chan...). Se conservan aunque el inglés diga "Mr. Tanaka".
- El inglés también corrige lo que Whisper oyó mal y fija cómo se escriben los nombres.

**Solo con el japonés** (usa los tiempos de Whisper y descarta las frases que Whisper inventa, como ご視聴ありがとうございました):

```powershell
python traducir.py "episodio 01.ja.ass"
```

**Varios episodios a la vez.** Las listas deben quedar en el mismo orden:

```powershell
python traducir.py (Get-ChildItem *.ja.ass).FullName --en (Get-ChildItem *.mkv).FullName
```

### 3. Adaptar español de España a español latino

```powershell
python traducir.py "episodio 01.es-ES.srt" --adaptar
```

Es una adaptación, no una traducción nueva. Se conservan la redacción y el tono, y solo cambia lo que suena a España:

- vosotros → ustedes
- vocabulario peninsular (vale, tío, coger, móvil...)
- leísmo
- "¿Qué ha pasado?" → "¿Qué pasó?"

**Directo desde el mkv, recuperando honoríficos del inglés y traduciendo solo algunos estilos del ASS:**

```powershell
python traducir.py "episodio 01.mkv" --pista 1 --adaptar --en "episodio 01.mkv" --pista-en 0 --estilos Default Italics
```

- `--en` aquí es una pista en inglés que **sí conserva los honoríficos**. Se usa solo para recuperar lo que la versión de España quitó ("señor Tanaka" → "Tanaka-san").
- `--estilos` cambia solo el texto de las líneas de esos estilos. La cabecera, los estilos, los tiempos, los carteles y las etiquetas como `{\i1}` quedan intactos.

### Opciones de `traducir.py`

| Opción | Descripción |
|---|---|
| `entrada` | Subtítulo(s) `.ass`/`.srt`/`.vtt` o video(s). Japonés de `transcribir.py`, o español de España con `--adaptar`. |
| `--pista N` | Pista de **subtítulos** a extraer si la entrada es un video (0 = la primera). |
| `--en ...` | Subtítulos en inglés o video(s) que los traigan, uno por cada entrada. |
| `--pista-en N` | Pista de subtítulos a extraer si `--en` es un video (0 = la primera). |
| `--adaptar` | La entrada está en español de España: adaptarla a latino. |
| `--estilos A B ...` | Solo ASS: estilos a traducir; el resto del archivo queda intacto. |
| `--api-key` | Clave de Anthropic. Si no se da, usa `ANTHROPIC_API_KEY`. |

### Encontrar el número de pista y los estilos

Lista las pistas de subtítulos del video. La primera línea es la pista 0, la segunda la 1, y así:

```powershell
ffprobe -v error -select_streams s -show_entries stream_tags=language,title -of csv=p=0 "episodio 01.mkv"
```

Al traducir, el script muestra el idioma y el título de cada pista extraída para que confirmes que es la correcta.

Si no conoces los nombres de los estilos, pasa cualquiera en `--estilos`. El script se detiene **antes de llamar a la API** y muestra los estilos que hay en el archivo, con cuántas líneas tiene cada uno.

### Archivos de salida

| Modo | Salida |
|---|---|
| Transcribir | `episodio 01.ja.ass` |
| Traducir | `episodio 01.es.ass` (o `.srt`, según la entrada) |
| Adaptar | `episodio 01.es-419.ass` (o `.srt`); nunca sobrescribe el original |

La salida es un archivo aparte; no se integra dentro del mkv. Si lo quieres dentro del video, agrégalo con una herramienta como MKVToolNix (mkvmerge).

---

## Notas

- **Modelo:** `claude-opus-5`, definido en la constante `MODELO` de `traducir.py`. Se traducen 120 líneas por petición, y cada petición recibe las últimas líneas ya traducidas para mantener la continuidad. Si el modelo omite alguna línea, se vuelve a pedir.
- **Rechazos:** si el filtro de seguridad de la API rechaza un fragmento (por ejemplo, por violencia), la API lo reintenta automáticamente con otro modelo (`fallbacks="default"`).
- **Costo:** depende de la duración del episodio. Revisa el consumo en [console.anthropic.com](https://console.anthropic.com).
- **Desfase entre versiones:** si los subtítulos en inglés vienen de otra versión del episodio con un desfase de más de ~15 s, sincronízalos antes (por ejemplo con Sushi).
- **Sin `--estilos`:** la salida ASS usa un estilo simple, y los carteles posicionados (`\pos`) no se traducen.
- **Líneas sin inglés:** en el modo japonés + inglés, las líneas japonesas que no tienen equivalente en inglés se ignoran. Casi siempre son murmullos o frases inventadas por Whisper.

## Pruebas

Ninguna de estas pruebas usa la API ni la red:

```powershell
python test_traducir.py
python -m doctest traducir.py transcribir.py
```

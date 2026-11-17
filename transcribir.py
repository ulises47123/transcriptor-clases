"""
Transcriptor local de clases (video y audio) -> Markdown + TXT ordenados por materia.

- 100 % gratuito y local (faster-whisper): el audio NUNCA sale de la PC.
- Acepta videos (mp4, mkv, avi, mov, webm...) y audios (mp3, m4a, wav, ogg, opus...).
- Pensado para archivos largos (20 min - 1 h+): muestra progreso y se puede
  REANUDAR si se corta (guarda lo avanzado en un archivo .parcial.jsonl).
- Filtra repeticiones/alucinaciones tipicas de Whisper (frases que se repiten en bucle).

Uso:
    python transcribir.py                     # procesa todo lo que haya en ./entrada
    python transcribir.py --modelo base       # mas rapido, menos preciso
    python transcribir.py --modelo medium     # mas preciso, mucho mas lento
    python transcribir.py --materia Fisica archivo.mp3   # archivo suelto

Organizacion de la entrada (cualquiera de las dos sirve):
    entrada/Fisica/clase1.mp4                 -> materia = carpeta
    entrada/fisica_2026-10-30.mp3             -> materia = primera palabra del nombre
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / "entrada"
SALIDA = BASE / "transcripciones"

EXT_MEDIA = {
    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".wma", ".amr",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".3gp", ".mpeg", ".mpg", ".ts",
}

# Nombres "bonitos" de materias conocidas (clave = forma normalizada sin acentos).
MATERIAS = {
    "fisica": "Física", "lengua": "Lengua", "literatura": "Literatura",
    "matematica": "Matemática", "matematicas": "Matemática", "mate": "Matemática",
    "quimica": "Química", "biologia": "Biología", "historia": "Historia",
    "geografia": "Geografía", "ingles": "Inglés", "filosofia": "Filosofía",
    "economia": "Economía", "informatica": "Informática", "programacion": "Programación",
    "psicologia": "Psicología", "sociologia": "Sociología", "arte": "Arte",
    "musica": "Música", "derecho": "Derecho", "contabilidad": "Contabilidad",
    "ciudadania": "Ciudadanía", "civica": "Cívica", "etica": "Ética",
}

# Frases que Whisper "inventa" en silencios o al final de los audios.
ALUCINACIONES = [
    r"subt[ií]tulos? (realizados|hechos|creados) por.*",
    r"amara\.org",
    r"gracias por ver( el v[ií]deo)?\.?",
    r"suscr[ií]bete.*",
    r"no olvides suscribirte.*",
]
RE_ALUCINACION = re.compile(r"^\s*(" + "|".join(ALUCINACIONES) + r")\s*$", re.IGNORECASE)

SR = 16000  # frecuencia de muestreo que usa Whisper


# ----------------------------------------------------------------- utilidades
def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalizar(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", sin_acentos(s.lower())).strip()


def hms(seg: float) -> str:
    seg = int(seg)
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def nombre_seguro(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", s).strip() or "sin_nombre"


def detectar_materia(ruta: Path, forzada: str | None) -> str:
    if forzada:
        return forzada
    try:
        rel = ruta.resolve().relative_to(ENTRADA)
        if len(rel.parts) > 1:  # esta dentro de una subcarpeta -> esa es la materia
            return rel.parts[0]
    except ValueError:
        pass
    palabras = re.split(r"[\s_\-.]+", sin_acentos(ruta.stem.lower()))
    for p in palabras:
        if p in MATERIAS:
            return MATERIAS[p]
    return "Sin_clasificar"


def detectar_fecha(ruta: Path) -> str:
    n = ruta.stem
    m = re.search(r"(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})", n)  # 2026-10-30
    if m:
        a, mes, d = m.groups()
        return f"{a}-{int(mes):02d}-{int(d):02d}"
    m = re.search(r"(\d{1,2})[-_.](\d{1,2})[-_.](20\d{2})", n)  # 30-10-2026
    if m:
        d, mes, a = m.groups()
        return f"{a}-{int(mes):02d}-{int(d):02d}"
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", n)  # 20261030 (nombres de grabadoras/celulares)
    if m:
        a, mes, d = m.groups()
        if 1 <= int(mes) <= 12 and 1 <= int(d) <= 31:
            return f"{a}-{mes}-{d}"
    return dt.datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m-%d")


# --------------------------------------------------------- limpieza de texto
def colapsar_bucles(texto: str) -> str:
    """'hola hola hola hola' -> 'hola'; frases de hasta 8 palabras repetidas 3+ veces seguidas."""
    for n in range(8, 0, -1):
        patron = re.compile(r"\b((?:\S+\s+){%d}?\S+?)(?:[\s,.]+\1\b){2,}" % (n - 1), re.IGNORECASE)
        texto = patron.sub(r"\1", texto)
    return texto


def limpiar_segmentos(segs: list[dict]) -> list[dict]:
    limpios: list[dict] = []
    recientes: list[str] = []
    for s in segs:
        t = colapsar_bucles(s["text"].strip())
        if not t or RE_ALUCINACION.match(t):
            continue
        clave = normalizar(t)
        if not clave or clave in recientes:  # misma frase que en los ultimos segmentos
            continue
        recientes = (recientes + [clave])[-4:]
        limpios.append({**s, "text": t})
    return limpios


def agrupar_parrafos(segs: list[dict], max_seg: float = 75.0, pausa: float = 2.5) -> list[dict]:
    """Une segmentos en parrafos: corta por pausa larga o cada ~75 s."""
    parrafos: list[dict] = []
    actual: dict | None = None
    for s in segs:
        if actual and (s["start"] - actual["end"] > pausa or s["end"] - actual["start"] > max_seg):
            parrafos.append(actual)
            actual = None
        if actual is None:
            actual = {"start": s["start"], "end": s["end"], "text": s["text"]}
        else:
            actual["end"] = s["end"]
            actual["text"] += " " + s["text"]
    if actual:
        parrafos.append(actual)
    return parrafos


# --------------------------------------------------------------- transcripcion
_modelo_cache: dict = {}


def cargar_modelo(nombre: str, hilos: int):
    if nombre not in _modelo_cache:
        from faster_whisper import WhisperModel

        print(f"Cargando modelo '{nombre}' (la primera vez se descarga)...", flush=True)
        _modelo_cache[nombre] = WhisperModel(nombre, device="cpu", compute_type="int8", cpu_threads=hilos)
    return _modelo_cache[nombre]


def transcribir_archivo(ruta: Path, args) -> Path | None:
    from faster_whisper.audio import decode_audio

    materia = detectar_materia(ruta, args.materia)
    fecha = detectar_fecha(ruta)
    carpeta = SALIDA / nombre_seguro(materia)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / nombre_seguro(f"{fecha} - {ruta.stem}")
    md, txt, parcial = base.with_suffix(".md"), base.with_suffix(".txt"), base.with_suffix(".parcial.jsonl")

    if md.exists() and not args.rehacer:
        print(f"  ya existe, se omite: {md.relative_to(BASE)}")
        return md

    print(f"\n=== {ruta.name}  ->  [{materia}] {fecha}")
    audio = decode_audio(str(ruta), sampling_rate=SR)  # ffmpeg extrae el audio (sirve para video)
    duracion = len(audio) / SR
    print(f"  duracion: {hms(duracion)}")

    # Reanudar si quedo un parcial de una ejecucion anterior
    segs: list[dict] = []
    if parcial.exists() and not args.rehacer:
        segs = [json.loads(l) for l in parcial.read_text(encoding="utf-8").splitlines() if l.strip()]
        if segs:
            print(f"  reanudando desde {hms(segs[-1]['end'])}")
    elif parcial.exists():
        parcial.unlink()
    desde = segs[-1]["end"] if segs else 0.0

    modelo = cargar_modelo(args.modelo, args.hilos)
    t0 = time.time()
    resto = audio[int(desde * SR):]
    if len(resto) > SR:  # queda mas de 1 s por transcribir
        resultado, _info = modelo.transcribe(
            resto,
            language=args.idioma,
            task="transcribe",
            beam_size=args.beam,
            vad_filter=True,  # salta silencios -> mas rapido y menos alucinaciones
            vad_parameters={"min_silence_duration_ms": 700},
            condition_on_previous_text=False,  # evita bucles de repeticion en audios largos
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.2,
            initial_prompt=f"Clase de {materia}. Transcripción en español con puntuación.",
        )
        with parcial.open("a", encoding="utf-8") as fp:
            for s in resultado:
                item = {"start": round(s.start + desde, 2), "end": round(s.end + desde, 2), "text": s.text.strip()}
                segs.append(item)
                fp.write(json.dumps(item, ensure_ascii=False) + "\n")
                fp.flush()
                hecho = item["end"] / duracion if duracion else 1
                trans = time.time() - t0
                avance = item["end"] - desde
                eta = trans / avance * (duracion - item["end"]) if avance > 0 else 0
                print(f"\r  {hecho:6.1%}  [{hms(item['end'])}/{hms(duracion)}]  faltan ~{hms(eta)}   ",
                      end="", flush=True)
        print()

    parrafos = agrupar_parrafos(limpiar_segmentos(segs))
    escribir_salidas(md, txt, ruta, materia, fecha, duracion, parrafos, args.modelo)
    parcial.unlink(missing_ok=True)
    print(f"  listo en {hms(time.time() - t0)} -> {md.relative_to(BASE)}")
    return md


def escribir_salidas(md: Path, txt: Path, origen: Path, materia, fecha, duracion, parrafos, modelo):
    palabras = sum(len(p["text"].split()) for p in parrafos)
    cab = [
        f"# {materia} — {fecha}",
        "",
        "| Campo | Valor |",
        "|---|---|",
        f"| Materia | {materia} |",
        f"| Fecha | {fecha} |",
        f"| Archivo original | `{origen.name}` |",
        f"| Tipo | {'Video' if origen.suffix.lower() in {'.mp4','.mkv','.avi','.mov','.webm','.wmv','.flv','.3gp','.mpeg','.mpg','.ts'} else 'Audio'} |",
        f"| Duración | {hms(duracion)} |",
        f"| Palabras | {palabras} |",
        f"| Modelo | faster-whisper `{modelo}` (local) |",
        "",
        "---",
        "",
        "## Transcripción",
        "",
    ]
    cuerpo = [f"**[{hms(p['start'])}]** {p['text']}\n" for p in parrafos]
    md.write_text("\n".join(cab) + "\n" + "\n".join(cuerpo), encoding="utf-8")

    t = [f"{materia} - {fecha} - {origen.name} (duracion {hms(duracion)})", "=" * 60, ""]
    t += [f"[{hms(p['start'])}] {p['text']}\n" for p in parrafos]
    txt.write_text("\n".join(t), encoding="utf-8")


def generar_indice():
    filas: dict[str, list[tuple[str, Path]]] = {}
    for md in sorted(SALIDA.glob("*/*.md")):
        filas.setdefault(md.parent.name, []).append((md.stem, md))
    lineas = ["# Índice de transcripciones", "", f"_Actualizado: {dt.datetime.now():%Y-%m-%d %H:%M}_", ""]
    for materia in sorted(filas, key=lambda m: normalizar(m)):
        lineas += [f"## {materia}", ""]
        for nombre, md in sorted(filas[materia]):
            dur = ""
            m = re.search(r"\| Duración \| ([\d:]+) \|", md.read_text(encoding="utf-8"))
            if m:
                dur = f" — {m.group(1)}"
            rel = md.relative_to(SALIDA).as_posix().replace(" ", "%20")
            lineas.append(f"- [{nombre}]({rel}){dur}")
        lineas.append("")
    (SALIDA / "INDICE.md").write_text("\n".join(lineas), encoding="utf-8")


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Transcribe videos/audios de clases a Markdown y TXT.")
    ap.add_argument("archivos", nargs="*", help="archivos o carpetas (por defecto ./entrada)")
    ap.add_argument("--modelo", default="small",
                    help="tiny | base | small (defecto) | medium | large-v3-turbo")
    ap.add_argument("--idioma", default="es")
    ap.add_argument("--materia", help="forzar la materia para todos los archivos indicados")
    ap.add_argument("--beam", type=int, default=1, help="1 = rapido (defecto); 5 = un poco mas preciso y ~2x lento")
    ap.add_argument("--hilos", type=int, default=4, help="nucleos de CPU a usar")
    ap.add_argument("--rehacer", action="store_true", help="volver a transcribir aunque ya exista")
    args = ap.parse_args()

    ENTRADA.mkdir(exist_ok=True)
    SALIDA.mkdir(exist_ok=True)
    origenes = [Path(a) for a in args.archivos] or [ENTRADA]
    archivos: list[Path] = []
    for o in origenes:
        if o.is_dir():
            archivos += [p for p in o.rglob("*") if p.suffix.lower() in EXT_MEDIA]
        elif o.suffix.lower() in EXT_MEDIA:
            archivos.append(o)
    archivos = sorted(set(archivos), key=lambda p: (normalizar(detectar_materia(p, args.materia)), detectar_fecha(p), p.name))

    if not archivos:
        print(f"No hay videos/audios. Copialos en: {ENTRADA}")
        return
    print(f"{len(archivos)} archivo(s) para procesar con el modelo '{args.modelo}'.")
    errores = []
    for i, a in enumerate(archivos, 1):
        print(f"\n[{i}/{len(archivos)}]", end="")
        try:
            transcribir_archivo(a, args)
        except KeyboardInterrupt:
            print("\nInterrumpido. Lo avanzado quedo guardado; al volver a ejecutar se reanuda.")
            break
        except Exception as e:  # sigue con el resto
            print(f"\n  ERROR con {a.name}: {e}")
            errores.append(a.name)
        generar_indice()
    generar_indice()
    print(f"\nIndice: {SALIDA / 'INDICE.md'}")
    if errores:
        print("Fallaron:", ", ".join(errores))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

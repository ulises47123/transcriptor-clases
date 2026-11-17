# Transcriptor de clases (video + audio → Markdown/TXT)

Gratis, local y privado: usa **faster-whisper** en tu PC, así que ningún audio se sube a internet.

## Uso

1. Copiá los videos y audios en `entrada/`. Podés organizarlos de dos formas:
   - **Por carpeta:** `entrada/Fisica/clase1.mp4`, `entrada/Lengua/audio.mp3`
   - **Por nombre:** `entrada/fisica_2026-10-30.mp3`, `entrada/lengua 31-10-2026.mp4`
2. Hacé doble clic en **`TRANSCRIBIR.bat`**.
3. Las transcripciones quedan en `transcripciones/` así:

```
transcripciones/
├── INDICE.md                      ← índice con todas las clases por materia y fecha
├── Fisica/
│   ├── 2026-10-30 - clase1.md     ← con marcas de tiempo [hh:mm:ss] por párrafo
│   └── 2026-10-30 - clase1.txt
└── Lengua/
    └── ...
```

## Detalles

- **Materia:** se toma de la subcarpeta. Si no hay subcarpeta, se busca en el nombre del archivo (física, lengua, matemática, química, historia…). Si no se encuentra, va a `Sin_clasificar/`.
- **Fecha:** se toma del nombre (`2026-10-30`, `30-10-2026` o `20261030`). Si no está, se usa la fecha de modificación del archivo.
- **Reanudar:** si se corta la luz o cerrás la ventana, al volver a ejecutar sigue desde donde quedó.
- **No repite trabajo:** los archivos ya transcritos se saltan (`--rehacer` para forzar).
- **Sin repeticiones:** filtra los bucles de frases repetidas y las frases que Whisper inventa ("Subtítulos realizados por…", "Gracias por ver el video").

## Velocidad en esta PC (Celeron N5100, sin GPU)

| Modelo | Calidad | Tiempo aprox. para 1 h de audio |
|---|---|---|
| `base` | aceptable | ~25–30 min |
| `small` (defecto) | muy buena | ~1 h |
| `medium` | excelente | ~3 h (dejarlo de noche) |

```
python transcribir.py --modelo base
python transcribir.py --modelo medium
python transcribir.py --materia Historia "D:\grabaciones\audio raro.m4a"
```

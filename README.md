# Transcriptor de clases

Script en Python que transcribe grabaciones de clases (video o audio) a **Markdown y TXT**, ordenadas por materia y fecha. Funciona 100 % local con [faster-whisper](https://github.com/SYSTRAN/faster-whisper): el audio nunca sale de la PC.

## Requisitos

- Python 3.10 o superior.
- `pip install faster-whisper` (incluye la decodificación de audio/video vía PyAV).

## Uso rápido

1. Poné los videos o audios en `entrada/` (por carpeta de materia, por ejemplo `entrada/Fisica/clase1.mp4`, o con la materia en el nombre del archivo).
2. Ejecutá `TRANSCRIBIR.bat` (Windows) o `python transcribir.py`.
3. Los resultados quedan en `transcripciones/<Materia>/` con un `INDICE.md` general.

Opciones: `--modelo base|small|medium`, `--materia <nombre> archivo`, `--rehacer`. Más detalles en [`LEEME.md`](LEEME.md).

> Las carpetas `entrada/` y `transcripciones/` están en `.gitignore`: las grabaciones y transcripciones no se suben al repositorio.

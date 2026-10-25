# Entrenar las voces en Colab (estrategia "IA XTTS Text to Voice")

Guía para fine-tunear XTTS v2 con los clips reales del doblaje usando el
cuaderno de Colab (GPU gratis) y usar el resultado en charla. Cuaderno de
referencia: "IA XTTS Text to Voice 2.3" (canal Sistema de Interés) —
`https://colab.research.google.com/drive/1Wpu1vBIKWn5eRXG_VIEsm6fLn0LU7_rH`.

## Qué ya está preparado en este repo

- `voices_preview/reales/dataset_rick.zip` — 1 clip de Rick (Juan Guzmán),
  WAV 48 kHz mono normalizado (27 s).
- `voices_preview/reales/dataset_morty.zip` — 7 clips de Morty (Eder La
  Barrera), WAV 48 kHz mono normalizados (63 s).

⚠ **Cantidad de audio**: con menos de 1 minuto por personaje el fine-tune
saldrá justo. XTTS mejora mucho con 2-10 min de audio limpio y variado
(sin música ni efectos de fondo). Si puedes, junta más clips antes de
entrenar — sobre todo de Rick, que solo tiene 27 s.

## Pasos en el cuaderno (una vez POR PERSONAJE)

1. **Celda 1 (Installing the requirements)**: ejecútala tal cual (monta tu
   Drive, clona el fork de TTS e instala dependencias). Runtime = GPU (T4).
2. **Celda "🕚 Entrenamiento de un nuevo Modelo"**: ejecuta
   `xtts_train.py`. Se abre una interfaz Gradio con 3 pasos:
   - *Step 1 — Data processing*: sube los WAV del zip del personaje
     (descomprímelo antes), idioma `es`. El cuaderno transcribe con Whisper
     y arma el dataset.
   - *Step 2 — Fine-tuning*: batch size 2, epochs 6 (los defaults de la
     celda). Con tan poco audio puedes subir epochs a 10-15 sin miedo.
   - *Step 3 — Inference*: prueba el modelo dentro del propio Gradio hasta
     que te convenza.
3. **Celda "✅ Save Model (Google Drive)"**: pon un `zip_filename` (p. ej.
   `xtts_rick`) y ejecútala — guarda en tu Drive un zip con
   `best_model.pth` + `config.json` + `vocab.json`.
4. Repite 2-3 con el otro personaje (`xtts_morty`).

## Volcar el resultado en charla

Descarga los zips de tu Drive y descomprímelos así:

```
models/xtts/rick/   best_model.pth  config.json  vocab.json
models/xtts/morty/  best_model.pth  config.json  vocab.json
```

Nada más: `charla ... --tts xtts` detecta el checkpoint por personaje
automáticamente (si falta, usa el modelo base con clonación zero-shot desde
`voices_preview/reales/<personaje>/`, que funciona sin entrenar nada).

## Notas

- La inferencia local corre en CPU (lenta: ~1-2 min por línea; se cachea
  por turno, así que solo pagas el coste la primera vez por guion).
- Con `--tts xtts` no hay word timings → los subtítulos salen por línea
  completa en vez de progresivos por palabra.
- Licencia XTTS (Coqui Public Model License): uso no comercial.

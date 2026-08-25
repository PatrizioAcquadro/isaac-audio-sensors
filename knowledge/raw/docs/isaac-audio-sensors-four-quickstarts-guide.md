# Guida personale — Quattro modi per provare Isaac Audio Sensors

Ultima verifica locale: 2026-08-25, branch `main`, commit `885d2a9`.

Questa guida spiega quattro percorsi indipendenti per provare
`isaac-audio-sensors`:

1. Core/CLI, senza Isaac.
2. Kit extension, visualmente in Isaac Sim.
3. Isaac Sim controllato tramite Python o in modalità headless.
4. Isaac Lab, con osservazioni tensoriali per il training RL.

Tutti e quattro i percorsi sono stati rieseguiti separatamente sul checkout
indicato sopra e hanno dato `PASS`.

## Mappa mentale

| Percorso | Cosa controlla | Output principale | Quando usarlo |
|---|---|---|---|
| Core/CLI | Il modello audio senza simulatore | `AudioSensorFrame` JSON | Configurazione, contratti e algoritmi |
| Kit extension | Lo stesso sensore dentro una scena USD, tramite GUI | Monitor, compass, RMS, WAV e JSONL | Esplorazione e debug visuale |
| Isaac Sim Python | Scena e sensore controllati da codice | Frame, WAV, JSONL e report headless | Automazione, batch e integrazione |
| Isaac Lab | Sensore batched per molti ambienti RL | Tensori PyTorch su GPU | Training e policy |

I quickstart sono indipendenti: non è necessario completare il primo per usare
gli altri.

## 1. Primo frame tramite CLI, senza Isaac

### Obiettivo

Verificare che configurazione, array, sorgenti e backend funzionino senza Isaac
Sim, GPU, USD o Torch.

### Passaggi

```bash
cd /home/pacquadr/Desktop/isaac-audio-sensors

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

isaac-audio-sensors validate-config \
  examples/configs/isaac_audio_sensors_demo.toml

isaac-audio-sensors simulate \
  examples/configs/isaac_audio_sensors_demo.toml \
  --backend geometry_only \
  --array-id rig_front
```

Configurazione usata:
[isaac_audio_sensors_demo.toml](../../../examples/configs/isaac_audio_sensors_demo.toml).

### Risultato atteso, annotato

Risultato reale ottenuto durante la verifica:

```text
schema_version = ias.audio_sensor_frame.v1
                 └─ formato pubblico e versionato del frame

backend_id = geometry_only
             └─ calcola geometria, direzione, distanza e RMS;
                non genera una forma d'onda fisica

array_id = rig_front
           └─ array a quattro microfoni selezionato

detection 0:
  source = speaker_front_right
  bearing = 26.565°
  sector = straight_right
  confidence = 1.0

detection 1:
  source = speaker_left
  bearing = 303.690°
  sector = straight_left
  confidence = 1.0

waveform_paths = []
                 └─ corretto con geometry_only
```

Qui “primo frame” significa una fotografia strutturata di ciò che il sensore
rileva nell'intervallo corrente.

### Errore più comune

Vedere `waveform_paths: []` e pensare che il sensore non funzioni.

Non è un errore: `geometry_only` produce feature geometriche, non audio PCM. Per
una forma d'onda multicanale serve `room_acoustics` e l'extra:

```bash
python -m pip install -e ".[room]"
```

## 2. Primo sensore live tramite Kit extension

### Obiettivo

Aprire il pannello visuale dentro Isaac Sim, costruire una scena demo, avviare
il sensore e osservare direzione e livelli dei microfoni.

### Passaggi

1. Uscire da eventuali virtual environment o ambienti Conda e avviare Isaac Sim:

   ```bash
   /home/pacquadr/isaacsim/isaac-sim.sh
   ```

2. Aprire `Window -> Extensions`.

3. Nelle impostazioni dell'Extension Manager aggiungere questo search path:

   ```text
   /home/pacquadr/Desktop/isaac-audio-sensors/exts
   ```

4. Cercare e abilitare `Isaac Audio Sensors`.

5. Aprire `Window -> Isaac Audio Sensors`.

   È disponibile anche la scorciatoia `Ctrl+Alt+A`.

6. Nel `Guided Workflow` seguire:

   ```text
   Setup -> Validate -> Run -> Inspect -> Record -> Export
   ```

Per riprodurre automaticamente l'intero controllo visuale:

```bash
cd /home/pacquadr/Desktop/isaac-audio-sensors
make smoke-kit
```

### Risultato atteso, con screenshot annotato

![Risultato live della Kit extension](../assets/isaac-audio-sensors-four-quickstarts/kit-live-monitor.png)

Annotazione:

1. In alto, `Guided Workflow`: i sei passaggi operativi.
2. `Backend: tdoa_synthetic`: il monitor mostra stime TDOA sintetiche.
3. La bussola indica `104.2°`, settore `right`, confidenza `0.93`.
4. Le quattro barre sono gli RMS dei microfoni `front`, `right`, `rear` e
   `left`, circa `-15 dBFS`.
5. `Detections: 1` significa che il frame contiene un evento attivo.
6. `Waveform: None yet` è corretto in questo momento perché lo screenshot usa
   `tdoa_synthetic`; lo smoke passa poi a `room_acoustics` e verifica un WAV a
   quattro canali.
7. `Sensor stopped` è lo stato finale dello smoke, che arresta intenzionalmente
   il sensore dopo la cattura; il frame visualizzato rimane valido.
8. L'avviso giallo `widths primvar is not valid` proviene dal rendering delle
   curve di debug. Nel test corrente è non bloccante: il report finale è
   `status: passed`.

Risultato reale del test:

```text
UI disponibile:                 sì
Workflow completato:            38 operazioni
Bearing:                        104.191°
Confidenza:                     0.9316
Sensor WAV:                     4 canali, 48 kHz
Kit listener/device mix:        2 canali, 48 kHz, non silenzioso
Stato finale:                   PASS
```

Il mix Kit a due canali rappresenta il dispositivo/listener. Non è il WAV a
quattro canali dell'array microfonico.

### Errore più comune

L'estensione non appare nell'Extension Manager.

Il search path deve essere la directory `exts`, cioè la cartella che contiene
`isaac_audio_sensors.omni`, non `src` e non la directory Python interna.

## 3. Prima scena audio tramite Python in Isaac Sim

### Obiettivo

Creare e controllare tramite codice una scena USD contenente:

- una sorgente `OmniSound`;
- un array a quattro microfoni;
- un `OmniListener`;
- discovery semantica;
- aggiornamenti del sensore e frame esportati.

### Passaggi

Il primo risultato completo e mantenuto è:

```bash
cd /home/pacquadr/Desktop/isaac-audio-sensors
make smoke-isaac-sim
```

Questo esegue
[live_isaac_sim_audio_smoke.py](../../../tools/smoke/live_isaac_sim_audio_smoke.py)
mediante l'interprete Isaac:

```text
/home/pacquadr/IsaacLab/isaaclab.sh -p
```

Lo script:

1. inizializza `SimulationApp` in modalità headless;
2. crea uno stage USD in memoria;
3. crea sorgente, listener, array e quattro microfoni;
4. scopre automaticamente gli elementi sotto `/World`;
5. muove sorgente e microfono in tre fasi;
6. esegue `geometry_only`, `tdoa_synthetic` e `room_acoustics`;
7. salva frame JSONL e WAV.

Il file
[live_audio_lab.py](../../../examples/isaac_sim/live_audio_lab.py)
è invece una ricetta concisa con funzioni riutilizzabili: da solo non contiene
un `main` e non stampa un risultato.

### Risultato atteso, annotato

Risultato reale sul commit verificato:

```text
status = passed
         └─ lo script è terminato con exit code 0

headless = true
           └─ Isaac Sim è attivo, ma non apre una finestra

source_count = 1
array_count = 1
microphone_count = 4

backend_statuses:
  geometry_only  = passed
  tdoa_synthetic = passed
  room_acoustics = passed

jsonl_frame_count = 9
                    └─ 3 fasi temporali × 3 backend
```

Il report completo viene generato in:

```text
build/validation/isaac_audio_sensors/isaac_sim_live_smoke.json
```

Rappresentazione visuale della stessa struttura di scena, catturata dal test
Python visuale:

![Scena audio controllata tramite Python](../assets/isaac-audio-sensors-four-quickstarts/python-audio-scene.png)

Annotazione:

1. Il gruppo blu è l'array microfonico.
2. Il cubo giallo è l'oggetto al quale è collegata la sorgente.
3. Il punto arancione identifica la posizione della sorgente.
4. Le linee verdi sono le primitive di debug che mostrano relazione spaziale,
   bearing e settore.

Il comando headless non apre questa viewport: il suo risultato ufficiale è il
report JSON/JSONL.

### Errore più comune

Eseguire lo script con `python3` di sistema e ricevere errori come:

```text
ModuleNotFoundError: No module named 'omni'
ModuleNotFoundError: No module named 'pxr'
```

Gli script Isaac devono essere eseguiti con `isaaclab.sh -p` oppure con
`isaacsim/python.sh`, non con il Python del virtual environment Core.

## 4. Prima osservazione tensoriale in Isaac Lab

### Obiettivo

Trasformare lo stato di molti ambienti Isaac Lab in osservazioni a forma fissa,
direttamente utilizzabili da una policy RL.

Il contratto è:

```text
event_presence [N,E]      bool
bearing_deg [N,E]         float32
confidence [N,E]          float32
sector_onehot [N,E,8]     float32
per_mic_rms [N,E,M]       float32
ambiguity_mask [N,E]      bool
```

Dove:

- `N` è il numero di ambienti paralleli;
- `E` è il massimo numero di eventi per ambiente;
- `M` è il numero di microfoni.

### Passaggi

Verifica completa:

```bash
cd /home/pacquadr/Desktop/isaac-audio-sensors
make smoke-isaac-lab
```

Per inserirlo in un task RL:

1. avviare prima `AppLauncher`;
2. creare `AudioArraySensorCfg`;
3. collegare il sensore alle entità `robot` e `speaker` tramite
   `bind_entities`;
4. chiamare `sensor.update(dt)`;
5. aggiungere i sei tensori al dizionario delle observation.

La ricetta esatta è in
[isaac_lab_audio_observation.py](../../../examples/isaac_lab/isaac_lab_audio_observation.py).

Il percorso di training usa `bind_entities`. `bind_reference` è il percorso
scalare di confronto/debug. Durante il training, entity mode supporta
`geometry_only` e `tdoa_synthetic`; non usa `room_acoustics` o effects e non
effettua fallback CUDA-to-CPU.

### Risultato atteso, annotato

Prima osservazione reale ottenuta su `cuda:0`:

```text
event_presence [1,2] bool
[[true, false]]
  │      └─ secondo slot vuoto
  └─ primo evento presente

bearing_deg [1,2] float32
[[13.994°, NaN]]
   │        └─ NaN è il padding previsto
   └─ direzione del primo evento

confidence [1,2] float32
[[0.9296, 0.0]]

sector_onehot [1,2,8] float32
primo slot   = [1,0,0,0,0,0,0,0]
secondo slot = tutti zero

per_mic_rms [1,2,4] float32
primo slot   = [0.2472, 0.2436, 0.2381, 0.2414]
secondo slot = [0, 0, 0, 0]

ambiguity_mask [1,2] bool
[[false, false]]

device = cuda:0
status = passed
```

Lo smoke completo ha inoltre verificato:

```text
GPU:                     NVIDIA GeForce RTX 4090
Ambienti paralleli:      4096
Update misurati:         50
Tempo medio:             1.991 ms/step
Budget:                  20 ms/step
Entity/reference parity: PASS
Partial reset:           PASS
```

### Errore più comune

Il `prim_path` non corrisponde ai prim realmente creati negli ambienti:

```text
ValueError: Binding has 1 environments; SensorBase resolved 0.
```

Il percorso deve risolvere esattamente un sensore per ambiente, per esempio:

```python
prim_path="{ENV_REGEX_NS}/Robot/audio_array"
```

Inoltre `AppLauncher` deve essere inizializzato prima di risolvere le classi
Isaac Lab.

## Stato verificato

- Core/CLI: **PASS**
- Kit extension visuale: **PASS**
- Isaac Sim Python/headless: **PASS**
- Isaac Lab CUDA/RL: **PASS**
- GPU usata per i gate Isaac: NVIDIA GeForce RTX 4090
- Commit verificato: `885d2a9`

Questi risultati provano il funzionamento software dei quattro percorsi. Non
dimostrano fedeltà acustica fisica, calibrazione hardware, qualità di una policy
downstream o sim-to-real.

## File principali

- Configurazione CLI:
  `examples/configs/isaac_audio_sensors_demo.toml`
- Ricetta Isaac Sim:
  `examples/isaac_sim/live_audio_lab.py`
- Smoke Isaac Sim:
  `tools/smoke/live_isaac_sim_audio_smoke.py`
- Ricetta Isaac Lab:
  `examples/isaac_lab/isaac_lab_audio_observation.py`
- Smoke Isaac Lab:
  `tools/smoke/live_isaac_lab_audio_smoke.py`
- Smoke Kit:
  `tools/smoke/live_omniverse_extension_ux.py`

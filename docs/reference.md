# sortering-pnp reference

Everything in detail: every tab, every setting and why it works the way it does. Start with the
[README](../README.md) for installing and using the machine; come here when you want to know more.
Settings are in [configs/machine.yaml](../configs/machine.yaml) (each has a comment there too).

## Contents

- [Hardware](#hardware)
- [Installing and the pinned versions](#installing-and-the-pinned-versions)
- [The Setup tab, step by step](#the-setup-tab-step-by-step)
- [Models: upload over WiFi, keep the old ones](#models-upload-over-wifi-keep-the-old-ones)
- [Files tab: files from the other projects](#files-tab-files-from-the-other-projects)
- [Camera Calibration tab](#camera-calibration-tab)
- [Only the tray goes to the model](#only-the-tray-goes-to-the-model)
- [Wild bins](#wild-bins)
- [How full the bins are](#how-full-the-bins-are)
- [Bin changes: full bins and new kinds](#bin-changes-full-bins-and-new-kinds)
- [Strategies and picking order](#strategies-and-picking-order)
- [Where a part is taken: grip point, direction, centre of mass](#where-a-part-is-taken-grip-point-direction-centre-of-mass)
- [Tweezers on a Z rotation axis](#tweezers-on-a-z-rotation-axis)
- [One cycle: photo, pick, drop, park](#one-cycle-photo-pick-drop-park)
- [X/Y acceleration profile](#xy-acceleration-profile)
- [Automatic mode](#automatic-mode)
- [The start-up check](#the-start-up-check)
- [Homing](#homing)
- [A camera on the tool head (optional)](#a-camera-on-the-tool-head-optional)
- [Real photos (Photos tab)](#real-photos-photos-tab)
- [On the machine (Setup tab)](#on-the-machine-setup-tab)
- [The console](#the-console)
- [Printer menu](#printer-menu)
- [Login](#login)
- [Frames, markers and safety](#frames-markers-and-safety)
- [Development](#development)

## Hardware

| Part | Notes |
|---|---|
| Printer running **Klipper + Moonraker** on the Pi | the usual Klipper install (KIAUH, MainsailOS); OctoPrint can stay or go |
| Pi Camera Module 3 over the bed | the same one, and the same calibration, as screw-synth |
| A **picker** on the toolhead | servo tweezers, suction cup, magnet or pneumatic tweezers (see below), wired to the Pi; swappable with the hotend |
| Gridfinity **baseplate** + **bins** | printed from the web page's *Print bins* tab |
| A matte TPU plate in the working area | blue or green, as for the camera |
| Addressable LEDs (optional) | a WS2812B ring round the lens, e.g. the Opulo LumenPnP top ring light (see below) |

### Picker

Chosen in the Setup tab (`picker.mode` in machine.yaml; the page's choice is kept in
`data/machine.json`). All four are wired to the **Raspberry Pi's pins**, which Klipper drives as a
second micro-controller (its Linux "host" MCU):

| `picker.mode` | Grabs with (GPIO12, pin 32) | Turns (GPIO13, pin 33) | Aims at |
|---|---|---|---|
| `servo_tweezers` | jaw servo | turn servo, 0–180° | centre of gravity, on the shank |
| `suction` | vacuum pump through a MOSFET module | – | the head |
| `magnet` | servo pressing a magnet against an iron rod | – | the head |
| `pneumatic_tweezers` | pump through a MOSFET module (springs open) | turn servo, 0–180° | centre of gravity |

The old names still work: `vacuum` = `suction`; `gripper`, `tweezers` and `both` = `servo_tweezers`.

**Suction cups** for `suction` are in [prints/cups/](../prints/cups/) (TPU 95A,
[printables/cups.py](../src/sortering_pnp/printables/cups.py)): a straight Ø7 body held in the
picker's 7 mm socket by 3 M3 screws in blind holes, a neck with a Ø4.3 bore (every cup 47 mm
long, shank to lip: swapping keeps the tip height), folds that go
inwards, and five tips (AS, AM: a short lip for flat faces; DS, DM, DL: a thin skirt for curved
ones); AM, DM and DL also with a sieve (a ring of holes on a dome the part rests on). Every hole
is smaller than the smallest head the tip picks (the head closes the cup). Soft: the folds and
the lip one line of a 0.4 mm nozzle, the cup's wall `SOFT_WALL` (0.6 mm); sized for a 0.4 mm
nozzle (`MIN_LINE`, `MIN_HOLE`): every wall one line or more across each layer.

- **Pins:** sortering-pnp switches them itself ([pins.py](../src/sortering_pnp/pins.py)); the
  picker is not in Klipper. GPIO12 (`picker.action_pin`) is a plain on/off output for a pump
  (gpiozero, part of Raspberry Pi OS) or a servo; GPIO13 (`picker.turn_pin`) the turning servo.
  Servos use the Pi's two hardware PWM channels (`/sys/class/pwm`), enabled by
  `dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4` in `/boot/firmware/config.txt`, which
  `install-pi.sh` adds (reboot once). GND is pin 34. A channel's files are root's for a moment
  after it is exported, until udev gives them to the `gpio` group: the program waits up to 3 s
  for that, and `install-pi.sh` adds a udev rule (`/etc/udev/rules.d/99-sortering-pnp-pwm.rules`)
  that does it for every PWM chip. "Permission denied: …/pwm1/period" means that rule or the
  `gpio` group is missing: run `install-pi.sh` again.
- **Order and safety:** before grabbing or letting go, sortering-pnp waits until Klipper has
  finished every move (`M400`). The pump goes off on Stop, on an error, on the emergency stop
  and when the program ends; a MOSFET module's pull-down keeps it off while nothing drives the
  pin.
- **Signals:** always from the Pi, never from the printer's board (the same wiring on any printer).
- **Power:** straight from the printer's 24 V supply, never from the heater outputs (Klipper
  switches those under heater safety). Servos: a 24 V pair to the tip and a 5 V buck converter
  there, never the Pi's 5 V pin. Pumps: 24 V through a MOSFET module (logic level, e.g. AOD4184:
  the IRF520 module only half-opens at 3.3 V), with a flyback diode across the pump. All grounds
  joined.
- **Servo angles:** each type has its own (jaws closed 20° / open 90°, magnet on 160° / off 20°,
  in [pickers.py](../src/sortering_pnp/pickers.py)); `picker.grab_angle` and
  `picker.release_angle` in `configs/machine.yaml` override them.
- **Where it aims:** a cup or a magnet goes onto the middle of the screw's head (seen from above);
  tweezers close on the shank at the centre of gravity. Headless parts are taken in the middle,
  nuts and washers at the centre of their outline.

### Lights

Addressable LEDs (WS2812B, 5 V; the Opulo LumenPnP ring has 8 and a 3-pin JST XH) are driven by
sortering-pnp itself ([leds.py](../src/sortering_pnp/leds.py)), like the picker: nothing in
Klipper and no extra package. The data goes out on the Pi's SPI0 MOSI, and the SPI hardware
makes the LEDs' timing (each LED bit is 3 SPI bits at 2.4 MHz).

| Ring | Goes to |
|---|---|
| 5V | a 5 V buck converter (set to 5.0 V) on the printer's 24 V supply, not the Pi's 5 V pins |
| GND | Pi pin 20 (ground), joined with the converter's minus |
| DIN | Pi pin 19 (GPIO10, SPI0 MOSI) |

The Setup tab's Lights step draws it, like the picker's wiring.

- **Set up:** `install-pi.sh` adds `dtparam=spi=on` and `core_freq_min=500` (a Pi 4's SPI clock
  follows the core clock: fixed, the timing holds) to `/boot/firmware/config.txt` and puts you
  in the `spi` group; reboot once. Then the Setup tab's **Lights** step (before the camera):
  colour (picker, hex or R/G/B sliders), intensity, *Always on* (off: lit only while a photo is
  taken, `lights.settle_s` before it). Every change shows on the LEDs at once and is kept in
  `data/machine.json`. *No lights* completes the step on a machine without them.
- **Level:** the Pi's 3.3 V data drives a short lead to WS2812B at 5 V in practice. If they
  flicker or show wrong colours, put a 74AHCT125 level shifter in the data line (or a 1N4001
  diode in the ring's 5 V lead, which lowers what it counts as high).
- **Power:** 8 LEDs at full white take about 0.5 A, fine from the Pi's 5 V pin with the
  official 3 A supply. For more LEDs, feed them from a 5 V buck converter on the 24 V supply,
  grounds joined.
- **Settings:** `lights:` in machine.yaml (count, colour order, SPI bus and device).

### Swappable tool

Klipper remembers whether the picker is on. **OK** in the Setup tab's Picker step runs
`TOOL_PICKER` (it also switches the heaters off); `TOOL_PICKER` / `TOOL_HOTEND` also work from the
printer menu (*Screw sorter → Picker mounted / Hotend mounted*) or Mainsail's console, e.g. when
the head is used for printing. **Sorting** refuses to move unless the picker is on and the hotend
is cold; the Setup tab's own moves (homing, the limits, jogging, the photos) only need a cold
hotend, because someone watches them and they come before the picker is put on.

## Installing and the pinned versions

A Raspberry Pi **4 or 5** (4 GB or more) with 64-bit Raspberry Pi OS (Bookworm or Trixie). A
Pi 3B has too little memory for Klipper, the camera and the model together.

```bash
git clone https://github.com/ama24/sortering-pnp.git ~/sortering-pnp
~/sortering-pnp/install-pi.sh --service      # --service: start sortering-pnp at every boot
```

The script also does Klipper's side (`sortering-pnp klipper`, [klippercfg.py](../src/sortering_pnp/klippercfg.py),
`paths.klipper_config`): sortering_pnp.cfg next to printer.cfg, its include once and after your
own sections (it sets `[stepper_y]` homing speeds, and the later value wins), `[safe_z_home]`
commented out, the old picker include removed, backups kept, then FIRMWARE_RESTART unless
Klipper prints. What can go wrong and what to do: README, *Klipper's config: what goes wrong*.

**Everything is pinned**, so installing again in a year gives exactly the same programs:
- [requirements-pi.lock.txt](../requirements-pi.lock.txt) lists every Python package with its
  exact version **and a checksum of the file**. It's installed with `--no-deps --require-hashes`,
  so pip installs nothing else and refuses a file that differs in any way.
- Nothing else is fetched: the camera, calibration and measurement code are part of
  sortering-pnp, and the trained model is uploaded in the web page (Models tab).
- The script puts everything in a Python environment inside the clone (`~/sortering-pnp/.venv`),
  checks that OpenCV has ArUco and that PyTorch is the CPU build, and says what to do next.

To upgrade on purpose: run `python scripts/lock_pi.py`, test it on the Pi, then commit.

Then restart Klipper (`FIRMWARE_RESTART`); the picker is chosen and installed later in the
Setup tab. Check everything with:

```bash
cd ~/sortering-pnp && sortering-pnp check
```

Start it with `sortering-pnp serve`, and open `http://<pi>:8080` on the PC or phone. The first
visit asks you to create an account (see [Login](#login)).

> **sortering-pnp is the only program that moves the printer.** The camera calibration and the
> real photos are taken from its web page (Calibrate and Photos tabs): sortering-pnp parks the bed
> and works the camera.

## The Setup tab, step by step

On a real printer, **Sort**, **One pick** and **Automatic** are refused, also from the printer
menu, until every step of the **Setup** tab is checked:

1. **Printer:** Klipper answers, `sortering_pnp.cfg` is included, the hotend is cold, nothing is
   printing. Only questions, nothing moves.
2. **Homing:** press *Home now* and watch. Z must come down over the middle of the plate, not
   over a bin. Then confirm.
3. **Machine:** limits, travel height, photo position and picker-change position
   (`printer.change_position`), editable on the page. *Show me* buttons drive to each position
   (at travel height). *Confirm* confirms and sends the head to the
   picker-change position.
4. **Picker:** choose the type (the page draws its wiring to the Pi and says whether its pins
   are ready); *Grab* / *Release* and, for tweezers, *Turn to 0°* / *90°* and the offset try it
   without moving. Put it on the head, then **OK** (`TOOL_PICKER`: sorting needs it). Choosing
   another type un-checks the step.
5. **Tip height:** in the step: *Go to centre* (over the plate), the Z jog buttons and *Set
   height* on one row. Checks itself.
6. **Lights:** colour and intensity of the LEDs (see [Lights](#lights)), shown at once; *OK*.
   *No lights* when there are none. Before the camera: its photos are taken with them.
7. **Camera to printer:** in the step: *Take photo* (the codes circled on it and listed with
   their bin size; no model needed), the jog pad, *Tip is here* per code (then *Move tip here* goes back to that point), *Fit*. Checks itself
   when the worst error is under 1 mm.
8. **Layout:** *Find bins* (= Resync). Checks itself when the bins and a plate are found
   without problems.

Until then the machine moves only when you ask it to in these steps. Jogging and the calibration
photos never home by themselves. Changing the machine values, a worse calibration or a layout
with problems un-checks the matching step again. In the simulator (`--sim`) the setup isn't
required.

The steps below are the same work in more detail.

1. **Choose your bed:** a baseplate of any size (5 × 5 cells is the most for an Ender 3), a
   tray as the plate (3 × 3, or 4 × 4 for big jobs), and as many bins as you like.
2. **Print the bins and the baseplate:** ready-made plates of every size are in
   [prints/](../prints/) (16 small bins per Ender 3 plate, with codes, and the slim 2.5 mm
   baseplate). The web page's **Print bins** tab makes the same for any other layout. Bins
   come as two-part 3MF files, the bin (white) and its code (black). With one extruder, add a
   colour change at the rim height (21 mm for 3-unit bins).
3. Put the baseplate anywhere on the bed, the tray and the bins anywhere on it (turned any way),
   and a TPU sheet cut to size in the tray. To hold the baseplate down, print the version that
   **covers the whole bed** (Ender 3 or Prusa MK3, slim or standard, in 4 pieces that fit the
   printer) and clamp it with binder clips, or on the Prusa stick it onto a spare steel sheet.
4. Put the picker on and press **OK** (Setup tab, Picker). Set `tool.offset` in
   [configs/machine.yaml](../configs/machine.yaml) if the picker tip is not where the nozzle was.
5. Set `printer.photo_position`: where the head waits during photos, out of the picture.
6. **Camera calibration** (Camera Calibration tab, *Camera calibration*): lay the ChArUco board **in the
   tray**, where the parts will lie. Its surface is the height everything is measured from.
   **Setup tab, Camera to printer**: take a photo, then jog the tip onto the centre of 3 or more markers
   (spread over the bed), pressing **Tip is here** on each. Then **Fit**. Errors under 0.5 mm
   are good. **Check** moves the tip just above a marker to confirm.
7. **Device tab → Resync** (next to the bed): one photo finds where the baseplate lies, which
   bins stand where and which way round, and makes the **biggest bin the plate**. To use
   another bin as the plate, give it the role *work*; Resync keeps your choice from then on.
   Bins taken off the bed keep their rules and get them back when they return. Give the other
   bins rules (*holds*) or leave them wild. With a model loaded, Resync also does the start-up
   check's **Bins check** on the same photo (see [The start-up check](#the-start-up-check)).
8. **Device tab**: pick a strategy and press **Start automatic** (*Manual* has Sort once and One
   pick), or use the printer menu.

## Models: upload over WiFi, keep the old ones

The **Models** tab (`http://<pi>:8080/#models`) is where models arrive. Drag a file onto the drop
zone, or click it to choose one. It takes:

| File | What it is |
|---|---|
| **package zip** (recommended) | training-synth's whole `package` folder zipped: `best.pt`, `model_card.json`, `exports/…` |
| zipped NCNN folder | e.g. `best_ncnn_model.zip` (contains `model.ncnn.param`, `model.ncnn.bin`, `metadata.yaml`) |
| `.onnx` or `.pt` | a single weights file |

Every upload is checked:
- **what kind of model it is** (from the model card or the NCNN metadata);
- **its classes**, compared with the catalogue: a model knowing none of them is refused, and
  missing or extra classes are listed;
- **its image size and score**.

Each upload is stored in its own folder (`models/`). **Old models are never replaced**: press
**Use** on any of them to switch back. The switch happens without a restart, and if the new
model fails to load, the old one stays in use. **Test** runs a stored model on the last photo
and shows its outlines, without switching. The first model of each kind is put in use by itself.

When a package holds several formats, the Pi uses **NCNN** (fastest on its CPU), full precision
first. You can pick another one from the list.

Kinds of models and what they do here:

| Model task | Role | What you get |
|---|---|---|
| **segment** | finds parts (stage 1) | outlines, classes, positions, lengths: everything |
| **obb** / **detect** | finds parts (stage 1) | classes and positions only; lengths are not measured, so part-number rules send parts to *unsure* |
| **pose** | measures length (stage 2, optional) | keypoints for a more precise length |
| **classify** | re-checks classes (optional) | looks at a close-up of every part and corrects the class when it is at least `models.classifier_conf` sure |

If the card has a recommended confidence, it is used for stage 1 (`models.use_recommended_conf`).

> Only upload models you trust: `.pt` files are Python pickles and can contain code.

## Files tab: files from the other projects

sortering-pnp keeps its own copy of every file it uses from the other projects, so it runs on its
own and never reads their folders. It comes with working defaults for all of them except the
calibration, which the Camera Calibration tab makes. The **Files** tab has a card for each one, saying where to
find it, what it is for and what is done without it, and which copy is in use. Fetch the file,
drop it on its card: it is checked, kept on the Pi (`paths.files`) and used at once.

| File | Where to get it | Without it |
|---|---|---|
| `calibration.json` | made here: Camera Calibration tab | nominal camera |
| `head_calibration.json` | the same, with a head camera | only needed with a head camera |
| `vision.yaml` | comes with sortering-pnp (`src/sortering_pnp/defaults/`): change and drop it back | the built-in one |
| `parts.json` | inside every model package; or screw-synth: `screwsynth-catalogue parts --out parts.json` | the built-in one (the whole screw-synth catalogue) |
| `classes.yaml` | inside every model package; or screw-synth: `configs/classes.yaml` | the built-in one |
| `items.json` | screw-synth: `screwsynth-partgen items --out items.json` | volumes estimated from the camera |

`parts.json` and `classes.yaml` come from the **active model** first, so they always match it.
After that: a dropped file, then a path set in machine.yaml, then the copy that comes with
sortering-pnp. Models, including ones from anywhere else, go in the Models tab.

## Camera Calibration tab

**Camera** (top card): the live picture, with
- **Rotate 90°** (clockwise) and **Mirror** (left-right): the camera flips its own picture
  (`camera.hflip`, `vflip`), a quarter turn is done in software (`camera.turn90`: the photo is
  then taller than wide). Afterwards redo Camera to printer.
- **Park bed:** the bed to the photo position, so the live picture shows the tray as the photos
  will.
- **Focus** (Auto, or Manual at a lens position; **Autofocus** focuses once on the tray and keeps
  that), **White balance** (Auto, or Manual red and blue gains), **Exposure** (Auto, or Manual
  shutter and gain) and **Image** (brightness, contrast, sharpness, saturation):
  `camera.adjust`, kept in `paths.machine`, applied at once to the photos and the live picture.
  Manual values go over the locked settings of a calibration's camera lock. **Now** shows what
  the camera runs with.


Everything on the Pi, from the page, with the camera's **live picture** at the top of the tab
(`/api/camera/live.mjpg`, a 1280 x 720 second stream of the camera; it runs only while the tab is
open). The result lands in the Files tab by itself.

**Skip for now** (same card): enter the lens' height above the tray floor
(`camera.height_mm`, kept in `paths.machine`, over vision.yaml's `nominal_camera.height_mm`).
Without a calibration the camera is taken as an ideal Camera Module 3 looking straight down at
the picture's centre from that height, and the model gets the 220 x 220 mm around the centre.
Camera to printer (Setup tab) absorbs where the camera really stands; what is left is the lens'
distortion and any tilt, so positions and lengths are less exact towards the picture's edge.
A calibration made later replaces it at once.

Before: download the tray board (7 x 6 squares of 15 mm, 105 x 90 mm: it lies flat in a 3 x 3
tray, away from the corner post), print it at 100 % and glue it on stiff card (a caliper
measurement of one square and the board's thickness can be entered, but the printed size is
used otherwise). Home the printer, empty the tray, light as when sorting. Then **Calibrate**, one
button ([calibjob.py](../src/sortering_pnp/calibjob.py)), which says on the page what to do:
1. **Park:** the bed goes to the photo position.
2. **Lock** (about a minute): the camera measures the light and focus once and freezes exposure,
   gain, white balance and lens position, so every later photo looks the same. Until then the
   live picture runs on the camera's automatic settings.
3. **Lens:** move the board slowly under the camera, over the whole picture, corners too, a
   little tilted now and then. A full-resolution photo is taken by itself each time the board
   holds still (4 live frames) somewhere new (another place, size or tilt); the covered cells
   turn green on the live picture. At 20 photos and 70 % of the picture (or 40 photos) the lens
   is solved; a poor fit (over 1.5 px) stops with a message.
4. **Position:** lay the board flat in the tray and let go. When it lies still and flat (tilted
   under 8°), one photo gives where the camera stands; this also sets where the model's view
   lies (220 x 220 mm around the board).

The plate's millimetres now start at the board, so the old **Camera to printer** fit is put aside
and that Setup step asks to be redone.

## Only the tray goes to the model (Camera cropping)

The camera sees the whole bed: the tray, the bins around it, their codes and the parts already
sorted. The model was trained on a plain plate with parts, so before it looks, everything
outside the tray's inside (and the corner post) is painted over with the colour of the tray's
floor (`camera.mask`, `camera.mask_colour`: `auto` or e.g. `#FFFFFF`). The photo keeps its
size, so the parts stay exactly as large as in the training pictures: cropping and enlarging
would change their scale and spoil the classes and the lengths. The photo with the outlines on
the Device tab's camera shows what the model saw.

The codes are always read from the photo itself, and the check after a bin change looks at it
unpainted (it must see into the bins).

**Set it once, in the Camera Calibration tab → Camera cropping**, after the camera calibration, Camera
to printer and Find bins (it follows the tray of the layout): the live picture and, next to
it, what the model gets, live. The painted edge should sit at the foot of the tray's walls. The
edge buttons move it: + keeps a strip of the wall's foot (parts lying right against the wall
stay whole), − paints more of the floor's edge. The colour is the tray floor's own (`auto`) or
one picked. Save keeps both (`camera.mask_margin_mm`, `camera.mask_colour`).

## Wild bins

A **wild** bin has no rules. The first part of a kind that no other bin takes **claims** a free
wild bin, and from then on that bin collects that kind. The bed's Settings (Device tab) set what "a kind" is for
all wild bins:

- **part number** (DIN912_M4x16): the default, one class and length per bin. Screws wait
  until their length is measured; nuts and washers (no length) go one class per bin.
- **class** (DIN912_M4): any length.
- **family** (DIN912).

- **A layout of only wild bins** sorts by itself, with no setup. New bins start out wild, and a
  wild bin becomes a rule bin as soon as you type rules into it.
- **Rules come first.** Bins with rules (and the unknown/unsure roles) are tried before wild bins.
  When every wild bin is taken, new kinds go to *overflow*, or stay on the plate.
- **Claims are kept** across runs and restarts (`data/wild_bins.json`). Each bin shows on the
  Device tab what it collects.

**Ready to take out.** After every photo sortering-pnp checks each filled bin. When nothing left on
the plate goes into that bin, the bin is marked:
- in soft green with a check mark on the Device tab's bed;
- in a notice at the top of every tab;
- with a line on the printer display.

Take the bin out, empty it, and press **Emptied**. A wild bin is then free for the next new
kind. If you throw in more of its parts, the mark goes away again. In a later version the
machine could move complete bins aside by itself.

**Bins the camera sees.** At the start of every run the camera reads the bin markers
(`run.scan_bins_on_start`):
- bins that moved are updated in the layout;
- markers the layout doesn't know join as new **wild** bins;
- bins the camera can't see (covered, removed) are left out of the run (`run.only_seen_bins`)
  until it sees them: when a part waits for a bin, and after every bin change, it photographs
  the bins again, and a bin seen then (uncovered, put back, or new, anywhere on the grid) is
  used from that moment ("bins seen now, used from here on: B5 ...").

So you can put a new printed bin on the bed and it's used straight away, even mid-run.

## How full the bins are

Cells are named like a chess board: a column letter from the left and a row number from the
front (A1 is front-left), so the machine can say "bin E1". Every bin on the Device tab's bed shows
how many parts went in since it was last emptied (the small number at its top right), and a
bar for how full it is, turning amber when it is full (`run.fill.full_at`, 90 %).

How full is an estimate:
- **each part's volume**, the best known:
  - with **items.json** dropped in the Files tab, a catalogued part has its **exact volume**
    from its 3D model: by part number, else by class at the measured length, else the class
    average;
  - anything else (unknown parts, new kinds of items) from what the camera measured: the area
    of its outline on the plate times its height, times `run.fill.shape` (0.5: a lying screw
    fills about half of that box). Nothing in it is specific to screws;
- **each bin's room** from its Gridfinity size: the inside from the floor to the rim, without
  the code's shelf or post. A 1x2 holds about twice a 1x1, a 6-unit bin about three times a
  3-unit one (the foot and floor are the same);
- **how densely loose parts pack:** `run.fill.packing` (0.3) to start with. Press **Full** in a
  bin's panel when a bin really is full: the machine learns how densely that family packs
  (its parts' volume / the bin's room; washers differ from long screws) and asks for the bin
  to be emptied. Each family uses its own learnt value; one never seen uses all of them.

The bin's panel says "about 60 % full, room for about 8 more like them".

After a bin change, the photo also looks **into** a bin that was said to be emptied: parts it
still sees there are counted (`run.check_emptied`), so a half-emptied bin is not taken for an
empty one. The camera may miss parts hidden by the walls.

## Bin changes: full bins and new kinds

The machine asks for a bin change when
- a bin is **full** (see above): its kind carries on in a free wild bin if there is one;
- a **new kind** needs a bin and no wild bin is free, and no wild bin collects a kind like it.
  `run.share_wild: class` (the default) first puts a new length in with its class: with no
  free bin, DIN912_M3x10 goes into the bin collecting DIN912_M3x8 ("in with DIN912_M3x8");
  `family` also shares across sizes (DIN912_M4 in with DIN912_M3x8), `none` never shares.
  Only when that fails (`run.when_no_bin: ask`; `overflow`
  sends it to the overflow bin instead, as before). When there is no bin it could ask for
  (every wild bin already asked for), that kind goes to the overflow bin; without one it
  waits. It chooses the bin to give up: a bin
  nothing on the plate goes to any more scores highest, a fuller bin higher, and a bin whose
  kind still lies on the plate lower (it would be needed again soon).

The request shows at the top of the web page ("Bin change: E1 DIN934_M4 30 · full"), the bin
is shown in amber on the Device tab's bed, the activity feed and the printer's display say it. The
machine never stops for it: it keeps sorting everything else. When only the waiting parts are
left, it waits, and still looks at the tray every `standby.interval_s`: parts thrown in
meanwhile are sorted. The requests are kept across a restart.

All bin changes are on one line above the bed on the Device tab (the bins to change and the
finished ones, with *Emptied*), with one button that steps through them (or **Change bin** in
the printer menu, or the bin's own menu on the bed):
1. **Park:** the machine finishes its move and parks (bed out, safe for your hands); also
   while automatic mode stands by;
2. empty the bins, or put other (empty) bins in their place;
3. **Done:** a photo checks what stands there now, and sorting goes on:
- **the same code:** the bin was emptied; its count starts again, a wild bin is free again;
- **another code:** a different bin stands there; it becomes a wild bin (or takes up its old
  rules, if it was used before). The old bin is kept aside with what it holds: put it back
  later and its count and contents come back with it;
- **no code:** the cell is empty; the old bin is kept aside the same way.

Change bin also works when the machine is not sorting: Park moves the bed out (when it is
homed), Done takes a photo and does the same check. A bin's menu on the bed has **Change**
(ask for it), **Full** and **Emptied**.

**Buttons that act at once:** Recheck, Resync and Change bin don't wait for the run to end:
the run (or automatic mode) stops after the move in progress, the action is done, and
automatic mode carries on if it was on. Every photo shows on the Device tab as soon as it is
taken, before the model has looked at it, with the bins' codes and their cells; in automatic
mode the camera counts down to the next photo.

## Strategies and picking order

| Strategy | What it does |
|---|---|
| **sort** | every part goes to the bin whose rule matches it best (part number > class > family > `*`), else to a wild bin |
| **clear** | everything into the bin with role *all* (or *overflow*), no sorting |
| **kit** | only the parts on `run.kit` (e.g. `{DIN912_M3x10: 4, DIN934_M3: 4}`) into the *kit* bin, then stop |

These rules apply to every strategy:
- **The largest group first, one group at a time** (`run.order: census`): the first photo
  counts every class on the plate (by class, so a part whose length is measured later stays
  in its group). The most numerous is picked
  until none is left, then the next most numerous. Parts dug out from under others can bring
  back a kind that was already done: the sorter goes back to it at once, then carries on where
  it was. The console says each change ("next: …", "back to …"). `largest_group` re-counts on
  every photo instead (it may switch back and forth); `nearest` skips the grouping. Within a
  group, parts with free space around them come first, then the most confident, then the
  nearest.
- Detections below `run.min_score` go to the *unsure* bin.
- UNKNOWN parts go to the *unknown* bin.
- A part whose length decides its bin, but which can't be measured yet (tilted, covered), waits.
  After a few bed shakes it goes to *unsure*.
- When nothing can be picked, the bed is shaken (`run.shake`) to spread the clump. After
  `max_in_a_row` shakes, the sorter pauses and asks for a hand: spread the parts and press Resume.
- A pick that leaves the part in place is retried. After `max_failed_picks` tries at the same
  spot, that part is left alone.

## Where a part is taken: grip point, direction, centre of mass

For every part the program knows **which way it lies**, **how long it is** and **where its
centre of mass is**. From these it picks the **grip point**.

- **Screws, standoffs, threaded rod:** the model already finds three points on each screw: the
  head's top, the underside of the head, and the tip. Together they give the direction and the
  length. With the head's size from the catalogue (diameter and height), the centre of mass
  follows: the head is heavy, so on short screws it lies near or even inside the head. The
  tweezers close on the **shank**, at the centre of mass, but never on the head (at least
  `picker.grip_from_head_mm` below it) and not on the very tip. Headless parts (set screws, rod,
  standoffs) are taken in the middle.
- **Everything else** (nuts, washers, brackets, unknown parts): the centre and the long axis of
  the outline.

**No new training data is needed for this.** The three keypoints are already in the training
set (`head_top`, `bearing`, `tip`), and the head sizes are in the catalogue. Should a part ever
need its own grip point (e.g. odd brackets), a fourth keypoint could be added to the dataset
later.

## Tweezers on a Z rotation axis

Instead of the hotend, the toolhead carries **tweezers that turn around Z**
(`picker.mode: servo_tweezers` or `pneumatic_tweezers`):
- before every pick they turn so their jaws close **across** the part, at the grip point;
- they close at the height of the shank's middle;
- they drop the part in the bin at whatever angle they hold it.

Normally a **servo on GPIO12/13 of the Pi** turns them (0–180° is enough: the jaws are
symmetric). In the **Setup tab → Picker**: *Turn to 0°* (the jaws must close along the printer's
X axis), *Turn to 90°*, and an **offset** in degrees if the servo's 0 isn't quite along X.

`klipper/sortering_pnp.cfg` also has two stepper-motor variants, instead of the servo; they turn
through Klipper, so set `picker.rotate_macro: SORTERING_ROTATE` (and for B
`picker.rotate_home: SORTERING_ROT_HOME`) in `configs/machine.yaml`:
- **A, the extruder's motor driver** (the hotend still prints after a tool swap): the angle is
  remembered; run `SORTERING_ROT_ZERO` in the console when the jaws close along X.
- **B, a spare driver with a small 0° switch:** the axis finds 0° by itself before every sort.

## One cycle: photo, pick, drop, park

1. **Photo:** the head is parked at the photo position (`printer.photo_position`), the picker
   empty, and the photo is taken and analysed. It also shows whether the last pick worked: if
   that part is still on the plate, the pick failed and is tried again.
2. **Pick** the part chosen from that photo and lift it.
3. **Drop:** carry the part to its bin and release it.
4. **Park:** back to the photo position. Back to 1.

The Device tab's activity shows how long the last cycle took. A Pi 3B (1 GB) is too small for
Klipper and the model together.

- **The photo position must keep the head outside the working area in the picture**, ideally
  off the plate.
- **Loose parts and quick bed moves:** the bed moves to the part, the bin and back, and fast
  moves can nudge loose parts. `printer.xy_motion` gives each axis its own acceleration and
  makes every X/Y move start and stop gently ([X/Y acceleration profile](#xy-acceleration-profile));
  `printer.accel` lowers the acceleration of all axes while sorting.

## X/Y acceleration profile

On a bed-slinger the loose parts ride on the Y axis (the bed), while X moves only the head. Klipper
has one acceleration for all axes and only straight (trapezoid) ramps, so sortering-pnp shapes
each move that changes X or Y itself (`printer/motion.py`, `printer/smooth.py`). On by default.

```yaml
printer:
  xy_motion:
    enabled: true       # false: plain moves (one G1 at the printer's acceleration)
    accel_x: 3000       # mm/s^2 for the head (the X part of a move): the Ender 3's own
    accel_y: 200        # mm/s^2 for the bed (the Y part): long soft ramps, loose parts ride on it
    carrying: 0.6       # accel_x x this while the picker holds a part (1: no change)
    profile: trapezoid  # trapezoid (one G1, a straight ramp) | s_curve (stepped)
    max_feed_x: null    # mm/min for the head (the X part); null: printer.feed_xy
    max_feed_y: 3000    # mm/min for the bed (the Y part); null: printer.feed_xy
    steps: 12           # s_curve: speed steps per ramp
    min_step_mm: 1.0    # s_curve: steps at least this long on average
```

An older machine.yaml with `printer.y_motion` still loads: it is read as `xy_motion`, its `accel`
and `max_feed` as `accel_y` and `max_feed_y`.

- **Acceleration per axis:** before the move `SET_VELOCITY_LIMIT ACCEL=` sets the largest
  acceleration whose X part stays within `accel_x` and whose Y part within `accel_y`:
  min(accel_x / |ux|, accel_y / |uy|) for the move's direction u. A pure Y move gets 200, a pure
  X move 3000, a 100 x 150 mm diagonal 240 (the bed binds). While the picker holds a part (grab
  until release) the head's limit is x `carrying` (1800); the bed's stays (the part hangs on
  the head, not on the bed). After the move it is set back
  to `printer.accel`, or else to Klipper's own value (read once), so other moves and macros keep
  it. It is never raised above that, and not sent when it is the same.
- **`trapezoid`** (the default): one G1 at the lowered acceleration. Klipper's own ramp: the
  speed rises in a straight line (constant acceleration, as AccelStepper does) and falls the same
  way; the bed reaches 50 mm/s in 0.25 s over 6.25 mm at 200 mm/s^2. Klipper's input shaper,
  if set up in printer.cfg, rounds the corners of the ramp.
- **`s_curve`** (not recommended): the speed follows an S (smoothstep: no jump in acceleration
  at the start and end of a ramp; its peak is `accel`). Klipper runs each step as a move of its
  own: it reaches the step's speed quickly and then holds it, so the S comes out as small
  stairs. The move is split into short G1 steps along the same straight
  line, their speeds rising and falling along the S, and Klipper's lookahead runs them without
  stopping between them. A short move gets a lower top speed and fewer steps; under 4 mm (with
  `min_step_mm: 1`) it is one G1. The last G1 is the target itself, so the end point is exact. A 0 -> 200 mm travel at
  6000 mm/min with the bed at 1000 mm/s^2 and 8 steps becomes 7 steps up (F87 ... F5913 over
  7.5 mm), one at F6000, 7 down.
- **No corners at speed for the bed:** Klipper takes a corner between two moves (e.g. lift in Z,
  then travel in Y) at up to its square corner velocity (5 mm/s): the bed would jump from rest
  to that speed with no ramp. Every move of the bed is sent with `SQUARE_CORNER_VELOCITY=0`
  (a full stop at both ends) and Klipper's own value is set back after it.
- **Homing** runs at `accel_y` with no corners at speed too (the homing macro's moves included).
  Homing Y still ends with the bed stopping at its switch: sortering_pnp.cfg slows it
  (`[stepper_y] homing_speed: 20`, `second_homing_speed: 5`), and `standby.motors_off` is false
  by default, so automatic mode does not home before every round.
- **Not shaped:** Z-only moves (up and down) and the shake (`run.shake`), whose quick moves are
  meant to be sharp (only when a clump is seen, `run.shake.enabled`).
- **Still moving?** Lower `accel_y` further (100), or `max_feed_y` (2000); check that Klipper's
  console shows `SET_VELOCITY_LIMIT ACCEL=200` before the bed moves.

## Automatic mode

Press **Start automatic** on the Device tab (or *Screw sorter → Automatic* on the printer). The
machine then runs by itself until you press Stop. The Device tab's header shows what really runs
(*Automatic · waiting · next photo in 0:42*, *Sort once · sorting*, *Idle*), and only the buttons
that apply then (Look now, Pause, Resume, Stop); *Manual* has Sort once and One pick:

1. **Standby:** the bed stays all the way out at the photo position (`printer.photo_position`)
   with the motors on (`standby.motors_off: true` switches them off, quiet, but then it homes
   before every round: the bed stops sharply at its switch with the parts on it). Every minute
   (`standby.interval_s`) the camera looks at the plate: the bed is still parked where the
   camera was calibrated. The page counts down to the next
   look ("next look in 45 s").
2. **Parts seen:** it starts at once (parts on the plate don't move by themselves). **Resume**
   (or Start) while it waits looks now, without waiting for the next look.
3. **Sorting:** it homes when needed (see below), finds the bins, and sorts the largest group first, until
   the plate is empty. Then it goes back to standby, and complete bins are marked ready.
4. **Stuck parts** (a clump that shaking can't spread) are left alone. It tries again as soon
   as they've been moved.

Automatic mode **stays on after a restart** or power cut: when `sortering-pnp serve` starts, it
carries on. Stop (or STOP) switches it off. After `standby.max_errors` errors in a row (printer
off, camera unplugged…) it switches itself off and says why on the page.

## The start-up check

**Every start is a new session** (real printer; the simulator keeps its layout): the layout
begins as the empty grid of `bed.cols` x `bed.rows` cells (machine.yaml, 5 x 5 by default: a
220 mm bed; set it for a bigger machine), with no bins, and what the bins collected, their
counts and open bin changes are forgotten (the learnt packing stays). Resync or this check
finds the bins and the tray again from the photo.

The first run after sortering-pnp starts (Automatic, Sort once or One pick; also automatic
mode carrying on after a restart) begins with a check, shown with a tick per step
in the left menu, under Device (**Recheck** runs it alone, also while sorting). It is `run.startup_check`:
1. **Homing**, with the usual checks before moving.
2. **Layout check:** one photo of the bins, then a resync: where the grid and every bin stand.
   The tray stays the bin it was.
3. **Bins check:** the model runs once on that same photo: the whole calibrated picture, at
   the scale it was trained at, with nothing painted over. A wild bin with parts on its floor
   collects their kind (the most common one; the class when no length was measured: it then
   takes every length of it), and its count is what the camera sees (more when it was already
   counting that kind: the camera sees only the top). An empty bin is a free wild bin, and an
   empty bin with no rules becomes wild. Nothing on or next to a bin's code (its shelf or
   post) is counted, as the model can take the printed code for parts, and nothing below
   `run.min_score`. The code is kept out twice: where the layout puts it and where the photo
   shows it (on a rim, seen from above, a code appears shifted outwards). A bin with only
   unknown parts keeps what it had; a bin with rules keeps them (the console says when it
   holds something its rules don't take). The walls of tall bins can hide parts from the
   camera: a bin that looks empty is taken as empty.
   The photo is shown at once, then replaced by the result: each bin's floor with its cell and
   code, the parts counted in it, the code areas shaded, parts dropped on a code crossed out,
   and what each bin collects now. Resync does the same check (only these two: sorting photos
   still show the model only the tray). [binscheck.py](../src/sortering_pnp/binscheck.py)
4. **Ready.**

## Homing

Two dangers when homing a sorter that a plain `G28` doesn't handle:

- **Bins on the bed.** An Ender 3 homes Z at the front-left corner, which is a bin. The tool would
  come down onto the bin's rim.
- **The picker tip may reach lower than the nozzle did.** The Z switch triggers on the gantry
  height, so with a longer tool the tip touches the plate before the switch triggers.

**What sortering-pnp does** (`klipper/sortering_pnp.cfg`, `[homing_override]`):

1. Lift Z by 30 mm first (more than the bins are tall).
2. Home X, then Y.
3. Move the tip over the **middle of the working area**: flat TPU, no bins. sortering-pnp sets this
   spot from the layout before every homing.
4. Home Z there, then lift again.

**For the tip that reaches lower: raise the Z switch.** Slide the Ender's Z endstop bracket up
until the switch triggers with the picker tip **2–3 mm above the plate**. Then:

1. In `printer.cfg`, allow Z a little below 0: `[stepper_z] position_min: -5`.
2. Home, then in the **Setup tab → Tip height**: jog the tip down over the plate in 0.1 mm
   steps until a sheet of paper just drags, and press **Tip touches the plate**. From then on,
   every Z that sortering-pnp uses counts from that point. Repeat this whenever the switch or the
   picker is moved.

The X and Y offset of the tip needs no measuring: the camera calibration already uses the tip
itself.

**Printing again with the hotend:** the raised switch would stop the nozzle above the bed.
Either slide the switch back down when you swap tools (re-level as usual), or print a spacer
that clips under the switch together with the picker swap, so the switch height comes with the
tool. Choose the picker's length so that the spacer is about the same for every swap.

**Motors off in standby:** Klipper forgets the homing when the motors switch off (and after its
own `idle_timeout`, 10 minutes by default). That's fine: the bed stays where it was for the
standby photos, and the machine homes again before the next sort.

## A camera on the tool head (optional)

`camera.source: head` uses a camera on the tool head instead of the one above the bed. It is
closer, so it sees more detail, but only a patch at a time (`camera.head.fov_mm`), so the
machine moves it around and joins the photos:
- **sorting:** only the tray, in a few overlapping photos (a part on the seam between two
  photos is counted once);
- **Resync, the check after a bin change, the start of a run:** the whole grid and one cell
  around it (`margin_cells`), so a bin put next to the grid is found too.

Set it up:
1. `printer.photo_position`: the tip X Y Z with the camera over the middle of the tray, at the
   height its model was trained for (the camera's height sets the pixels per mm).
2. `camera.head.offset`: roughly how far the image centre is from the tip (X, Y), and
   `fov_mm`: what one photo covers at that height.
3. Camera Calibration tab, as for the fixed camera: the photo is taken at the photo position; jog the
   tip onto three markers. Every other photo is shifted by how far the head moved, so this one
   calibration places all of them.
4. Models tab: **Use on head camera** on a stage-1 model trained at the head camera's scale.
   Without one the normal stage-1 model is used, with a warning.

The head camera travels with the head, so in automatic mode the motors stay on (it must move to
look).

## Real photos (Photos tab)

Photos of real parts, for checking the model on the PC (screw-synth's real data):
make a session, note on the PC what lies in the tray (inventory.csv), take a photo after each
change (the bed is parked first, the camera uses the locked settings), then **Download** the
session and put the folder in screw-synth's `data/real/`.

## On the machine (Setup tab)

The Setup tab ends with a list of what only you can do on the real machine: the calibration
with the board in the tray, checking what the model sees, measuring for the camera arm, the
Pi's clearance in the screen holder, the printer menu, the picker, a corner bin read by the
camera, Full taught once, the parts table. They never block sorting. Some tick themselves off
when the program notices (a calibration dropped, a corner bin's code read, a bin marked Full);
the others you tick with Done.

## The console

The Device tab's **Activity** panel is a console: one short line per thing the machine sees or decides, e.g.

```
14:02:11 sorting: sort
14:02:13 7 on the plate: 3 DIN912_M4x16 · 2 DIN934_M4 · 1 DIN125A_M4 · 1 UNKNOWN
14:02:13 pick DIN912_M4x16 at X102 Y88, jaws 35° → bin 105
14:02:19 bin 105 now holds DIN912_M4x16
14:02:19 dropped in bin 105
14:03:40 missed DIN934_M4: try again
14:05:02 bin 105 complete (DIN912_M4x16): take it out
14:05:02 done: the working area is empty
```

## Printer menu

`sortering_pnp.cfg` adds **Screw sorter** to the printer's display menu: *Sort*, *Clear plate*,
*Pick kit*, *One pick*, *Change bin*, *Pause*, *Resume*, *Stop*, *Picker mounted*,
*Hotend mounted*. You can also
type the commands in any Klipper console: `SORTERING CMD=start STRATEGY=sort`.

## Login

The page needs a user name and password (`web.require_login`, on by default):

- The **first visit** creates the first account.
- The **Users** tab adds or removes users and changes your password. Every user can do
  everything.
- **Passwords** are stored only as salted, slow hashes in `data/users.json`, which is readable
  only by the Pi's user.
- **Sessions** last `web.session_days` (30) per browser. **Log out** ends one, and changing a
  password ends all sessions of that user.
- **Ten wrong passwords** from one address block it for 5 minutes.
- **Locked out?** On the Pi: `sortering-pnp user add NAME` sets a new password, and
  `sortering-pnp user list` / `remove` manage the accounts.

The page is plain HTTP, so it is meant for your home network. Logging in keeps others off the
page; it is not protection against someone already listening on your WiFi. The printer-menu
buttons never need a login: they come from Klipper on the Pi itself.

## Frames, markers and safety

- **Camera → plate mm:** screw-synth's calibration and model. The model always runs
  on the full calibrated image, at the scale it was trained on. sortering-pnp then ignores
  everything outside the working area, including the parts already in bins.
- **Plate mm → printer X/Y:** one 2D transform (rotation, scale, shift) fitted from the marker
  points you record in the Camera Calibration tab. The plate is fixed to the bed, so this works for
  moving-bed printers too. Bed markers are read at their real height (parallax-correct).
- **Bin markers:** ArUco 4x4 codes, ids 100–249, so they can't be confused with the calibration
  board. Each code's top edge points to the back of its bin, which gives both the bin's position
  and its rotation.
- **Safety:** every move is checked against the soft limits in `machine.yaml`. Moves happen at
  `travel_z`, the descent is slow, and the program refuses to run while the printer is
  printing, hot, unhomed or carrying the hotend. **STOP NOW** on the web page sends Klipper's
  emergency stop.

## Development

```
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

Code: [src/sortering_pnp/](../src/sortering_pnp/). `runner.py` is the loop, `strategies.py` and `rules.py`
decide, `printer/` talks to Klipper (or the simulator), `vision.py` wraps the model, and
`printables/` makes the bins.

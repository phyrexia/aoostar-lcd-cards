# Design notes

Short record of the decisions behind aoostar-lcd-cards and why they were taken.

## Sources consulted

- asterctl / aoostar-rs at tag `v0.2.0`: `README.md`, `docs/asterctl.md`, `docs/installation.md`,
  `Cargo.toml` (`license = "MIT or Apache-2.0"`, Rust >= 1.88), `LICENSE-MIT`, `LICENSE-APACHE`,
  `crates/asterctl/src/main.rs` (what `--image`, `--simulate`, `--device`, `--usb` do) and the
  GitHub releases API (tag commit, asset names, `asterctl.hash`).
- The release binary itself: it links `libudev.so.1` and needs glibc >= 2.34 (runs on
  Debian 12+, Ubuntu 22.04+).
- DejaVu fonts 2.37 `LICENSE` (Bitstream Vera + Arev terms, DejaVu changes in the public domain).
- Prior art: `homefree-aoostar-lcd` (a psutil sampler feeding asterctl) confirms the
  "Python renders, asterctl transports" split. asterctl is also packaged in FreeBSD ports
  and nixpkgs. No other pure-Python driver for this panel was found.
- A previous private deployment (separate collector and renderer, 3-hour network histogram)
  on an AOOSTAR WTR MAX, whose card style this project generalizes.

## Architecture

```
 host                                 display side (same host, LXC or container)
 ┌───────────────┐   state.json   ┌──────────────────────────────┐   PNG   ┌──────────┐
 │ collector     │ ─────────────▶ │ renderer: rotation, banner,  │ ──────▶ │ asterctl │ ─▶ LCD
 │ card.collect()│  atomic write  │ card.render(canvas, ...)     │         └──────────┘
 └───────────────┘                └──────────────────────────────┘
          └──────────── `aoostar-lcd run`: both halves in one process ─────────────┘
```

- **Collector and renderer are decoupled by one JSON file** (`collect` writes it with
  `os.replace`, `display` reads it). This is what makes the Proxmox case simple: the host
  measures (it sees every NIC, pool and disk), an unprivileged LXC only needs a read-only
  bind mount and the serial device. No sockets, no ports, no shared Python state.
- **`run` keeps both halves in one process** for the common case (bare metal, Docker): no
  file is needed, but the snapshot has exactly the same shape.
- The state carries a timestamp; older than `collector.max_age` means **NO DATA** on the
  panel instead of stale numbers.
- History (CPU and network charts) lives in the collector and is persisted to
  `history_file` every 60 s and on SIGTERM, so a restart does not wipe 3 hours of bars.

## Configuration

- **One YAML file** for both processes. Each card entry mixes common keys (`type`, `id`,
  `title`, `duration`, `enabled`, `refresh`) with its own options at the same level: flat
  YAML is easier to write than nested `options:` blocks.
- **Strict validation**: unknown keys are errors, with a "did you mean" hint and the full
  path (`cards[2] (network).units: must be one of bits, bytes`). Typos must not silently
  fall back to defaults. `aoostar-lcd check` validates a file (and asterctl) without
  touching the panel.
- Order in the file is the rotation order; `enabled: false` keeps a card configured but
  out of the rotation.
- Paths are relative to the config file, so a config folder can be moved as a unit.

## Card API

```python
class Card:
    type_name = "card"; defaults = {}; refresh = 0.0; full_bleed = False
    def configure(self, options): ...                 # validate, raise ConfigError
    def collect(self) -> dict | None: ...             # collector side, JSON only
    def render(self, canvas, theme, data): ...        # renderer side
    def sample(self) -> dict | None: ...              # synthetic data for previews/tests
    def alerts(self, data) -> list[str]: ...          # red banner on every card
    def state(self) / restore(state): ...             # persisted history
    def visit_pages(self) -> int / set_page(i): ...   # multi-frame cards (image folders)
```

- `render` receives `data` explicitly (not `self.something`) because `collect` and `render`
  may run in different processes; the JSON in between is the contract.
- Plugins are loaded with `type: plugin` and `plugin: path/file.py:Class` or
  `package.module:Class`. They get the same validation (`defaults` lists allowed options).
- The collector side never imports Pillow (tested), so the host only needs PyYAML and psutil.

## Built-in cards: notable choices

- **Network**: mirrored histogram, inbound up, outbound down, average per bucket with the
  bucket's peak as a lighter cap. `aggregate` (default) sums the NICs into one chart:
  four stacked series in ~130 px per side cannot be read from a distance, and the useful
  question is "how much enters and leaves the box". `split` draws up to four small charts
  for those who need per-NIC detail. `interfaces: auto` keeps only interfaces backed by a
  device (`/sys/class/net/*/device`) and drops bridges, veth, tap, VPN and bonds, so traffic
  is not counted twice. The full scale is a 1-2-5 step in the unit shown (Mbit/s or MB/s),
  never lower than `min_scale`, so idle noise stays small.
- **CPU**: busy share computed from `cpu_times` deltas (not `psutil.cpu_percent`, whose
  global state breaks with two cards). History bars are time-weighted averages; caps are
  the highest 5-second sample of each bucket.
- **Storage**: ZFS pools use `zfs list` (usable space after parity) plus `zpool list`
  (health); any mount point uses `statvfs`. Defaults: SI units (TB) because disks are sold
  that way; memory defaults to IEC (GiB) because RAM is.
- **Temperature**: psutil hwmon chips, plain files, or `smartctl --json --nocheck=standby`
  (never wakes a sleeping disk; keeps the last value instead).
- **custom**: runs a command without a shell (or reads a file) and accepts JSON or text; the
  output is sanitised (control characters, length limits). Covers most one-off needs
  without writing Python.
- **image**: folder re-listed on every pass so files can be dropped in without restarting;
  bad files are skipped with a warning and remembered until they change; size, pixel-count
  and file-count limits protect the renderer from huge or hostile images.
- Labels exist in English and Spanish (`language`); everything else is numbers.

## Rendering and the panel

- Cards draw on a **logical 960x376 canvas** (the panel's native size). If
  `display.width/height` differ, the finished frame is resized; layouts stay simple.
- A frame is sent only when it differs from the previous one (SHA-256 of the pixels), and a
  failed send is retried on the next frame interval, never in a tight loop.
- Each send spawns `asterctl --image` (about one second per frame). The frame is written in
  a private `mkdtemp` folder, not a fixed `/tmp` path.

## asterctl as a dependency

asterctl is **MIT OR Apache-2.0** (dual, at the user's option). Both allow redistribution
and linking from an MIT project; neither is copyleft. Still, **this repository does not copy
its code or binaries**:

- `asterctl.version` is the single pin: repository, tag `v0.2.0`, the commit that tag points
  to (`078dc267...`) and the SHA-256 of the Linux x64 release archive. The installer, the
  Dockerfile and CI read it; a test checks that the Python wrapper (`PINNED_TAG`,
  `MIN_VERSION`) agrees.
- `scripts/install-asterctl.sh` downloads the release and checks the pinned SHA-256
  (`--from release`, default on Linux x86_64) or runs
  `cargo install --locked --git <repo> --rev <commit> asterctl` (`--from source`, any
  architecture). It is idempotent and parses the pin file instead of executing it.
- Builds use `--rev <commit>` rather than `--tag`: a tag can be moved upstream, a commit
  cannot. CI checks weekly that the tag still resolves to the pinned commit.
- `licenses/asterctl/` holds asterctl's license texts verbatim; the installer and the
  Docker image copy them next to the binary, as both licenses require when redistributing.
  Images built from the Dockerfile also contain asterctl's Rust dependencies (their licenses
  apply to anyone who redistributes such an image; this project publishes no images).
- **Git submodule** (`git submodule add https://github.com/zehnm/aoostar-rs
  third_party/aoostar-rs` and `git -C third_party/aoostar-rs checkout <commit>`) is allowed
  by the licenses and documented as an option for people who want the source next to the
  project, but it is not the default: it bloats every clone, most users never build Rust,
  and the pinned commit plus checksum give the same reproducibility.
- `aoostar_lcd.asterctl` wraps the binary: locates it, checks `--version >= 0.2.0`, sends
  images, switches the panel on or off, and turns every failure into a clear error.

**Future idea, not implemented**: talk to the panel directly from Python over the serial
port (pyserial), which would avoid spawning a process per frame and allow partial updates.
The protocol is reverse-engineered and a wrong command can hang the panel until it is
power-cycled, so for now asterctl stays the single place that knows it.

## License

- Project: **MIT**. Compatible with asterctl (MIT OR Apache-2.0, not bundled), Pillow
  (MIT-CMU), PyYAML (MIT) and psutil (BSD-3-Clause), installed as normal dependencies.
- Bundled fonts: DejaVu Sans Bold and DejaVu Sans Mono Bold under their own license
  (`src/aoostar_lcd/fonts/LICENSE-DejaVu.txt`): free to bundle and redistribute, must keep
  the notice, may not be sold on their own, modified versions must be renamed. That license
  covers only the font files; it does not change the MIT license of the code.
- Example images in `examples/images/` are original, generated by
  `scripts/make-example-images.py`, under the project's MIT license.

## Security notes

- `type: custom` commands, `type: plugin` modules and `theme.fonts` run or load whatever the
  config points to, with the privileges of the process. The config file must be writable
  only by root (or the service user).
- Commands run without a shell, with a timeout and an output size limit.
- The state file is world-readable (0644) because a container must read it; it contains
  metrics, never credentials. The history file is 0600.
- The display side needs no root: read access to the state file and the `dialout` group.

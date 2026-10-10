# Writing your own cards

There are three ways to show something that is not built in, from least to most effort:

1. **`type: custom`**: any command or file that produces JSON or text. No Python.
2. **`type: image`**: a picture or a folder of pictures.
3. **`type: plugin`**: a small Python class, for full control over the layout.

## 1. A command or a file (`type: custom`)

```yaml
- type: custom
  title: BACKUPS
  command: ["/usr/local/bin/backup-status", "--json"]   # no shell; a string is split like one
  refresh: 60          # seconds between runs (in the collector)
  timeout: 10
```

The command prints one JSON object. Every key is optional:

```json
{"title": "BACKUPS", "value": "OK", "unit": "", "label": "last run 03:10",
 "percent": 64, "status": "ok", "lines": ["12 snapshots", "next run 03:10"]}
```

- `status` (`ok`, `warn`, `crit`) colors the value and the bar.
- `percent` draws a bar (0-100).
- `rows: [{"label": "Queue", "value": 3, "status": "warn"}]` draws a table of up to four rows instead.

Any other JSON works too if you pick values with `fields` (dotted paths, list indexes allowed):

```yaml
- type: custom
  title: UPS
  file: /var/lib/ups/status.json
  fields:
    - {label: Battery, key: battery.charge, unit: "%", decimals: 0}
    - {label: Load, key: ups.load, unit: "%", decimals: 0, warn: 70, crit: 90}
    - {label: Status, key: ups.status}
```

Plain text also works: the first line is the big value and up to three more lines go below.
See `examples/scripts/sessions.sh`.

## 2. Pictures (`type: image`)

```yaml
- type: image
  path: /etc/aoostar-lcd/images     # a file or a folder
  mode: contain                     # contain | cover | fit-width
  background: "#000000"
  duration: 6                       # seconds per picture
  per_visit: all                    # all = every picture each pass; one = one per pass
```

PNG, JPEG, WebP and GIF (first frame). Transparent areas show `background`. The folder is
listed again on every pass: drop or delete files at any time. Broken files, files above
`max_file_mb` (20) or above `max_pixels` (40 million) are skipped and logged. Only use
pictures you have the right to display.

## 3. A Python card (`type: plugin`)

```python
# /etc/aoostar-lcd/plugins/hello_card.py
from aoostar_lcd import Card


class HelloCard(Card):
    type_name = "hello"
    defaults = {"greeting": "Hello"}          # every allowed option and its default

    def collect(self):                         # collector side (the host)
        import os
        return {"processes": len(os.listdir("/proc"))}

    def sample(self):                          # fake data for `aoostar-lcd preview`
        return {"processes": 321}

    def render(self, canvas, theme, data):     # renderer side (next to the LCD)
        canvas.title("HELLO")
        count = "-" if not data else str(data["processes"])
        canvas.text((canvas.left, canvas.top + 170), f"{self.options['greeting']}!",
                    size=90, anchor="ls")
        canvas.text((canvas.left, canvas.top + 240), f"{count} entries in /proc",
                    size=40, color="muted", anchor="ls")
```

```yaml
- type: plugin
  plugin: /etc/aoostar-lcd/plugins/hello_card.py:HelloCard   # or my_package.cards:HelloCard
  greeting: Hi
```

Preview it without the panel: `aoostar-lcd preview -c config.yaml --png /tmp/hello.png --card hello`.

### The contract

| Method / attribute | Where it runs | What it does |
|---|---|---|
| `type_name` | - | Default card id. |
| `defaults` | - | Allowed options and their defaults; unknown YAML keys are rejected. |
| `refresh` | collector | Minimum seconds between `collect()` calls (0 = every tick, 5 s by default). |
| `configure(options)` | both | Validate/normalise `self.options`; raise `aoostar_lcd.ConfigError`. Helpers in `aoostar_lcd.validate` (`as_int`, `as_choice`...) give good messages. |
| `collect()` | collector | Return JSON-serialisable data or `None`. Exceptions are logged and the last good data is kept. |
| `render(canvas, theme, data)` | renderer | Draw the frame. `data` is what `collect()` returned, or `None` before the first collect. Never assume keys exist. |
| `sample()` | renderer | Synthetic data for previews and tests. |
| `alerts(data)` | renderer | Short strings for the red banner shown on every card. |
| `state()` / `restore(state)` | collector | Persist something (a history) across restarts. |
| `visit_pages()` / `set_page(i)` | renderer | Show several frames per visit (like the image folder). |
| `full_bleed = True` | renderer | No page dots drawn on top (for pictures). |

The two halves may run in different processes or machines: keep everything that `render`
needs inside the returned `dict`.

### The canvas

`canvas` is 960x376. Useful members:

- `canvas.left`, `canvas.right`, `canvas.top`, `canvas.bottom`: the area for the card
  (`top` moves down when the alert banner is shown, `bottom` leaves room for the dots).
- `canvas.text(xy, text, size=40, color="text", kind="sans"|"mono", anchor="la", max_width=None)`:
  draws and returns the width; with `max_width` the font shrinks until it fits. Anchors are
  Pillow's (`la` top-left, `ls` baseline-left, `rs` baseline-right, `mm` centre).
- `canvas.title(text)`, `canvas.message(text)`, `canvas.bar(x, y, w, h, percent, color)`.
- `canvas.level(value, warn, crit)`: the ok/warn/crit color for a value.
- `canvas.color(name)`: theme colors `background text muted dim track grid ok warn crit rx tx accent`.
- `canvas.draw` / `canvas.image`: the raw Pillow `ImageDraw` / `Image` for anything else.
- `canvas.tr(key)`: built-in translations (`en`, `es`).

A complete, realistic example is `examples/plugins/top_processes.py`.

**Security**: a plugin is ordinary Python running with the privileges of the collector or
renderer. Only load files you trust and keep them writable by root only.

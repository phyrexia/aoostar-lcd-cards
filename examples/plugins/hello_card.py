"""The smallest useful custom card. Load it with:

- type: plugin
  plugin: examples/plugins/hello_card.py:HelloCard
  greeting: Hi
"""

from aoostar_lcd import Card


class HelloCard(Card):
    type_name = "hello"
    defaults = {"greeting": "Hello"}  # every option must be declared here

    def collect(self):
        # Runs in the collector (on the host). Return JSON-serialisable data.
        import os

        return {"processes": len(os.listdir("/proc")) if os.path.isdir("/proc") else None}

    def sample(self):
        # Fake data for `aoostar-lcd preview` and tests.
        return {"processes": 321}

    def render(self, canvas, theme, data):
        # Runs in the renderer. `data` is what collect() returned (None until then).
        canvas.title("HELLO")
        count = "-" if not data or data.get("processes") is None else str(data["processes"])
        # anchor "ls" = x is the left edge, y is the text baseline.
        canvas.text(
            (canvas.left, canvas.top + 170), f"{self.options['greeting']}!", size=90, anchor="ls"
        )
        canvas.text(
            (canvas.left, canvas.top + 240),
            f"{count} entries in /proc",
            size=40,
            color="muted",
            anchor="ls",
        )

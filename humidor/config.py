"""Names, rules and settings for a fleet of marker humidors.

Each humidor has a display name ("Chucho") and a URL name ("chucho"), and is
deployed as the Unison Cloud service "marker-humidor-chucho".
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SERVICE_PREFIX = "marker-humidor"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# Display names end up inside HTML and Unison text literals, so they may not
# contain markup or quote characters.
LABEL_RE = re.compile(r"^\w[\w .,'()-]{0,39}$")
# The repo link is placed in an href and a Unison text literal.
REPO_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~%/-]*)?$")
# Relative paths the admin proxy may call on a humidor.
API_PATH_RE = re.compile(r"^[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$")

# The message card printed under each QR card. {name} becomes the humidor's name.
# Text flows like Markdown: lines join into paragraphs, a blank line starts a new one.
DEFAULT_CARD_MESSAGE = """\
This is a marker humidor. Its name is {name}.

Seal markers inside to prevent them from drying out.
There should be a puddle of isopropyl alcohol in the bottom,
but not so deep that markers are submerged.

The humidor will not restore dry markers, either throw them away or visit https://www.ifixit.com/Guide/How+to+Restore++An+Expo+Marker/146008
"""

# Saved before a humidor is deleted.
BACKUP_PATH = "api/comments"


@dataclass(frozen=True)
class Check:
    path: str
    status: int = 200
    contains: str | None = None


# What every live humidor must answer, at both its name URL and its hash URL.
CHECKS = (
    Check("", contains='<textarea id="text"'),
    Check("api/comments", contains='"maxChars"'),
)


class ConfigError(Exception):
    pass


def slug(name: str) -> str:
    """The URL name for a display name: "Chucho" -> "chucho", "Big Blue (2)" -> "big-blue-2",
    "Chuchó" -> "chucho". Empty if nothing usable is left."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40].rstrip("-")


def check_slug(value: str) -> str:
    if not SLUG_RE.match(value):
        raise ConfigError(f"humidor URL name {value!r} must be lowercase letters, digits and dashes (max 40)")
    return value


def check_label(label: str) -> str:
    label = " ".join(label.split())
    if not LABEL_RE.match(label):
        raise ConfigError(
            f"humidor name {label!r} must be 1-40 letters, digits, spaces or .,'()- and start with a letter or digit"
        )
    return label


def service_name(humidor: str) -> str:
    return f"{SERVICE_PREFIX}-{check_slug(humidor)}"


@dataclass(frozen=True)
class Config:
    root: Path
    repo_url: str
    card_message: str = DEFAULT_CARD_MESSAGE

    def message_for(self, label: str) -> list[str]:
        """The card message as paragraphs: lines joined, split at blank lines."""
        text = self.card_message.replace("{name}", label)
        return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]

    @property
    def sources(self) -> list[Path]:
        """The Unison app, loaded together into one scratch file."""
        return sorted((self.root / "unison" / "src").glob("*.u"))

    @property
    def base_transcript(self) -> Path:
        return self.root / "unison" / "base.md"


def load_config(root: Path) -> Config:
    path = root / "humidor.toml"
    if not path.exists():
        raise ConfigError(f"No humidor.toml in {root}; run from the repo root or set HUMIDOR_REPO")
    data = tomllib.loads(path.read_text())
    repo_url = data.get("repo_url", "").strip().rstrip("/")
    if repo_url and not REPO_URL_RE.match(repo_url):
        raise ConfigError(f"humidor.toml: repo_url {repo_url!r} must be a plain https:// URL")
    card_message = data.get("card_message", DEFAULT_CARD_MESSAGE)
    if not isinstance(card_message, str):
        raise ConfigError("humidor.toml: card_message must be text")
    return Config(root=root, repo_url=repo_url, card_message=card_message)

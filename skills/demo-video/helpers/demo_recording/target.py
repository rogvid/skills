"""Classify the host a take is pointed at, and refuse anything public.

A demo is an outbound artifact: it leaves the repository boundary the moment
somebody downloads it, and it renders whatever was on the screen. Pointed at a
production host it is a screen recording of real customer data, published to
everyone who can reach the artifact, for as long as the artifact lives.

So the target is classified, not trusted:

| class | example | verdict |
|---|---|---|
| loopback | `127.0.0.1`, `localhost`, `[::1]` | always allowed |
| private | `10.x`, `192.168.x`, `svc.internal`, a bare hostname | allowed only with the private opt-in |
| public | `demo.example.com`, `93.184.216.34` | **refused, with no option that permits it** |

There is deliberately **no `allow_public`**, in any form — no parameter, no
environment variable, no workflow input. Recording against a public host is not
a thing this skill should make easy to configure; a team that truly needs it has
to write their own runner and own that decision explicitly.

**This is a target classifier, not a secret scanner.** The distinction is the
whole design (issue #138): the skill has no masking, no scrubbing and no
redaction, because a masker that works almost always is what persuades somebody
it is safe to point the recorder at production. A classifier fails closed on a
decidable question — what class of host is this — and makes no claim about what
reaches the screen once the answer is "loopback".

**The limit.** A storyboard that *computes* its URL at run time — from an
environment variable this module was not given, from a config file, by string
concatenation — is invisible to `scan`, and a recorder guarded on `base_url`
does not see a `fetch` the page makes to somewhere else. This is a static check
on the configuration and the source text, not a network egress control.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

LOOPBACK, PRIVATE, PUBLIC, MALFORMED = "loopback", "private", "public", "malformed"

# Suffixes reserved by RFC 2606/6761/8375 or conventional for internal naming.
_PRIVATE_SUFFIXES = (
    ".test",
    ".invalid",
    ".example",
    ".local",
    ".internal",
    ".localdomain",
    ".home.arpa",
)

URL_LITERAL = re.compile(r"https?://[^\s'\"`<>)\]}\\]+")

# How a caller words the way out of a *private* refusal. There is no equivalent
# for a public one, and that asymmetry is the point of the module.
CLI_PRIVATE_REMEDY = (
    "Pass allow-private-network-target: true if this really is a test host."
)
RECORDER_PRIVATE_REMEDY = (
    "Pass allow_private=True (or set DEMO_VIDEO_ALLOW_PRIVATE=1) if this "
    "really is a test host."
)
PUBLIC_REFUSAL = (
    "Recording a demo against a public host is refused; there is no option "
    "that permits it."
)


class TargetRefused(RuntimeError):
    """The recorder will not be pointed at this host."""


def classify(url: str) -> tuple[str, str]:
    """Return (class, why) for a URL string."""
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        return MALFORMED, f"unparseable ({exc})"
    if parts.scheme not in ("http", "https"):
        return MALFORMED, f"scheme {parts.scheme or '(none)'!r} is not http or https"
    try:
        host = parts.hostname
    except ValueError as exc:
        return MALFORMED, f"unparseable host ({exc})"
    if not host:
        return MALFORMED, "no host"
    host = host.rstrip(".").lower()

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return LOOPBACK, f"loopback address {ip}"
        if ip.is_private or ip.is_link_local or ip.is_unspecified:
            return PRIVATE, f"private address {ip}"
        return PUBLIC, f"publicly routable address {ip}"

    if host == "localhost" or host.endswith(".localhost"):
        return LOOPBACK, f"{host} resolves to loopback by RFC 6761"
    if host.endswith(_PRIVATE_SUFFIXES):
        return PRIVATE, f"{host} is under a reserved internal suffix"
    if "." not in host:
        # A single label cannot be reached from the public internet without a
        # search domain; in CI it is a service name on a container network.
        return PRIVATE, f"{host} is a single-label host name"
    return PUBLIC, f"{host} is a public DNS name"


def check(
    url: str,
    allow_private: bool,
    private_remedy: str = CLI_PRIVATE_REMEDY,
) -> str | None:
    """None when the URL may be recorded against, else the reason it may not.

    The reason names the **class** as well as the host, because "10.0.0.4 is
    refused" and "10.0.0.4 is refused *as a private address, and here is the
    opt-in*" send a reader to different places. `private_remedy` is the caller's
    own way out — the workflow input for the CLI, the constructor argument for a
    recorder — and there is no parameter for a public one.
    """
    kind, why = classify(url)
    if kind == LOOPBACK:
        return None
    if kind == PRIVATE and allow_private:
        return None
    if kind == PRIVATE:
        return f"{url} — classified {PRIVATE}: {why}. {private_remedy}"
    if kind == PUBLIC:
        return f"{url} — classified {PUBLIC}: {why}. {PUBLIC_REFUSAL}"
    return f"{url} — classified {MALFORMED}: {why}."


def scan(text: str) -> list[str]:
    """The http(s) literals in a blob of source, in order, deduplicated."""
    seen, out = set(), []
    for match in URL_LITERAL.findall(text):
        url = match.rstrip(".,;")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def guard_target(url: str | None, allow_private: bool) -> None:
    """Raise `TargetRefused` unless a recorder may be pointed at `url`.

    Called from `_DemoBase.__init__` and `Recorder.__init__` — at construction,
    before a browser exists, so the refusal happens before anything can be
    painted let alone encoded. An empty or absent URL is not a target and is
    left alone; the recorder's own default is loopback.
    """
    if not url or not url.strip():
        return
    reason = check(url, allow_private, private_remedy=RECORDER_PRIVATE_REMEDY)
    if reason is not None:
        raise TargetRefused(f"refusing to record against {reason}")

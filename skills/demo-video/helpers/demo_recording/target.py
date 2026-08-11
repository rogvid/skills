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
| malformed | `ftp://x`, `3639549472`, `0x8080808` | refused, and no opt-in reaches it either |

There is deliberately **no `allow_public`**, in any form — no parameter, no
environment variable, no workflow input. Recording against a public host is not
a thing this skill should make easy to configure; a team that truly needs it has
to write their own runner and own that decision explicitly.

**A host that is a number is malformed, not a bare hostname.** `3639549472`,
`0x8080808` and `127.1` carry no dot, and reading them as single-label service
names is how a public host got through the guard: the WHATWG URL parser, every
browser and every resolver read a host whose last label is a number as an IPv4
address, so `http://3639549472/` is `216.239.30.32`. This module does not decode
those forms, it refuses them — a second implementation of that parser (decimal,
octal, hex, and the 1-, 2- and 3-part shorthands) would be another thing to get
right, and getting it wrong in the permissive direction is exactly the failure
being fixed. The caller writes the address out as a dotted quad or a bracketed
IPv6 literal, and the classifier grades the address rather than a guess at it.

**Two edges that are correct and surprising**, so they are written down rather
than rediscovered:

- `100.64.0.0/10` — the CGNAT range — is **public**, and therefore refused with
  no way to permit it. A team whose test network hands out addresses in that
  range cannot record against them at all; give the host a name under one of the
  reserved suffixes above, or record against loopback.
- `169.254.169.254` — cloud instance metadata — is link-local and therefore
  **private**, so the private opt-in allows it. The opt-in exists for a service
  name on a container network, and it permits this too.

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

**The second limit: this is not a UTS-46 implementation.** A host is folded with
`unicodedata.normalize` and the three full stops UTS-46 maps to `.` before the
dot test, because `evil。com` has no ASCII dot and used to classify as a bare
hostname while Chromium navigated to `evil.com`. What that stdlib fold does
*not* do, and a third-party `idna` dependency in a shipped skill would: decode
`xn--` labels, reject characters IDNA disallows, apply the bidi and
joiner rules, or notice a homoglyph (`gοogle.com` with a Greek omicron is a
different name from `google.com` and both classify public here, which is the
harmless direction). Every gap listed is a host that classifies *public* or
*malformed* — refused — rather than one that slips through as private.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
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

# The three characters UTS-46 (and RFC 3490 §3.1) map to `.`, spelled out
# rather than left to `unicodedata.normalize`: that turns U+FF0E into a full
# stop and U+FF61 into U+3002, but nothing in the stdlib turns U+3002 into `.`,
# and a host with no ASCII dot in it used to read as a bare hostname.
_FULL_STOPS = str.maketrans(
    {
        "。": ".",  # IDEOGRAPHIC FULL STOP
        "．": ".",  # FULLWIDTH FULL STOP
        "｡": ".",  # HALFWIDTH IDEOGRAPHIC FULL STOP
    }
)

# A label a URL parser reads as an IPv4 number: decimal or octal (`0100`) as
# digits, or `0x`-prefixed hex — `0x` alone is a valid zero. Anchored with
# `fullmatch` at the call site.
_DECIMAL_LABEL = re.compile(r"[0-9]+")
_HEX_LABEL = re.compile(r"0x[0-9a-f]*")

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


def _fold(host: str) -> str:
    """A host in the form the rules below read: dotted, width-folded, lower."""
    host = unicodedata.normalize("NFKC", host)
    return host.translate(_FULL_STOPS).rstrip(".").lower()


def _ends_in_a_number(host: str) -> bool:
    """Whether a URL parser would read this host as an address, not a name.

    The WHATWG rule, and the one browsers implement: a host whose **last** label
    is a number is an IPv4 address in some notation, never a DNS name. Callers
    reach this only after `ipaddress` has already declined the host, so anything
    it answers True for is a notation this module refuses to decode.
    """
    last = host.rpartition(".")[2]
    return bool(_DECIMAL_LABEL.fullmatch(last) or _HEX_LABEL.fullmatch(last))


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
    host = _fold(host)
    if not host:
        return MALFORMED, "no host"

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

    if _ends_in_a_number(host):
        # Before the single-label branch below, which is what used to answer
        # for these: `ipaddress` has already declined the host, so this is a
        # number written in a notation this module will not decode.
        return MALFORMED, (
            f"{host} is a number, not a host name — a browser reads it as an "
            "IPv4 address, and this classifier will not guess which one. "
            "Write it as a dotted quad, or as a bracketed IPv6 literal"
        )
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


def guard_target(url: str | None, allow_private: bool, source: str = "") -> None:
    """Raise `TargetRefused` unless a recorder may be pointed at `url`.

    Called from `_DemoBase.__init__` and `Recorder.__init__` — at construction,
    before a browser exists, so the refusal happens before anything can be
    painted let alone encoded. An empty or absent URL is not a target and is
    left alone; the recorder's own default is loopback.

    **`source` says where the URL came from, and it is not decoration.** The
    hard case is a public `DEMO_VIDEO_BASE_URL` exported into the shell while
    the storyboard passes a loopback `base_url`: the refusal then names a host
    that appears nowhere in the file the author is looking at. Without the
    source that reads as the recorder inventing a URL, and there is nothing in
    the message to act on — while the private branch two lines up helpfully
    names its opt-in. Whoever knows which input was read says so.
    """
    if not url or not url.strip():
        return
    reason = check(url, allow_private, private_remedy=RECORDER_PRIVATE_REMEDY)
    if reason is not None:
        where = f" (from {source})" if source else ""
        raise TargetRefused(f"refusing to record against {reason}{where}")

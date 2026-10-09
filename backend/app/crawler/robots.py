"""robots.txt parser following RFC 9309 semantics (longest match wins, Allow wins ties, * and $)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

AI_CRAWLERS = {
    "GPTBot": "OpenAI (model training)",
    "OAI-SearchBot": "OpenAI (ChatGPT search)",
    "ChatGPT-User": "OpenAI (user-initiated browsing)",
    "ClaudeBot": "Anthropic",
    "Claude-SearchBot": "Anthropic (search)",
    "PerplexityBot": "Perplexity",
    "Google-Extended": "Google (Gemini training/grounding control token)",
    "CCBot": "Common Crawl",
    "Applebot-Extended": "Apple (AI training control token)",
    "Bytespider": "ByteDance",
}


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: float | None = None


@dataclass
class Robots:
    groups: list[_Group] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    raw: str = ""
    fetched: bool = False
    status_code: int | None = None
    # RFC 9309: 4xx => allow all; 5xx/unreachable => disallow all (we treat as "assume disallowed").
    disallow_all: bool = False

    def _group_for(self, agent: str) -> _Group | None:
        agent_l = agent.lower()
        best: _Group | None = None
        best_len = -1
        star: _Group | None = None
        for g in self.groups:
            for a in g.agents:
                a_l = a.lower()
                if a_l == "*":
                    star = star or g
                elif agent_l.startswith(a_l) and len(a_l) > best_len:
                    best, best_len = g, len(a_l)
        return best or star

    def is_allowed(self, url: str, agent: str = "*") -> bool:
        if self.disallow_all:
            return False
        p = urlsplit(url)
        path = (p.path or "/") + (("?" + p.query) if p.query else "")
        if path == "/robots.txt":
            return True
        g = self._group_for(agent)
        if g is None:
            return True
        best_len, allowed = -1, True
        for allow, pattern in g.rules:
            if pattern == "":
                continue
            if _match(pattern, path):
                plen = len(pattern)
                if plen > best_len or (plen == best_len and allow):
                    best_len, allowed = plen, allow
        return allowed

    def crawl_delay(self, agent: str = "*") -> float | None:
        g = self._group_for(agent)
        return g.crawl_delay if g else None

    def explicitly_blocks_root(self, agent: str) -> bool:
        """True if a group *specifically naming* this agent disallows the whole site."""
        for g in self.groups:
            if any(a.lower() == agent.lower() for a in g.agents):
                return not self._eval(g, "/")
        return False

    def _eval(self, g: _Group, path: str) -> bool:
        best_len, allowed = -1, True
        for allow, pattern in g.rules:
            if pattern and _match(pattern, path) and (len(pattern) > best_len or (len(pattern) == best_len and allow)):
                best_len, allowed = len(pattern), allow
        return allowed


def _match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in unquote(pattern))
    return re.match(regex + ("$" if anchored else ""), unquote(path)) is not None


def parse_robots(text: str) -> Robots:
    r = Robots(raw=text[:500_000], fetched=True)
    current: _Group | None = None
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = _Group()
                r.groups.append(current)
            current.agents.append(value)
            last_was_agent = True
            continue
        last_was_agent = False
        if key == "sitemap" and value:
            r.sitemaps.append(value)
        elif current is not None and key in ("allow", "disallow"):
            current.rules.append((key == "allow", value))
        elif current is not None and key == "crawl-delay":
            try:
                current.crawl_delay = float(value)
            except ValueError:
                pass
    return r

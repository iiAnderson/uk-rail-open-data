"""Work out which physical track sections a service runs over.

This is the expensive half of the map, and the reason the daily job is cheap:
attribution depends only on a service's ordered stop route, never on the date it
ran. The same route recurs day after day and across services, so the answer is
computed once per distinct route and cached.

Two passes, carried over unchanged from the original generator so the numbers
stay comparable:

1. **Direct match.** A section is attributed when the route touches at least
   ``min(2, len(section tiplocs))`` of the section's stations, compared as CRS
   codes rather than TIPLOCs — 29 stations span several TIPLOCs and Clapham
   Junction alone has five.

2. **Gap fill.** Long-distance services stop at neither end of the sections they
   pass through, so pass 1 misses the middle of every fast route. For each pair
   of consecutive stops, BFS the section-adjacency graph (sections are adjacent
   when they share a TIPLOC) and attribute everything on the path.

Both passes are heuristics. A section attributed to a service is a statement
that the service almost certainly ran over that track, not a signalling record.
"""

from __future__ import annotations

from collections import deque

# Consecutive stops further apart than this in the section graph are treated as
# unreachable rather than routed through half the network. 12 is the value the
# published dataset was built with.
MAX_HOPS = 12


def is_bus_tiploc(tpl: str) -> bool:
    """True for bus-replacement TIPLOCs. PROBUS is a signal box, not a bus."""
    return tpl.endswith("BUS") and tpl != "PROBUS"


class Network:
    """The physical network: sections, the stations on them, how they connect.

    Built once and reused for every route. Everything here is derived from
    ``reference/track_sections.json`` and the TIPLOC to CRS mapping, so it is a
    property of the railway rather than of any particular day.
    """

    def __init__(
        self,
        sections: list[dict],
        tiploc_to_sections: dict[str, list[str]],
        tiploc_to_crs: dict[str, str],
    ) -> None:
        self.tiploc_to_crs = tiploc_to_crs
        self.tiploc_to_sections = tiploc_to_sections

        self._section_tpls = {
            s["id"]: set(s["tiplocs"]) for s in sections if s["tiplocs"]
        }
        self._section_crs = {
            sid: self.to_crs(tpls) for sid, tpls in self._section_tpls.items()
        }

        # Sections sharing a TIPLOC meet there, which is what makes them walkable.
        adjacency: dict[str, set[str]] = {}
        for sids in tiploc_to_sections.values():
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    adjacency.setdefault(sids[i], set()).add(sids[j])
                    adjacency.setdefault(sids[j], set()).add(sids[i])
        self._adjacency = adjacency

        # Pass 2 starts from a CRS rather than a TIPLOC, so it needs the index
        # the other way round and CRS-expanded.
        crs_to_sids: dict[str, set[str]] = {}
        for tpl, crs in tiploc_to_crs.items():
            for sid in tiploc_to_sections.get(tpl, []):
                crs_to_sids.setdefault(crs, set()).add(sid)
        self._crs_to_sids = crs_to_sids

        # Consecutive-stop paths repeat constantly, both within a day and across
        # them. Keyed by CRS pair, this is the single biggest saving in the job.
        self._path_cache: dict[tuple[str, str], list[str] | None] = {}

    def to_crs(self, tpls) -> set[str]:
        """Normalise TIPLOCs to CRS, keeping the TIPLOC when there is no mapping."""
        return {self.tiploc_to_crs.get(t, t) for t in tpls}

    # -- pass 1 ------------------------------------------------------------

    def _direct(self, tpls: set[str]) -> set[str]:
        route_crs = self.to_crs(tpls)

        # Only sections the route actually touches are worth testing. The index
        # is by TIPLOC, deliberately: CRS-expanding the candidate search as well
        # would pull in every platform of every multi-TIPLOC station.
        candidates: set[str] = set()
        for tpl in tpls:
            candidates.update(self.tiploc_to_sections.get(tpl, ()))

        matched = set()
        for sid in candidates:
            section_crs = self._section_crs.get(sid)
            if not section_crs:
                continue
            # A one-station section matches on one hit; anything longer needs two.
            if len(route_crs & section_crs) >= min(2, len(self._section_tpls[sid])):
                matched.add(sid)
        return matched

    # -- pass 2 ------------------------------------------------------------

    def _path(self, from_crs: str, to_crs: str) -> list[str] | None:
        key = (from_crs, to_crs)
        if key not in self._path_cache:
            self._path_cache[key] = self._bfs(
                set(self._crs_to_sids.get(from_crs, ())),
                set(self._crs_to_sids.get(to_crs, ())),
            )
        return self._path_cache[key]

    def _bfs(self, start: set[str], end: set[str]) -> list[str] | None:
        """Shortest run of adjacent sections from *start* to *end*.

        Returns None when the two overlap: the stops are already on a shared
        section and pass 1 has it.
        """
        if start & end:
            return None

        queue = deque((sid, [sid]) for sid in start)
        seen = set(start)
        while queue:
            sid, path = queue.popleft()
            if len(path) > MAX_HOPS:
                continue
            for nxt in self._adjacency.get(sid, ()):
                if nxt in end:
                    return path + [nxt]
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, path + [nxt]))
        return None

    def _gap_fill(self, route: tuple[str, ...]) -> set[str]:
        filled: set[str] = set()
        for a, b in zip(route, route[1:]):
            path = self._path(
                self.tiploc_to_crs.get(a, a), self.tiploc_to_crs.get(b, b)
            )
            if path:
                filled.update(path)
        return filled

    # -- public ------------------------------------------------------------

    def sections_for_route(
        self, route: tuple[str, ...], passed: frozenset[str] = frozenset()
    ) -> list[str]:
        """Every section a service calling at *route*, in order, runs over.

        *passed* is the optional set of non-stopping timing points the service
        was scheduled through. It sharpens pass 1 and is only available when the
        raw location data has been read, which the daily job does not do — see
        seed_cache.py.
        """
        # Bus legs are not track. Below two real stations there is nothing for
        # pass 1 to match on, but pass 2 still runs: a service can be gap-filled
        # on the strength of its stop sequence alone.
        stations = {t for t in set(route) | set(passed) if not is_bus_tiploc(t)}
        direct = self._direct(stations) if len(stations) >= 2 else set()
        return sorted(direct | self._gap_fill(route))

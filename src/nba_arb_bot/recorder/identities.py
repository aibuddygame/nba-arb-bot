"""Explicit NBA team identities; no partial/city-word matching."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    aliases: tuple[str, ...] = ()


TEAMS = (
    Team("ATL", "Atlanta Hawks"),
    Team("BOS", "Boston Celtics"),
    Team("BKN", "Brooklyn Nets", ("BRK",)),
    Team("CHA", "Charlotte Hornets"),
    Team("CHI", "Chicago Bulls"),
    Team("CLE", "Cleveland Cavaliers"),
    Team("DAL", "Dallas Mavericks"),
    Team("DEN", "Denver Nuggets"),
    Team("DET", "Detroit Pistons"),
    Team("GSW", "Golden State Warriors"),
    Team("HOU", "Houston Rockets"),
    Team("IND", "Indiana Pacers"),
    Team("LAC", "Los Angeles Clippers", ("LA Clippers", "L.A. Clippers")),
    Team("LAL", "Los Angeles Lakers", ("LA Lakers", "L.A. Lakers")),
    Team("MEM", "Memphis Grizzlies"),
    Team("MIA", "Miami Heat"),
    Team("MIL", "Milwaukee Bucks"),
    Team("MIN", "Minnesota Timberwolves"),
    Team("NOP", "New Orleans Pelicans", ("NO Pelicans",)),
    Team("NYK", "New York Knicks"),
    Team("OKC", "Oklahoma City Thunder"),
    Team("ORL", "Orlando Magic"),
    Team("PHI", "Philadelphia 76ers"),
    Team("PHX", "Phoenix Suns", ("PHO",)),
    Team("POR", "Portland Trail Blazers"),
    Team("SAC", "Sacramento Kings"),
    Team("SAS", "San Antonio Spurs"),
    Team("TOR", "Toronto Raptors"),
    Team("UTA", "Utah Jazz", ("UTH",)),
    Team("WAS", "Washington Wizards", ("WSH",)),
)


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


_ALIASES = {_key(alias): team.team_id for team in TEAMS
            for alias in (team.team_id, team.name, *team.aliases)}


def team_id(value: str) -> str:
    """Resolve only explicit IDs/full names/aliases; unknown values fail closed."""
    try:
        return _ALIASES[_key(value)]
    except (KeyError, AttributeError) as exc:
        raise ValueError(f"Unknown or ambiguous NBA team: {value!r}") from exc

"""Make a team variant of the Custom1 scenario.

Default: player 1 (human) + player 2 (ally AI) vs players 3-8 (allied AIs).
With --1v7: player 1 alone vs players 2-8 (allied AIs), written to
Custom1_1v7.aoe2scenario.
Everything else (units, triggers, resources, Regicide) is kept as is.
AI slots stay on the standard AI type, so the lobby dropdown can pick any
.per script from the game's AI folder for each computer player.

Usage:
    .venv/Scripts/python tools/make_custom1_teams.py [--1v7] [source] [output]
"""
import contextlib
import io
import os
import sys

from AoE2ScenarioParser.datasets.players import AiType
from AoE2ScenarioParser.datasets.trigger_lists import DiplomacyState
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario

SCENARIO_DIR = os.path.expanduser(
    "~/Games/Age of Empires 2 DE/76561199063786381/resources/_common/scenario")
ONE_V_SEVEN = "--1v7" in sys.argv
args = [a for a in sys.argv[1:] if a != "--1v7"]
default_name = "Custom1_1v7.aoe2scenario" if ONE_V_SEVEN else "Custom1_2v6.aoe2scenario"
SOURCE = args[0] if len(args) > 0 else os.path.join(SCENARIO_DIR, "Custom1.aoe2scenario")
OUTPUT = args[1] if len(args) > 1 else os.path.join(SCENARIO_DIR, default_name)

TEAM_A = [1] if ONE_V_SEVEN else [1, 2]
TEAM_B = [p for p in range(2, 9) if p not in TEAM_A]

if os.path.abspath(SOURCE) == os.path.abspath(OUTPUT):
    sys.exit("refusing to overwrite the source scenario")

# The parser prints emoji progress lines; keep the console quiet.
with contextlib.redirect_stdout(io.StringIO()):
    scenario = AoE2DEScenario.from_file(SOURCE)

players = scenario.player_manager.players
for team, enemies in ((TEAM_A, TEAM_B), (TEAM_B, TEAM_A)):
    for pid in team:
        p = players[pid]
        allies = [o for o in team if o != pid]
        if allies:
            p.set_player_diplomacy(allies, DiplomacyState.ALLY)
        p.set_player_diplomacy(enemies, DiplomacyState.ENEMY)
        p.allied_victory = True
        if pid != 1 and p.ai_type != AiType.STANDARD:
            print(f"note: player {pid} has AI type {p.ai_type.name}; lobby AI choice may be fixed")

# Lock teams so lobby team settings can't override the scenario's diplomacy.
options = scenario.option_manager
options.lock_teams = True
options.allow_players_choose_teams = False

with contextlib.redirect_stdout(io.StringIO()):
    scenario.write_to_file(OUTPUT)
print("wrote", OUTPUT)

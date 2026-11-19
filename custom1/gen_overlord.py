"""Generate custom1/c1_enemy/overlord.per: team coordination for the enemy AIs (v7).

Built for this setup: Regicide, player 1 alone against players 2-8 who are all
allied, with a 30-minute truce.

v7 is deliberately simple. The v2-v6 leader/phase/rally system never got past
"gathering" in playtests (it waited for armies to assemble near the target, which
never happened), so the armies sat idle. Everything now runs on shared clocks,
the same mechanism that made Treason fire exactly on time:

  * Treason (castle tech 408): one team clock. First one ov-spy-lead seconds
    before the truce ends, then every ov-spy-every seconds, by the first AI with
    a castle (gold topped up by cheat). 20s later that AI says in chat whether
    it saw the king.
  * King: every AI scans for your king every pass (by unit type and by class)
    and shares his position. After the truce, a sighting more than
    ov-retarget-dist tiles from the current team target makes him the target and
    sends every army at once.
  * Waves: after the truce, every ov-wave-every seconds (team clock) the first AI
    picks ONE target for the whole team (king's last known position if seen in the
    last ov-king-memory seconds, otherwise your nearest building) and EVERY soldier
    of EVERY AI attack-moves there in box formation.
  * Between waves, every ov-idle-every ticks, idle soldiers out in the field
    (not the ones at home) attack-move to the same target, so nobody stands around.
  * After the truce the stock AI's own attack groups are off, so they don't pull
    soldiers elsewhere. Its town defense still works.
  * Chat: type 200 for every AI's resources, 202-208 for one AI.
  * Plenty of resources: new camps stay near a town center. At the pop cap,
    idle trade carts are deleted.

Edit the numbers in TUNING, then run (from the repo folder):
    .venv/Scripts/python custom1/gen_overlord.py
    .venv/Scripts/python custom1/lint_per.py custom1/c1_enemy/overlord.per
    .venv/Scripts/python custom1/install.py
"""
import re
from pathlib import Path

TUNING = {
    "ov-target-player": 1,      # who the coalition attacks
    "ov-truce-max": 1800,       # the truce length in game seconds (your 30 minutes); attacks start after it
    "ov-tick-secs": 5,          # how often the team logic runs (game seconds)
    "ov-wave-every": 180,       # every 3 min: EVERY soldier attack-moves to the team target
    "ov-idle-every": 6,         # every N ticks (6 x 5s = 30s): idle soldiers in the field re-sent
    "ov-home-radius": 30,       # soldiers within this many tiles of their own town wait for the next wave
    "ov-retarget-dist": 12,     # a king sighting this far from the current target re-sends everyone
    "ov-king-memory": 1200,     # the king's last known position stays the target this long
    "ov-attack-formation": 4,   # 2 line, 4 box, 7 staggered, 8 flank, -1 none. AoE2 has no column
                                # formation; orders go out in groups of <=20, so box = a column of tight blocks
    "ov-spy-every": 900,        # Treason every 15 min
    "ov-spy-lead": 30,          # first Treason this many seconds before the truce ends
    "ov-spy-gold": 1000,        # top up gold to this before Treason (cheat; Treason costs 400)
    "ov-spy-check": 20,         # seconds after my Treason to report whether I saw the king
    "ov-report-all": 200,       # type this number in chat: every AI reports (202-208: one AI)
    "ov-defend-flags": 14,      # sn-disable-defend-groups after the truce
    "ov-cart-headroom": 15,     # delete idle trade carts when pop headroom is below this
    "ov-chatty": 1,             # 1 = announce waves, sightings and Treason in chat
    "ov-plenty": 3000,          # with this much wood (or gold+stone) stockpiled...
    "ov-camp-dist": 12,         # ...new lumber/mining camps stay this close to a town center
}
TUNING["ov-first-spy"] = TUNING["ov-truce-max"] - TUNING["ov-spy-lead"]

# Game constants, under our own names so nothing depends on other files.
GAME = {
    "ov-fact-game-time": 0, "ov-fact-military-pop": 31,
    "ov-pos-self": 9, "ov-pos-target": 10, "ov-pos-focus": 11,
    "ov-search-local": 1, "ov-search-remote": 2,
    "ov-act-attack-move": 19, "ov-stance-aggressive": 0,
    "ov-cmdid-military": 4, "ov-all-units": -1,
    "ov-od-class": 2, "ov-od-px": 8, "ov-od-py": 9,
    "ov-od-garrisoned": 17, "ov-od-distance": 44, "ov-od-idling": 49,
    "ov-king-class": 959, "ov-king-unit": 434, "ov-transport-class": 920, "ov-fishing-class": 921,
    "ov-warship-class": 922, "ov-unpacked-treb-class": 954,
    "ov-idle-trade-cart": 1, "ov-ri-spies": 408, "ov-castle": 82,
}

# Goals the stock AI leaves unused (402-417, 421-424, 426-445; checked against Promisory).
# Pairs used as points must be consecutive (x, then y).
GOALS = {
    "ov-now": 402, "ov-me": 403, "ov-next-tick": 404, "ov-tick": 405, "ov-slow": 406,
    "ov-tmp": 408, "ov-tmp2": 409, "ov-ordid": 410, "ov-myord": 411, "ov-spied": 412,
    "ov-army": 413, "ov-dist": 424, "ov-ktime": 426,
    "ov-ss": 432, "ov-ss-last": 433, "ov-ss-remote": 434, "ov-ss-remote-last": 435,
    "ov-kx": 436, "ov-ky": 437, "ov-tgt-x": 438, "ov-tgt-y": 439,
    "ov-home-x": 440, "ov-home-y": 441, "ov-spytime": 445,
}

# Shared goals (1-256), visible to every AI on the team.
SHARED = {"TX": 206, "TY": 207, "KX": 240, "KY": 241, "KTIME": 242, "SPYNEXT": 243,
          "ORDID": 245, "ORDNEXT": 246}

# Removed from every army search: our own king (and queen), ships, unpacked
# trebuchets (can't move) and garrisoned units.
EXCLUDE_CLASSES = ["ov-king-class", "ov-transport-class", "ov-fishing-class",
                   "ov-warship-class", "ov-unpacked-treb-class"]

out = []


def rule(facts, actions, comment=None):
    if comment:
        out.append(f"; {comment}")
    f = "\n".join(f"    {x}" for x in facts)
    a = "\n".join(f"    {x}" for x in actions)
    out.append(f"(defrule\n{f}\n=>\n{a}\n)\n")


def sget(shared_id, goal):
    return f"(up-get-shared-goal c: {shared_id} {goal})"


def sset(shared_id, goal):
    return f"(up-set-shared-goal c: {shared_id} g: {goal})"


TICK = "(up-compare-goal ov-tick c:== 1)"
CHATTY = "(up-compare-const ov-chatty == 1)"
TRUCE_OVER = "(up-compare-goal ov-now c:>= ov-truce-max)"


def army(facts, prep, comment=None, batches=3):
    """Order this AI's soldiers to attack-move to the team target (ov-tgt-x/y).

    Up to 3 batches of 240 (the search list limit) cover a 500-pop army.
    `prep` holds extra removals, applied after the standard ones.
    """
    find = ["(up-find-local c: ov-all-units c: 240)", "(up-get-search-state ov-ss)",
            *[f"(up-remove-objects ov-search-local ov-od-class == {c})" for c in EXCLUDE_CLASSES],
            "(up-remove-objects ov-search-local ov-od-garrisoned == 1)",
            *prep,
            "(up-target-point ov-tgt-x ov-act-attack-move ov-attack-formation ov-stance-aggressive)"]
    rule(facts, ["(up-full-reset-search)", "(up-filter-include ov-cmdid-military -1 -1 -1)", *find], comment)
    for _ in range(batches - 1):
        rule(facts + ["(up-compare-goal ov-ss-last c:>= 240)"], ["(up-reset-search 0 1 0 0)", *find])


out.append(";;; overlord.per - generated by custom1/gen_overlord.py; edit that file, not this one.")
out.append(";;; Team coordination layer (v7) for c1_enemy on top of the stock Promisory AI.\n")
for name, value in {**TUNING, **GAME, **GOALS}.items():
    out.append(f"(defconst {name} {value})")
out.append("")

# ---------------------------------------------------------------- basics
rule(["(true)"], [
    "(set-strategic-number sn-target-player-number ov-target-player)",
    "(set-strategic-number sn-focus-player-number ov-target-player)",
], "always attack the overlord")
for n in range(1, 9):
    rule([f"(player-number {n})"], [f"(up-modify-goal ov-me c:= {n})", "(disable-self)"])
rule(["(true)"], ["(up-get-fact ov-fact-game-time 0 ov-now)", "(up-modify-goal ov-tick c:= 0)"], "clock")
rule(["(up-compare-goal ov-now g:>= ov-next-tick)"], [
    "(up-modify-goal ov-tick c:= 1)",
    "(up-modify-goal ov-next-tick g:= ov-now)", "(up-modify-goal ov-next-tick c:+ ov-tick-secs)",
    "(up-modify-goal ov-slow c:+ 1)",
])
rule([TICK, "(up-compare-goal ov-slow c:>= ov-idle-every)"], ["(up-modify-goal ov-slow c:= 0)"])
for n in range(2, 9):
    rule([f"(player-number {n})", "(up-compare-goal ov-now c:>= 3)", CHATTY], [
        f'(chat-to-all "c1_enemy: player {n} joined the coalition (v7)")', "(disable-self)",
    ], "proof the coalition layer is running" if n == 2 else None)

# ------------------------------------------------------ finding the king
# Every pass, not every tick: a Treason reveal is brief.
rule(["(true)"], [
    "(set-strategic-number sn-focus-player-number ov-target-player)",
    "(up-full-reset-search)",
    "(up-find-remote c: ov-king-unit c: 1)",
    "(up-get-search-state ov-ss)",
], "every AI: look for your king (by unit type first)")
rule(["(up-compare-goal ov-ss-remote c:< 1)"], [
    "(up-find-remote c: ov-king-class c: 1)",
    "(up-get-search-state ov-ss)",
], "...then by class")
rule(["(up-compare-goal ov-ss-remote c:>= 1)"], [
    "(up-set-target-object ov-search-remote c: 0)",
    "(up-get-object-data ov-od-px ov-kx)",
    "(up-get-object-data ov-od-py ov-ky)",
    "(up-modify-goal ov-ktime g:= ov-now)",
    sset(SHARED["KX"], "ov-kx"), sset(SHARED["KY"], "ov-ky"), sset(SHARED["KTIME"], "ov-now"),
    sget(SHARED["TX"], "ov-tgt-x"), sget(SHARED["TY"], "ov-tgt-y"),
    "(up-modify-goal ov-dist c:= 9999)",
], "I can see him: share his position")
rule(["(up-compare-goal ov-ss-remote c:>= 1)", "(up-compare-goal ov-tgt-x c:> 0)"],
     ["(up-get-point-distance ov-kx ov-tgt-x ov-dist)"])
rule(["(up-compare-goal ov-ss-remote c:>= 1)", TRUCE_OVER, "(up-compare-goal ov-dist c:> ov-retarget-dist)"], [
    sset(SHARED["TX"], "ov-kx"), sset(SHARED["TY"], "ov-ky"),
    sget(SHARED["ORDID"], "ov-tmp"), "(up-modify-goal ov-tmp c:+ 1)", sset(SHARED["ORDID"], "ov-tmp"),
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp c:+ ov-wave-every)",
    sset(SHARED["ORDNEXT"], "ov-tmp"),
    '(up-chat-data-to-all "c1_enemy: player %d sees your king - ALL armies attack him" g: ov-me)',
], "after the truce, a sighting away from the current target: he's the target now, everyone goes")

# ---------------------------------------------------------------- Treason
rule([TICK], [sget(SHARED["SPYNEXT"], "ov-spytime"), sget(SHARED["KTIME"], "ov-ktime"),
              "(up-modify-goal ov-spytime c:max ov-first-spy)"],
     "Treason: one team clock (SPYNEXT); first one ov-spy-lead seconds before the truce ends")
SPY_DUE = [TICK, "(up-compare-goal ov-now g:>= ov-spytime)", "(building-type-count ov-castle >= 1)"]
rule(SPY_DUE + ["(gold-amount < ov-spy-gold)"], ["(cc-add-resource gold ov-spy-gold)"],
     "Treason due and I have a castle: make sure the gold is there (the queen's pad can drain it)")
NEXT_SPY = ["(up-modify-goal ov-spied g:= ov-now)",
            "(up-modify-goal ov-spytime g:= ov-now)", "(up-modify-goal ov-spytime c:+ ov-spy-every)",
            sset(SHARED["SPYNEXT"], "ov-spytime")]
rule(SPY_DUE + ["(can-research ov-ri-spies)"], [
    "(research ov-ri-spies)", *NEXT_SPY,
    '(up-chat-data-to-all "c1_enemy: player %d researched Treason to find your king" g: ov-me)',
], "Treason = castle tech 408. The team clock stops the others until the next one")
rule(SPY_DUE + ["(not (can-research ov-ri-spies))", "(can-spy)"], [
    "(spy)", *NEXT_SPY,
    '(up-chat-data-to-all "c1_enemy: player %d used Treason to find your king" g: ov-me)',
], "backup: the spy command")
rule([TICK, "(up-compare-goal ov-spied c:> 0)"], [
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-spied)",
])
rule([TICK, "(up-compare-goal ov-spied c:> 0)", "(up-compare-goal ov-tmp c:>= ov-spy-check)",
      "(up-compare-goal ov-ktime g:>= ov-spied)", CHATTY],
     ['(up-chat-data-to-all "c1_enemy: player %d - Treason worked, your king was seen" g: ov-me)'],
     "20s after my Treason: tell you whether anyone on the team saw the king since")
rule([TICK, "(up-compare-goal ov-spied c:> 0)", "(up-compare-goal ov-tmp c:>= ov-spy-check)",
      "(up-compare-goal ov-ktime g:< ov-spied)", CHATTY],
     ['(up-chat-data-to-all "c1_enemy: player %d - Treason did NOT show us your king" g: ov-me)'])
rule([TICK, "(up-compare-goal ov-spied c:> 0)", "(up-compare-goal ov-tmp c:>= ov-spy-check)"],
     ["(up-modify-goal ov-spied c:= 0)"])

# -------------------------------------------------------- waves (team clock)
rule([TICK, TRUCE_OVER], [sget(SHARED["ORDNEXT"], "ov-tmp2")], "waves: ov-tmp2 = when the next wave is due")
WAVE_DUE = [TICK, TRUCE_OVER, "(up-compare-goal ov-now g:>= ov-tmp2)"]
rule(WAVE_DUE, [
    "(up-modify-goal ov-tgt-x c:= -1)", "(up-modify-goal ov-tgt-y c:= -1)",
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-ktime)",
], "wave due and I'm first: pick the team target")
rule(WAVE_DUE + ["(up-compare-goal ov-ktime c:> 0)", "(up-compare-goal ov-tmp c:<= ov-king-memory)"],
     [sget(SHARED["KX"], "ov-tgt-x"), sget(SHARED["KY"], "ov-tgt-y"),
      '(up-chat-data-to-all "c1_enemy: player %d - wave: ALL armies to your king\'s last known position" g: ov-me)'],
     "the king's last known position, if he was seen recently")
rule(WAVE_DUE + ["(up-compare-goal ov-tgt-x c:< 0)"], ["(up-get-point ov-pos-focus ov-tgt-x)"],
     "otherwise your nearest building")
rule(WAVE_DUE + ["(up-compare-goal ov-tgt-x c:< 0)"], ["(up-get-point ov-pos-target ov-tgt-x)"])
rule(WAVE_DUE + ["(up-compare-goal ov-tgt-x c:>= 0)", "(up-compare-goal ov-tmp c:> ov-king-memory)"],
     ['(up-chat-data-to-all "c1_enemy: player %d - wave: ALL armies to your nearest building" g: ov-me)'])
rule(WAVE_DUE + ["(up-compare-goal ov-tgt-x c:>= 0)"], [
    sset(SHARED["TX"], "ov-tgt-x"), sset(SHARED["TY"], "ov-tgt-y"),
    sget(SHARED["ORDID"], "ov-tmp"), "(up-modify-goal ov-tmp c:+ 1)", sset(SHARED["ORDID"], "ov-tmp"),
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp c:+ ov-wave-every)",
    sset(SHARED["ORDNEXT"], "ov-tmp"),
], "share it: every AI sends everything on its next tick")

# ------------------------------------------------- every AI: follow orders
rule([TICK], [sget(SHARED["ORDID"], "ov-ordid"), sget(SHARED["TX"], "ov-tgt-x"), sget(SHARED["TY"], "ov-tgt-y"),
              "(up-get-point ov-pos-self ov-home-x)"],
     "every AI: read the team order")
ORDER_NEW = [TICK, TRUCE_OVER, "(up-compare-goal ov-ordid g:!= ov-myord)", "(up-compare-goal ov-tgt-x c:>= 0)"]
out.append(";;; ---------- WAVE: every soldier attack-moves to the team target")
army(ORDER_NEW, [], "new team order: EVERY soldier I have, wherever it is, attack-moves to the target")
rule(ORDER_NEW, ["(up-modify-goal ov-myord g:= ov-ordid)"])
IDLE_DUE = [TICK, TRUCE_OVER, "(up-compare-goal ov-slow c:== 0)", "(up-compare-goal ov-tgt-x c:>= 0)",
            "(up-compare-goal ov-home-x c:>= 0)"]
army(IDLE_DUE, ["(up-remove-objects ov-search-local ov-od-idling == 0)",
                "(up-set-target-point ov-home-x)",
                "(up-remove-objects ov-search-local ov-od-distance < ov-home-radius)"],
     "every 30s: idle soldiers out in the field go to the target too (the ones at home wait for the wave)")

# ------------------------------------- take the army away from the stock AI
rule([TRUCE_OVER], [
    "(set-strategic-number sn-number-attack-groups 0)",
    "(set-strategic-number sn-disable-attack-groups 1)",
    "(set-strategic-number sn-task-ungrouped-soldiers 0)",
    "(set-strategic-number sn-disable-defend-groups ov-defend-flags)",
    "(set-strategic-number sn-number-tasked-units 0)",
    "(set-strategic-number sn-enable-patrol-attack 1)",
], "after the truce: no stock attack groups pulling soldiers elsewhere")

# ------------------------------------- keep new camps off the open routes
rule(["(wood-amount >= ov-plenty)"], ["(set-strategic-number sn-lumber-camp-max-distance ov-camp-dist)"],
     "plenty of wood: new lumber camps only right next to a town center")
rule(["(wood-amount < ov-plenty)"], ["(set-strategic-number sn-lumber-camp-max-distance 0)"])
rule(["(gold-amount >= ov-plenty)", "(stone-amount >= ov-plenty)"],
     ["(set-strategic-number sn-mining-camp-max-distance ov-camp-dist)"])
rule(["(or (gold-amount < ov-plenty) (stone-amount < ov-plenty))"],
     ["(set-strategic-number sn-mining-camp-max-distance 0)"])

# ------------------------------------------- army management (pop space)
rule([TICK, "(population-headroom < ov-cart-headroom)", "(up-idle-unit-count ov-idle-trade-cart >= 1)"],
     ["(up-delete-idle-units ov-idle-trade-cart)"],
     "at the pop cap, idle trade carts give their population to soldiers")

# --------------------------------------------- resource report on request
# Type 200 in chat for every AI, or 202-208 for one player. A chat line that starts with a
# number counts as a taunt, and AIs can detect taunts from player 1.
out.append(";;; ---------- REPORT: type 200 (all AIs) or 202-208 (one AI) in chat")
for n in range(2, 9):
    asked = (f"(or (taunt-detected ov-target-player ov-report-all) "
             f"(taunt-detected ov-target-player {200 + n}))")
    rule([f"(player-number {n})", asked], [
        f'(chat-to-all "c1_enemy: player {n} resources -")',
        "(up-get-fact food-amount 0 ov-tmp)", '(up-chat-data-to-all "food %d" g: ov-tmp)',
        "(up-get-fact wood-amount 0 ov-tmp)", '(up-chat-data-to-all "wood %d" g: ov-tmp)',
        "(up-get-fact gold-amount 0 ov-tmp)", '(up-chat-data-to-all "gold %d" g: ov-tmp)',
        "(up-get-fact stone-amount 0 ov-tmp)", '(up-chat-data-to-all "stone %d" g: ov-tmp)',
        "(up-get-fact ov-fact-military-pop 0 ov-tmp)", '(up-chat-data-to-all "soldiers %d" g: ov-tmp)',
    ], "resource report for you" if n == 2 else None)
rule(["(taunt-detected ov-target-player ov-report-all)"],
     ["(acknowledge-taunt ov-target-player ov-report-all)"])
for n in range(2, 9):
    rule([f"(taunt-detected ov-target-player {200 + n})"],
         [f"(acknowledge-taunt ov-target-player {200 + n})"])

# --------------------------------------------------------------- output
here = Path(__file__).resolve().parent
target = here / "c1_enemy" / "overlord.per"
target.write_text("\n".join(out) + "\n", encoding="utf-8")
print("wrote", target, f"({sum(1 for x in out if x.startswith('(defrule'))} rules)")

# The stock AI's 2023 grouped-micro system re-orders soldiers on its own;
# force-old-micro switches it off for this package.
consts = here / "c1_enemy" / "Promisory" / "customConstants.per"
text = consts.read_text(encoding="latin-1")
patched = re.sub(r"\(defconst force-old-micro 0\)", "(defconst force-old-micro 1)", text)
if patched != text:
    consts.write_text(patched, encoding="latin-1")
    print("set force-old-micro to 1 in", consts)

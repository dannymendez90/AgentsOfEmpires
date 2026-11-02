"""Generate custom1/c1_enemy/overlord.per: team coordination for the enemy AIs.

Built for this setup: Regicide, player 1 alone against players 2-8 who are all
allied, usually with a truce (treaty) at the start.

What the generated rules do (on top of the stock Promisory AI):
  * Every AI targets player 1 and they elect a leader through shared goals.
  * Finding the king: every AI reports when it sees your king. When nobody has
    seen him for a while, the leader researches Treason (Regicide),
    which reveals your king. In non-Regicide games they research Spies once.
    A king sighting stays the attack target for ov-king-memory seconds;
    otherwise the target is your nearest building.
  * Truce: armies start moving to the rally point ov-stage-secs before the
    truce ends and attack together the moment it ends.
  * Phases, shared by the whole team:
      GATHER - every soldier marches to a rally point in front of the target
               (no formation, so they flow through chokes). Idle soldiers
               are re-sent every tick so nobody is left behind.
      ATTACK - once most armies are assembled, every AI launches its whole
               army at the target in one formation. Reinforcements wait at
               the rally point and go in as a group every ov-reinforce-every
               ticks instead of trickling in. If the king moves, the order is
               re-issued to the new spot.
      REGROUP- when the wave falls below ov-retreat-pct, survivors fall back
               to the rally point and the cycle repeats.
  * While the coalition runs, the stock AI's own attack groups, town-spread
    and defend-assist systems are switched off so they stop pulling soldiers
    away from the coalition's orders. Its grouped-micro system is also
    disabled (force-old-micro in the c1_enemy package).
  * Idle trade carts are deleted when the AI is at its population cap.
  * Phase changes are announced in chat so you can follow them while testing.

Edit the numbers in TUNING, then run (from the repo folder):
    .venv/Scripts/python custom1/gen_overlord.py
    .venv/Scripts/python custom1/install.py
"""
import re
from pathlib import Path

TUNING = {
    "ov-target-player": 1,      # who the coalition attacks
    "ov-tick-secs": 5,          # how often the team logic runs (game seconds)
    "ov-cmd-every": 3,          # march orders every N ticks (3 x 5s = 15s)
    "ov-hb-stale": 20,          # an AI silent this long counts as dead
    "ov-min-army": 25,          # an AI needs this many soldiers to report ready
    "ov-min-team-army": 150,    # the team needs this many soldiers to attack
    "ov-ready-pct": 60,         # % of an AI's army that must be at the rally
    "ov-ready-cap": 200,        # ...capped at this many units
    "ov-team-ready-pct": 75,    # % of living AIs that must be ready to attack
    "ov-gather-timeout": 180,   # attack anyway after gathering this long
    "ov-retreat-pct": 40,       # regroup when the wave falls below this %
    "ov-attack-timeout": 600,   # regroup after attacking this long
    "ov-rally-dist": 35,        # rally point distance in front of the target
    "ov-rally-move": 12,        # only move the rally point if it shifts this far
    "ov-near-dist": 20,         # "at the rally" radius
    "ov-arrived-dist": 8,       # don't re-order units already this close
    "ov-launch-radius": 60,     # soldiers this close to the target join the attack
    "ov-retarget-dist": 12,     # re-issue the attack if the target moves this far
    "ov-reinforce-every": 6,    # send waiting reinforcements every N ticks (30s)
    "ov-attack-formation": 2,   # 2 line, 4 box, 7 staggered, 8 flank, -1 none
    "ov-march-formation": -1,   # formation used to reach the rally (-1 none)
    "ov-stage-secs": 240,       # start gathering this long before the truce ends
    "ov-king-memory": 180,      # a king sighting stays the target this long
    "ov-king-stale": 90,        # research Treason when the king's unseen this long
    "ov-spy-every": 180,        # minimum gap between Treason researches
    "ov-defend-flags": 14,      # sn-disable-defend-groups while the coalition runs
    "ov-cart-headroom": 15,     # delete idle carts when pop headroom is below
    "ov-chatty": 1,             # 1 = announce phases and Treason in chat
}

# Game constants, under our own names so nothing depends on other files.
GAME = {
    "ov-fact-game-time": 0, "ov-fact-military-pop": 31,
    "ov-pos-center": 0, "ov-pos-self": 9, "ov-pos-target": 10, "ov-pos-focus": 11,
    "ov-search-local": 1, "ov-search-remote": 2,
    "ov-act-move": 1, "ov-act-attack-move": 19,
    "ov-form-none": -1, "ov-stance-aggressive": 0,
    "ov-actionid-attack": 600, "ov-cmdid-military": 4, "ov-all-units": -1,
    "ov-od-class": 2, "ov-od-action": 5, "ov-od-px": 8, "ov-od-py": 9,
    "ov-od-garrisoned": 17, "ov-od-distance": 44, "ov-od-idling": 49,
    "ov-king-class": 959, "ov-transport-class": 920, "ov-fishing-class": 921,
    "ov-warship-class": 922, "ov-unpacked-treb-class": 954,
    "ov-idle-trade-cart": 1, "ov-ri-spies": 408,
}

# Goals the stock AI leaves unused (402-417, 421-424, 426-445).
GOALS = {
    "ov-now": 402, "ov-me": 403, "ov-next-tick": 404, "ov-tick": 405, "ov-slow": 406,
    "ov-leader": 407, "ov-tmp": 408, "ov-tmp2": 409, "ov-phase": 410, "ov-last-phase": 411,
    "ov-wave": 412, "ov-army": 413, "ov-needed": 414, "ov-regroup-first": 415,
    "ov-pulses": 416, "ov-idx": 417,
    "ov-treaty": 421, "ov-sent-x": 422, "ov-sent-y": 423, "ov-dist": 424,
    "ov-ktime": 426, "ov-reinforce": 427,
    "ov-alive": 428, "ov-ready": 429, "ov-armysum": 430, "ov-armystart": 431,
    "ov-ss": 432, "ov-ss-last": 433, "ov-ss-remote": 434, "ov-ss-remote-last": 435,
    "ov-rally-x": 436, "ov-rally-y": 437, "ov-tgt-x": 438, "ov-tgt-y": 439,
    "ov-home-x": 440, "ov-home-y": 441, "ov-lead-num": 442, "ov-lead-time": 443,
    "ov-launch": 444, "ov-spytime": 445,
}

# Shared goals (1-256), visible to every AI on the team.
SHARED = {
    "LEADER": 200, "LEADTIME": 201, "PHASE": 202, "WAVE": 203,
    "RX": 204, "RY": 205, "TX": 206, "TY": 207, "PHASESTART": 208, "ARMYSTART": 209,
    "KX": 240, "KY": 241, "KTIME": 242, "SPYTIME": 243,
}
HB, READY, ARMY = 210, 220, 230   # + player number

# Removed from every army search: our own king (and queen), ships, unpacked
# trebuchets (can't move) and garrisoned units.
EXCLUDE_CLASSES = ["ov-king-class", "ov-transport-class", "ov-fishing-class",
                   "ov-warship-class", "ov-unpacked-treb-class"]

GATHER, ATTACK = 1, 2

out = []


def rule(facts, actions, comment=None):
    if comment:
        out.append(f"; {comment}")
    f = "\n".join(f"    {x}" for x in facts)
    a = "\n".join(f"    {x}" for x in actions)
    out.append(f"(defrule\n{f}\n=>\n{a}\n)\n")


TICK = "(up-compare-goal ov-tick c:== 1)"
LEAD = "(up-compare-goal ov-leader c:== 1)"
CMD = [TICK, "(up-compare-goal ov-slow c:== 0)"]
CHATTY = "(up-compare-const ov-chatty == 1)"


def sget(shared_id, goal):
    return f"(up-get-shared-goal c: {shared_id} {goal})"


def per_player_slot(base):
    return [f"(up-modify-goal ov-idx c:= {base})", "(up-modify-goal ov-idx g:+ ov-me)"]


def army(facts, near, lo, hi, prep, dest, action, formation, comment=None, batches=2):
    """Order this AI's soldiers in batches of up to 240 (the search list limit).

    Picks soldiers whose distance to point `near` is between lo and hi (-1 =
    no limit), applies the extra removals in `prep`, then sends the rest to
    point `dest`. All unit types go in one order, so a formation moves as one
    body at the pace of its slowest unit.
    """
    find = [f"(up-set-target-point {near})", f"(up-filter-distance c: {lo} c: {hi})",
            "(up-find-local c: ov-all-units c: 240)", "(up-get-search-state ov-ss)",
            *[f"(up-remove-objects ov-search-local ov-od-class == {c})" for c in EXCLUDE_CLASSES],
            "(up-remove-objects ov-search-local ov-od-garrisoned == 1)",
            *prep,
            f"(up-target-point {dest} {action} {formation} ov-stance-aggressive)"]
    rule(facts, ["(up-full-reset-search)", "(up-filter-include ov-cmdid-military -1 -1 -1)", *find], comment)
    for _ in range(batches - 1):
        rule(facts + ["(up-compare-goal ov-ss-last c:>= 240)"], ["(up-reset-search 0 1 0 0)", *find])


NOT_FIGHTING = "(up-remove-objects ov-search-local ov-od-action == ov-actionid-attack)"
ONLY_IDLE = "(up-remove-objects ov-search-local ov-od-idling == 0)"
OUTSIDE_RALLY_NEAR = ["(up-set-target-point ov-rally-x)",
                      "(up-remove-objects ov-search-local ov-od-distance < ov-near-dist)"]
OUTSIDE_RALLY_ARRIVED = ["(up-set-target-point ov-rally-x)",
                         "(up-remove-objects ov-search-local ov-od-distance < ov-arrived-dist)"]


out.append(";;; overlord.per - generated by custom1/gen_overlord.py; edit that file, not this one.")
out.append(";;; Team coordination layer for c1_enemy on top of the stock Promisory AI.\n")
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

rule(["(true)"], [
    "(up-get-fact ov-fact-game-time 0 ov-now)",
    "(up-modify-goal ov-tick c:= 0)",
], "clock")
rule(["(up-compare-goal ov-now g:>= ov-next-tick)"], [
    "(up-modify-goal ov-tick c:= 1)",
    "(up-modify-goal ov-next-tick g:= ov-now)",
    "(up-modify-goal ov-next-tick c:+ ov-tick-secs)",
    "(up-modify-goal ov-slow c:+ 1)",
    "(up-get-treaty-data ov-treaty)",
])
rule([TICK, "(up-compare-goal ov-slow c:>= ov-cmd-every)"], ["(up-modify-goal ov-slow c:= 0)"])

rule(["(up-compare-goal ov-me c:>= 1)", "(up-compare-goal ov-now c:>= 3)", CHATTY], [
    '(up-chat-data-to-all "c1_enemy: player %d joined the coalition" g: ov-me)',
    "(disable-self)",
])

# ------------------------------------------------- heartbeat + army report
rule([TICK], [
    "(up-get-fact ov-fact-military-pop 0 ov-army)",
    *per_player_slot(HB), "(up-set-shared-goal g: ov-idx g: ov-now)",
    *per_player_slot(ARMY), "(up-set-shared-goal g: ov-idx g: ov-army)",
], "heartbeat and army size for the leader")

# ------------------------------------------------------ finding the king
# Checked every pass, not every tick: Treason only reveals the king briefly.
rule(["(true)"], [
    "(up-full-reset-search)",
    "(up-find-remote c: ov-king-class c: 1)",
    "(up-get-search-state ov-ss)",
], "every AI: report your king whenever it can see him")
rule(["(up-compare-goal ov-ss-remote c:>= 1)"], [
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-ktime)",
])
rule(["(up-compare-goal ov-ss-remote c:>= 1)", LEAD, "(up-compare-goal ov-tmp c:> ov-king-stale)", CHATTY], [
    '(chat-to-all "c1_enemy coalition: king spotted, attacking his position")',
], "leader: announce a fresh sighting so you can tell Treason worked")
rule(["(up-compare-goal ov-ss-remote c:>= 1)"], [
    "(up-modify-goal ov-ktime g:= ov-now)",
    "(up-set-target-object ov-search-remote c: 0)",
    "(up-get-object-data ov-od-px ov-tmp)",
    "(up-get-object-data ov-od-py ov-tmp2)",
    f"(up-set-shared-goal c: {SHARED['KX']} g: ov-tmp)",
    f"(up-set-shared-goal c: {SHARED['KY']} g: ov-tmp2)",
    f"(up-set-shared-goal c: {SHARED['KTIME']} g: ov-now)",
])
rule([TICK], [
    sget(SHARED["KTIME"], "ov-ktime"), sget(SHARED["SPYTIME"], "ov-spytime"),
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-ktime)",
    "(up-modify-goal ov-tmp2 g:= ov-now)", "(up-modify-goal ov-tmp2 g:- ov-spytime)",
], "ov-tmp = seconds since the king was seen, ov-tmp2 = seconds since the team's last Treason")
rule([TICK, LEAD, "(up-compare-goal ov-phase c:>= 1)", "(up-compare-goal ov-tmp c:> ov-king-stale)",
      "(up-compare-goal ov-tmp2 c:> ov-spy-every)", "(can-spy)"], [
    "(spy)",
    f"(up-set-shared-goal c: {SHARED['SPYTIME']} g: ov-now)",
    "(up-modify-goal ov-spytime c:= -1)",
], "Regicide: the leader researches Treason, only when nobody has seen your king for a while")
rule([TICK, "(up-compare-goal ov-spytime c:== -1)", CHATTY], [
    '(up-chat-data-to-all "c1_enemy: player %d used Treason to find your king" g: ov-me)',
])
rule(["(up-compare-goal ov-phase c:>= 1)", "(can-research ov-ri-spies)"], ["(research ov-ri-spies)"],
     "other game modes: Spies shows everything your units see")

# ------------------------------------------------------- leader election
rule([TICK], [
    sget(SHARED["LEADER"], "ov-lead-num"), sget(SHARED["LEADTIME"], "ov-lead-time"),
    "(up-modify-goal ov-leader c:= 0)",
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-lead-time)",
], "leader election: first AI to find no living leader takes over")
rule([TICK, "(up-compare-goal ov-lead-num g:== ov-me)"], [
    "(up-modify-goal ov-leader c:= 1)",
    f"(up-set-shared-goal c: {SHARED['LEADTIME']} g: ov-now)",
])
rule([TICK, "(up-compare-goal ov-leader c:== 0)",
      "(or (up-compare-goal ov-lead-num c:== 0) (up-compare-goal ov-tmp c:> ov-hb-stale))"], [
    f"(up-set-shared-goal c: {SHARED['LEADER']} g: ov-me)",
    f"(up-set-shared-goal c: {SHARED['LEADTIME']} g: ov-now)",
    "(up-modify-goal ov-leader c:= 1)",
])

# ------------------------------------------------ leader: count the team
rule([TICK, LEAD], [
    "(up-modify-goal ov-alive c:= 0)", "(up-modify-goal ov-ready c:= 0)",
    "(up-modify-goal ov-armysum c:= 0)",
], "leader: count living, ready and total army across the team")
for p in range(1, 9):
    rule([TICK, LEAD], [
        sget(HB + p, "ov-tmp2"),
        "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-tmp2)",
    ])
    rule([TICK, LEAD, "(up-compare-goal ov-tmp2 c:<= 0)"], ["(up-modify-goal ov-tmp c:= 9999)"])
    rule([TICK, LEAD, "(up-compare-goal ov-tmp c:<= ov-hb-stale)"], [
        "(up-modify-goal ov-alive c:+ 1)",
        sget(ARMY + p, "ov-tmp2"), "(up-modify-goal ov-armysum g:+ ov-tmp2)",
        sget(READY + p, "ov-tmp2"),
    ])
    rule([TICK, LEAD, "(up-compare-goal ov-tmp c:<= ov-hb-stale)", "(up-compare-goal ov-tmp2 c:== 1)"],
         ["(up-modify-goal ov-ready c:+ 1)"])

# ------------------------------------------- leader: target + rally point
rule([TICK, LEAD], [
    sget(SHARED["PHASE"], "ov-phase"),
    "(up-get-point ov-pos-self ov-home-x)",
    "(up-get-point ov-pos-target ov-tgt-x)",
], "leader: default target is your nearest building")
rule([TICK, LEAD, "(up-compare-goal ov-home-x c:< 0)"], ["(up-get-point ov-pos-center ov-home-x)"])
rule([TICK, LEAD, "(up-compare-goal ov-tgt-x c:< 0)"], ["(up-get-point ov-pos-focus ov-tgt-x)"],
     "no target yet (for example during the truce): use your start position")
rule([TICK, LEAD, "(up-compare-goal ov-ktime c:> 0)"], [
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-ktime)",
], "leader: a recent king sighting overrides that")
rule([TICK, LEAD, "(up-compare-goal ov-ktime c:> 0)", "(up-compare-goal ov-tmp c:<= ov-king-memory)"], [
    sget(SHARED["KX"], "ov-tgt-x"), sget(SHARED["KY"], "ov-tgt-y"),
])
rule([TICK, LEAD, "(up-compare-goal ov-tgt-x c:>= 0)", "(up-compare-goal ov-tgt-y c:>= 0)"], [
    f"(up-set-shared-goal c: {SHARED['TX']} g: ov-tgt-x)",
    f"(up-set-shared-goal c: {SHARED['TY']} g: ov-tgt-y)",
    "(up-modify-goal ov-rally-x g:= ov-tgt-x)", "(up-modify-goal ov-rally-y g:= ov-tgt-y)",
    "(up-lerp-tiles ov-rally-x ov-home-x c: ov-rally-dist)",
    "(up-bound-point ov-rally-x ov-rally-x)",
    sget(SHARED["RX"], "ov-home-x"), sget(SHARED["RY"], "ov-home-y"),
    "(up-get-point-distance ov-rally-x ov-home-x ov-dist)",
], "leader: rally point sits ov-rally-dist tiles in front of the target, toward the leader's base")
rule([TICK, LEAD, "(up-compare-goal ov-tgt-x c:>= 0)",
      "(or (up-compare-goal ov-home-x c:<= 0) (up-compare-goal ov-dist c:> ov-rally-move))"], [
    f"(up-set-shared-goal c: {SHARED['RX']} g: ov-rally-x)",
    f"(up-set-shared-goal c: {SHARED['RY']} g: ov-rally-y)",
], "...but only move it when it shifts noticeably, so marching armies aren't re-ordered for nothing")

# ---------------------------------------------------- leader: phase logic
rule([TICK, LEAD, "(up-compare-goal ov-phase c:== 0)", "(up-compare-goal ov-treaty c:<= ov-stage-secs)"], [
    f"(up-set-shared-goal c: {SHARED['PHASE']} c: {GATHER})",
    f"(up-set-shared-goal c: {SHARED['PHASESTART']} g: ov-now)",
    f"(up-modify-goal ov-phase c:= {GATHER})",
], "leader: start the first gather (right away, or near the end of the truce)")
rule([TICK, LEAD, f"(up-compare-goal ov-phase c:== {GATHER})", "(up-compare-goal ov-treaty c:> 0)", CHATTY], [
    '(up-chat-data-to-all "c1_enemy coalition: gathering, truce ends in %d seconds" g: ov-treaty)',
    "(disable-self)",
])
rule([TICK, LEAD], [
    sget(SHARED["PHASESTART"], "ov-tmp2"),
    "(up-modify-goal ov-tmp g:= ov-now)", "(up-modify-goal ov-tmp g:- ov-tmp2)",
    "(up-modify-goal ov-tmp2 g:= ov-ready)", "(up-modify-goal ov-tmp2 c:* 100)",
    "(up-modify-goal ov-needed g:= ov-alive)", "(up-modify-goal ov-needed c:* ov-team-ready-pct)",
], "leader: ov-tmp = seconds in phase, ov-tmp2 = ready x 100, ov-needed = alive x pct")
rule([TICK, LEAD, f"(up-compare-goal ov-phase c:== {GATHER})", "(up-compare-goal ov-treaty c:<= 0)",
      "(up-compare-goal ov-armysum c:>= ov-min-team-army)", "(up-compare-goal ov-ready c:>= 1)",
      "(or (up-compare-goal ov-tmp2 g:>= ov-needed) (up-compare-goal ov-tmp c:>= ov-gather-timeout))"], [
    f"(up-set-shared-goal c: {SHARED['PHASE']} c: {ATTACK})",
    f"(up-set-shared-goal c: {SHARED['PHASESTART']} g: ov-now)",
    f"(up-set-shared-goal c: {SHARED['ARMYSTART']} g: ov-armysum)",
    sget(SHARED["WAVE"], "ov-wave"), "(up-modify-goal ov-wave c:+ 1)",
    f"(up-set-shared-goal c: {SHARED['WAVE']} g: ov-wave)",
    f"(up-modify-goal ov-phase c:= {ATTACK})",
    "(up-modify-goal ov-tmp c:= 0)",
    '(up-chat-data-to-all "c1_enemy coalition: ATTACK! wave %d" g: ov-wave)',
], "leader: gather -> attack when most armies are ready (or the gather timer ran out) and the truce is over")
rule([TICK, LEAD], [
    sget(SHARED["ARMYSTART"], "ov-armystart"),
    "(up-modify-goal ov-tmp2 g:= ov-armysum)", "(up-modify-goal ov-tmp2 c:* 100)",
    "(up-modify-goal ov-needed g:= ov-armystart)", "(up-modify-goal ov-needed c:* ov-retreat-pct)",
])
rule([TICK, LEAD, f"(up-compare-goal ov-phase c:== {ATTACK})",
      "(or (up-compare-goal ov-tmp2 g:< ov-needed) (up-compare-goal ov-tmp c:>= ov-attack-timeout))"], [
    f"(up-set-shared-goal c: {SHARED['PHASE']} c: {GATHER})",
    f"(up-set-shared-goal c: {SHARED['PHASESTART']} g: ov-now)",
    f"(up-modify-goal ov-phase c:= {GATHER})",
    '(up-chat-data-to-all "c1_enemy coalition: regrouping, %d soldiers left" g: ov-armysum)',
], "leader: attack -> regroup after heavy losses or a long fight")

# ------------------------------------------------- every AI: read the plan
rule([TICK], [
    sget(SHARED["PHASE"], "ov-phase"),
    sget(SHARED["RX"], "ov-rally-x"), sget(SHARED["RY"], "ov-rally-y"),
    sget(SHARED["TX"], "ov-tgt-x"), sget(SHARED["TY"], "ov-tgt-y"),
], "every AI: read the shared plan")
rule([TICK, "(up-compare-goal ov-phase g:!= ov-last-phase)"], [
    "(up-modify-goal ov-pulses c:= 0)", "(up-modify-goal ov-regroup-first c:= 0)",
    *per_player_slot(READY), "(up-set-shared-goal g: ov-idx c: 0)",
], "phase changed: reset my ready flag and pulse count")
rule([TICK, f"(up-compare-goal ov-phase c:== {GATHER})", f"(up-compare-goal ov-last-phase c:== {ATTACK})"],
     ["(up-modify-goal ov-regroup-first c:= 1)", "(up-modify-goal ov-slow c:= 0)"],
     "coming back from an attack: pull everyone out on this tick")
rule([TICK, f"(up-compare-goal ov-phase c:== {ATTACK})", f"(up-compare-goal ov-last-phase c:!= {ATTACK})"], [
    "(up-modify-goal ov-launch c:= 1)", "(up-modify-goal ov-reinforce c:= 1)",
    "(up-modify-goal ov-sent-x g:= ov-tgt-x)", "(up-modify-goal ov-sent-y g:= ov-tgt-y)",
], "attack just started: launch the whole army on this tick")
rule([TICK], ["(up-modify-goal ov-last-phase g:= ov-phase)"])
rule([TICK, f"(up-compare-goal ov-phase c:== {ATTACK})", "(up-compare-goal ov-launch c:== 0)"], [
    "(up-get-point-distance ov-tgt-x ov-sent-x ov-dist)",
    "(up-modify-goal ov-reinforce c:+ 1)",
])
rule([TICK, f"(up-compare-goal ov-phase c:== {ATTACK})", "(up-compare-goal ov-launch c:== 0)",
      "(up-compare-goal ov-dist c:> ov-retarget-dist)"], [
    "(up-modify-goal ov-launch c:= 1)",
    "(up-modify-goal ov-sent-x g:= ov-tgt-x)", "(up-modify-goal ov-sent-y g:= ov-tgt-y)",
], "the target (your king) moved: re-launch at the new spot")
rule([TICK, "(up-compare-goal ov-reinforce c:> ov-reinforce-every)"], ["(up-modify-goal ov-reinforce c:= 0)"])

# ------------------------------------- take the army away from the stock AI
rule(["(up-compare-goal ov-phase c:>= 1)"], [
    "(set-strategic-number sn-number-attack-groups 0)",
    "(set-strategic-number sn-disable-attack-groups 1)",
    "(set-strategic-number sn-task-ungrouped-soldiers 0)",
    "(set-strategic-number sn-disable-defend-groups ov-defend-flags)",
    "(set-strategic-number sn-number-tasked-units 0)",
    "(set-strategic-number sn-enable-patrol-attack 1)",
], "coalition running: no stock attack groups, town-spreading or far defend-assists")

# ------------------------------------------- army management (pop space)
rule([*CMD, "(population-headroom < ov-cart-headroom)",
      "(up-idle-unit-count ov-idle-trade-cart >= 1)"],
     ["(up-delete-idle-units ov-idle-trade-cart)"],
     "at the pop cap, idle trade carts give their population to soldiers")

# ------------------------------------------------------- gather: orders
GATHER_ON = [TICK, f"(up-compare-goal ov-phase c:== {GATHER})", "(up-compare-goal ov-rally-x c:> 0)"]

out.append(";;; ---------- GATHER: everyone marches to the rally point")
rule(GATHER_ON + ["(up-compare-goal ov-slow c:== 0)"], [
    "(up-full-reset-search)", "(up-filter-include ov-cmdid-military -1 -1 -1)",
    "(up-set-target-point ov-rally-x)", "(up-filter-distance c: -1 c: ov-near-dist)",
    "(up-find-local c: ov-all-units c: 240)", "(up-get-search-state ov-ss)",
    "(up-modify-goal ov-needed g:= ov-army)", "(up-modify-goal ov-needed c:* ov-ready-pct)",
    "(up-modify-goal ov-needed c:/ 100)", "(up-modify-goal ov-needed c:min ov-ready-cap)",
], "count my soldiers at the rally point")
rule(GATHER_ON + ["(up-compare-goal ov-slow c:== 0)", "(up-compare-goal ov-army c:>= ov-min-army)",
                  "(up-compare-goal ov-ss g:>= ov-needed)", "(up-compare-goal ov-pulses c:>= 1)"],
     [*per_player_slot(READY), "(up-set-shared-goal g: ov-idx c: 1)"],
     "enough of my army is assembled: report ready")
army(GATHER_ON + ["(up-compare-goal ov-regroup-first c:== 1)"], "ov-rally-x", "ov-near-dist", -1, [],
     "ov-rally-x", "ov-act-move", "ov-march-formation",
     "regroup: everyone falls back, plain move, even mid-fight")
army(GATHER_ON + ["(up-compare-goal ov-regroup-first c:== 0)", "(up-compare-goal ov-slow c:== 0)"],
     "ov-rally-x", "ov-arrived-dist", -1, [NOT_FIGHTING],
     "ov-rally-x", "ov-act-attack-move", "ov-march-formation",
     "march pulse: every soldier not fighting and not there yet")
army(GATHER_ON + ["(up-compare-goal ov-regroup-first c:== 0)", "(up-compare-goal ov-slow c:!= 0)"],
     "ov-rally-x", "ov-near-dist", -1, [ONLY_IDLE],
     "ov-rally-x", "ov-act-attack-move", "ov-march-formation",
     "between pulses: idle soldiers away from the rally get moving again")
rule([TICK, f"(up-compare-goal ov-phase c:== {GATHER})", "(up-compare-goal ov-slow c:== 0)"],
     ["(up-modify-goal ov-pulses c:+ 1)", "(up-modify-goal ov-regroup-first c:= 0)"])

# ------------------------------------------------------- attack: orders
ATTACK_ON = [TICK, f"(up-compare-goal ov-phase c:== {ATTACK})", "(up-compare-goal ov-tgt-x c:> 0)"]
LAUNCH = ATTACK_ON + ["(up-compare-goal ov-launch c:== 1)"]
REINFORCE = ATTACK_ON + ["(up-compare-goal ov-launch c:== 0)", "(up-compare-goal ov-reinforce c:== 0)"]
STEADY = ATTACK_ON + ["(up-compare-goal ov-launch c:== 0)", "(up-compare-goal ov-reinforce c:!= 0)"]

out.append(";;; ---------- ATTACK: launch, reinforce in groups, keep idle soldiers moving")
army(LAUNCH, "ov-tgt-x", -1, "ov-launch-radius", [NOT_FIGHTING],
     "ov-tgt-x", "ov-act-attack-move", "ov-attack-formation",
     "launch: the whole army near the target goes in as one formation")
army(LAUNCH, "ov-tgt-x", "ov-launch-radius", -1, [NOT_FIGHTING, *OUTSIDE_RALLY_ARRIVED],
     "ov-rally-x", "ov-act-move", "ov-march-formation",
     "launch: soldiers still far away head to the rally point")
rule(LAUNCH, ["(up-modify-goal ov-launch c:= 0)"])
army(REINFORCE, "ov-rally-x", -1, "ov-near-dist", [NOT_FIGHTING],
     "ov-tgt-x", "ov-act-attack-move", "ov-attack-formation",
     "reinforce: everyone waiting at the rally goes in together")
army(REINFORCE, "ov-tgt-x", "ov-launch-radius", -1, [NOT_FIGHTING, *OUTSIDE_RALLY_ARRIVED],
     "ov-rally-x", "ov-act-move", "ov-march-formation",
     "reinforce: new soldiers from home head to the rally point")
army(STEADY, "ov-tgt-x", -1, "ov-launch-radius", [ONLY_IDLE, *OUTSIDE_RALLY_NEAR],
     "ov-tgt-x", "ov-act-attack-move", "ov-attack-formation",
     "every tick: idle soldiers in the fight (not those waiting at the rally) push on")
army(STEADY, "ov-tgt-x", "ov-launch-radius", -1, [ONLY_IDLE, *OUTSIDE_RALLY_ARRIVED],
     "ov-rally-x", "ov-act-move", "ov-march-formation",
     "every tick: idle soldiers far away head to the rally point")

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

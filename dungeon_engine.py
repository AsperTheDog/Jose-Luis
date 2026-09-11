from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Optional

DATA_PATH = "dungeon_data.json"

OFFENSIVE_TAGS = {"BURN", "BLEED", "POISON", "STUN", "CHILL", "WEAKEN", "VULNERABLE", "MARK", "CURSE"}
DEFENSIVE_TAGS = {"RAGE", "FORTIFY", "REGEN", "HASTE", "THORNS"}


def load_data(path: str = DATA_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def progress_bar(current: int, maximum: int, size: int = 10, fill: str = "█", empty: str = "░") -> str:
    maximum = max(1, int(maximum))
    current = max(0, min(int(current), maximum))
    filled = int(round(size * current / maximum))
    return fill * filled + empty * (size - filled)


def fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> Optional[str]:
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return None
    roll = rng.uniform(0, total)
    upto = 0.0
    for key, weight in weights.items():
        upto += max(0.0, weight)
        if roll <= upto:
            return key
    return next(iter(weights))


@dataclass
class StatusInstance:
    tag: str
    stacks: int = 1
    turns: int = 1
    power: int = 0

    def to_dict(self) -> dict:
        return {"tag": self.tag, "stacks": self.stacks, "turns": self.turns, "power": self.power}

    @classmethod
    def from_dict(cls, payload: dict) -> "StatusInstance":
        return cls(
            tag=payload["tag"],
            stacks=int(payload.get("stacks", 1)),
            turns=int(payload.get("turns", 1)),
            power=int(payload.get("power", 0)),
        )


@dataclass
class Combatant:
    name: str
    emoji: str
    max_hp: int
    hp: int
    attack: int
    defense: int
    max_energy: int = 0
    energy: int = 0
    shield: int = 0
    crit: float = 0.0
    dodge: float = 0.0
    statuses: dict[str, StatusInstance] = field(default_factory=dict)
    defending: bool = False
    is_boss: bool = False
    archetype: str = ""
    enrage: float = 0.0
    phase: int = 0
    phase_name: str = ""
    mods: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "emoji": self.emoji,
            "max_hp": self.max_hp,
            "hp": self.hp,
            "attack": self.attack,
            "defense": self.defense,
            "max_energy": self.max_energy,
            "energy": self.energy,
            "shield": self.shield,
            "crit": self.crit,
            "dodge": self.dodge,
            "statuses": {tag: instance.to_dict() for tag, instance in self.statuses.items()},
            "defending": self.defending,
            "is_boss": self.is_boss,
            "archetype": self.archetype,
            "enrage": self.enrage,
            "phase": self.phase,
            "phase_name": self.phase_name,
            "mods": self.mods,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Combatant":
        return cls(
            name=payload["name"],
            emoji=payload.get("emoji", ""),
            max_hp=int(payload["max_hp"]),
            hp=int(payload["hp"]),
            attack=int(payload["attack"]),
            defense=int(payload.get("defense", 0)),
            max_energy=int(payload.get("max_energy", 0)),
            energy=int(payload.get("energy", 0)),
            shield=int(payload.get("shield", 0)),
            crit=float(payload.get("crit", 0.0)),
            dodge=float(payload.get("dodge", 0.0)),
            statuses={tag: StatusInstance.from_dict(data) for tag, data in payload.get("statuses", {}).items()},
            defending=bool(payload.get("defending", False)),
            is_boss=bool(payload.get("is_boss", False)),
            archetype=payload.get("archetype", ""),
            enrage=float(payload.get("enrage", 0.0)),
            phase=int(payload.get("phase", 0)),
            phase_name=payload.get("phase_name", ""),
            mods=payload.get("mods", []),
        )


@dataclass
class BattleState:
    floor: int
    stage: str
    player: Combatant
    enemy: Combatant
    player_level: int = 1
    is_boss: bool = False
    is_anomaly: bool = False
    anomaly_id: Optional[str] = None
    training: bool = False
    farm: bool = False
    turn: int = 0
    potions: int = 0
    log: list[str] = field(default_factory=list)
    cooldowns: dict[str, int] = field(default_factory=dict)
    damage_dealt: int = 0
    damage_taken: int = 0
    bonus_gold: int = 0
    bonus_xp: int = 0
    rewards: dict = field(default_factory=dict)
    seed: int = 0
    shifts: list[str] = field(default_factory=list)
    skill_id: str = "golpe_pesado"
    no_potions: bool = False
    mutations: dict = field(default_factory=dict)
    echoes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "floor": self.floor,
            "stage": self.stage,
            "player": self.player.to_dict(),
            "enemy": self.enemy.to_dict(),
            "player_level": self.player_level,
            "is_boss": self.is_boss,
            "is_anomaly": self.is_anomaly,
            "anomaly_id": self.anomaly_id,
            "training": self.training,
            "farm": self.farm,
            "turn": self.turn,
            "potions": self.potions,
            "log": self.log[-60:],
            "cooldowns": self.cooldowns,
            "damage_dealt": self.damage_dealt,
            "damage_taken": self.damage_taken,
            "bonus_gold": self.bonus_gold,
            "bonus_xp": self.bonus_xp,
            "rewards": self.rewards,
            "seed": self.seed,
            "shifts": self.shifts,
            "skill_id": self.skill_id,
            "no_potions": self.no_potions,
            "mutations": self.mutations,
            "echoes": self.echoes,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BattleState":
        return cls(
            floor=int(payload["floor"]),
            stage=payload.get("stage", "active"),
            player=Combatant.from_dict(payload["player"]),
            enemy=Combatant.from_dict(payload["enemy"]),
            player_level=int(payload.get("player_level", 1)),
            is_boss=bool(payload.get("is_boss", False)),
            is_anomaly=bool(payload.get("is_anomaly", False)),
            anomaly_id=payload.get("anomaly_id"),
            training=bool(payload.get("training", False)),
            farm=bool(payload.get("farm", False)),
            turn=int(payload.get("turn", 0)),
            potions=int(payload.get("potions", 0)),
            log=list(payload.get("log", [])),
            cooldowns=dict(payload.get("cooldowns", {})),
            damage_dealt=int(payload.get("damage_dealt", 0)),
            damage_taken=int(payload.get("damage_taken", 0)),
            bonus_gold=int(payload.get("bonus_gold", 0)),
            bonus_xp=int(payload.get("bonus_xp", 0)),
            rewards=dict(payload.get("rewards", {})),
            seed=int(payload.get("seed", 0)),
            shifts=list(payload.get("shifts", [])),
            skill_id=payload.get("skill_id", "golpe_pesado"),
            no_potions=bool(payload.get("no_potions", False)),
            mutations=dict(payload.get("mutations", {})),
            echoes=dict(payload.get("echoes", {})),
        )


class Runtime:
    def __init__(self, engine: "DungeonEngine", state: BattleState, rng: random.Random):
        self.engine = engine
        self.state = state
        self.rng = rng
        self.events: dict[str, Any] = {}
        self.depth = 0

    def log(self, message: str) -> None:
        self.state.log.append(message)


class DungeonEngine:
    def __init__(self, data: Optional[dict] = None):
        self.data = data if data is not None else load_data()
        self.cfg = self.data["config"]

    def enemy_max_hp(self, floor: int) -> int:
        return max(1, int(self.cfg["enemy_hp_base"] * self.cfg["enemy_hp_growth"] ** floor))

    def enemy_attack(self, floor: int) -> int:
        return max(1, int(self.cfg["enemy_dmg_base"] * self.cfg["enemy_dmg_growth"] ** floor))

    def enemy_defense(self, floor: int) -> int:
        return max(0, int(self.cfg["enemy_def_base"] * self.cfg["enemy_def_growth"] ** floor))

    def level_xp_needed(self, level: int) -> int:
        return max(1, int(self.cfg["level_xp_base"] * level ** self.cfg["level_xp_exponent"]))

    def xp_multiplier(self, level: int, floor: int) -> float:
        delta = level - floor
        if delta <= 0:
            return 1.0
        return max(0.05, 1.0 - 0.20 * delta)

    def xp_reward(self, floor: int, level: int) -> int:
        base = self.cfg["xp_base"] * self.cfg["xp_growth"] ** floor
        return max(1, int(base * self.xp_multiplier(level, floor)))

    def gold_reward(self, floor: int) -> int:
        return max(1, int(self.cfg["gold_base"] * self.cfg["gold_growth"] ** floor))

    def dust_for(self, floor: int) -> int:
        if floor <= 0:
            return 0
        return int((floor / self.cfg["dust_divisor"]) ** self.cfg["dust_exponent"])

    def conversion_cap(self, tier: int) -> int:
        tier = max(1, int(tier))
        cap = self.cfg["conversion_cap_base"] * self.cfg["conversion_cap_growth"] ** (tier - 1)
        return int(min(self.cfg["conversion_cap_max"], cap))

    def potion_price(self, level: int) -> int:
        return int(self.cfg["potion_price_base"] * self.cfg["potion_price_growth"] ** max(0, level - 1))

    def upgrade_cost(self, key: str, current_level: int) -> int:
        spec = self.data["upgrades"][key]
        return int(spec["cost"] * spec["growth"] ** current_level)

    def gain_xp(self, level: int, xp: int, amount: int) -> tuple[int, int, int]:
        xp += max(0, int(amount))
        gained = 0
        while xp >= self.level_xp_needed(level):
            xp -= self.level_xp_needed(level)
            level += 1
            gained += 1
        return level, xp, gained

    def boss_tier_for_floor(self, floor: int) -> int:
        interval = self.cfg["boss_interval"]
        return max(1, floor // interval)

    def is_gate_floor(self, floor: int) -> bool:
        return floor > 0 and floor % self.cfg["boss_interval"] == 0

    def boss_coins_for_tier(self, tier: int) -> int:
        return self.cfg["boss_coin_per_tier"] * max(1, tier)

    def skill_cost(self, skill: dict, shift_effects: Optional[dict] = None) -> int:
        mult = (shift_effects or {}).get("skill_cost_mult", 1.0)
        return int(skill["cost"] * mult)

    def available_skills(self, level: int) -> list[dict]:
        return [skill for skill in self.data["skills"] if skill["level"] <= level]

    def get_skill(self, skill_id: str) -> Optional[dict]:
        for skill in self.data["skills"]:
            if skill["id"] == skill_id:
                return skill
        return None

    def mutation_level(self, mutations: dict, mutation_id: str) -> int:
        entry = mutations.get(mutation_id)
        if not entry:
            return 0
        return int(entry.get("level", 0) if isinstance(entry, dict) else entry)

    def shift_effects(self, shift_ids: list[str]) -> dict:
        effects = {
            "enemy_dmg_mult": 1.0,
            "loot_mult": 1.0,
            "gold_mult": 1.0,
            "xp_mult": 1.0,
            "loot_chance": 0.0,
            "skill_cost_mult": 1.0,
            "attack_mult": 1.0,
            "max_hp_mult": 1.0,
            "no_potions": False,
            "random_status": False,
            "double_strike": 0,
        }
        for shift_id in shift_ids:
            spec = self.data["shifts"].get(shift_id)
            if not spec:
                continue
            for key in list(effects.keys()):
                if key == "loot_chance":
                    continue
                if key in spec:
                    if isinstance(effects[key], bool) or isinstance(spec[key], bool):
                        effects[key] = bool(spec[key]) or effects[key]
                    elif isinstance(effects[key], int) and not isinstance(effects[key], bool) and key == "double_strike":
                        effects[key] = max(effects[key], int(spec[key]))
                    elif isinstance(effects[key], float):
                        effects[key] *= spec[key]
                    else:
                        effects[key] = spec[key]
            effects["loot_chance"] += spec.get("loot_chance", 0.0)
        return effects

    def _roll_rarity(self, rng: random.Random, floor: int, bonus: float = 0.0) -> str:
        weights: dict[str, float] = {}
        for index, (key, spec) in enumerate(self.data["rarities"].items()):
            weights[key] = spec["weight"] * (1.0 + (floor * 0.012 + bonus) * index)
        return _weighted_choice(rng, weights) or "comun"

    def generate_item(self, rng: random.Random, floor: int, rarity: Optional[str] = None, sockets_bonus: int = 0, rarity_bonus: float = 0.0) -> dict:
        rarity = rarity or self._roll_rarity(rng, floor, rarity_bonus)
        rarity_spec = self.data["rarities"][rarity]
        slot = rng.choice(list(self.data["gear_slots"].keys()))
        slot_spec = self.data["gear_slots"][slot]
        prefix = rng.choice(self.data["prefixes"])
        base = rng.choice(slot_spec["bases"])
        weights = slot_spec["stats"]
        mult = 0.75 + 0.25 * float(rarity_spec["stat_mult"])

        stats = {
            "attack": int(self.cfg["gear_attack_base"] * weights.get("attack", 0.0) * mult * self.cfg["gear_attack_growth"] ** floor),
            "defense": int(self.cfg["gear_defense_base"] * weights.get("defense", 0.0) * mult * self.cfg["gear_defense_growth"] ** floor),
            "max_hp": int(self.cfg["gear_hp_base"] * weights.get("max_hp", 0.0) * mult * self.cfg["gear_hp_growth"] ** floor),
            "max_energy": int(self.cfg["gear_energy_base"] * weights.get("max_energy", 0.0) * mult * self.cfg["gear_energy_growth"] ** floor),
            "crit": round(self.cfg["gear_crit_mult"] * weights.get("crit", 0.0) * mult, 4),
        }
        stats = {key: value for key, value in stats.items() if value}

        socket_count = max(0, int(rarity_spec["sockets"]) + int(sockets_bonus))
        sockets = [self.generate_mod(rng, rarity_spec["power"], floor) for _ in range(socket_count)]

        return {
            "item_uid": f"{rng.getrandbits(48):012x}",
            "name": f"{prefix} {base}",
            "slot": slot,
            "rarity": rarity,
            "stats": stats,
            "sockets": sockets,
            "floor_found": floor,
        }

    def generate_mod(self, rng: random.Random, power: float, floor: int) -> dict:
        triggers = self.data["enabled_triggers"]
        weights = {name: self.data["trigger_weights"].get(name, 1) for name in triggers}
        trigger = _weighted_choice(rng, weights) or "ON_ATTACK"

        mod: dict = {"on": trigger}
        if rng.random() < 0.5:
            mod["if"] = self.generate_condition(rng)
        mod["then"] = self.generate_effect(rng, power, floor)
        return mod

    def generate_condition(self, rng: random.Random) -> dict:
        templates = self.data["condition_templates"]
        names = [name for name in self.data["enabled_conditions"] if name in templates]
        weights = {name: templates[name].get("weight", 1) for name in names}
        ctype = _weighted_choice(rng, weights) or "ALWAYS"
        template = templates.get(ctype, {})

        if ctype == "HP_BELOW":
            return {"type": ctype, "target": "self", "pct": rng.randint(template["pct_min"], template["pct_max"])}
        if ctype == "HP_ABOVE":
            return {"type": ctype, "target": "self", "pct": rng.randint(template["pct_min"], template["pct_max"])}
        if ctype == "FOE_HP_BELOW":
            return {"type": "HP_BELOW", "target": "foe", "pct": rng.randint(template["pct_min"], template["pct_max"])}
        if ctype in ("ENERGY_BELOW", "ENERGY_ABOVE"):
            return {"type": ctype, "target": "self", "pct": rng.randint(template["pct_min"], template["pct_max"])}
        if ctype in ("SHIELD_ABOVE", "SHIELD_BELOW"):
            return {"type": ctype, "target": "self", "pct": rng.randint(template["pct_min"], template["pct_max"])}
        if ctype == "IS_CRITICAL":
            return {"type": "IS_CRITICAL"}
        if ctype in ("TARGET_HAS_STATUS", "SELF_HAS_STATUS"):
            tag = rng.choice(sorted(DEFENSIVE_TAGS | OFFENSIVE_TAGS))
            target = "foe" if ctype == "TARGET_HAS_STATUS" else "self"
            return {"type": "HAS_STATUS", "target": target, "tag": tag}
        if ctype == "STATUS_STACKS_ABOVE":
            return {"type": "HAS_STATUS", "target": "foe", "tag": rng.choice(sorted(OFFENSIVE_TAGS)), "stacks": rng.randint(template["value_min"], template["value_max"])}
        if ctype == "RANDOM":
            return {"type": "RANDOM", "chance": round(rng.uniform(template["chance_min"], template["chance_max"]), 2)}
        if ctype == "TURN_ABOVE":
            return {"type": "TURN_ABOVE", "value": rng.randint(template["value_min"], template["value_max"])}
        if ctype == "FLOOR_ABOVE":
            return {"type": "FLOOR_ABOVE", "value": rng.randint(template["value_min"], template["value_max"])}
        return {"type": "ALWAYS"}

    def generate_effect(self, rng: random.Random, power: float, floor: int) -> dict:
        templates = self.data["effect_templates"]
        names = [name for name in self.data["enabled_effects"] if name in templates]
        weights = {name: templates[name].get("weight", 1) for name in names}
        etype = _weighted_choice(rng, weights) or "DEAL_DAMAGE"
        template = templates[etype]

        if etype == "DEAL_DAMAGE":
            ratio = rng.uniform(template["ratio_min"], template["ratio_max"]) * power
            return {"type": etype, "target": "foe", "ratio": round(ratio, 2),
                    "damage_type": rng.choice(template["types"])}
        if etype == "APPLY_STATUS":
            tag = rng.choice(template["tags"])
            target = "foe" if tag in OFFENSIVE_TAGS else "self"
            return {"type": "APPLY_STATUS", "target": target, "tag": tag,
                    "stacks": rng.randint(template["stacks_min"], template["stacks_max"]),
                    "turns": rng.randint(template["turns_min"], template["turns_max"])}
        if etype == "BUFF_SELF":
            return {"type": "APPLY_STATUS", "target": "self", "tag": rng.choice(template["tags"]),
                    "stacks": 1, "turns": int(template["turns"])}
        if etype == "GAIN_SHIELD":
            return {"type": etype, "target": "self", "ratio": round(rng.uniform(template["ratio_min"], template["ratio_max"]) * power, 2)}
        if etype == "HEAL_HP":
            return {"type": etype, "target": "self", "ratio": round(rng.uniform(template["ratio_min"], template["ratio_max"]) * power, 2)}
        if etype in ("REFUND_ENERGY", "STEAL_ENERGY"):
            target = "self" if etype == "REFUND_ENERGY" else "foe"
            return {"type": etype, "target": target, "value": rng.randint(template["value_min"], template["value_max"])}
        if etype == "LIFESTEAL":
            return {"type": etype, "target": "self", "ratio": round(rng.uniform(template["ratio_min"], template["ratio_max"]), 2)}
        if etype == "PURGE_STATUS":
            return {"type": etype, "target": "foe", "tag": rng.choice(template["tags"])}
        if etype == "CLEANSE":
            return {"type": etype, "target": "self", "value": rng.randint(template["value_min"], template["value_max"])}
        if etype == "GAIN_GOLD":
            value = int(rng.randint(template["value_min"], template["value_max"]) * self.cfg["gold_growth"] ** (floor * 0.5))
            return {"type": etype, "target": "self", "value": value}
        if etype == "GRANT_XP":
            return {"type": etype, "target": "self", "value": rng.randint(template["value_min"], template["value_max"])}
        if etype == "EXECUTE":
            return {"type": etype, "target": "foe", "pct": round(rng.uniform(template["pct_min"], template["pct_max"]), 2)}
        if etype == "REFLECT":
            return {"type": "APPLY_STATUS", "target": "self", "tag": "THORNS", "stacks": 1, "turns": 3}
        if etype == "EXTRA_TURN":
            return {"type": etype, "target": "self", "chance": template["chance"]}
        return {"type": "DEAL_DAMAGE", "target": "foe", "ratio": round(power, 2), "damage_type": "fisico"}

    @staticmethod
    def _parse_json(value: Any, fallback: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback

    def equipped_items(self, items: list[dict]) -> list[dict]:
        return [item for item in items if item.get("is_equipped")]

    def item_mods(self, item: dict, mutations: dict) -> list[dict]:
        sockets = list(self._parse_json(item.get("sockets"), []))
        extra = self.mutation_level(mutations, "quantum_sockets")
        floor = int(item.get("floor_found", 1))
        power = self.data["rarities"].get(item.get("rarity", "comun"), {}).get("power", 1.0)
        for index in range(extra):
            seeded = random.Random(f"{item.get('item_uid', '?')}:xsocket:{index}")
            sockets.append(self.generate_mod(seeded, power, floor))
        return [mod for mod in sockets if isinstance(mod, dict)]

    def echo_multiplier(self, echoes: dict, key: str) -> float:
        total = 1.0
        for echo_id, level in (echoes or {}).items():
            spec = self.data["echoes"].get(echo_id)
            if spec and key in spec and level:
                total *= 1.0 + float(spec[key]) * int(level)
        return total

    def echo_flat(self, echoes: dict, key: str) -> float:
        total = 0.0
        for echo_id, level in (echoes or {}).items():
            spec = self.data["echoes"].get(echo_id)
            if spec and key in spec and level:
                total += float(spec[key]) * int(level)
        return total

    def player_stats(self, user: dict, items: list[dict], mutations: dict, echoes: Optional[dict] = None) -> dict:
        cfg = self.cfg
        level = max(1, int(user.get("level", 1)))
        upgrades = self._parse_json(user.get("upgrades"), {})
        echoes = echoes or {}

        attack_level = min(cfg["level_cap_attack"], 1.0 + cfg["level_attack_mult"] * (level - 1))
        hp_level = min(cfg["level_cap_hp"], 1.0 + cfg["level_hp_mult"] * (level - 1))
        defense_level = min(cfg["level_cap_defense"], 1.0 + cfg["level_defense_mult"] * (level - 1))

        base_attack = cfg["player_base_attack"] + level * cfg["player_attack_per_level"]
        base_attack += int(upgrades.get("attack", 0)) * cfg["attack_upgrade_per_level"]
        base_defense = cfg["player_base_defense"] + level * cfg["player_defense_per_level"]
        base_defense += int(upgrades.get("defense", 0)) * cfg["defense_upgrade_per_level"]
        base_hp = cfg["player_base_hp"] + level * cfg["player_hp_per_level"]
        base_hp += int(upgrades.get("vitality", 0)) * cfg["vitality_upgrade_per_level"]
        base_energy = cfg["player_base_energy"] + int(upgrades.get("energy", 0)) * cfg["energy_upgrade_per_level"]
        crit = cfg["crit_chance_base"] + int(upgrades.get("crit", 0)) * cfg["crit_upgrade_per_level"]
        crit += cfg["level_crit_per_level"] * (level - 1)

        gear_attack = gear_defense = gear_hp = gear_energy = 0
        mods: list[dict] = []
        for item in self.equipped_items(items):
            stats = self._parse_json(item.get("stats"), {})
            gear_attack += int(stats.get("attack", 0))
            gear_defense += int(stats.get("defense", 0))
            gear_hp += int(stats.get("max_hp", 0))
            gear_energy += int(stats.get("max_energy", 0))
            crit += float(stats.get("crit", 0.0))
            mods.extend(self.item_mods(item, mutations))

        attack = (base_attack + gear_attack) * attack_level * self.echo_multiplier(echoes, "attack_mult")
        defense = (base_defense + gear_defense) * defense_level
        max_hp = (base_hp + gear_hp) * hp_level * self.echo_multiplier(echoes, "hp_mult")
        max_energy = base_energy + gear_energy
        crit += self.echo_flat(echoes, "crit")

        return {
            "attack": int(attack),
            "defense": int(defense),
            "max_hp": int(max_hp),
            "max_energy": int(max_energy),
            "crit": float(min(cfg["crit_cap"], crit)),
            "mods": mods,
        }

    def make_player(self, user: dict, items: list[dict], mutations: dict, shift_effects: dict,
                    echoes: Optional[dict] = None) -> Combatant:
        stats = self.player_stats(user, items, mutations, echoes)
        attack = int(stats["attack"] * shift_effects.get("attack_mult", 1.0))
        max_hp = max(1, int(stats["max_hp"] * shift_effects.get("max_hp_mult", 1.0)))
        return Combatant(
            name=user.get("name") or "Aventurero",
            emoji="🧙",
            max_hp=max_hp,
            hp=max_hp,
            attack=max(1, attack),
            defense=stats["defense"],
            max_energy=stats["max_energy"],
            energy=stats["max_energy"],
            crit=stats["crit"],
            dodge=self.cfg["dodge_base"],
            mods=stats["mods"],
        )

    def make_enemy(self, floor: int, rng: random.Random, extra_mods: Optional[list[dict]] = None) -> Combatant:
        candidates = [a for a in self.data["enemy_archetypes"] if a["floor_min"] <= floor <= a["floor_max"]]
        if not candidates:
            candidates = self.data["enemy_archetypes"]
        archetype = rng.choices(candidates, weights=[a.get("weight", 10) for a in candidates], k=1)[0]
        max_hp = max(1, int(self.enemy_max_hp(floor) * archetype["hp"]))
        enemy = Combatant(
            name=archetype["name"],
            emoji=archetype["emoji"],
            max_hp=max_hp,
            hp=max_hp,
            attack=max(1, int(self.enemy_attack(floor) * archetype["dmg"])),
            defense=int(self.enemy_defense(floor) * archetype.get("def", 1.0)),
            crit=0.05,
            dodge=0.02,
            archetype=archetype["id"],
            mods=list(archetype.get("mods", [])),
        )
        if extra_mods:
            enemy.mods.extend(extra_mods)
        return enemy

    def make_boss(self, tier: int, rng: random.Random) -> Combatant:
        floor = tier * self.cfg["boss_interval"]
        bosses = self.data["bosses"]
        spec = bosses[(tier - 1) % len(bosses)]
        hp = int(self.enemy_max_hp(floor) * spec["hp_mult"] * (1 + self.cfg["boss_hp_tier_growth"] * (tier - 1)))
        boss = Combatant(
            name=spec["name"],
            emoji=spec["emoji"],
            max_hp=max(1, hp),
            hp=max(1, hp),
            attack=max(1, int(self.enemy_attack(floor) * spec["dmg_mult"])),
            defense=int(self.enemy_defense(floor) * 1.2),
            crit=0.08,
            dodge=0.0,
            is_boss=True,
            archetype=spec["id"],
            phase=0,
            phase_name=spec["phases"][0]["name"],
            mods=list(spec["phases"][0].get("mods", [])),
        )
        return boss

    def boss_phases(self, enemy: Combatant) -> list[dict]:
        if not enemy.is_boss:
            return []
        for spec in self.data["bosses"]:
            if spec["id"] == enemy.archetype:
                return spec["phases"]
        return []

    def grant_shield(self, rt: Runtime, combatant: Combatant, amount: int) -> int:
        amount = max(1, int(amount))
        if combatant.is_boss:
            amount = min(amount, int(0.5 * rt.events.get("last_damage", 0)) + 1)
        combatant.shield += amount
        return amount

    def apply_boss_phase(self, rt: Runtime) -> None:
        state = rt.state
        enemy = state.enemy
        phases = self.boss_phases(enemy)
        if not phases:
            return
        fraction = enemy.hp / max(1, enemy.max_hp)
        index = 0
        for position, phase in enumerate(phases):
            if fraction <= phase["min_hp"]:
                index = position
        phase = phases[index]

        if index != enemy.phase:
            enemy.phase = index
            enemy.phase_name = phase.get("name", enemy.phase_name)
            rt.log(f"⚡ **{enemy.emoji} {enemy.name}** cambia de postura: **{enemy.phase_name}**")
            enemy.shield += int(enemy.max_hp * 0.15)
            self.fire(rt, "ON_BOSS_PHASE", state.player.mods, state.player)

        enemy.enrage = float(phase.get("enrage", 0.0))
        shield_ratio = phase.get("shield_ratio", 0.0)
        if shield_ratio:
            self.grant_shield(rt, enemy, int(enemy.max_hp * shield_ratio))
        heal_ratio = phase.get("heal_ratio", 0.0)
        if heal_ratio:
            healed = int(enemy.max_hp * heal_ratio)
            enemy.hp = min(enemy.max_hp, enemy.hp + healed)
            rt.log(f"💚 **{enemy.name}** se regenera **{fmt_int(healed)}** PV.")

    @staticmethod
    def resolve_target(state: BattleState, actor: Combatant, name: str) -> Combatant:
        if name == "self":
            return actor
        return state.enemy if actor is state.player else state.player

    def has_status(self, combatant: Combatant, tag: str) -> bool:
        return tag in combatant.statuses

    def _sum_status(self, combatant: Combatant, key: str) -> float:
        total = 0.0
        for instance in combatant.statuses.values():
            spec = self.data["statuses"].get(instance.tag)
            if not spec:
                continue
            total += float(spec.get(key, 0.0)) * instance.stacks
        return total

    def attack_multiplier(self, combatant: Combatant) -> float:
        return max(0.1, 1.0 + combatant.enrage + self._sum_status(combatant, "attack_mult"))

    def taken_multiplier(self, combatant: Combatant) -> float:
        return max(0.1, 1.0 + self._sum_status(combatant, "taken_mult"))

    def defense_value(self, combatant: Combatant) -> int:
        return max(0, int(combatant.defense * (1.0 + self._sum_status(combatant, "defense_mult"))))

    def dot_multiplier(self, combatant: Combatant) -> float:
        return max(0.1, 1.0 + self._sum_status(combatant, "dot_mult"))

    def heal_multiplier(self, combatant: Combatant) -> float:
        return max(0.0, 1.0 + self._sum_status(combatant, "heal_mult"))

    def crit_bonus(self, combatant: Combatant) -> float:
        return self._sum_status(combatant, "crit_bonus")

    def dodge_chance(self, combatant: Combatant) -> float:
        return min(0.6, combatant.dodge + self._sum_status(combatant, "dodge"))

    def reflect_ratio(self, combatant: Combatant) -> float:
        return min(0.9, self._sum_status(combatant, "reflect_ratio"))

    def energy_regen(self, combatant: Combatant) -> int:
        return self.cfg["player_energy_regen"] + int(self._sum_status(combatant, "energy_regen"))

    def eval_condition(self, rt: Runtime, cond: dict, actor: Combatant) -> bool:
        ctype = cond.get("type", "ALWAYS")
        if ctype == "ALWAYS":
            return True
        default_target = "foe" if ctype in ("TARGET_HAS_STATUS",) else "self"
        target = self.resolve_target(rt.state, actor, cond.get("target", default_target))
        state = rt.state

        if ctype in ("HP_BELOW", "HP_ABOVE"):
            pct = float(cond.get("pct", 50))
            current = target.hp / max(1, target.max_hp) * 100
            return current < pct if ctype == "HP_BELOW" else current > pct
        if ctype in ("ENERGY_BELOW", "ENERGY_ABOVE"):
            if target.max_energy <= 0:
                return False
            pct = float(cond.get("pct", 50))
            current = target.energy / max(1, target.max_energy) * 100
            return current < pct if ctype == "ENERGY_BELOW" else current > pct
        if ctype in ("SHIELD_ABOVE", "SHIELD_BELOW"):
            threshold = float(cond.get("value", 0))
            if "pct" in cond:
                threshold = target.max_hp * float(cond["pct"]) / 100.0
            return target.shield > threshold if ctype == "SHIELD_ABOVE" else target.shield < threshold
        if ctype == "IS_CRITICAL":
            return bool(rt.events.get("is_crit"))
        if ctype == "HAS_STATUS":
            instance = target.statuses.get(cond.get("tag", ""))
            if instance is None:
                return False
            return instance.stacks >= int(cond.get("stacks", 1))
        if ctype == "RANDOM":
            return rt.rng.random() < float(cond.get("chance", 0.0))
        if ctype == "TURN_ABOVE":
            return state.turn > int(cond.get("value", 0))
        if ctype == "FLOOR_ABOVE":
            return state.floor > int(cond.get("value", 0))
        return False

    def fire(self, rt: Runtime, trigger: str, mods: list[dict], actor: Combatant) -> None:
        if rt.depth > 8:
            return
        for mod in mods:
            if not isinstance(mod, dict) or mod.get("on") != trigger:
                continue
            effect = mod.get("then")
            if not isinstance(effect, dict):
                continue
            condition = mod.get("if")
            if condition and not self.eval_condition(rt, condition, actor):
                continue
            self.apply_effect(rt, actor, effect)

    def apply_effect(self, rt: Runtime, actor: Combatant, effect: dict) -> None:
        if rt.depth > 8:
            return
        rt.depth += 1
        try:
            self._apply_effect_inner(rt, actor, effect)
        finally:
            rt.depth -= 1

    def _apply_effect_inner(self, rt: Runtime, actor: Combatant, effect: dict) -> None:
        state = rt.state
        etype = effect.get("type", "")
        target = self.resolve_target(state, actor, effect.get("target", "foe"))

        if etype == "DEAL_DAMAGE":
            amount = int(actor.attack * float(effect.get("ratio", 0.5)))
            self.deal_damage(rt, actor, target, amount, effect.get("damage_type", "fisico"))
        elif etype == "APPLY_STATUS":
            tag = effect.get("tag", "")
            turns = int(effect["turns"]) if "turns" in effect else int(self.data["statuses"].get(tag, {}).get("turns", 2))
            self.apply_status(rt, actor, target, tag, int(effect.get("stacks", 1)), turns)
        elif etype == "GAIN_SHIELD":
            gained = self.grant_shield(rt, target, max(1, int(target.max_hp * float(effect.get("ratio", 0.1)))))
            rt.log(f"🛡️ **{target.name}** gana **{fmt_int(gained)}** de escudo.")
        elif etype == "HEAL_HP":
            heal = max(1, int(target.max_hp * float(effect.get("ratio", 0.1)) * self.heal_multiplier(target)))
            before = target.hp
            target.hp = min(target.max_hp, target.hp + heal)
            healed = target.hp - before
            if healed > 0:
                rt.log(f"💚 **{target.name}** recupera **{fmt_int(healed)}** PV.")
                self.fire(rt, "ON_HEAL", actor.mods, actor)
        elif etype == "REFUND_ENERGY":
            if actor.max_energy > 0:
                actor.energy = min(actor.max_energy, actor.energy + int(effect.get("value", 10)))
                self.fire(rt, "ON_ENERGY_GAIN", actor.mods, actor)
        elif etype == "STEAL_ENERGY":
            if target.max_energy > 0:
                stolen = min(target.energy, int(effect.get("value", 10)))
                target.energy -= stolen
                if actor.max_energy > 0:
                    actor.energy = min(actor.max_energy, actor.energy + stolen)
                if stolen:
                    rt.log(f"🔋 **{actor.name}** drena **{stolen}** de energía a **{target.name}**.")
        elif etype == "LIFESTEAL":
            damage = int(rt.events.get("last_damage", 0))
            heal = int(damage * float(effect.get("ratio", 0.1)) * self.heal_multiplier(actor))
            if heal > 0:
                before = actor.hp
                actor.hp = min(actor.max_hp, actor.hp + heal)
                if actor.hp > before:
                    rt.log(f"🩸 **{actor.name}** drena **{fmt_int(actor.hp - before)}** PV.")
                    self.fire(rt, "ON_HEAL", actor.mods, actor)
        elif etype == "PURGE_STATUS":
            tag = effect.get("tag", "")
            if tag in target.statuses:
                instance = target.statuses.pop(tag)
                rt.log(f"🧹 Se disipa **{self.data['statuses'].get(tag, {}).get('name', tag)}** ({instance.stacks}) de **{target.name}**.")
        elif etype == "CLEANSE":
            removed = 0
            for tag in list(target.statuses.keys()):
                if removed >= int(effect.get("value", 1)):
                    break
                spec = self.data["statuses"].get(tag, {})
                if spec.get("kind") in ("dot", "debuff", "control"):
                    target.statuses.pop(tag)
                    removed += 1
            if removed:
                rt.log(f"✨ **{target.name}** limpia **{removed}** estado(s) negativo(s).")
        elif etype == "GAIN_GOLD":
            value = int(effect.get("value", 0))
            state.bonus_gold += value
            rt.log(f"💰 Botín extra: **+{fmt_int(value)}** oro interno.")
        elif etype == "GRANT_XP":
            state.bonus_xp += int(effect.get("value", 0))
        elif etype == "EXECUTE":
            if target.hp / max(1, target.max_hp) <= float(effect.get("pct", 0.2)):
                amount = int(target.max_hp * float(effect.get("pct", 0.2)))
                rt.log(f"⚖️ **{actor.name}** ejecuta a **{target.name}**.")
                self.deal_damage(rt, actor, target, amount, "arcano", can_crit=False, pierce=True)
        elif etype == "EXTRA_TURN":
            if rt.rng.random() < float(effect.get("chance", 0.1)):
                rt.log(f"⚡ **{actor.name}** encadena un ataque extra.")
                self.basic_attack(rt, actor)

    def apply_status(self, rt: Runtime, source: Combatant, target: Combatant, tag: str,
                     stacks: int = 1, turns: int = 2, power: Optional[int] = None) -> None:
        spec = self.data["statuses"].get(tag)
        if not spec or stacks <= 0:
            return
        if tag == "SHIELD":
            target.shield += max(1, (power or source.attack) * stacks)
            return

        power = int(power if power is not None else max(1, source.attack))
        existing = target.statuses.get(tag)
        if existing:
            existing.stacks = min(int(spec.get("max_stacks", 99)), existing.stacks + stacks)
            existing.turns = max(existing.turns, turns)
            existing.power = max(existing.power, power)
        else:
            target.statuses[tag] = StatusInstance(tag=tag, stacks=min(int(spec.get("max_stacks", 99)), stacks),
                                                   turns=turns, power=power)
        rt.log(f"{spec.get('emoji', '')} **{target.name}** sufre **{spec['name']}** x{stacks} ({turns}t).")

        self.fire(rt, "ON_STATUS_APPLIED", source.mods, source)

        level = self.mutation_level(rt.state.mutations, "tag_transmutation") if hasattr(rt.state, "mutations") else 0
        if level > 0 and source is rt.state.player:
            links = self.data["mutations"]["tag_transmutation"]["links"][:level]
            for origin, linked in links:
                if origin == tag and linked not in target.statuses:
                    self.apply_status(rt, source, target, linked, stacks=1, turns=max(2, turns), power=power)
                    break

    def tick_statuses(self, rt: Runtime, owner: Combatant) -> None:
        state = rt.state
        applier = state.player if owner is state.enemy else state.enemy
        for tag, instance in list(owner.statuses.items()):
            spec = self.data["statuses"].get(tag, {})
            if spec.get("kind") == "dot":
                raw = instance.power * float(spec.get("dot_ratio", 0.3)) * instance.stacks * self.dot_multiplier(owner)
                if spec.get("low_hp_bonus") and owner.hp / max(1, owner.max_hp) < 0.35:
                    raw *= float(spec["low_hp_bonus"])
                damage = max(1, int(raw))
                self.fire(rt, "ON_STATUS_TICK", applier.mods, applier)
                self.deal_damage(rt, applier, owner, damage, spec.get("damage_type", "fisico"),
                                 can_crit=False, pierce=bool(spec.get("pierce")), apply_mods=False)
            elif spec.get("kind") == "buff" and spec.get("heal_ratio"):
                heal = int(owner.max_hp * float(spec["heal_ratio"]) * instance.stacks * self.heal_multiplier(owner))
                if heal > 0:
                    owner.hp = min(owner.max_hp, owner.hp + heal)

        for tag, instance in list(owner.statuses.items()):
            instance.turns -= 1
            if instance.turns <= 0:
                owner.statuses.pop(tag, None)

    def deal_damage(self, rt: Runtime, source: Combatant, target: Combatant, amount: int,
                    damage_type: str = "fisico", can_crit: bool = True, pierce: bool = False,
                    apply_mods: bool = True) -> int:
        if rt.depth > 10:
            return 0
        if amount <= 0 or target.hp <= 0:
            return 0
        rt.depth += 1
        try:
            is_dot = not apply_mods
            if not is_dot and rt.rng.random() < self.dodge_chance(target):
                rt.log(f"💨 **{target.name}** esquiva el ataque.")
                self.fire(rt, "ON_DODGE", target.mods, target)
                return 0

            is_crit = False
            if can_crit and not is_dot:
                chance = min(0.95, source.crit + self.crit_bonus(target))
                is_crit = rt.rng.random() < chance
                if is_crit:
                    amount = int(amount * self.cfg["crit_multiplier"])

            if apply_mods:
                amount = int(amount * self.attack_multiplier(source) * self.taken_multiplier(target))
            else:
                amount = int(amount * self.taken_multiplier(target))

            defense_effective = self.defense_value(target)
            scale = max(1, source.attack)
            reduction = defense_effective / (defense_effective + scale)
            if is_dot:
                reduction *= 0.5
            amount = max(1, int(amount * (1.0 - reduction)))

            if target.defending:
                amount = max(1, int(amount * self.cfg["defend_block"]))
                target.defending = False

            if not pierce and target.shield > 0:
                absorbed = min(target.shield, amount)
                target.shield -= absorbed
                amount -= absorbed
                if absorbed:
                    rt.log(f"🛡️ El escudo de **{target.name}** absorbe **{fmt_int(absorbed)}**.")
                if target.shield <= 0:
                    self.fire(rt, "ON_SHIELD_BREAK", target.mods, target)

            dealt = max(0, amount)
            if dealt > 0:
                target.hp -= dealt

            if source is rt.state.player:
                rt.state.damage_dealt += dealt
            elif target is rt.state.player:
                rt.state.damage_taken += dealt

            rt.events["last_damage"] = dealt
            rt.events["is_crit"] = is_crit
            crit_tag = " ¡CRÍTICO!" if is_crit else ""
            rt.log(f"{'🔪' if source is rt.state.player else '💥'} **{source.name}** golpea a **{target.name}** por **{fmt_int(dealt)}** ({damage_type}){crit_tag}.")

            if dealt > 0:
                if is_crit:
                    self.fire(rt, "ON_CRIT", source.mods, source)
                self.fire(rt, "ON_HIT_TAKEN", target.mods, target)
                if target.hp / max(1, target.max_hp) < 0.3:
                    self.fire(rt, "ON_LOW_HP", target.mods, target)
                reflect = self.reflect_ratio(target)
                if reflect > 0 and source.hp > 0:
                    reflected = max(1, int(dealt * reflect))
                    source.hp -= reflected
                    rt.log(f"🌵 **{target.name}** refleja **{fmt_int(reflected)}** de daño.")

            self.check_death(rt)
        finally:
            rt.depth -= 1
        return dealt

    def check_death(self, rt: Runtime) -> None:
        state = rt.state
        if state.stage != "active":
            return
        if state.enemy.hp <= 0:
            state.enemy.hp = 0
            state.stage = "victory"
            rt.log(f"☠️ **{state.enemy.name}** ha caído.")
            self.fire(rt, "ON_KILL", state.player.mods, state.player)
            self.fire(rt, "ON_BATTLE_END", state.player.mods, state.player)
            self.finalize(rt)
        elif state.player.hp <= 0:
            state.player.hp = 0
            state.stage = "defeat"
            rt.log("💀 Has caído en combate.")
            self.fire(rt, "ON_BATTLE_END", state.player.mods, state.player)

    def finalize(self, rt: Runtime) -> None:
        state = rt.state
        if state.rewards:
            return
        rng = rt.rng
        floor = state.floor
        level = state.player_level
        shifts = self.shift_effects(state.shifts)
        self.fire(rt, "ON_FLOOR_CLEAR", state.player.mods, state.player)
        gold = int(self.gold_reward(floor) * shifts.get("gold_mult", 1.0) * self.echo_multiplier(state.echoes, "gold_mult"))
        xp = int(self.xp_reward(floor, level) * shifts.get("xp_mult", 1.0))
        item = None
        coins = 0
        dust = 0

        if state.training:
            gold = int(gold * 0.25)
            xp = max(1, int(xp * 0.5))
        elif state.is_boss:
            gold *= 4
            xp *= 4
            coins = self.boss_coins_for_tier(self.boss_tier_for_floor(floor))
            item = self.generate_item(rng, floor, rarity_bonus=1.5)
        elif state.is_anomaly:
            spec = self.data["anomalies"].get(state.anomaly_id or "", {})
            level_bonus = 1.0 + float(self.data["mutations"]["alternative_floors"].get("reward_per_level", 0.35)) * max(0, self.mutation_level(state.mutations, "alternative_floors") - 1)
            gold = int(gold * spec.get("gold_mult", 1.0) * level_bonus)
            dust = int(spec.get("dust_reward", 0) * level_bonus * self.echo_multiplier(state.echoes, "dust_mult"))
            item = self.generate_item(rng, floor, sockets_bonus=int(spec.get("loot_bonus", 0) * level_bonus))
        else:
            drop_chance = min(self.cfg["drop_chance_max"], self.cfg["drop_chance_base"] + floor * self.cfg["drop_chance_per_floor"])
            drop_chance *= shifts.get("loot_mult", 1.0)
            drop_chance += shifts.get("loot_chance", 0.0)
            if rng.random() < drop_chance:
                item = self.generate_item(rng, floor)

        gold += state.bonus_gold
        xp += state.bonus_xp
        state.rewards = {"gold": max(0, int(gold)), "xp": max(0, int(xp)), "item": item, "coins": int(coins), "dust": int(dust), "floor": floor}

    def basic_attack(self, rt: Runtime, actor: Combatant) -> None:
        state = rt.state
        foe = self.resolve_target(state, actor, "foe")
        self.fire(rt, "ON_ATTACK", actor.mods, actor)
        self.deal_damage(rt, actor, foe, actor.attack, "fisico")

    def gain_shield(self, rt: Runtime, combatant: Combatant, ratio: float) -> None:
        gained = self.grant_shield(rt, combatant, int(combatant.max_hp * ratio))
        rt.log(f"🛡️ **{combatant.name}** se blinda con **{fmt_int(gained)}** de escudo.")

    def can_use_skill(self, state: BattleState, shift_effects: dict) -> tuple[bool, str]:
        skill = self.get_skill(state.skill_id)
        if not skill:
            return False, "No tienes una habilidad activa."
        if state.cooldowns.get(skill["id"], 0) > 0:
            return False, f"**{skill['name']}** está en enfriamiento ({state.cooldowns[skill['id']]} turnos)."
        cost = self.skill_cost(skill, shift_effects)
        if state.player.energy < cost:
            return False, f"Energía insuficiente: **{skill['name']}** cuesta {cost}⚡ (tienes {state.player.energy})."
        return True, ""

    def player_action(self, state: BattleState, action: str, shift_effects: Optional[dict] = None, rng: Optional[random.Random] = None) -> dict:
        if state.stage != "active":
            return {"ok": False, "reason": "El combate ya ha terminado."}
        shift_effects = shift_effects or self.shift_effects(state.shifts)
        rng = rng or random.Random()
        rt = Runtime(self, state, rng)

        if action == "flee":
            state.stage = "fled"
            rt.log("🏃 Te retiras del combate sin recompensas.")
            self.fire(rt, "ON_BATTLE_END", state.player.mods, state.player)
            return {"ok": True, "reason": ""}

        if action == "skill":
            usable, reason = self.can_use_skill(state, shift_effects)
            if not usable:
                return {"ok": False, "reason": reason}
        if action == "potion":
            if state.no_potions:
                blocker = next((self.data["shifts"][shift_id]["name"] for shift_id in state.shifts
                                if self.data["shifts"].get(shift_id, {}).get("no_potions")), None)
                label = f"**{blocker}**" if blocker else "Un desplazamiento dimensional"
                return {"ok": False, "reason": f"{label} te impide usar pociones."}
            if state.potions <= 0:
                return {"ok": False, "reason": "No te quedan pociones."}
            if state.player.hp >= state.player.max_hp:
                return {"ok": False, "reason": "Ya tienes la vida al máximo."}

        state.turn += 1
        rt.log(f"━━━ Turno {state.turn} ━━━")
        self.fire(rt, "ON_TURN_START", state.player.mods, state.player)

        if shift_effects.get("random_status"):
            tags = [tag for tag, spec in self.data["statuses"].items() if spec.get("kind") in ("dot", "debuff", "control")]
            self.apply_status(rt, state.enemy, state.player, rng.choice(tags), 1, 2)

        if action == "attack":
            self.basic_attack(rt, state.player)
        elif action == "defend":
            self.gain_shield(rt, state.player, self.cfg["defend_shield_ratio"])
            state.player.defending = True
            if state.player.max_energy > 0:
                state.player.energy = min(state.player.max_energy,
                                          state.player.energy + self.cfg["defend_energy"])
            self.fire(rt, "ON_DEFEND", state.player.mods, state.player)
            self.fire(rt, "ON_ENERGY_GAIN", state.player.mods, state.player)
        elif action == "skill":
            skill = self.get_skill(state.skill_id)
            cost = self.skill_cost(skill, shift_effects)
            state.player.energy = max(0, state.player.energy - cost)
            state.cooldowns[skill["id"]] = int(skill.get("cooldown", 0))
            rt.log(f"{skill.get('emoji', '✨')} Usas **{skill['name']}** (-{cost}⚡).")
            self.fire(rt, "ON_SKILL_USE", skill.get("mods", []), state.player)
        elif action == "potion":
            state.potions -= 1
            heal = int(state.player.max_hp * self.cfg["potion_heal_ratio"] * self.heal_multiplier(state.player))
            state.player.hp = min(state.player.max_hp, state.player.hp + max(1, heal))
            rt.log(f"🧪 Bebes una poción y recuperas **{fmt_int(max(1, heal))}** PV.")
            self.fire(rt, "ON_POTION_USE", state.player.mods, state.player)
            self.fire(rt, "ON_HEAL", state.player.mods, state.player)

        if state.stage == "active":
            self.enemy_turn(rt, shift_effects)
        if state.stage == "active":
            self.end_of_round(rt)
        if state.stage == "active" and state.turn >= int(self.cfg["max_turns"]):
            state.stage = "timeout"
            rt.log(f"⏳ El combate se alarga demasiado (turno {state.turn}). Te retiras agotado.")
            self.fire(rt, "ON_BATTLE_END", state.player.mods, state.player)
        return {"ok": True, "reason": ""}

    def enemy_turn(self, rt: Runtime, shift_effects: dict) -> None:
        state = rt.state
        enemy = state.enemy
        player = state.player
        if state.stage != "active":
            return

        self.fire(rt, "ON_TURN_START", enemy.mods, enemy)
        self.apply_boss_phase(rt)

        if self.has_status(enemy, "STUN"):
            rt.log(f"💫 **{enemy.name}** está aturdido y pierde su turno.")
            self.fire(rt, "ON_TURN_END", enemy.mods, enemy)
            return

        hits = 1
        if shift_effects.get("double_strike") and state.turn % int(shift_effects["double_strike"]) == 0:
            hits = 2

        archetype_ai = next((a.get("ai") for a in self.data["enemy_archetypes"] if a["id"] == enemy.archetype), "agresivo")
        for index in range(hits):
            if state.stage != "active":
                break
            if archetype_ai == "defensivo" and rt.rng.random() < 0.35 and index == 0:
                self.gain_shield(rt, enemy, 0.10)
            self.fire(rt, "ON_ATTACK", enemy.mods, enemy)
            damage = int(enemy.attack * shift_effects.get("enemy_dmg_mult", 1.0))
            self.deal_damage(rt, enemy, player, damage, "fisico")
            if state.stage != "active":
                break
            if archetype_ai == "conjurador" and rt.rng.random() < 0.35:
                tags = [tag for tag, spec in self.data["statuses"].items()
                        if spec.get("kind") in ("dot", "debuff", "control")]
                self.apply_status(rt, enemy, player, rt.rng.choice(tags), 1, 3)

        self.fire(rt, "ON_TURN_END", enemy.mods, enemy)

    def end_of_round(self, rt: Runtime) -> None:
        state = rt.state
        self.tick_statuses(rt, state.player)
        self.tick_statuses(rt, state.enemy)
        if state.stage != "active":
            return
        if state.player.max_energy > 0:
            state.player.energy = min(state.player.max_energy,
                                      state.player.energy + self.energy_regen(state.player))
        for skill_id in list(state.cooldowns.keys()):
            state.cooldowns[skill_id] = max(0, state.cooldowns[skill_id] - 1)

    def auto_sim_rewards(self, floor: int, level: int, ratio: float, rng: random.Random) -> dict:
        gold = int(self.gold_reward(floor) * ratio)
        xp = int(self.xp_reward(floor, level) * ratio)
        item = self.generate_item(rng, floor) if rng.random() < 0.15 * ratio else None
        return {"gold": max(0, gold), "xp": max(0, xp), "item": item}

    def socket_reroll_cost(self, item: dict) -> int:
        spec = self.data["forge"]
        rarity_mult = float(spec["reroll_rarity_mult"].get(item.get("rarity", "comun"), 1.0))
        unlocked = sum(1 for mod in item.get("sockets", []) if not mod.get("locked"))
        return int(self.gold_reward(int(item.get("floor_found", 1)))
                   * float(spec["reroll_base_floors"]) * rarity_mult * max(1, unlocked))

    def socket_infuse_cost(self) -> int:
        return int(self.data["forge"]["infuse_cost"])

    def roll_socket_mod(self, item: dict, rng: random.Random) -> dict:
        rarity = self.data["rarities"].get(item.get("rarity", "comun"), {})
        return self.generate_mod(rng, float(rarity.get("power", 1.0)), int(item.get("floor_found", 1)))

    def reroll_sockets(self, item: dict, rng: random.Random) -> list[dict]:
        return [
            dict(mod) if mod.get("locked") else self.roll_socket_mod(item, rng)
            for mod in item.get("sockets", [])
        ]

    def infuse_candidates(self, item: dict, rng: random.Random, count: Optional[int] = None) -> list[dict]:
        count = int(count or self.data["forge"]["infuse_choices"])
        return [self.roll_socket_mod(item, rng) for _ in range(max(1, count))]

    def _make_state(self, user: dict, items: list[dict], mutations: dict, floor: int,
                    enemy: Combatant, seed: int, shifts: list[str], skill_id: str, potions: int,
                    echoes: Optional[dict] = None, **flags) -> BattleState:
        shift_effects = self.shift_effects(shifts)
        player = self.make_player(user, items, mutations, shift_effects, echoes)
        state = BattleState(
            floor=int(floor),
            stage="active",
            player=player,
            enemy=enemy,
            player_level=int(user.get("level", 1)),
            potions=int(potions),
            seed=int(seed),
            shifts=list(shifts),
            skill_id=skill_id or "golpe_pesado",
            no_potions=bool(shift_effects.get("no_potions")),
            mutations=mutations,
            echoes=echoes or {},
            **flags,
        )
        rt = Runtime(self, state, random.Random(seed))
        self.fire(rt, "ON_BATTLE_START", player.mods, player)
        rt.log(f"⚔️ Te enfrentas a **{enemy.emoji} {enemy.name}** (Piso {floor}).")
        return state

    def start_floor(self, user: dict, items: list[dict], mutations: dict, floor: int,
                    shifts: Optional[list[str]] = None, skill_id: str = "golpe_pesado",
                    potions: int = 0, seed: Optional[int] = None, farm: bool = False,
                    echoes: Optional[dict] = None) -> BattleState:
        seed = seed if seed is not None else random.SystemRandom().getrandbits(32)
        rng = random.Random(seed)
        enemy = self.make_enemy(floor, rng)
        return self._make_state(user, items, mutations, floor, enemy, seed, shifts or [], skill_id, potions, echoes=echoes, farm=farm)

    def start_boss(self, user: dict, items: list[dict], mutations: dict, tier: int,
                   shifts: Optional[list[str]] = None, skill_id: str = "golpe_pesado",
                   potions: int = 0, seed: Optional[int] = None,
                   echoes: Optional[dict] = None) -> BattleState:
        seed = seed if seed is not None else random.SystemRandom().getrandbits(32)
        rng = random.Random(seed)
        floor = tier * self.cfg["boss_interval"]
        boss = self.make_boss(tier, rng)
        return self._make_state(user, items, mutations, floor, boss, seed, shifts or [], skill_id, potions, echoes=echoes, is_boss=True)

    def start_anomaly(self, user: dict, items: list[dict], mutations: dict, anomaly_id: str,
                      highest_floor: int, shifts: Optional[list[str]] = None,
                      skill_id: str = "golpe_pesado", potions: int = 0,
                      seed: Optional[int] = None, echoes: Optional[dict] = None) -> Optional[BattleState]:
        spec = self.data["anomalies"].get(anomaly_id)
        if not spec:
            return None
        seed = seed if seed is not None else random.SystemRandom().getrandbits(32)
        rng = random.Random(seed)
        base = max(self.cfg["boss_interval"], highest_floor)
        floor = max(1, int(base * spec.get("floor_mult", 1.0)))
        enemy = self.make_enemy(floor, rng, extra_mods=spec.get("enemy_mods", []))
        return self._make_state(user, items, mutations, floor, enemy, seed, shifts or [], skill_id, potions, echoes=echoes, is_anomaly=True, anomaly_id=anomaly_id)

    def start_training(self, user: dict, items: list[dict], mutations: dict, dummy_level: int,
                       skill_id: str = "golpe_pesado", potions: int = 0,
                       seed: Optional[int] = None, echoes: Optional[dict] = None) -> BattleState:
        seed = seed if seed is not None else random.SystemRandom().getrandbits(32)
        rng = random.Random(seed)
        max_hp = max(1, int(self.enemy_max_hp(max(1, dummy_level)) * 1.4))
        dummy = Combatant(
            name="Muñeco de Entrenamiento",
            emoji="🎯",
            max_hp=max_hp,
            hp=max_hp,
            attack=0,
            defense=0,
            crit=0.0,
            dodge=0.0,
            archetype="dummy",
            mods=[],
        )
        return self._make_state(user, items, mutations, max(1, dummy_level), dummy, seed, [], skill_id, potions, echoes=echoes, training=True)

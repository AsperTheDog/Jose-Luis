import json
from collections import defaultdict
from typing import Dict, List, Type, Any

from impression_scripts.base_rule import EventHook, EventRule


class RuleDB:
    _registry: Dict[str, Type[EventRule]] = {}

    @classmethod
    def register_rule(cls, rule_type: str):
        def decorator(subclass: Type[EventRule]):
            cls._registry[rule_type] = subclass
            return subclass
        return decorator

    def __init__(self, config_path: str = None):
        self.hook_buckets: Dict[EventHook, List[EventRule]] = defaultdict(list)
        self.all_rules: List[EventRule] = []

        if config_path:
            self.load_from_config(config_path)

    def load_from_config(self, config_path: str) -> None:
        self.hook_buckets.clear()
        self.all_rules.clear()

        with open(config_path, "r", encoding="utf-8") as f:
            rules_config = json.load(f)

        for rule_cfg in rules_config:
            rule_type = rule_cfg.get("type")
            if rule_type not in self._registry:
                print(f"[RuleDB Warning] Unknown rule type '{rule_type}'. Skipping.")
                continue

            rule_class = self._registry[rule_type]
            rule_instance = rule_class(**rule_cfg)

            self.all_rules.append(rule_instance)

            for hook in rule_instance.EVENT_HOOKS:
                self.hook_buckets[hook].append(rule_instance)

    def get_eligible_rules(self, hook: EventHook, context: Any, tracker: Any = None) -> List[EventRule]:
        candidates = []
        for rule in self.hook_buckets.get(hook, []):
            if rule.check_eligibility(context, tracker):
                candidates.append(rule)
        return candidates
import importlib
import pkgutil

for _, module_name, _ in pkgutil.walk_packages(__path__):
    full_module_name = f"{__name__}.{module_name}"
    importlib.import_module(full_module_name)
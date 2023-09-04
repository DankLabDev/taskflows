from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

environment = Environment(loader=FileSystemLoader(Path(__file__).parent))


@lru_cache
def load_template(name: str):
    """Load a Jinja2 template."""
    return environment.get_template(f"{name}.jinja2")

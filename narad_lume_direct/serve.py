"""Publish the ring's NARAD signals using LUME-PVA."""

import argparse
import os
from pathlib import Path
import sys

# Pixi builds the native parser in this project. Explicit overrides are useful
# when running against a prebuilt library.
project = Path(__file__).resolve().parent
extension = "dylib" if sys.platform == "darwin" else "so"
os.environ.setdefault("PALS_PARSER_CPP_LIB", str(project / ".build/native" / f"libPALSParserCpp.{extension}"))
os.environ.setdefault("ACC_ROOT_DIR", sys.prefix)

from lume.model import LUMEModel
from lume_pva.runner import PutMode, Runner

from bmad_adapter import build_model
from graph import HERE


class PublishedSignals(LUMEModel):
    """Present just the NARAD signals to the LUME-PVA runner."""

    def __init__(self, model, bindings):
        self.model = model
        variables = model.supported_variables
        self.variables = {
            binding.signal.id: variables[binding.signal.id] for binding in bindings
        }

    @property
    def supported_variables(self):
        return self.variables

    def _get(self, names):
        return self.model.get(names)

    def _set(self, values):
        self.model.set(values)

    def reset(self):
        self.model.reset()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lattice", type=Path, default=HERE / "ring.pals.yaml")
    parser.add_argument("--hardware", type=Path, default=HERE / "hardware.yaml")
    parser.add_argument("--prefix", default="FODO:")
    args = parser.parse_args()

    model, bindings = build_model(args.lattice, args.hardware)
    published = PublishedSignals(model, bindings)
    config = Runner.generate_config(published, prefix=args.prefix, put_mode=PutMode.Complete)
    config["protocol"] = ["pva"]
    Runner(model=published, config=config).run()


if __name__ == "__main__":
    main()

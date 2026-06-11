"""rasfem -- open-source 2D FEM for concrete affected by Alkali-Silica Reaction.

Scalar tensile damage (fracture-energy regularised) coupled with ASR expansion
and property degradation. See ``docs/`` for the model and the user manual.
"""

from . import analysis, assembly, damage, elements, materials, ras, solver, stages
from .materials import MaterialDamage
from .ras import RASModel
from .damage import ConstitutiveModel, GPState
from .assembly import Assembler
from .solver import SolverOptions
from .analysis import SteppingOptions

__version__ = "0.1.0"

__all__ = [
    "analysis", "assembly", "damage", "elements", "materials", "ras", "solver",
    "stages", "MaterialDamage", "RASModel", "ConstitutiveModel", "GPState",
    "Assembler", "SolverOptions", "SteppingOptions",
]

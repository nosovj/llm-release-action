"""Per-phase model configuration."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    """Configuration for models used in different phases.

    Allows using different models for semantic analysis (Phase 1)
    and changelog generation (Phase 2).

    Examples:
        - Use a smarter model for analysis, cheaper for formatting
        - Use the same model for both phases
        - Override only one phase
    """

    default: str  # Default model used if phase-specific not set
    analysis: Optional[str] = None  # Phase 1: version analysis
    changelog: Optional[str] = None  # Phase 2: changelog generation

    def get_analysis_model(self) -> str:
        """Get the model to use for Phase 1 (semantic analysis).

        Returns:
            Model string for Phase 1
        """
        return self.analysis if self.analysis else self.default

    def get_changelog_model(self) -> str:
        """Get the model to use for Phase 2 (changelog generation).

        Returns:
            Model string for Phase 2
        """
        return self.changelog if self.changelog else self.default

    @classmethod
    def from_env(
        cls,
        model: str,
        model_analysis: Optional[str] = None,
        model_changelog: Optional[str] = None,
    ) -> "ModelConfig":
        """Create ModelConfig from environment variables.

        Args:
            model: Default model (INPUT_MODEL)
            model_analysis: Optional Phase 1 model (INPUT_MODEL_ANALYSIS)
            model_changelog: Optional Phase 2 model (INPUT_MODEL_CHANGELOG)

        Returns:
            ModelConfig instance
        """
        return cls(
            default=model,
            analysis=model_analysis if model_analysis else None,
            changelog=model_changelog if model_changelog else None,
        )

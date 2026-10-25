"""Typed loading of config/models.yaml and config/run.yaml.

Model IDs are only ever read from config/models.yaml.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .paths import CONFIG


class Pricing(BaseModel):
    """USD per million tokens."""

    model_config = ConfigDict(extra="forbid")
    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    provider: Literal["anthropic", "openai", "fake"]
    model_id: str
    effort: str | None = None
    max_output_tokens: int = 16000
    pricing: Pricing | None = None
    behaviour: Literal["oracle", "mixed", "cheater"] | None = None


class NativeHarness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    adapter: Literal["claude_code", "codex_cli"]
    cli: str
    model_key: str


class JudgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["anthropic", "openai", "fake"]
    model_id: str
    max_output_tokens: int = 2000
    sample_rate: float | None = None
    pricing: Pricing | None = None


class JudgeConfig(BaseModel):
    primary: JudgeModel
    cross_check: JudgeModel


class ModelsConfig(BaseModel):
    agents: list[AgentModel]
    native_harnesses: list[NativeHarness] = Field(default_factory=list)
    judge: JudgeConfig
    fake_agents: list[AgentModel]
    fake_judges: JudgeConfig

    def agent(self, key: str) -> AgentModel:
        for agent in [*self.agents, *self.fake_agents]:
            if agent.key == key:
                return agent
        raise KeyError(f"no agent model {key!r} in config/models.yaml")


class SandboxConfig(BaseModel):
    cpus: float = 2
    memory_mb: int = 2048
    pids: int = 512
    command_timeout_s: int = 300
    output_limit_chars: int = 12000


class DryRunConfig(BaseModel):
    k: int = 3
    workers: int = 3


class GradingConfig(BaseModel):
    repeated_runs_timezones: list[str] = Field(default_factory=lambda: ["UTC"])


class RunConfig(BaseModel):
    k: int = 5
    backend: Literal["auto", "docker", "local"] = "auto"
    workers: int = 3
    bootstrap_samples: int = 10000
    seed: int = 0
    dry_run: DryRunConfig = Field(default_factory=DryRunConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    grading: GradingConfig = Field(default_factory=GradingConfig)


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache
def models_config(path: Path = CONFIG / "models.yaml") -> ModelsConfig:
    return ModelsConfig.model_validate(_load(path))


@lru_cache
def run_config(path: Path = CONFIG / "run.yaml") -> RunConfig:
    return RunConfig.model_validate(_load(path))

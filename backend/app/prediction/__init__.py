"""Phase 9 AI prediction, recommendation, and memory retrieval stub."""

from app.prediction.bedrock_client import (
    AwsBedrockClient,
    BedrockAccessError,
    BedrockClient,
    BedrockInvocationError,
    MockBedrockClient,
    extract_json_object,
)
from app.prediction.confidence import adjust_confidence
from app.prediction.memory import (
    MemoryRetrieval,
    MemoryRetrievalResult,
    RetrievedMemory,
    StubMemoryRetrieval,
)
from app.prediction.models import (
    AdjustedPrediction,
    ConfidenceAdjustment,
    ExplainabilityBundle,
    ModelPredictionOutput,
    RecommendationOutput,
)
from app.prediction.predictor import PredictionEngine, PredictionValidationError
from app.prediction.recommender import RecommendationEngine, RecommendationValidationError

__all__ = [
    "AdjustedPrediction",
    "AwsBedrockClient",
    "BedrockAccessError",
    "BedrockClient",
    "BedrockInvocationError",
    "ConfidenceAdjustment",
    "ExplainabilityBundle",
    "MemoryRetrieval",
    "MemoryRetrievalResult",
    "MockBedrockClient",
    "ModelPredictionOutput",
    "PredictionEngine",
    "PredictionValidationError",
    "RecommendationEngine",
    "RecommendationOutput",
    "RecommendationValidationError",
    "RetrievedMemory",
    "StubMemoryRetrieval",
    "adjust_confidence",
    "extract_json_object",
]

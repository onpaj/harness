"""Round-trip tests for GitHub label constants."""

from agentharness.github_labels import (
    FEAT_QUESTIONING,
    FEAT_STATUS_LABELS,
    FEATURE_STATUS_TO_LABEL,
    LABEL_TO_FEATURE_STATUS,
    LABEL_TO_QUEUE_NAME,
    QUEUE_NAME_TO_LABEL,
    QUEUE_PRODUCT,
)
from agentharness.models import FeatureStatus


class TestQuestioningLabels:
    def test_feat_questioning_constant(self):
        assert FEAT_QUESTIONING == "feat:questioning"

    def test_queue_product_constant(self):
        assert QUEUE_PRODUCT == "queue:product"

    def test_feat_questioning_in_status_labels(self):
        assert FEAT_QUESTIONING in FEAT_STATUS_LABELS

    def test_feature_status_to_label_round_trip(self):
        assert FEATURE_STATUS_TO_LABEL[FeatureStatus.questioning] == FEAT_QUESTIONING
        assert LABEL_TO_FEATURE_STATUS[FEAT_QUESTIONING] == FeatureStatus.questioning

    def test_queue_name_round_trip(self):
        assert QUEUE_NAME_TO_LABEL["product-queue"] == QUEUE_PRODUCT
        assert LABEL_TO_QUEUE_NAME[QUEUE_PRODUCT] == "product-queue"

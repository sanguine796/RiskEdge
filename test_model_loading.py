import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, '.')
import app as app_module


class ModelLoadingTests(unittest.TestCase):
    def test_load_or_rebuild_model_retrains_after_load_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = os.path.join(tmp_dir, 'model.joblib')
            features_path = os.path.join(tmp_dir, 'features.txt')
            with open(features_path, 'w', encoding='utf-8') as fh:
                fh.write('age\ncredit_score\n')

            retrain_calls = []

            def retrain_func():
                retrain_calls.append(True)
                with open(model_path, 'wb') as fh:
                    fh.write(b'new-model')
                return 'rebuilt-model'

            with patch.object(app_module.joblib, 'load', side_effect=ValueError('bad model')):
                model = app_module.load_or_rebuild_model(
                    model_path=model_path,
                    features_path=features_path,
                    retrain_func=retrain_func,
                    state={},
                    model_attr='ml_model',
                    features_attr='features',
                )

            self.assertEqual(model, 'rebuilt-model')
            self.assertEqual(len(retrain_calls), 1)


if __name__ == '__main__':
    unittest.main()

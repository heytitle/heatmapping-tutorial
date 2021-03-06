import unittest
import logging
import tensorflow as tf
import os

from utils import data_provider
from model import provider

tf.logging.set_verbosity(tf.logging.ERROR)
logging.disable(logging.DEBUG)

NO_TESTING_DATA = 10

PROJECT_ROOT = '/'.join(os.path.abspath(__file__).split('/')[:-2])


def prepend_project_root(path):
    return '%s/%s' % (PROJECT_ROOT, path)


class TestNetwork(unittest.TestCase):
    def test_shallow(self):
        TestNetwork._test_lrp('test-models/shallow-mnist-seq-7')

    def test_deep(self):
        TestNetwork._test_lrp('test-models/deep-mnist-seq-7')

    def test_deep_v2(self):
        TestNetwork._test_lrp('test-models/deep_v2-mnist-seq-7')

    def test_convdeep(self):
        TestNetwork._test_lrp('test-models/convdeep-mnist-seq-7')

    def test_convdeep_transcribe(self):
        TestNetwork._test_lrp('test-models/convdeep_transcribe-mnist-3-digits-maj-seq-12')

    def test_rlstm(self):
        TestNetwork._test_lrp('test-models/rlstm-mnist-3-digits-maj-seq-12')

    # def test_rgru(self):
    #     TestNetwork._test_lrp('experiment-results/models-for-exp3-100epoches/rgru-mnist-3-digits-maj-seq-12---2018-04-08--23-41-58')

    def test_convrlstm(self):
        TestNetwork._test_lrp('test-models/convrlstm-mnist-3-digits-maj-seq-12')

    def test_convtran_rlstm(self):
        TestNetwork._test_lrp('test-models/convtran_rlstm_persisted_dropout-fashion-mnist-3-items-maj-seq-12')

    def test_no_variables(self):
        networks = [('test-models/shallow-mnist-seq-7', 162826),
                    ('test-models/deep-mnist-seq-7', 132074)]
        for network, expected in networks:
            model_obj = TestNetwork._load_model(network)
            no_variables = model_obj.dag.no_variables()

            print(model_obj.experiment_artifact)
            self.assertEqual(int(no_variables), expected, 'Correct no. variables of %s' % network)

    @staticmethod
    def _test_lrp(model):
        model = TestNetwork._load_model(model)
        data = data_provider.DatasetLoader(data_dir=prepend_project_root('/data/')).load(model._.dataset)

        start_idx = 100
        x = data.test2d.x[start_idx:(start_idx+NO_TESTING_DATA), :, :]
        y = data.test2d.y[start_idx:(start_idx+NO_TESTING_DATA), :]
        model.rel_lrp_deep_taylor(x, y, debug=True)
        # model.rel_lrp_alpha2_beta1(x, y, debug=True)

    @staticmethod
    def _load_model(model):
        return provider.load(prepend_project_root(model))


if __name__ == '__main__':
    unittest.main()

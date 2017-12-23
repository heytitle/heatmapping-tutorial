from collections import namedtuple

import tensorflow as tf

from model import base
from model.components.layer import Layer
from utils import experiment_artifact
from utils import logging as lg
from utils import network_architecture

lg.set_logging()


Architecture = namedtuple('S2Architecture', ['hidden', 'out', 'recur'])


def load(model_path):
    return Network.load(model_path)


class Dag(base.BaseDag):
    def __init__(self, no_input_cols, dims, max_seq_length, architecture: Architecture, optimizer):
        super(Dag, self).__init__(architecture, dims, max_seq_length, optimizer=optimizer)

        self.ly_input = Layer((dims*no_input_cols + architecture.recur, architecture.hidden), 's2__input')

        self.ly_output = Layer((architecture.hidden, architecture.out), 's2__output')

        self.ly_recurrent = Layer((architecture.hidden, architecture.recur), 's2__recurrent')

        self.layers = {
            'input': self.ly_input,
            'output': self.ly_output,
            'recurrent': self.ly_recurrent
        }

        # define placeholders
        self.rx = tf.placeholder(tf.float32, shape=(None, architecture.recur), name='s2__recurrent_input')
        self.x = tf.placeholder(tf.float32, shape=(None, dims, dims), name='s2__data_input')
        self.y_target = tf.placeholder(tf.float32, [None, 10], name='s2__output_target')
        self.lr = tf.placeholder(tf.float32, name='s2__lr')
        self.keep_prob = tf.placeholder(tf.float32, name='s2__keep_prob')

        rr = self.rx

        self.ha_activations = []
        self.rr_activations = [self.rx]

        # define  dag
        for i in range(0, max_seq_length, no_input_cols):
            ii = tf.reshape(self.x[:, :, i:i + no_input_cols], [-1, no_input_cols * dims])
            xr = tf.concat([ii, rr], axis=1)

            ha = tf.nn.relu(tf.matmul(xr, self.ly_input.W) - tf.nn.softplus(self.ly_input.b))
            self.ha_activations.append(ha)

            rr = tf.nn.relu(tf.matmul(ha, self.ly_recurrent.W) - tf.nn.softplus(self.ly_recurrent.b))
            self.rr_activations.append(rr)

            ha_do = tf.nn.dropout(ha, keep_prob=self.keep_prob)
            ot = tf.matmul(ha_do, self.ly_output.W) - tf.nn.softplus(self.ly_output.b)

        self.y_pred = ot

        self.setup_loss_and_opt()


class Network(base.BaseNetwork):
    def __init__(self, artifact: experiment_artifact.Artifact):
        super(Network, self).__init__(artifact)

        self.architecture = Architecture(**network_architecture.parse(artifact.architecture))

        tf.reset_default_graph()
        self.dag = Dag(artifact.column_at_a_time, 28, 28, self.architecture, artifact.optimizer)

        self.experiment_artifact = artifact
        self._ = artifact

        self.name = 's2_network'

    def lrp(self, x, factor=1, debug=False):

        x_3d = x.reshape(-1, 28, 28)
        with self.get_session() as sess:

            # lwr start here
            self.dag.setup_variables_for_lrp()
            rel_to_input = [None]*self._.seq_length

            rel_to_hidden = self.dag.layers['output'].rel_z_plus_prop(
                self.dag.ha_activations[-1],
                self.dag.total_relevance, factor=factor
            )
            weight_px_parts = self.dag.layers['input'].W[:-self.architecture.recur, :]
            weight_rr_parts = self.dag.layers['input'].W[-self.architecture.recur:, :]

            rel_to_recurrent, rel_to_input[-1] = Layer.rel_z_plus_beta_prop(
                self.dag.rr_activations[-2],
                weight_rr_parts,
                tf.reshape(self.dag.x[:, :, -self.experiment_artifact.column_at_a_time:], shape=[x_3d.shape[0], -1]),
                weight_px_parts,
                rel_to_hidden,
                factor=factor
            )

            for i in range(self._.seq_length - 1)[::-1]:
                rel_to_hidden = self.dag.layers['recurrent'].rel_z_plus_prop(
                    self.dag.ha_activations[i],
                    rel_to_recurrent, factor=factor
                )

                c_i = self._.column_at_a_time * i
                c_j = c_i + self._.column_at_a_time

                rel_to_recurrent, rel_to_input[i] = Layer.rel_z_plus_beta_prop(
                    self.dag.rr_activations[i],
                    weight_rr_parts,
                    tf.reshape(self.dag.x[:, :, c_i:c_j], shape=[x_3d.shape[0], -1]),
                    weight_px_parts,
                    rel_to_hidden,
                    factor=factor
                )

            pred, heatmaps = self._build_heatmap(sess, x,
                                                 rr_of_pixels=rel_to_input, debug=debug)

        return pred, heatmaps

import imp
import tensorflow as tf
import os
import numpy as np
import math
from tensorflow.python.ops import math_ops

# deepknight_root = os.environ.get('DEEPKNIGHT_ROOT')
# AbstractModel = imp.load_source("abstractmodel", os.path.join(deepknight_root, "models/model.py")).AbstractModel

class Model:

    def __init__(self,
                 sess=tf.Session(),
                 trainable=False,
                 CONFIG=None):

        full_size_IMG_SHAPE = [None, 250, 400, 3]
        INPUT_IMG_SHAPE = [None, 74, 192, 3]

        self.sess = sess
        self.CONFIG = CONFIG

        self.tf_xs = tf.placeholder(tf.float32, shape=INPUT_IMG_SHAPE, name='camera')
        self.tf_ys = tf.placeholder(tf.float32, shape=[None,1], name='control')
        self.tf_rs = tf.placeholder(tf.float32, shape=[None,1], name='rewards')

        self.keep_prob = tf.placeholder(tf.float32)

        self.rewards_ep = tf.placeholder(tf.float32, shape=[None,1], name='rewards_ep')
        self.distance_ep = tf.placeholder(tf.float32, shape=[None,1], name='distance_ep')

        # batch color normalization
        self.x_image = tf.map_fn(lambda frame: tf.image.per_image_standardization(frame), self.tf_xs)

        # convolutional layers
        self.h_conv1 = tf.layers.conv2d(inputs=self.x_image, filters=24, kernel_size=[5,5], strides=[2,2], padding="valid", activation=tf.nn.relu)
        self.h_conv2 = tf.layers.conv2d(inputs=self.h_conv1, filters=36, kernel_size=[5,5], strides=[2,2], padding="valid", activation=tf.nn.relu)
        self.h_conv3 = tf.layers.conv2d(inputs=self.h_conv2, filters=48, kernel_size=[3,3], strides=[2,2], padding="valid", activation=tf.nn.relu)
        self.h_conv4 = tf.layers.conv2d(inputs=self.h_conv3, filters=64, kernel_size=[3,3], strides=[1,1], padding="valid", activation=tf.nn.relu)
        self.h_conv5 = tf.layers.conv2d(inputs=self.h_conv4, filters=64, kernel_size=[3,3], strides=[1,1], padding="valid", activation=tf.nn.relu)

        # fully connected layers
        self.h_conv5_flat = tf.layers.flatten(self.h_conv5)
        self.h_fc1 = tf.layers.dense(self.h_conv5_flat, units=2048, activation=tf.nn.relu)
        self.h_fc1_drop = tf.nn.dropout(self.h_fc1, self.keep_prob)

        self.h_fc2 = tf.layers.dense(self.h_fc1_drop, units=512, activation=tf.nn.relu)
        self.h_fc2_drop = tf.nn.dropout(self.h_fc2, self.keep_prob)

        self.normal_params = tf.layers.dense(self.h_fc2_drop, units=2, activation=None)
        self.mu, self.log_sigma = tf.split(self.normal_params, 2, axis=1)

        self.mu = 1/5. * tf.tanh(self.mu)
        self.sigma = 0.05 * tf.sigmoid(self.log_sigma) + 0.001
        self.dist = tf.distributions.Normal(self.mu, self.sigma)

        self.y_sample = self.dist.sample()
        self.y_ = tf.identity(self.mu, name='prediction')

        if trainable:
            self.neg_log_prob = -1 * self.dist.log_prob(self.tf_ys)
            self.loss = tf.reduce_mean(self.neg_log_prob * self.tf_rs)

            optimizer = tf.train.AdamOptimizer(5e-5)
            self.gradients, variables = zip(*optimizer.compute_gradients(self.loss))
            self.gradients, _ = tf.clip_by_global_norm(self.gradients, 5.0)
            self.train_step = optimizer.apply_gradients(zip(self.gradients, variables))


    def get_step_reward(self, translation_state, car_width, road_width):
        trans_space_available = (road_width-car_width)/2.
        reward = -(1./abs(trans_space_available))*(abs(translation_state)) + 1
        # print "TRANSLATION STATE SQRD: ", translation_state**2, ", REWARD: ", reward
        # or:
        # reward = 1.0
        return reward

    ''' These are required functions that must be part
        of every model class definition '''

    def init_summaries(self, logdir):
        # create a summary to monitor cost tensor
        tf.summary.scalar("loss", self.loss)
        tf.summary.scalar("neglogprob", tf.reduce_mean(self.neg_log_prob))
        tf.summary.scalar("rewards", tf.reduce_sum(self.tf_rs))
        tf.summary.scalar("ys", tf.reduce_mean(self.tf_ys))
        tf.summary.image("cropped image", self.x_image, max_outputs=1)
        self.rewards_ep_summary = tf.summary.scalar("rewards_ep", tf.reduce_mean(self.rewards_ep))
        self.merged_summary_op = tf.summary.merge_all()

        self.distances_ep_summary = tf.summary.scalar("distance_ep", tf.reduce_mean(self.distance_ep))

        self.summary_writer = tf.summary.FileWriter(logdir, graph=tf.get_default_graph())
        self.summary_iter = 0

    def init_saver(self):
        self.saver = tf.train.Saver()

    def inference(self, feed):
        y = self.sess.run(self.y_sample, feed_dict=feed)
        return y


    def train_iter(self, feed):
        (_, y, y_sample, mu, sigma, loss, neg_log_prob, norm_pdf) = self.sess.run([self.train_step, self.y, self.y_sample, self.mu, self.sigma, self.loss, self.neg_log_prob, self.norm_pdf], feed_dict=feed)
        report = {'y':y, 'y_':y_sample, 'mu':mu, 'sigma':sigma, 'loss':loss, 'product':product, 'log_prob': neg_log_prob, 'norm_pdf':norm_pdf, 'delta': y - y_sample}
        return report

    def write_summary(self, feed):
        summary = self.sess.run(self.merged_summary_op, feed_dict=feed)
        self.summary_writer.add_summary(summary, self.summary_iter)
        self.summary_iter += 1

    def write_checkpoint(self, path, name='model'):
        if not os.path.exists(path):
            os.makedirs(path)
        checkpoint_path = os.path.join(path, name )
        filename = self.saver.save(self.sess, checkpoint_path)

    def restore(self, path):
        self.saver = tf.train.Saver()
        self.saver.restore(self.sess, path)

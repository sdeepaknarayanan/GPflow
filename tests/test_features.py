# Copyright 2017 Mark van der Wilk
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np
import tensorflow as tf

import gpflow
from gpflow import features
from gpflow import settings
from gpflow.test_util import GPflowTestCase


class TestInducingPoints(GPflowTestCase):
    def test_feature_len(self):
        with self.test_context():
            N, D = 17, 3
            Z = np.random.randn(N, D)
            f = gpflow.features.InducingPoints(Z)

            self.assertTrue(len(f), N)
            with gpflow.params_as_tensors_for(f):
                self.assertTrue(len(f), N)
                # GPflow does not support re-assignment with different shapes at the moment

    def test_inducing_points_equivalence(self):
        # Inducing features must be the same as the kernel evaluations
        with self.test_context() as session:
            Z = np.random.randn(101, 3)
            f = features.InducingPoints(Z)

            kernels = [
                gpflow.kernels.RBF(3, 0.46, lengthscales=np.array([0.143, 1.84, 2.0]), ARD=True),
                gpflow.kernels.Periodic(3, 0.4, 1.8)
            ]

            for k in kernels:
                self.assertTrue(np.allclose(session.run(features.Kuu(f, k)), k.compute_K_symm(Z)))


class TestMultiScaleInducing(GPflowTestCase):
    def prepare(self):
        rbf = gpflow.kernels.RBF(2, 1.3441, lengthscales=np.array([0.3414, 1.234]))
        Z = np.random.randn(23, 3)
        feature_0lengthscale = gpflow.features.Multiscale(Z, np.zeros(Z.shape))
        feature_inducingpoint = gpflow.features.InducingPoints(Z)
        return rbf, feature_0lengthscale, feature_inducingpoint

    def test_equivalence_inducing_points(self):
        # Multiscale must be equivalent to inducing points when variance is zero
        with self.test_context() as session:
            rbf, feature_0lengthscale, feature_inducingpoint = self.prepare()
            Xnew = np.random.randn(13, 3)

            ms, point = session.run([features.Kuf(feature_0lengthscale, rbf, Xnew),
                                     features.Kuf(feature_inducingpoint, rbf, Xnew)])
            pd = np.max(np.abs(ms - point) / point * 100)
            self.assertTrue(pd < 0.1)

            ms, point = session.run([features.Kuu(feature_0lengthscale, rbf),
                                     features.Kuu(feature_inducingpoint, rbf)])
            pd = np.max(np.abs(ms - point) / point * 100)
            self.assertTrue(pd < 0.1)


class TestFeaturesPsdSchur(GPflowTestCase):
    def test_matrix_psd(self):
        # Conditional variance must be PSD.
        X = np.random.randn(13, 2)

        def init_feat(feature):
            if feature is gpflow.features.InducingPoints:
                return feature(np.random.randn(71, 2))
            elif feature is gpflow.features.Multiscale:
                return feature(np.random.randn(71, 2), np.random.rand(71, 2))

        featkerns = [(gpflow.features.InducingPoints, gpflow.kernels.RBF),
                     (gpflow.features.InducingPoints, gpflow.kernels.Matern12),
                     (gpflow.features.Multiscale, gpflow.kernels.RBF)]
        for feat_class, kern_class in featkerns:
            with self.test_context() as session:
                # rbf, feature, feature_0lengthscale, feature_inducingpoint = self.prepare()
                kern = kern_class(2, 1.84, lengthscales=[0.143, 1.53])
                feature = init_feat(feat_class)
                Kuf, Kuu = session.run([features.Kuf(feature, kern, X),
                                        features.Kuu(feature, kern, jitter=settings.jitter)])
                Kff = kern.compute_K_symm(X)
            Qff = Kuf.T @ np.linalg.solve(Kuu, Kuf)
            self.assertTrue(np.all(np.linalg.eig(Kff - Qff)[0] > 0.0))


def test_convolutional_patch_features():
    """
    Predictive variance of convolutional kernel must be unchanged when using inducing points, and inducing patches where
    all patches of the inducing points are used.
    :return:
    """
    settings = gpflow.settings.get_settings()
    settings.numerics.jitter_level = 1e-14
    with gpflow.settings.temp_settings(settings):
        M = 10
        image_size = [4, 4]
        patch_size = [2, 2]

        kern = gpflow.kernels.Convolutional(gpflow.kernels.SquaredExponential(4), image_size, patch_size)

        # Evaluate with inducing points
        Zpoints = np.random.randn(M, np.prod(image_size))
        points = gpflow.features.InducingPoints(Zpoints)
        points_var = gpflow.conditionals.conditional(tf.identity(Zpoints), points, kern, np.zeros((M, 1)),
                                                     full_output_cov=True, q_sqrt=None, white=False)[1]

        # Evaluate with inducing patches
        Zpatches = kern.compute_patches(Zpoints).reshape(M * kern.num_patches, np.prod(patch_size))
        patches = gpflow.features.InducingPatch(Zpatches)
        patches_var = gpflow.conditionals.conditional(tf.identity(Zpoints), patches, kern, np.zeros((len(patches), 1)),
                                                      full_output_cov=True, q_sqrt=None, white=False)[1]

        sess = gpflow.get_default_session()

        points_var_eval = sess.run(points_var)
        patches_var_eval = sess.run(patches_var)
        assert np.all(points_var_eval > 0.0)
        assert np.all(points_var_eval < 1e-13)
        assert np.all(patches_var_eval > 0.0)
        assert np.all(patches_var_eval < 1e-13)


if __name__ == "__main__":
    tf.test.main()

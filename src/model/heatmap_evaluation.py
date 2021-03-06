import logging

import matplotlib.pyplot as plt
import numpy as np
from skimage import img_as_ubyte
from skimage.filters.rank import entropy
from skimage.measure import block_reduce
from skimage.morphology import square

import config
from model import provider
from model.architectures import base
from notebook_utils import plot as nb_plot
from utils import logging as lg

FLIP_FUNCTION = {
    'zero': lambda x: np.zeros(x.shape),
    'minus_one': lambda x: -np.ones(x.shape),
    'flip_value': lambda x: -x,
    'reduce_intensity_to_1_percent': lambda x: 0.01 * x
}


lg.set_logging()


def aopc(model_obj: base.BaseNetwork, x, y, max_k=49, patch_size=(4, 4), order="morf", method="deep_taylor",
         ref_model="conv-seq1",
         verbose=False, flip_function='minus_one', plot_result=False):

    specified_method = method

    if method == 'random':
        method = 'sensitivity'



    print('using %s flip' % flip_function)

    rel_prop = getattr(model_obj, 'rel_%s' % method)
    _, relevance_heatmaps = rel_prop(x, y)

    # select only positive relevance
    relevance_heatmaps = relevance_heatmaps * (relevance_heatmaps > 0)

    rel_patches = block_reduce(relevance_heatmaps, block_size=(1, patch_size[0], patch_size[1]), func=np.sum)

    rel_patches_flatted = rel_patches.reshape(x.shape[0], -1)
    if verbose:
        print('negative relevance : %f' % np.sum(rel_patches_flatted<0))

    logging.info('AOPC Using %s flipping' % flip_function)

    if order == "morf":
        logging.info("Using MoRF strategy")
        patch_indices = np.argsort(-rel_patches_flatted, axis=1)[:, :max_k]
    else:
        logging.info("Using random order strategy")
        patch_indices = np.zeros((x.shape[0], max_k))
        seed = 0
        np.random.seed(seed)
        logging.info('set seed to %d' % seed)
        for i in range(x.shape[0]):
            patch_indices[i, :] = np.random.choice(rel_patches_flatted.shape[1], max_k, replace=False)

    patch_indices_i = np.floor( patch_indices / rel_patches.shape[1] )
    patch_indices_j = patch_indices % rel_patches.shape[2]

    ii_start, jj_start = (patch_indices_i * patch_size[0]).astype(int), (patch_indices_j * patch_size[1]).astype(int)
    ii_end, jj_end = ii_start + patch_size[0], jj_start + patch_size[1]


    relevances = []

    # reference model
    if ref_model == 'conv-seq1':
        ref_model_path = provider._model_path('convdeep_4l', model_obj._.dataset, 1)
    elif ref_model == 'conv-same-seq':
        ref_model_path = provider._model_path('convdeep_4l', model_obj._.dataset, model_obj._.seq_length)
    elif ref_model == 'lenet':
        ref_model_path = './final-models/lenet-%s' % model_obj._.dataset
    else:
        raise SystemError('No ref_model %s defined' % ref_model)

    logging.info('Using reference model %s' % ref_model_path)
    ref_model_name = ref_model
    ref_model = provider.load(ref_model_path)

    with ref_model.get_session() as sess:
        rr_inputs = np.zeros((x.shape[0], ref_model.architecture.recur))
        relevance_at_0 = sess.run(ref_model.dag.y_pred_y_target,
                                  feed_dict={ref_model.dag.x: x, ref_model.dag.y_target: y,
                                             ref_model.dag.rx: rr_inputs, ref_model.dag.keep_prob: 1
                                             })

        relevance_at_0 = np.mean(np.sum(relevance_at_0, axis=1))

        relevances.append(relevance_at_0)

        x_permuted = np.copy(x)
        if plot_result:
            for k in range(x.shape[0]):
                plt.subplot(9, x.shape[0], k+1)
                plt.imshow(_make_rgb_heatmap(relevance_heatmaps[k,:, :]))
                plt.xticks([])
                plt.yticks([])

            for k in range(x.shape[0]):
                plt.subplot(9, x.shape[0], k+1 + x.shape[0])
                plt.imshow(_make_rgb_heatmap(rel_patches[k,:, :]))
                plt.xticks([])
                plt.yticks([])

        baskets = []

        for i in range(max_k):
            for j in range(x_permuted.shape[0]):
                ix, iy = ii_start[j, i], ii_end[j, i]
                jx, jy = jj_start[j, i], jj_end[j, i]

                x_j = x_permuted[j, ix:iy, jx:jy]

                values = FLIP_FUNCTION[flip_function](x_j)
                x_permuted[j, ix:iy, jx:jy] = values




            if i%7 == 0 and plot_result:
                baskets.append(np.copy(x_permuted))


            relevance_at_k = sess.run(ref_model.dag.y_pred_y_target, feed_dict={
                ref_model.dag.x: x_permuted, ref_model.dag.y_target:y,
                ref_model.dag.rx: rr_inputs, ref_model.dag.keep_prob: 1
            })

            relevance_at_k = np.mean(np.sum(relevance_at_k, axis=1))

            relevances.append(relevance_at_k)

        if plot_result:
            for st in range(len(baskets)):
                xt = baskets[st]
                for k in range(x_permuted.shape[0]):
                    plt.subplot(9, x.shape[0], k+1 + (st+1)*x.shape[0] + x.shape[0])
                    if k == 0:
                        plt.title('step %d' % (st*7))
                    plt.imshow(xt[k,:, :], cmap='gist_gray')
                    plt.xticks([])
                    plt.yticks([])

        ar_name = model_obj._.architecture_name.replace('_network', '')
        if plot_result:
            plt.suptitle('%s-%d - %s' % (config.MODEL_NICKNAMES[ar_name], model_obj._.seq_length, method))
            plt.savefig('./heatmap-temp/relevance-%s-refmodel-%s-%s-seq-%d-%s' %
                        (ref_model_name, model_obj._.dataset,
                         model_obj._.architecture_name, model_obj._.seq_length, specified_method))

    return relevances


def relevance_distributions(model_obj: base.BaseNetwork, x, y, method, batch_size=200):
    logging.info('Compute relevance dist of %s with %s method' % (model_obj._.architecture_name, method))

    cols = int(model_obj._.max_seq_length / model_obj._.seq_length)

    _, heatmaps = getattr(model_obj, 'rel_%s' % method)(x, y)

    # select only positive relevance and sum over rows
    positive_heatmaps = heatmaps * (heatmaps > 0)

    # accurate for all rows in each sample
    positive_relevance = np.sum(positive_heatmaps, axis=1)

    relevance_for_step = np.zeros((x.shape[0], model_obj._.seq_length))
    for i in range(model_obj._.seq_length):
        relevance_for_step[:, i] = np.sum(positive_relevance[:, (i * cols):(i + 1) * cols], axis=1)

    total_relevance = np.sum(relevance_for_step, axis=1).reshape(-1, 1)
    relevance_dist = relevance_for_step / (total_relevance + 1e-100)

    return np.mean(relevance_dist, axis=0), np.std(relevance_dist, axis=0), relevance_for_step


def image_entropy(model_obj: base.BaseNetwork, x, patch_size=4):
    _, relevance_heatmaps = model_obj.rel_lrp_deep_taylor(x)

    entropies = []

    for i in range(relevance_heatmaps.shape[0]):
        img = relevance_heatmaps[i, :, :]
        img = img_as_ubyte(img)
        entropies.append(entropy(img, square(patch_size)))

    return np.mean(entropies)


def _make_rgb_heatmap(heatmap):
    heatmap = heatmap / (np.abs(heatmap).max() + 1e-10)

    return nb_plot.make_rgb_heatmap(heatmap)


# def count_flip(model_obj: base.BaseNetwork, x, y_true, max_k=16, patch_size=(7,7), order="morf", method="deep_taylor",
#                verbose=False, flip_function='minus_one'):
#     if method == 'random':
#         method = 'sensitivity'
#
#     rel_prop = getattr(model_obj, 'rel_%s' % method)
#     print('total x : %d' % x.shape[0])
#     y_pred, relevance_heatmaps = rel_prop(x)
#     print(y_pred)
#
#
#     # correct_prediction_indices = np.argmax(y_true, axis=1) == y_pred
#     # x = x[correct_prediction_indices, :, :]
#     # relevance_heatmaps = relevance_heatmaps[correct_prediction_indices, :, :]
#     # print('correctly predicted x : %d' % x.shape[0])
#
#     rel_patches = block_reduce(relevance_heatmaps, block_size=(1, patch_size[0], patch_size[1]), func=np.sum)
#
#     rel_patches_flatted = rel_patches.reshape(x.shape[0], -1)
#     if verbose:
#         print('negative relevance : %f' % np.sum(rel_patches_flatted<0))
#
#     if order == "morf":
#         logging.info("Using MoRF strategy")
#         patch_indices = np.argsort(-rel_patches_flatted, axis=1)[:, :max_k]
#     else:
#         logging.info("Using random order strategy")
#         patch_indices = np.zeros((x.shape[0], max_k))
#         for i in range(x.shape[0]):
#             np.random.seed(0)
#             choice = np.random.choice(rel_patches_flatted.shape[1], max_k, replace=False)
#             print(choice)
#             patch_indices[i, :] = choice
#
#     print('Rel patches shape')
#     print(rel_patches.shape)
#     patch_indices_i = np.floor( patch_indices / rel_patches.shape[2] )
#     patch_indices_j = patch_indices % rel_patches.shape[2]
#
#     ii_start, jj_start = (patch_indices_i * patch_size[0]).astype(int), (patch_indices_j * patch_size[1]).astype(int)
#     # ii_start = (ii_start / patch_size[0]).astype(int)
#     ii_end, jj_end = ii_start + patch_size[0], jj_start + patch_size[1]
#
#
#     pred_indices = np.zeros((x.shape[0], 1+max_k))
#
#     with model_obj.get_session() as sess:
#         rr_inputs = np.zeros((x.shape[0], model_obj.architecture.recur))
#         y_pred = sess.run(model_obj.dag.y_pred, feed_dict={model_obj.dag.x: x, model_obj.dag.rx: rr_inputs,
#                                                            model_obj.dag.keep_prob:1 })
#
#         pred_at_0 = np.argmax(y_pred, axis=1)
#         pred_indices[:, 0] = pred_at_0
#
#         x_permuted = np.copy(x)
#
#         for i in range(max_k):
#             for j in range(x_permuted.shape[0]):
#                 ix, iy = ii_start[j,i], ii_end[j,i]
#                 jx, jy = jj_start[j,i], jj_end[j,i]
#                 values = FLIP_FUNCTION[flip_function](patch_size)
#                 x_permuted[j, ix:iy, jx:jy] = values
#
#             y_pred = sess.run(model_obj.dag.y_pred, feed_dict={
#                 model_obj.dag.x: x_permuted, model_obj.dag.rx: rr_inputs, model_obj.dag.keep_prob: 1
#             })
#
#             # for k in range(10):
#             #     plt.subplot(2, 10, k+1)
#             #     plt.imshow(rel_patches[k,:, :], cmap='Reds')
#             #
#             #     plt.subplot(2, 10, k+1 + 10)
#             #     plt.imshow(x_permuted[k,:, :], cmap='Reds')
#             #
#             # plt.savefig('./tmp/no-flip-%s-permuted-%d.png' % (method, i+1))
#
#             pred_at_k = np.argmax(y_pred, axis=1)
#
#             pred_indices[:, i+1] = pred_at_k
#
#     no_flips = - np.ones((x.shape[0], 1))
#     for i in range(x.shape[0]):
#         change_idxs = np.argwhere(pred_indices[i, :] != pred_indices[i, 0])
#
#         if len(change_idxs) > 0:
#             no_flips[i, 0] = change_idxs[0]
#
#
#     return np.mean(no_flips)

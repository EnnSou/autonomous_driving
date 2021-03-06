import os
import numpy as np
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.animation import FuncAnimation
import matplotlib.pyplot as plt
from code_base.tools.kalman_filtering import kalman_xy
#import seaborn

fig, ax = plt.subplots()
fig.set_tight_layout(True)
# Query the figure's on-screen size and DPI. Note that when saving the figure to
# a file, we need to provide a DPI for that separately.
print('fig size: {0} DPI, size in inches {1}'.format(
    fig.get_dpi(), fig.get_size_inches()))
valid_data_array = np.load('/home/public/synthia/car_trajectory_prediction/valid_data_array.npy')
test_data_array = np.load('/home/public/synthia/car_trajectory_prediction/test_data_array.npy')
print('Finish Loading')


def get_img_list(valid_data, test_data):

    valid_img_list = []
    for d in valid_data:
        item_list = [x[6] for x in d]
        valid_img_list.append(item_list)

    test_img_list = []
    for d in test_data:
        item_list = [x[6] for x in d]
        test_img_list.append(item_list)

    return  valid_img_list, test_img_list


def get_data_with_img_list(valid_data, test_data):
    valid_data_array = np.array(valid_data[:, :, :6]).astype('float')
    test_data_array = np.array(test_data[:, :, :6]).astype('float')
    return  valid_data_array, test_data_array


def prepare_data_image_list(cf):
    import pickle
    with open(os.path.join(cf['trajectory_path'], cf['sequence_name'] + '_valid.npy'), 'rb') as fp:
        valid_data = pickle.load(fp)
    with open(os.path.join(cf['trajectory_path'], cf['sequence_name'] + '_test.npy'), 'rb') as fp:
        test_data = pickle.load(fp)

    valid_data_array, test_data_array = get_data_with_img_list(valid_data, test_data)
    valid_img_list, test_img_list = get_img_list(valid_data, test_data)

    return  valid_data_array, test_data_array, valid_img_list, test_img_list


def demo_kalman_xy(i):
    x = np.matrix('0. 0. 0. 0.').T
    P = np.matrix(np.eye(4))*1000  # initial uncertainty
    for f, data in enumerate([valid_data_array[i]]):
        fig.clear()
        observed_x = np.array([d[0] for d in data])
        observed_y = np.array([d[1] for d in data])
        color = [str(item * 1.0/len(observed_y)) for item in range(len(observed_y))]
        ax.scatter(observed_x, observed_y, c=color)
        #ax.gray()
        result = []
        R = 1**2
        #R = 0.01 ** 2
        for meas in zip(observed_x[:15], observed_y[:15]):
            x, P = kalman_xy(x, P, meas, R)
            result.append((x[:2]).tolist())
        kalman_x, kalman_y = zip(*result)
        ax.plot(kalman_x, kalman_y, 'g-')
        ax.scatter(kalman_x, kalman_y, c='g')

        result_new = []
        result_new.append([result[-1][0], result[-1][1]])
        for t in range(8):
            x_pred = result_new[-1][0] + x[2]
            y_pred = result_new[-1][1] + x[3]
            result_new.append([x_pred, y_pred])
        kalman_x, kalman_y = zip(*result_new)
        ax.plot(kalman_x, kalman_y, 'r-')
        ax.scatter(kalman_x, kalman_y, c='r')

        x_range = (observed_x.max() - observed_x.min())
        y_range = (observed_y.max() - observed_y.min())
        ax.set_xlim((observed_x.min() - x_range, observed_x.max() + x_range))
        ax.set_ylim((observed_y.min() - y_range, observed_y.max() + y_range))
        ax.set_title('frame %d' %f)
        # plt.xlim((0, 760))
        # plt.ylim((0, 1280))
        #plt.show()
        #plt.waitforbuttonpress(0.01)


# Entry point of the script
if __name__ == "__main__":
    # FuncAnimation will call the 'update' function for each frame; here
    # animating over 10 frames, with an interval of 200ms between frames.
    anim = FuncAnimation(fig, demo_kalman_xy, frames=np.arange(0, 10), interval=200)
    if True:
        anim.save(r'/home/public/synthia/car_trajectory_prediction/kalman.gif', dpi=80, writer='imagemagick')
    else:
        # plt.show() will just loop the animation forever.
        plt.show()

from code_base.models.PyTorch_fcn import FeatureResNet, SegResNet, iou
from code_base.models.PyTorch_drn import drn_c_26, drn_d_22, DRNSeg, DRNSegF
from code_base.models.PyTorch_PredictModels import *
from code_base.tools.PyTorch_model_training import calc_seq_err_robust
import torch
from torchvision import models
from torch import nn
from torch import optim
from torch.autograd import Variable
from torch.nn import functional as F
from torchvision.utils import save_image
from code_base.tools.logger import Logger
from datetime import datetime

import numpy as np
from matplotlib import pyplot as plt
import os
import sys



def adjust_learning_rate(lr, optimizer, epoch, decrease_epoch=10):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    lr = lr * (0.1 ** (epoch // decrease_epoch))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
    return lr


def save_output_images(predictions, filenames, output_dir):
    """
    Saves a given (B x C x H x W) into an image file.
    If given a mini-batch tensor, will save the tensor as a grid of images.
    """
    # pdb.set_trace()
    root = '/home/public/CITYSCAPE'
    from PIL import Image
    import numpy as np
    for ind in range(len(filenames)):
        im = Image.fromarray(predictions[ind].astype(np.uint8))
        name = filenames[ind].replace(root, output_dir)
        # fn = os.path.join(output_dir, filenames[ind])
        out_dir = os.path.split(name)[0]
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        im.save(name)


# Build the model
class Model_Factory_semantic_seg():
    def __init__(self, cf):
        # If we load from a pretrained model
        self.exp_dir = cf.savepath + '___' + datetime.now().strftime('%a, %d %b %Y-%m-%d %H:%M:%S') + '_' + cf.model_name
        os.mkdir(self.exp_dir)
        # Enable log file
        self.log_file = os.path.join(self.exp_dir, "logfile.log")
        sys.stdout = Logger(self.log_file)

        self.model_name = cf.model_name
        self.num_classes = cf.num_classes
        if cf.model_name == 'segnet_basic':
            pretrained_net = FeatureResNet()
            pretrained_net.load_state_dict(models.resnet34(pretrained=True).state_dict())
            self.net = SegResNet(cf.num_classes, pretrained_net).cuda()
        elif cf.model_name == 'drn_c_26':
            self.net = DRNSeg('drn_c_26', cf.num_classes, pretrained=True, linear_up=True)
        elif cf.model_name == 'drn_d_22':
            self.net = DRNSeg('drn_d_22', cf.num_classes, pretrained=True, linear_up=False)
        elif cf.model_name == 'drn_d_38':
            self.net = DRNSeg('drn_d_38', cf.num_classes, pretrained=True, linear_up=False)
        # Set the loss criterion
        if cf.cb_weights_method == 'rare_freq_cost':
            print('Use ' +cf.cb_weights_method+', loss weight method!')
            loss_weight = torch.Tensor([0]+cf.cb_weights)
            self.crit = nn.NLLLoss2d(weight=loss_weight, ignore_index=cf.ignore_index).cuda()
        else:
            self.crit = nn.NLLLoss2d(ignore_index=cf.ignore_index).cuda()



        # we print the configuration file here so that the configuration is traceable
        self.cf = cf
        print(help(cf))

        # Construct optimiser
        if cf.load_trained_model:
            print("Load from pretrained_model weight: "+cf.train_model_path)
            self.net.load_state_dict(torch.load(cf.train_model_path))

        # self.net = DRNSegF(self.net, 20)
        params_dict = dict(self.net.named_parameters())
        params = []
        for key, value in params_dict.items():
            if 'bn' in key:
                # No weight decay on batch norm
                params += [{'params': [value], 'weight_decay': 0}]
            elif '.bias' in key:
                # No weight decay plus double learning rate on biases
                params += [{'params': [value], 'lr': 2 * cf.learning_rate, 'weight_decay': 0}]
            else:
                params += [{'params': [value]}]
        if cf.optimizer == 'rmsprop':
            self.optimiser = optim.RMSprop(params, lr=cf.learning_rate, momentum=cf.momentum, weight_decay=cf.weight_decay)
        elif cf.optimizer == 'sgd':
            self.optimiser = optim.SGD(params, lr=cf.learning_rate, momentum=cf.momentum, weight_decay=cf.weight_decay)
        elif cf.optimizer == 'adam':
            self.optimiser = optim.Adam(params, lr=cf.learning_rate, weight_decay=cf.weight_decay)

        self.scores, self.mean_scores = [], []

        if torch.cuda.is_available():
            self.net = self.net.cuda()

    def train(self, train_loader, epoch):
        lr = adjust_learning_rate(self.cf.learning_rate, self.optimiser, epoch)
        print('learning rate:', lr)
        self.net.train()
        for i, (input, target) in enumerate(train_loader):
            self.optimiser.zero_grad()
            input, target = Variable(input.cuda(async=True)), Variable(target.cuda(async=True))
            output = F.log_softmax(self.net(input))
            self.loss = self.crit(output, target)
            print(epoch, i, self.loss.data[0])
            self.loss.backward()
            self.optimiser.step()

    def test(self, val_loader, epoch, cf):
        self.net.eval()
        total_ious = []
        for i, (input, target) in enumerate(val_loader):
            input, target = Variable(input.cuda(async=True), volatile=True), Variable(target.cuda(async=True), volatile=True)
            output = F.log_softmax(self.net(input))
            b, _, h, w = output.size()
            pred = output.permute(0, 2, 3, 1).contiguous().view(-1, self.num_classes).max(1)[1].view(b, h, w)
            total_ious.append(iou(pred, target, self.num_classes))



        # Calculate average IoU
        total_ious_t = torch.Tensor(total_ious).transpose(0, 1)
        # we only ignore one class 0!!!!
        if type(cf.ignore_index) == int and cf.ignore_index == 0:
            ious = torch.Tensor(self.num_classes - 1)

        for i, class_iou in enumerate(total_ious_t):
            if i != cf.ignore_index:
                ious[i-1] = class_iou[class_iou == class_iou].mean()  # Calculate mean, ignoring NaNs
        print(ious, ious.mean())
        self.scores.append(ious)

        # Save weights and scores
        torch.save(self.net.state_dict(), os.path.join(self.exp_dir, 'epoch_' + str(epoch) + '_' + 'mIOU:.%4f'%ious.mean() + '_net.pth'))
        torch.save(self.scores, os.path.join(self.exp_dir, 'scores.pth'))

        # Plot scores
        self.mean_scores.append(ious.mean())
        es = list(range(len(self.mean_scores)))
        plt.switch_backend('agg')  # Allow plotting when running remotely
        plt.plot(es, self.mean_scores, 'b-')
        plt.xlabel('Epoch')
        plt.ylabel('Mean IoU')
        plt.savefig(os.path.join(self.exp_dir, 'ious.png'))
        plt.close()


class Model_Factory_LSTM():
    def __init__(self, cf):
        # If we load from a pretrained model
        self.model_name = cf.model_name   #['LSTM_ManyToMany', 'LSTM_To_FC']
        if cf.model_name == 'LSTM_ManyToMany':
            self.net = LSTM_ManyToMany(input_dims=cf.lstm_input_dims,
                                       hidden_sizes=cf.lstm_hidden_sizes,
                                       outlayer_input_dim=cf.outlayer_input_dim,
                                       outlayer_output_dim=cf.outlayer_output_dim,
                                       cuda=cf.cuda)
        elif cf.model_name == 'LSTM_To_FC':
            self.net = LSTM_To_FC(input_dims=cf.lstmToFc_input_dims,
                                  hidden_sizes=cf.lstmToFc_hidden_sizes,
                                  future_frame=cf.lstmToFc_future,
                                  output_dim=cf.lstmToFc_output_dim,
                                  cuda=cf.cuda)
        elif cf.model_name == 'CNN_LSTM_To_FC':
            self.net = CNN_LSTM_To_FC(conv_paras=cf.cnnLstmToFc_conv_paras,
                                      input_dims=cf.cnnLstmToFc_input_dims,
                                      hidden_sizes=cf.cnnLstmToFc_hidden_sizes,
                                      future_frame=cf.cnnLstmToFc_future,
                                      output_dim=cf.cnnLstmToFc_output_dim,
                                      cuda=cf.cuda)
        # Set the loss criterion
        if cf.loss == 'MSE':
            self.crit = nn.MSELoss()
        elif cf.loss == 'SmoothL1Loss':
            self.crit = nn.SmoothL1Loss()

        self.net.float()
        if cf.cuda and torch.cuda.is_available():
            print('Using cuda')
            self.net = self.net.cuda()
            self.crit = self.crit.cuda()

        self.exp_dir = cf.savepath + '_' + datetime.now().strftime('%a, %d %b %Y-%m-%d %H:%M:%S') + '_' + cf.model_name
        os.mkdir(self.exp_dir)
        # Enable log file
        self.log_file = os.path.join(self.exp_dir, "logfile.log")
        sys.stdout = Logger(self.log_file)

        # we print the configuration file here so that the configuration is traceable
        self.cf = cf
        print(help(cf))

        # Construct optimiser
        if cf.load_trained_model:
            print("Load from pretrained_model weight: "+cf.train_model_path)
            self.net.load_state_dict(torch.load(cf.train_model_path))

        # use LBFGS as optimizer since we can load the whole data to train
        if cf.optimizer == 'LBFGS':
            self.optimiser = optim.LBFGS(self.net.parameters(), lr=cf.learning_rate)
        elif cf.optimizer == 'adam':
            self.optimiser = optim.Adam(self.net.parameters(), lr=cf.learning_rate, weight_decay=cf.weight_decay)
        elif cf.optimizer == 'rmsprop':
            self.optimiser = optim.RMSprop(self.net.parameters(), lr=cf.learning_rate, momentum=cf.momentum, weight_decay=cf.weight_decay)
        elif cf.optimizer == 'sgd':
            self.optimiser = optim.SGD(self.net.parameters(), lr=cf.learning_rate, momentum=cf.momentum, weight_decay=cf.weight_decay, nesterov=True)

    def train(self, cf, train_loader, epoch):
        # begin to train
        lr = adjust_learning_rate(self.cf.learning_rate, self.optimiser, epoch, decrease_epoch=cf.lr_decay_epoch)
        print('learning rate:', lr)

        # if cf.model_name == 'CNN_LSTM_To_FC':
        #     input = tuple([train_images, train_input])
        # else:
        #     input = tuple([train_input])

        # if cf.optimizer == 'LBFGS':
        #     def closure():
        #         self.optimiser.zero_grad()
        #         out = self.net(*input)[0]
        #         loss = self.crit(out, train_target)
        #         if cf.cuda:
        #             print('loss: ', loss.data.cpu().numpy()[0])
        #         else:
        #             print('loss: ', loss.data.numpy()[0])
        #         loss.backward()
        #         return loss
        #     self.optimiser.step(closure)
        # else:
        train_losses=[]
        for i, (sementic, input_trajectory, target_trajectory) in enumerate(train_loader):
            self.optimiser.zero_grad()
            sementic, input_trajectory, target_trajectory = Variable(sementic.cuda(async=True), requires_grad=False), \
                                                            Variable(input_trajectory.cuda(async=True), requires_grad=False), \
                                                            Variable(target_trajectory.cuda(async=True), requires_grad=False)
            if cf.model_name == 'CNN_LSTM_To_FC':
                input = tuple([sementic, input_trajectory])
            else:
                input = tuple([input_trajectory])
            output = self.net(*input)[0]
            self.loss = self.crit(output, target_trajectory)
            train_losses.append(self.loss.data[0])
            # print(epoch, i, self.loss.data[0])
            self.loss.backward()
            self.optimiser.step()

        train_loss = np.array(train_losses).mean()
        print('Train Loss', epoch, train_loss )

        # # output loss
        # out = self.net(*input)[0]
        # loss = self.crit(out, train_target)
        # if cf.cuda:
        #     return loss.data.cpu().numpy()[0]
        # else:
        return train_loss

    def test(self, cf, valid_loader, data_mean, data_std, epoch=None):
        # if cf.model_name == 'CNN_LSTM_To_FC':
        #     input = tuple([valid_images, valid_input])
        # else:
        #     input = tuple([valid_input])

        output_trajectories = []
        target_trajectories = []
        for i, (sementic, input_trajectory, target_trajectory) in enumerate(valid_loader):
            sementic, input_trajectory, target_trajectory = Variable(sementic.cuda(async=True)), \
                                                            Variable(input_trajectory.cuda(async=True)), \
                                                            Variable(target_trajectory.cuda(async=True))
            if cf.model_name == 'CNN_LSTM_To_FC':
                input = tuple([sementic, input_trajectory])
            else:
                input = tuple([input_trajectory])
            output = self.net(*input, future=cf.lstm_predict_frame)[-1]
            output_trajectories.append(output)
            target_trajectories.append(target_trajectory)

        # concatenate
        output_trajectories = torch.cat(output_trajectories, 0)
        target_trajectories = torch.cat(target_trajectories, 0)

        self.loss = self.crit(output_trajectories, target_trajectories)

        # evaluations
        if cf.cuda:
            results = output_trajectories.data.cpu().numpy() * data_std + data_mean
            rect_anno = target_trajectories.data.cpu().numpy() * data_std + data_mean
        else:
            results = output_trajectories.data.numpy() * data_std + data_mean
            rect_anno = target_trajectories.data.numpy() * data_std + data_mean

        aveErrCoverage, aveErrCenter, errCoverage, iou_2d, \
        aveErrCoverage_realworld, aveErrCenter_realworld, errCenter_realworld, iou_3d = calc_seq_err_robust(results, rect_anno, cf.focal_length)

        # Save weights and scores
        if epoch:
            print('############### VALID #############################################')
            print('Valid Loss', epoch, self.loss.data[0])
            print('2D aveErrCoverage: %.4f, aveErrCenter: %.2f' % (aveErrCoverage, aveErrCenter))
            print('3D aveErrCoverage_realworld: %.4f, aveErrCenter_realworld: %.4f' % (
            aveErrCoverage_realworld, aveErrCenter_realworld))

            model_checkpoint = 'Epoch:%2d_net_Coverage:%.4f_Center:%.2f_CoverageR:%.4f_CenterR:%.2f.PTH' % \
                               (epoch, aveErrCoverage, aveErrCenter, aveErrCoverage_realworld, aveErrCenter_realworld)
        else:
            print('############### TEST #############################################')
            print('Test Loss', epoch, self.loss.data[0])
            print('2D aveErrCoverage: %.4f, aveErrCenter: %.2f' % (aveErrCoverage, aveErrCenter))
            print('3D aveErrCoverage_realworld: %.4f, aveErrCenter_realworld: %.4f' % (
            aveErrCoverage_realworld, aveErrCenter_realworld))
            model_checkpoint = 'Final_test:Coverage:%.4f_Center:%.2f_CoverageR:%.4f_CenterR:%.2f.PTH' % \
                               (aveErrCoverage, aveErrCenter, aveErrCoverage_realworld, aveErrCenter_realworld)
            # Plot scores
            # self.aveErrCoverage.append(aveErrCoverage.mean())
            # es = list(range(len(self.aveErrCoverage)))
            # plt.plot(es, self.aveErrCoverage, 'b-')
            # plt.xlabel('aveErrCoverage')
            # plt.ylabel('Mean IoU')
            # plt.savefig(os.path.join(self.exp_dir, 'ious.png'))
            # plt.close()
        torch.save(self.net.state_dict(), os.path.join(self.exp_dir, model_checkpoint))
        if cf.cuda:
            return self.loss.data.cpu().numpy()[0]
        else:
            return self.loss.data.numpy()[0]


